#!/usr/bin/env python3
"""Generate the 1 km terrain maps: heightmap, biome mask and surface-ID map.

Run:
    python tools/generators/terrain_maps.py --out artifacts/terrain
    python tools/generators/terrain_maps.py --out artifacts/terrain --seed drowned-greenwood-v1

Why these three maps together, from one generator: they must agree. A biome mask derived from a
different heightmap than the terrain's would place a bog on a ridge, and a surface-ID map that
disagrees with the heightmap puts deep water on a hillside. Deriving all three from one height
field in one pass makes disagreement impossible rather than merely unlikely.

The heightfield is fractal noise shaped by the brief's world: a temperate rainforest valley with a
bog basin, ridges at the edges, and a river running out of it. The shaping is written as named
steps so the intent survives — a reader can see "the bog is a bowl, not a random dip".

Outputs, all lossless and all deterministic from the seed:
  terrain_heightmap_master_1km  R16, 1025², 0..65535 mapped to 0..200 m
  terrain_biome_mask            R8,  1025², bit field: 1 bog, 2 forest, 4 ridge, 8 riverbed, 16 clearing
  terrain_surface_id_map        R8,  1025², ids from assets/surface_ids.json

The biome mask is a BIT FIELD, not a palette of levels, and that is a sampling constraint, not
just a format note: bilinear filtering or a mipmap chain averages neighbouring bits together and
invents surfaces — a texel halfway between bog (1) and forest (2) decodes as 1.5, which is neither
and sets both. Anything that samples it must use `filter_nearest` and no mipmaps, which is the
opposite of the rule every other sampler in this project follows. The surface-ID map has the same
constraint for the same reason; the splat weights, the depth mask and the normal map are the
continuous ones and are meant to be filtered.

1025² rather than 1024² so texel centres land on grid vertices: a 1024-cell terrain needs 1025
height samples, and using 1024 makes the last row of cells share the edge sample. Sample x sits at
x/1024 of the way across the kilometre, which is the convention hydrology and terrain_surfaces
share.
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    GENERATOR_VERSION,
    bilinear_upsample,
    fbm_field,
    input_hash,
    record,
    sha256_file,
    write_gray_png,
)

CELLS = 1024
SAMPLES = CELLS + 1

# 1 km across, 200 m of relief. The first version used 600 m, which over one kilometre is a
# 27-degree average slope — a mountain, not the temperate rainforest valley the brief describes.
# The measured result was 82 % bare rock. This is a playable valley with ridges at its rim.
MAX_HEIGHT_M = 200.0

# The world is 1 km across and 1024 cells wide, so one cell is about 0.977 m. Every slope in this
# file is a true gradient — metres of rise per metre of run — because a threshold in "metres per
# sample step" is a number nobody can reason about, and the first version of this file had exactly
# that bug.
CELL_SPACING_M = 1000.0 / CELLS

# Slope thresholds as dimensionless gradients, from where soil actually stops holding:
#   0.70 is 35° — bare rock. Vegetation grows on far steeper ground than intuition suggests;
#                alpine grass and scrub hold to about 35°, and only beyond that does rock show.
#   0.40 is 22° — scree and loose gravel, where soil is thin and plants are sparse.
# The first version used 0.55 (29°) for rock, which is a conservative guess that made a normal
# forested hillside read as a cliff. Combined with a too-steep terrain it produced a world that
# was 82 % bare rock.
SLOPE_ROCK = 0.70
SLOPE_SCREE = 0.40
SLOPE_RIVER_STONE = 0.30

# Biome bits. These are a bit field rather than an enum because a cell can be both ridge and
# forest, and a scatter pass wants to ask "is this forest?" without decoding a priority order.
BIOME_BOG = 1
BIOME_FOREST = 2
BIOME_RIDGE = 4
BIOME_RIVERBED = 8
BIOME_CLEARING = 16

# Surface ids, mirrored from assets/surface_ids.json. The generator asserts they still match, so a
# renumbering there fails here rather than silently painting the wrong surface.
SURFACE = {
    "mud": 1,
    "moss": 3,
    "wet_stone": 4,
    "gravel": 5,
    "sand": 6,
    "water_shallow": 8,
    "water_deep": 9,
    "dirt_path": 11,
    "grass": 12,
    "clay": 13,
}

# The lake in the bog bowl. This is the surface of ONE water body, not a waterline for the whole
# map: a river that flows has a surface that descends, and no single level can express one.
#
# Treating it as a global level was the defect the published maps shipped. The carved channel floor
# lies below the lake — it has to, or the lake could not drain — so "ground below the level" filled
# the entire channel to one flat sheet. The result was a flooded trench that every gate passed,
# because each gate asked whether the line descended and whether water sat above its bed.
#
# Water is decided per body by water_surface() below. The valley floor (40-62 m) is deliberately
# ABOVE this level, so the lake cannot spill onto the land.
WATER_LEVEL_M = 34.0
# Deep water is a DEPTH, not an absolute height. It was 22 m above sea level, which no texel can
# reach once the lake sits at 34, so the water_deep surface id was unreachable and dead.
DEEP_WATER_DEPTH_M = 2.0

# How the height field is composed, in normalised units. The floor sits at 0.20 (40 m) and the
# noise moves it by 0.11 (22 m), so the valley is 40..62 m — comfortably above the waterline, and
# the bog and river are carved below it deliberately. The rim contributes the remaining 0.40
# (80 m), concentrated at the edge by RIM_POWER. Each figure below is the constant it describes;
# an earlier version of this comment quoted the round-2 values and had drifted from the code.
#
# These are tuned against measured output, in two rounds, and both numbers are recorded because
# the first two attempts were wrong in an instructive way:
#
#   round 1: 600 m relief, noise blended 40/60 with the rim  -> 82 % bare rock
#   round 2: 200 m relief, additive, RIM 0.62 / POWER 3.0     -> 40 % bare rock
#   round 3: RIM 0.50 / POWER 2.6                             -> 30 % bare rock
#
# Round 3 was still wrong, and the reason was not the terrain at all: the rock threshold was
# 29°, which is a conservative guess at where soil stops holding. Vegetation grows on steeper
# ground than that. The threshold is now 35°, and the rim is a little gentler again.
#
# The rim gradient is RIM_AMPLITUDE · RIM_POWER · r^(RIM_POWER-1) · MAX_HEIGHT_M / 500. At
# 0.40 / 2.4 that peaks at 0.38 — a ridge you can walk up, well below the 0.70 (35°) rock
# threshold, so bare rock appears only where the noise adds enough on top of it.
FLOOR = 0.20
NOISE_AMPLITUDE = 0.11
# A valley needs a rim: the ridges are what make it read as a bowl rather than a plate, and they
# are the horizon the game is designed around. The first version of the walkability gate asked for
# 85 % of the whole map under 30 degrees, which can only be met by flattening the rim — a worse
# world than a failing gate. The gate now measures the valley floor (the playable space) at 92 %
# and accepts that the rim is steep, because the rim is supposed to be steep.
RIM_AMPLITUDE = 0.40
RIM_POWER = 2.4

# The river. It has to read as a river at a kilometre across — the shape a player names, not a
# stream they step over — so the channel is 80 m wide inside a 140 m floodplain. The first version
# cut a 16 m stream, and the version after it cut 44 m, which is a creek at this scale.
RIVER_HALF_WIDTH_M = 40.0
# The bank is a floodplain, not a wall: the ground rises from the bed to the valley floor over
# 140 m, which is what puts the river in a broad valley instead of a slot.
RIVER_BANK_M = 140.0
# How wide the rim opens to let the river out. It has to exceed the carve it opens for — the channel
# plus its bank is 180 m — or the rim closes in either side of the channel at the map edge and puts
# a wall there, which is exactly what an earlier 200 m notch against a 32 m channel was tuned for.
RIVER_NOTCH_M = 200.0

# The water on the river, and how far it falls. THESE are what make it flow:
#
#   * the surface is bed + depth, so it descends with the bed;
#   * the bed drops 7.4 m over the 340 m from the lake's outlet to the mouth — 22 mm per texel,
#     seven 16-bit steps — which is what D8 needs to find a strictly lower neighbour.
#
# The previous bed fell 1 m over the same valley: 1.4 mm per texel, under one 3 mm step, so the
# channel was FLAT in the stored heightfield. D8 could not route it, the depression fill raised
# 696,054 cells (66 % of the map) to the spill level, and the traced centreline came out 1.4 % on
# water with 361 of 970 segments climbing. Those figures are from the CI run on 1baa3aa, not an
# estimate: a river's slope is a sampling-rate question as much as a design one.
#
# 2.6 m is deliberate, not arbitrary: DEEP_WATER_DEPTH_M is 2.0, so a river shallower than that is
# classified as shallow water for its whole length. At 1.6 m every texel of the channel was
# water_shallow and the water_deep id existed only in the lake — a river nobody would call deep.
RIVER_DEPTH_M = 2.6

# Where the river leaves the lake, as a v coordinate. The bowl's floor is 29.6 m and the lake's
# surface is 34.0 m, so the water body reaches a long way up the valley — and how far depends on the
# noise that warps the bowl's edge, measured at roughly v = 0.34 to 0.52 across the rows.
#
# This is the EARLIEST of those, not the average, and that is the whole point: upstream of it the
# lake's rule decides the water, so the lake covers the whole basin however the warp falls and the
# two bodies meet at one height. Picking a value inside the range would leave the downstream part of
# the basin decided by the river's rule, i.e. a water surface that descends across what a player
# sees as one lake.
#
# It is a design constant with gates behind it rather than a measurement: the head of the
# centreline must lie on water, its surface must equal the lake's there, and the fall from it to the
# mouth must be at least 2 m. Moving the bowl without moving this fails the build instead of quietly
# changing where the lake ends.
RIVER_HEAD_V = 0.34

# The meander, in u units (1.0 is the whole kilometre across). A straight line reads as a canal, and
# the drift is what carries the river across the valley rather than down one side of it. One and a
# half cycles is three visible bends over the river's length — the scale of a river's own curves,
# not a squiggle.
RIVER_MEANDER_U = 0.05
RIVER_MEANDER_CYCLES = 1.5
RIVER_DRIFT_U = 0.045

# The bed at the lake's outlet, one depth below the lake's surface — DERIVED, not typed, so the two
# bodies meet at one height and the river leaves the lake at the lake's own level. As a typed 32.4
# against a 34.0 lake it was the mistake that made the river's surface 2 m below the lake along the
# reach they share: a groove through the water.
RIVER_BED_SOURCE_M = WATER_LEVEL_M - RIVER_DEPTH_M
# The mouth, on the northern edge, well below the lake: the water falls from the bog to the edge
# the way a river draining a lake does.
RIVER_BED_OUTLET_M = 24.0

# The bog bowl, as a radius in u/v units (1.0 is the whole map across).
BOG_CENTRE_U = 0.30
BOG_CENTRE_V = 0.68
BOG_RADIUS_U = 0.26
# Below the waterline: the basin holds a lake rather than being a damp lawn. At 0.168 (33.6 m) it
# sat above the 32 m water level and the bog came out dry.
BOG_FLOOR = 0.148


def smoothstep(edge0, edge1, x):
    """0 below edge0, 1 above edge1, smooth between. Used so every carve has soft banks."""
    if edge1 == edge0:
        return 0.0 if x < edge0 else 1.0
    t = (x - edge0) / (edge1 - edge0)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


def river_centre_u(v):
    """Meandering centreline of the river, as a u coordinate for a given v.

    A straight line reads as a canal, so the line bends: t runs 0 at the lake's outlet and 1 at the
    mouth, the sine gives one and a half full bends over that length, and the linear term carries
    the whole river east as it runs north. The previous version had one small sine and a much
    larger drift, so the "meander" was a gentle curve — at a kilometre across, a river needs bends
    a player can see.

    It is a function of v alone, so the channel is continuous along its whole length. An earlier
    version cut the carve off at v = 0.72, which put a 14-23 m cliff straight across the map where
    the carving stopped.
    """
    t = 1.0 - max(0.0, min(1.0, v / RIVER_HEAD_V))
    return (
        BOG_CENTRE_U
        + RIVER_MEANDER_U * math.sin(t * RIVER_MEANDER_CYCLES * 2.0 * math.pi)
        + RIVER_DRIFT_U * t
    )


def river_bed_m(v):
    """Bed height along the river, and the lake's outlet height upstream of it.

    t is 0 at the mouth and 1 at RIVER_HEAD_V, so the bed descends towards v = 0 and the water runs
    out of the map there. It used to run the other way across 1 m, which is the flat channel
    described above the constants.

    Above RIVER_HEAD_V the bed HOLDS at RIVER_BED_SOURCE_M instead of continuing to climb. That is
    what makes the two water bodies meet at one height: the river's surface at its outlet is
    RIVER_BED_SOURCE_M + RIVER_DEPTH_M, which is the lake's level by construction. A bed that kept
    rising through the bowl would put the river's surface above the lake it drains, and the lake
    would be the lower body — a waterfall backwards.
    """
    t = max(0.0, min(1.0, v / RIVER_HEAD_V))
    return RIVER_BED_OUTLET_M + (RIVER_BED_SOURCE_M - RIVER_BED_OUTLET_M) * t


def river_surface_m(v):
    """The river's water surface: the bed plus its depth. Descending, so the water flows."""
    return river_bed_m(v) + RIVER_DEPTH_M


def river_taper(v):
    """How much of the channel exists at this v.

    Full strength all the way to the northern edge, so the river reaches the map boundary and
    leaves through the notch. An earlier version also faded the channel IN over the first 10 % of
    v, which left the mouth high and dry and made the outlet a cell on the rim instead of the
    river.

    It fades OUT at the bowl's centre, NOT at the outlet. A taper at the outlet would raise the
    carved channel back to the lake's natural bed over its last 50 m, which is a bar of land across
    the water between the river and the lake — a dam the player can walk over. Running the carve on
    through the outlet instead leaves a trench under the lake's surface, which costs nothing to look
    at and keeps the water continuous.
    """
    return 1.0 - smoothstep(BOG_CENTRE_V, BOG_CENTRE_V + 0.10, v)


def channel_weight(u, v):
    """How strongly the river carve applies here: 1 on the centreline, 0 outside the floodplain."""
    taper = river_taper(v)
    if taper <= 0.0:
        return 0.0
    distance_m = abs(u - river_centre_u(v)) * 1000.0
    return taper * (
        1.0 - smoothstep(RIVER_HALF_WIDTH_M, RIVER_HALF_WIDTH_M + RIVER_BANK_M, distance_m)
    )


def notch_weight(u, v):
    """How far the rim drops away along the channel, so the river leaves through a gap."""
    taper = river_taper(v)
    if taper <= 0.0:
        return 0.0
    distance_m = abs(u - river_centre_u(v)) * 1000.0
    return taper * (1.0 - smoothstep(0.0, RIVER_NOTCH_M, distance_m))


def water_surface(v, channel, ground_m):
    """The height of the water body at this point, or None where there is no water.

    Two bodies, each with its own rule:

      1. The river — downstream of the lake's outlet, where the carve reaches and the ground is
         below the river's own surface. That surface is bed + depth, so it descends.
      2. The lake — upstream of the outlet wherever the ground is below the lake's level. That
         includes the channel's own outlet reach: the bed holds one depth below the lake there, so
         the water in it IS the lake's, at the lake's level.

    Where both could apply the higher one wins, which matters because the river's surface is at or
    below the lake's everywhere.

    The seam is continuous by construction — river_surface_m(RIVER_HEAD_V) == WATER_LEVEL_M — so
    the two bodies meet at one height instead of stepping. Deciding the whole channel by the
    river's rule instead, which is what the published maps did, cut a groove through the lake: the
    river's surface is 2 m below the lake's along the reach the two share, and the lake on either
    side stood above it.

    Water is a body, not a waterline. Everything that needs to know where the water is — the
    surface classifier, hydrology's depth mask, the splat shore band — calls this one function
    rather than keeping its own rule, so they cannot disagree.
    """
    river_surface = None
    if v < RIVER_HEAD_V and channel > 0.0:
        candidate = river_surface_m(v)
        if ground_m < candidate:
            river_surface = candidate

    lake_covers = ground_m < WATER_LEVEL_M and (channel <= 0.0 or v >= RIVER_HEAD_V)
    if lake_covers and (river_surface is None or WATER_LEVEL_M > river_surface):
        return WATER_LEVEL_M

    return river_surface


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_surface_ids():
    """Fail if surface_ids.json has renumbered anything this generator hardcodes.

    The path is resolved from this file rather than the working directory, so the check runs
    wherever the generator is invoked from — a check that silently skips is worse than none.
    """
    path = os.path.join(REPO_ROOT, "assets", "surface_ids.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("cannot read %s (%s)" % (path, exc))
    by_name = {
        row["name"]: row["id"]
        for row in doc.get("surfaces", [])
        if isinstance(row, dict) and "name" in row
    }
    for name, expected in SURFACE.items():
        actual = by_name.get(name)
        if actual != expected:
            raise SystemExit(
                "surface id for %r is %r in %s but this generator writes %r; ids are a contract "
                "and must not change" % (name, actual, path, expected)
            )


def shape_height(base, valley):
    """Turn noise into a place: a valley floor, a bog bowl, and ridges at the edges.

    Written as explicit steps because the alternative — one expression — produces terrain that is
    plausible noise and not a place anyone can describe.

    The composition is additive in normalised units rather than a blend of two noise fields. The
    first version blended noise with the rim at 40/60, which let the noise alone swing the height
    by 40 % of the range over a 166 m feature — an average gradient near the rock threshold, and
    the measured result was 82 % bare rock. Separating "a floor", "a little undulation" and "a
    rim" makes each one tunable and the arithmetic visible.
    """
    field = []
    # Where the river carve reaches, kept beside the height. Hydrology and terrain_surfaces need
    # the same weights to decide where the water is, and recomputing them from the helpers keeps
    # the three files in step; carrying them here keeps the generator from doing it twice.
    channel_field = []
    for y in range(SAMPLES):
        # Divide by CELLS, not CELLS - 1. There are CELLS cells across and SAMPLES = CELLS + 1
        # samples, so sample x sits at x/1024 of the way across the kilometre. Dividing by 1023
        # put the last sample 0.1 % past the edge and, worse, disagreed with the convention every
        # other file uses: hydrology divides the same x by CELLS, so two generators were
        # describing one texel with two different coordinates. Found by reading, not by a gate — a
        # tenth of a percent is invisible in a hillshade and quite capable of moving a river.
        v = y / CELLS
        row = [0.0] * SAMPLES
        channel_row = [0.0] * SAMPLES
        for x in range(SAMPLES):
            u = x / CELLS

            # The channel and the notch come from the shared helpers, because hydrology and
            # terrain_surfaces have to reach the same answer about where the water is. A second
            # copy of this arithmetic here is how two files end up describing one river differently.
            #
            # Both are computed before the rim, because the rim has to open for the channel: a
            # river leaves a valley through a notch, and cutting a slot straight through the rim
            # instead put a 150 m wall either side of the water at the map edge.
            channel = channel_weight(u, v)
            notch = notch_weight(u, v)
            bed_norm = river_bed_m(v) / MAX_HEIGHT_M
            channel_row[x] = channel

            # Distance from the centre, 0 at the middle and 1 at the edge. The world is a valley,
            # so height rises towards the rim. The power concentrates the rise near the edge and
            # keeps the interior broad rather than making a cone.
            #
            # The radius is warped by the noise before the power is taken. Without the warp the
            # rim is a perfect circle, and the surface classifier then paints a rock-and-gravel
            # ring exactly along its gradient threshold — a geometric feature in an organic world.
            dx = (u - 0.5) * 2.0
            dy = (v - 0.5) * 2.0
            radius = min(1.0, (dx * dx + dy * dy) ** 0.5)
            warp = 1.0 + 0.22 * (base[y][x] * 2.0 - 1.0)
            rim = min(1.0, max(0.0, radius * warp)) ** RIM_POWER
            # The rim drops away along the channel: that is the notch the river leaves the valley
            # through, and it is why the water does not end at a wall.
            rim *= 1.0 - 0.85 * notch

            noise = base[y][x] * 0.55 + valley[y][x] * 0.45
            h = FLOOR + NOISE_AMPLITUDE * noise + RIM_AMPLITUDE * rim

            # The bog basin, low and flat, south-west of centre. A bowl rather than a dip: the
            # noise is suppressed inside it so the floor stays level and water can sit. The edge
            # is a smoothstep and the radius is warped, because a hard-edged disc is exactly what
            # the hillshade showed.
            bog_dx = (u - BOG_CENTRE_U) * 2.0
            bog_dy = (v - BOG_CENTRE_V) * 2.0
            bog_distance = (bog_dx * bog_dx + bog_dy * bog_dy) ** 0.5
            bog_distance *= 1.0 + 0.35 * (valley[y][x] * 2.0 - 1.0)
            bog_weight = 1.0 - smoothstep(BOG_RADIUS_U * 0.7, BOG_RADIUS_U * 2.0, bog_distance)
            h = h * (1.0 - bog_weight) + BOG_FLOOR * bog_weight

            # The channel itself: a blend toward a bed height, not a proportional cut of whatever
            # the terrain happens to be. That is what makes it a few metres deep along its whole
            # length instead of 100 m deep where the valley is tall. It only ever lowers ground,
            # so it cannot cut a step upward where it meets a floor that is already below the bed.
            if channel > 0.0:
                h = min(h, h * (1.0 - channel) + bed_norm * channel)

            row[x] = max(0.0, min(1.0, h))
        field.append(row)
        channel_field.append(channel_row)

    # One 3x3 smoothing pass, and the reason is measurable. The fractal noise is generated at 256
    # and upsampled bilinearly, so its gradient is piecewise constant: two adjacent texels a metre
    # apart can differ by the full lattice step, which came out as an 8 m cliff in the shape gate
    # even after every carve was made continuous. Averaging keeps every feature larger than three
    # texels and removes the one-texel spikes, without touching the valley, the bog or the channel.
    smoothed = [[0.0] * SAMPLES for _ in range(SAMPLES)]
    for y in range(SAMPLES):
        y0 = max(0, y - 1)
        y1 = min(SAMPLES - 1, y + 1)
        for x in range(SAMPLES):
            x0 = max(0, x - 1)
            x1 = min(SAMPLES - 1, x + 1)
            total = 0.0
            for yy in (y0, y, y1):
                for xx in (x0, x, x1):
                    total += field[yy][xx]
            smoothed[y][x] = total / 9.0
    return smoothed, channel_field


def height_metres(normalised):
    return normalised * MAX_HEIGHT_M


def slope(field, x, y):
    """True gradient at a sample: metres of rise per metre of run.

    The central difference spans two cells (x-1 to x+1), so the run is 2 · CELL_SPACING_M.
    Forgetting that factor is what made the first version's thresholds meaningless.
    """
    x0 = max(0, x - 1)
    x1 = min(SAMPLES - 1, x + 1)
    y0 = max(0, y - 1)
    y1 = min(SAMPLES - 1, y + 1)
    run_x = (x1 - x0) * CELL_SPACING_M
    run_y = (y1 - y0) * CELL_SPACING_M
    dx = height_metres(field[y][x1]) - height_metres(field[y][x0])
    dy = height_metres(field[y1][x]) - height_metres(field[y0][x])
    gx = dx / run_x if run_x else 0.0
    gy = dy / run_y if run_y else 0.0
    return (gx * gx + gy * gy) ** 0.5


def classify_surface(height_m, gradient, biome, noise, surface_m, above_water_m):
    """One surface id per cell. Ordered: water wins, then the shore, then what grows there.

    `surface_m` is the water body's height here, or None where there is no water. `above_water_m`
    is how far this ground stands above the body it belongs to. Both are passed in because there
    are two bodies now, and one map-wide waterline cannot describe either of them.
    """
    if surface_m is not None:
        return (
            SURFACE["water_deep"]
            if surface_m - height_m > DEEP_WATER_DEPTH_M
            else SURFACE["water_shallow"]
        )

    # The shoreline is sand or gravel, decided by noise so it is not a uniform ring.
    if above_water_m < 1.5:
        return SURFACE["sand"] if noise < 0.6 else SURFACE["gravel"]

    if biome & BIOME_BOG:
        return SURFACE["mud"] if noise < 0.7 else SURFACE["clay"]

    if biome & BIOME_RIVERBED:
        return SURFACE["wet_stone"] if gradient > SLOPE_RIVER_STONE else SURFACE["gravel"]

    # Steep ground is bare rock whatever grows around it; a 35° slope does not hold soil.
    if gradient > SLOPE_ROCK:
        return SURFACE["wet_stone"]
    if gradient > SLOPE_SCREE:
        return SURFACE["gravel"] if noise < 0.5 else SURFACE["wet_stone"]

    if biome & BIOME_CLEARING:
        return SURFACE["grass"]
    if biome & BIOME_FOREST:
        return SURFACE["moss"] if noise < 0.55 else SURFACE["grass"]
    return SURFACE["grass"]


def classify_biome(gradient, bog_distance, forest_noise, above_water_m):
    """The bit field for a cell, measured against the water body it belongs to.

    It used to take the absolute height and compare it with one waterline. With two bodies that
    would have marked the whole upper river as underwater and put a forest on the lake.
    """
    bits = 0
    if bog_distance < BOG_RADIUS_U * 2.0 and above_water_m < 6.0:
        bits |= BIOME_BOG
    if above_water_m >= 0.0 and forest_noise > 0.45:
        bits |= BIOME_FOREST
    if gradient > SLOPE_ROCK:
        bits |= BIOME_RIDGE
    if above_water_m < 2.0:
        bits |= BIOME_RIVERBED
    # Clearings are where the forest noise dips: gaps in the canopy, which is what a hunting game
    # needs to be readable from a distance.
    if above_water_m >= 2.0 and forest_noise < 0.28:
        bits |= BIOME_CLEARING
    return bits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", default="drowned-greenwood-v1")
    parser.add_argument(
        "--report",
        default="",
        help="write a JSON report of what was produced (path, sha256, input_hash) here",
    )
    args = parser.parse_args()

    check_surface_ids()

    # The noise is generated at 256 and upsampled: fractal noise at 1025² would be a million
    # lattice samples per octave for detail the terrain does not need, and the upsample is what
    # makes the terrain smooth rather than noisy at texel scale.
    base = fbm_field(256, args.seed + ":base", octaves=5, base_size=6)
    valley = fbm_field(256, args.seed + ":valley", octaves=3, base_size=3)
    forest = fbm_field(256, args.seed + ":forest", octaves=4, base_size=5)
    detail = fbm_field(256, args.seed + ":detail", octaves=3, base_size=12)

    base = bilinear_upsample(base, SAMPLES)
    valley = bilinear_upsample(valley, SAMPLES)
    forest = bilinear_upsample(forest, SAMPLES)
    detail = bilinear_upsample(detail, SAMPLES)

    field, channel_field = shape_height(base, valley)

    height_rows = []
    biome_rows = []
    surface_rows = []
    heights = []
    max_step = 0.0
    max_step_at = (0, 0, 0.0, 0.0)
    land_cells = 0
    land_under_30 = 0
    inner_land = 0
    inner_under_30 = 0
    # The wet width of the river, one row at a time, over the reach the carve owns. This is the
    # number a player's eye actually measures: the carved channel is 2 * RIVER_HALF_WIDTH_M wide,
    # but the water reaches further where the bank shelves below the surface, and it is the water a
    # player sees, not the constant.
    river_widths = []
    river_rows = int(round(RIVER_HEAD_V * CELLS))

    for y in range(SAMPLES):
        height_row = []
        biome_row = []
        surface_row = []
        v = y / CELLS
        for x in range(SAMPLES):
            u = x / CELLS
            # Classify from the QUANTISED height, not the float. The heightmap is what hydrology
            # reads, so deciding water from a value no other file can see would let the two
            # generators disagree by a fraction of a texel along every shoreline.
            stored = int(round(field[y][x] * 65535))
            h_m = stored / 65535.0 * MAX_HEIGHT_M
            height_row.append(stored)
            heights.append(h_m)

            gradient = slope(field, x, y)
            bog_dx = (u - BOG_CENTRE_U) * 2.0
            bog_dy = (v - BOG_CENTRE_V) * 2.0
            bog_distance = (bog_dx * bog_dx + bog_dy * bog_dy) ** 0.5

            channel = channel_field[y][x]
            surface_m = water_surface(v, channel, h_m)
            # How far this ground stands above the body it belongs to: the river downstream of the
            # lake's outlet, the lake from there up. The shore band and the biome bits both need
            # this, and neither can use one map-wide level any more. A channel texel on the lake
            # side of the outlet is lake bed, so it is measured against the lake, not against the
            # river's surface that the lake covers.
            reference_m = (
                river_surface_m(v) if channel > 0.0 and v < RIVER_HEAD_V else WATER_LEVEL_M
            )
            above_water_m = h_m - reference_m

            biome = classify_biome(gradient, bog_distance, forest[y][x], above_water_m)
            biome_row.append(biome)
            surface_row.append(
                classify_surface(h_m, gradient, biome, detail[y][x], surface_m, above_water_m)
            )

            # Shape metrics. A format gate passes a terrain with a cliff across it, which is what
            # happened: every check was about bit depth and value ranges, and the hillshade showed
            # a 20 m step. These are the numbers that would have caught it, plus the location of
            # the worst one — guessing where a cliff is has cost three runs already.
            if x > 0:
                step = abs(h_m - heights[-2])
                if step > max_step:
                    max_step = step
                    max_step_at = (x, y, round(h_m, 2), round(heights[-2], 2))
            if y > 0:
                step = abs(h_m - heights[(y - 1) * SAMPLES + x])
                if step > max_step:
                    max_step = step
                    max_step_at = (x, y, round(h_m, 2), round(heights[(y - 1) * SAMPLES + x], 2))
            if surface_m is None:
                land_cells += 1
                if gradient < math.tan(math.radians(30.0)):
                    land_under_30 += 1
                # The playable floor is the inner valley; the rim is meant to be steep, so it is
                # measured separately rather than dragging the whole map's number down.
                if max(abs((u - 0.5) * 2.0), abs((v - 0.5) * 2.0)) <= 0.55:
                    inner_land += 1
                    if gradient < math.tan(math.radians(30.0)):
                        inner_under_30 += 1

        if y <= river_rows:
            wet = sum(
                1
                for x, value in enumerate(surface_row)
                if channel_field[y][x] > 0.0
                and value in (SURFACE["water_shallow"], SURFACE["water_deep"])
            )
            river_widths.append(wet * CELL_SPACING_M)

        height_rows.append(height_row)
        biome_rows.append(biome_row)
        surface_rows.append(surface_row)

    os.makedirs(args.out, exist_ok=True)
    products = []

    height_path = os.path.join(args.out, "terrain_heightmap_master_1km.png")
    write_gray_png(height_path, height_rows, bit_depth=16)
    products.append(
        ("terrain_heightmap_master_1km", height_path, {"texture_sizes": {"r16": [SAMPLES, SAMPLES]}})
    )

    biome_path = os.path.join(args.out, "terrain_biome_mask.png")
    write_gray_png(biome_path, biome_rows, bit_depth=8)
    products.append(
        ("terrain_biome_mask", biome_path, {"texture_sizes": {"r8": [SAMPLES, SAMPLES]}})
    )

    surface_path = os.path.join(args.out, "terrain_surface_id_map.png")
    write_gray_png(surface_path, surface_rows, bit_depth=8)
    products.append(
        ("terrain_surface_id_map", surface_path, {"texture_sizes": {"r8": [SAMPLES, SAMPLES]}})
    )

    in_hash = input_hash(
        {
            "generator": "terrain_maps",
            "version": GENERATOR_VERSION,
            "seed": args.seed,
            "cells": CELLS,
            "max_height_m": MAX_HEIGHT_M,
            "water_level_m": WATER_LEVEL_M,
            "deep_water_depth_m": DEEP_WATER_DEPTH_M,
            "river_depth_m": RIVER_DEPTH_M,
            "river_bed_source_m": RIVER_BED_SOURCE_M,
            "river_bed_outlet_m": RIVER_BED_OUTLET_M,
            "river_half_width_m": RIVER_HALF_WIDTH_M,
            "river_bank_m": RIVER_BANK_M,
            "river_notch_m": RIVER_NOTCH_M,
            "river_head_v": RIVER_HEAD_V,
            "river_meander_u": RIVER_MEANDER_U,
            "river_meander_cycles": RIVER_MEANDER_CYCLES,
            "river_drift_u": RIVER_DRIFT_U,
            "surface_ids": SURFACE,
        }
    )

    # A sidecar recording the heightmap's scale, so the hydrology generator decodes it correctly
    # instead of duplicating the constants and drifting. The hash binds it to the exact file it
    # describes: a stale sidecar is caught rather than trusted.
    meta_path = os.path.join(args.out, "terrain_meta.json")
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "name": "terrain_meta",
                "note": "The scale of the heightmap beside this file. Read by hydrology.py; "
                "duplicating these numbers in another generator is how water ends up at the "
                "wrong height with no error.",
                "generator": "terrain_maps",
                "version": GENERATOR_VERSION,
                "seed": args.seed,
                "samples": SAMPLES,
                "cells": CELLS,
                "cell_spacing_m": CELL_SPACING_M,
                "max_height_m": MAX_HEIGHT_M,
                "water_level_m": WATER_LEVEL_M,
                "deep_water_depth_m": DEEP_WATER_DEPTH_M,
                "river_depth_m": RIVER_DEPTH_M,
                "river_bed_source_m": RIVER_BED_SOURCE_M,
                "river_bed_outlet_m": RIVER_BED_OUTLET_M,
                "river_head_v": RIVER_HEAD_V,
                "river_half_width_m": RIVER_HALF_WIDTH_M,
                "heightmap_sha256": sha256_file(height_path),
                "input_hash": in_hash,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")

    report = {
        "generator": "terrain_maps",
        "version": GENERATOR_VERSION,
        "seed": args.seed,
        "input_hash": in_hash,
        "assets": [],
    }
    for name, path, extra in products:
        sha = sha256_file(path)
        report["assets"].append(
            record(
                name,
                path,
                sha,
                in_hash,
                "terrain_maps/" + GENERATOR_VERSION,
                size_kb=os.path.getsize(path) // 1024,
                **extra
            )
        )

    # Coverage numbers, so the report says what was made rather than only that something was.
    surface_histogram = {}
    for row in surface_rows:
        for value in row:
            surface_histogram[value] = surface_histogram.get(value, 0) + 1
    total = SAMPLES * SAMPLES
    widths = sorted(river_widths)
    median_width = widths[len(widths) // 2] if widths else 0.0
    report["coverage"] = {
        "samples": SAMPLES,
        "surface_histogram": {str(k): v for k, v in sorted(surface_histogram.items())},
        "surface_percent": {
            str(k): round(100.0 * v / total, 2) for k, v in sorted(surface_histogram.items())
        },
        "height_min_m": round(min(heights), 2),
        "height_max_m": round(max(heights), 2),
        # The two shape numbers. `max_neighbour_step_m` is the cliff detector: a natural valley
        # does not jump 20 m between samples 1 m apart, and the first published terrain did.
        # `land_under_30_deg_percent` is the playability number: a hunting world that is mostly
        # unwalkable is not the valley the brief describes.
        "max_neighbour_step_m": round(max_step, 2),
        "max_neighbour_step_at": {
            "x": max_step_at[0],
            "y": max_step_at[1],
            "height_m": max_step_at[2],
            "neighbour_m": max_step_at[3],
        },
        "land_under_30_deg_percent": round(100.0 * land_under_30 / land_cells, 2)
        if land_cells
        else 0.0,
        "inner_valley_under_30_deg_percent": round(100.0 * inner_under_30 / inner_land, 2)
        if inner_land
        else 0.0,
        "water_percent": round(
            100.0
            * sum(
                1
                for row in surface_rows
                for value in row
                if value in (SURFACE["water_deep"], SURFACE["water_shallow"])
            )
            / total,
            2,
        ),
        # The river's own numbers: a run should say whether it made a river or a trench. The fall
        # is the drop of the water SURFACE from the lake's outlet to the mouth, which is what
        # "flowing" means here — a flat surface over a sloping bed is a flooded channel, not a river.
        "river_surface_at_lake_m": round(river_surface_m(RIVER_HEAD_V), 2),
        "river_surface_at_mouth_m": round(river_surface_m(0.0), 2),
        "river_fall_m": round(river_surface_m(RIVER_HEAD_V) - river_surface_m(0.0), 2),
        # What the water actually covers, against what was carved. A river that reads as a river
        # from a distance is wide on the screen, and "wide" is the wet width rather than the
        # constant: a shallow carve in a tall bank puts most of the water on a shelf.
        "river_channel_width_m": round(2.0 * RIVER_HALF_WIDTH_M, 1),
        "river_wet_width_median_m": round(median_width, 1),
        "river_wet_width_min_m": round(widths[0], 1) if widths else 0.0,
        "river_depth_m": RIVER_DEPTH_M,
        "deep_water_depth_m": DEEP_WATER_DEPTH_M,
    }

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")

    print("terrain: %d² samples, height %.1f..%.1f m" % (
        SAMPLES, report["coverage"]["height_min_m"], report["coverage"]["height_max_m"]))
    print("water: %.2f%% of the map" % report["coverage"]["water_percent"])
    print(
        "river: %.1f m wet across a %.0f m channel, surface %.1f -> %.1f m"
        % (
            report["coverage"]["river_wet_width_median_m"],
            report["coverage"]["river_channel_width_m"],
            report["coverage"]["river_surface_at_lake_m"],
            report["coverage"]["river_surface_at_mouth_m"],
        )
    )
    for key, value in report["coverage"]["surface_percent"].items():
        print("  surface %s: %.2f%%" % (key, value))
    for asset in report["assets"]:
        print("%s: %s (%d KB)" % (asset["name"], asset["sha256"][:16], asset["size_kb"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
