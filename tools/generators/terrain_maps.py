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

1025² rather than 1024² so texel centres land on grid vertices: a 1024-cell terrain needs 1025
height samples, and using 1024 makes the last row of cells share the edge sample.
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

# Where the water sits. A single level keeps the hydrology honest: a river cannot run uphill, and
# a basin cannot hold water below the level it drains at.
#
# The valley floor is deliberately ABOVE this level and only the carved river and bog bowl go
# below it. That is what makes water read as a feature in the land rather than as a sea the land
# pokes out of.
WATER_LEVEL_M = 32.0
DEEP_WATER_M = 22.0

# How the height field is composed, in normalised units. The floor sits at 0.22 (44 m) and the
# noise moves it by 0.14 (28 m), so the valley is 44..72 m — comfortably above the waterline, and
# the bog and river are carved below it deliberately. The rim contributes the remaining 0.50
# (100 m), concentrated at the edge by RIM_POWER.
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
# 0.45 / 2.6 that peaks at 0.47 — a ridge you can walk up, well below the 35° rock threshold, so
# bare rock appears only where the noise adds enough on top of it.
FLOOR = 0.22
NOISE_AMPLITUDE = 0.14
RIM_AMPLITUDE = 0.43
RIM_POWER = 2.3

# The river. The first version carved a band 0.09 of the map wide — 90 m either side — down by
# 70 % of the terrain's own height, which is a canyon, not a stream: the measured channel was about
# 200 m across and ~100 m deep and its floor sat 13 m above the waterline, so most of the river was
# dry. A river a hunter can step over is 8 m wide, cut a few metres into the valley floor, and it
# descends from the bog to the outlet so the water on it can actually flow.
RIVER_HALF_WIDTH_M = 8.0
# The bank is a floodplain, not a wall. The valley floor sits at 44-72 m and the waterline at 32 m,
# so the channel is necessarily cut 20-40 m down; over a 24 m bank that is a 50 degree wall for the
# half-kilometre of its length, which alone put the walkable fraction under the gate.
RIVER_BANK_M = 80.0
# How wide the rim opens to let the river out. The notch is deliberately much wider than the
# channel: a rim 100 m high that drops over the 32 m of the bank is a wall, and measured as one.
RIVER_NOTCH_M = 200.0
RIVER_DEPTH_M = 1.4
# Bed height at the bog and at the northern edge, in metres. Both end below the waterline on
# purpose: a river whose bed is above lake level is a dry channel, which is what the first
# published terrain had — a carved trench with a floor 13 m above the water and nothing in it.
RIVER_BED_SOURCE_M = 30.0
RIVER_BED_OUTLET_M = 29.0

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

    A straight line reads as a canal. Two low-frequency sine terms make it wander the way water
    does, and they are functions of v alone so the channel is continuous along its whole length —
    the previous version cut the carve off at v = 0.72, which put a 14-23 m cliff straight across
    the map where the carving stopped.
    """
    t = max(0.0, min(1.0, (BOG_CENTRE_V - v) / BOG_CENTRE_V))
    return BOG_CENTRE_U + 0.035 * math.sin(t * 6.0) + 0.055 * t


def river_bed_m(v):
    """Bed height along the river, descending from the bog to the outlet."""
    t = max(0.0, min(1.0, (BOG_CENTRE_V - v) / BOG_CENTRE_V))
    return RIVER_BED_SOURCE_M + (RIVER_BED_OUTLET_M - RIVER_BED_SOURCE_M) * t


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
    for y in range(SAMPLES):
        v = y / (CELLS - 1)
        row = [0.0] * SAMPLES
        for x in range(SAMPLES):
            u = x / (CELLS - 1)

            # The river channel, computed before the rim because the rim has to open for it. A
            # river leaves a valley through a notch; cutting a slot straight through the rim
            # instead put a 150 m wall either side of the water at the map edge, which is exactly
            # what the measured 13.3 m neighbour step was.
            #
            # `taper` fades the channel in and out along v rather than switching it on at a row.
            # Both previous versions ended the carve with an `if` on v, and each one left a cliff
            # at that row: that is the same fault twice, so the boundary is a smoothstep now.
            taper = smoothstep(0.0, 0.10, v) * (1.0 - smoothstep(BOG_CENTRE_V, BOG_CENTRE_V + 0.10, v))
            channel = 0.0
            notch = 0.0
            bed_norm = 0.0
            if taper > 0.0:
                distance_m = abs(u - river_centre_u(v)) * 1000.0
                channel = taper * (
                    1.0 - smoothstep(RIVER_HALF_WIDTH_M, RIVER_HALF_WIDTH_M + RIVER_BANK_M, distance_m)
                )
                # The notch is much wider than the channel on purpose. The rim is 70-150 m high,
                # so scaling it by a weight that changes over the 32 m of the bank put an 8 m step
                # per texel into the map — measured at x=299, y=99, 91.9 m against 99.9 m. The
                # valley opens over 200 m, which is a slope rather than a wall.
                notch = taper * (1.0 - smoothstep(0.0, RIVER_NOTCH_M, distance_m))
                bed_norm = river_bed_m(v) / MAX_HEIGHT_M

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
    return smoothed


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


def classify_surface(height_m, gradient, biome, noise):
    """One surface id per cell. Ordered: water wins, then the shore, then what grows there."""
    if height_m < DEEP_WATER_M:
        return SURFACE["water_deep"]
    if height_m < WATER_LEVEL_M:
        return SURFACE["water_shallow"]

    # The shoreline is sand or gravel, decided by noise so it is not a uniform ring.
    if height_m < WATER_LEVEL_M + 1.5:
        return SURFACE["sand"] if noise < 0.6 else SURFACE["gravel"]

    if biome & BIOME_BOG:
        return SURFACE["mud"] if noise < 0.7 else SURFACE["clay"]

    if biome & BIOME_RIVERBED:
        return SURFACE["wet_stone"] if gradient > SLOPE_RIVER_STONE else SURFACE["gravel"]

    # Steep ground is bare rock whatever grows around it; a 29° slope does not hold soil.
    if gradient > SLOPE_ROCK:
        return SURFACE["wet_stone"]
    if gradient > SLOPE_SCREE:
        return SURFACE["gravel"] if noise < 0.5 else SURFACE["wet_stone"]

    if biome & BIOME_CLEARING:
        return SURFACE["grass"]
    if biome & BIOME_FOREST:
        return SURFACE["moss"] if noise < 0.55 else SURFACE["grass"]
    return SURFACE["grass"]


def classify_biome(height_m, gradient, bog_distance, forest_noise):
    bits = 0
    if bog_distance < BOG_RADIUS_U * 2.0 and height_m < WATER_LEVEL_M + 6.0:
        bits |= BIOME_BOG
    if height_m >= WATER_LEVEL_M and forest_noise > 0.45:
        bits |= BIOME_FOREST
    if gradient > SLOPE_ROCK:
        bits |= BIOME_RIDGE
    if height_m < WATER_LEVEL_M + 2.0:
        bits |= BIOME_RIVERBED
    # Clearings are where the forest noise dips: gaps in the canopy, which is what a hunting game
    # needs to be readable from a distance.
    if height_m >= WATER_LEVEL_M + 2.0 and forest_noise < 0.28:
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

    field = shape_height(base, valley)

    height_rows = []
    biome_rows = []
    surface_rows = []
    heights = []
    max_step = 0.0
    max_step_at = (0, 0, 0.0, 0.0)
    land_cells = 0
    land_under_30 = 0

    for y in range(SAMPLES):
        height_row = []
        biome_row = []
        surface_row = []
        v = y / (CELLS - 1)
        for x in range(SAMPLES):
            u = x / (CELLS - 1)
            h_m = height_metres(field[y][x])
            height_row.append(int(round(field[y][x] * 65535)))
            heights.append(h_m)

            gradient = slope(field, x, y)
            bog_dx = (u - BOG_CENTRE_U) * 2.0
            bog_dy = (v - BOG_CENTRE_V) * 2.0
            bog_distance = (bog_dx * bog_dx + bog_dy * bog_dy) ** 0.5

            biome = classify_biome(h_m, gradient, bog_distance, forest[y][x])
            biome_row.append(biome)
            surface_row.append(classify_surface(h_m, gradient, biome, detail[y][x]))

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
            if h_m >= WATER_LEVEL_M:
                land_cells += 1
                if gradient < math.tan(math.radians(30.0)):
                    land_under_30 += 1

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
            "deep_water_m": DEEP_WATER_M,
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
                "deep_water_m": DEEP_WATER_M,
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
    }

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")

    print("terrain: %d² samples, height %.1f..%.1f m" % (
        SAMPLES, report["coverage"]["height_min_m"], report["coverage"]["height_max_m"]))
    print("water: %.2f%% of the map" % report["coverage"]["water_percent"])
    for key, value in report["coverage"]["surface_percent"].items():
        print("  surface %s: %.2f%%" % (key, value))
    for asset in report["assets"]:
        print("%s: %s (%d KB)" % (asset["name"], asset["sha256"][:16], asset["size_kb"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
