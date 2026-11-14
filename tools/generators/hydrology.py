#!/usr/bin/env python3
"""Derive hydrology from the 1 km heightmap: water depth, flow direction, shore and river lines.

Run:
    python tools/generators/hydrology.py --heightmap artifacts/terrain/terrain_heightmap_master_1km.png \
        --out artifacts/terrain

Why derive rather than author: water has to obey the land. A river drawn by hand runs uphill
somewhere, and a bog basin painted on a slope drains. This reads the heightmap that the terrain
was built from, so the water is where gravity puts it by construction rather than by care.

The method is D8 flow accumulation, the standard approach and the reason it is standard:

  1. Fill the depressions. D8 follows only a strictly lower neighbour, so a level surface has no
     drainage at all; the bog basin and the near-level channel both needed raising to their spill
     level before anything could be routed across them. Skip this and the highest-flow cell is a
     sink in the middle of the map rather than an outlet — which is exactly what the first
     published river was.
  2. For each cell, find the steepest of its eight neighbours that is lower.
  3. Process cells from highest to lowest, adding each cell's accumulated area to the cell it
     drains into. Because every upstream cell is higher, it has already been processed by the time
     a cell is reached, so one pass gives the full upstream area.
  4. Where the accumulated area is large, there is a channel. Where the height is below the water
     level, there is standing water.

The outlet is the boundary cell that collects the most water, and the centreline is walked
upstream from it. Both halves matter: "highest flow anywhere" and "where the water leaves the map"
are the same cell only when the field has no sinks.

Outputs:
  terrain_hydrology_mask   RGB8, 1025², R = water depth (0..8 m), G,B = flow direction as a unit
                           vector (0..255 mapped to -1..1). A vector rather than an angle so that
                           bilinear filtering between neighbouring texels is meaningful.
                           AXIS CONVENTION: G is the east component (cos of the angle, so +G points
                           towards increasing x) and B is the south component (sin, so +B points
                           towards increasing row index, i.e. south on the map as drawn). A neutral
                           texel is (128,128): no flow, or a cell whose neighbours are all higher.
  terrain_shore_mask       R8,  1025², 255 at the waterline falling to 0 over 4 m
  terrain_river_splines    JSON, the main stem, headwater to outlet
  terrain_water_level_table JSON, the water surface height and flow at each centreline point
"""

import argparse
import collections
import heapq
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    GENERATOR_VERSION,
    input_hash,
    read_png,
    record,
    sha256_file,
    write_gray_png,
    write_png,
)

CELLS = 1024
SAMPLES = CELLS + 1
CELL_SPACING_M = 1000.0 / CELLS

# MAX_HEIGHT_M and WATER_LEVEL_M are read from the heightmap's sidecar metadata, not duplicated
# here. They were duplicated at first, bound together only by a comment saying "must match", and
# that is the exact shape of a silent bug: change the relief in one file and the hydrology decodes
# the heightmap at the wrong scale, producing water in the wrong places with no error.

# The mask encodes depth as 0..255 over this range. 8 m is deeper than the deepest point of the
# bog, so nothing clamps and the encoding is lossless for this terrain.
MAX_MASK_DEPTH_M = 8.0

# A cell drains into its steepest downhill neighbour among these eight.
NEIGHBOURS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)

# Flow accumulation is in cells. A channel is where more than this many cells drain through one
# point: about 1,200 m² of catchment, which is a stream rather than a wet patch.
RIVER_FLOW_CELLS = 1200.0

# A river cell that is above the waterline still holds water, to this depth. Without it the river
# would appear only where the land happened to dip below the lake level, and the channel carved
# into the terrain would read as a dry gully.
RIVER_DEPTH_M = 1.2

SHORE_FALLOFF_M = 4.0


def index(x, y):
    return y * SAMPLES + x


def read_meta(path, heightmap_path):
    """The heightmap's own account of its scale, checked against the file it describes.

    A sidecar rather than a duplicated constant: the heightmap is normalised 0..65535, so the
    metres it represents live only in the file that wrote it. Reading them back is the difference
    between a contract and a comment.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except OSError as exc:
        raise SystemExit(
            "cannot read %s (%s). terrain_maps.py writes this alongside the heightmap; without it "
            "the heightmap's scale is unknown and the water would be placed at the wrong height."
            % (path, exc)
        )
    except json.JSONDecodeError as exc:
        raise SystemExit("%s is not valid JSON (%s)" % (path, exc))

    for field in ("max_height_m", "water_level_m", "samples"):
        if field not in meta:
            raise SystemExit("%s has no %s" % (path, field))
    if meta["samples"] != SAMPLES:
        raise SystemExit(
            "%s was written at %d samples but this generator works on %d"
            % (path, meta["samples"], SAMPLES)
        )
    recorded = meta.get("heightmap_sha256")
    actual = sha256_file(heightmap_path)
    if recorded and recorded != actual:
        raise SystemExit(
            "%s describes a heightmap with sha256 %s but %s is %s; the sidecar is stale"
            % (path, recorded[:16], heightmap_path, actual[:16])
        )
    return meta


def read_heightmap(path):
    """The heightmap as flat normalised heights, and its size checked against this generator."""
    width, height, channels, rows = read_png(path)
    if channels != 1:
        raise SystemExit("%s has %d channels; the heightmap must be single-channel" % (path, channels))
    if (width, height) != (SAMPLES, SAMPLES):
        raise SystemExit(
            "%s is %dx%d but this generator works on %dx%d; it must match terrain_maps.py"
            % (path, width, height, SAMPLES, SAMPLES)
        )
    flat = []
    for row in rows:
        flat.extend(row)
    return flat


def compute_downhill(heights, samples=SAMPLES):
    """For each cell, the index of its steepest lower neighbour, or -1 for a pit.

    Steepest means steepest GRADIENT, not largest drop. A diagonal neighbour is sqrt(2) cells
    away, so an equal drop across it is a gentler slope. The first version compared raw drops,
    which made a diagonal tie with a cardinal neighbour and — because the neighbour list is
    scanned in a fixed order — win it. On a uniform slope that sends flow zig-zagging diagonally
    instead of running straight down the fall line, which on real terrain shows up as spurious
    diagonal channels in the river network.

    `samples` is a parameter rather than the module constant so this can be tested on a small
    grid. The first version read the global, which made the accumulation untestable — and flow
    accumulation is exactly the kind of code that is subtly wrong and still looks plausible.
    """
    downhill = [-1] * len(heights)
    for y in range(samples):
        row = y * samples
        for x in range(samples):
            here = row + x
            h = heights[here]
            best = -1
            best_slope = 0.0
            for dx, dy in NEIGHBOURS:
                nx = x + dx
                ny = y + dy
                if 0 <= nx < samples and 0 <= ny < samples:
                    other = ny * samples + nx
                    drop = h - heights[other]
                    if drop <= 0:
                        continue
                    slope = drop / math.hypot(dx, dy)
                    if slope > best_slope:
                        best_slope = slope
                        best = other
            downhill[here] = best
    return downhill


def accumulate(heights, downhill, samples=SAMPLES):
    """Upstream area in cells, by processing from highest to lowest.

    A counting sort by height rather than a comparison sort: heights are 16-bit integers, so 65536
    buckets put a million cells in order in one pass instead of sorting them.

    The direction of this loop is the whole algorithm. Visiting from highest to lowest means every
    cell's upstream contributors have already been counted when it is reached. Visiting the other
    way gives a map that still looks like a river network and has the flow running backwards.
    """
    buckets = [[] for _ in range(65536)]
    for cell, h in enumerate(heights):
        buckets[h].append(cell)

    flow = [1.0] * len(heights)
    for h in range(65535, -1, -1):
        for cell in buckets[h]:
            target = downhill[cell]
            if target >= 0:
                flow[target] += flow[cell]
    return flow


def fill_depressions(heights, samples=SAMPLES):
    """Raise every enclosed pit to the level at which its water can escape.

    D8 can only follow a neighbour that is strictly lower, so a perfectly flat surface has no
    downhill direction at all. This terrain contains two of them by construction: the bog basin,
    which is deliberately level so it can hold water, and the carved river bed, which descends
    about a metre over the whole valley — well under one 16-bit step every other row, and rounded
    to nothing at all by the 3x3 smoothing pass in terrain_maps.py. Both were pit fields.

    The consequence was not subtle once it was looked for. With every flat area a pit, the cell
    that collects the most water is a *sink*, not an outlet: the published centreline ran from the
    eastern rim at 105 m to a hole in the middle of the map at 52 m and stopped there, and the
    water level table duly reported a river surface 21 m above the lake. The real river sits at
    29-30 m in the channel the terrain generator carved. Every gate passed, because each one asked
    whether the line descended and whether the water sat above its bed, and it did both.

    Priority-flood: seed the boundary — the only place water can leave the map — and visit cells
    in order of the level water would have to reach to get there. A cell lower than its own escape
    level is raised to that level plus one step, which is the smallest amount that opens a
    downstream neighbour, so the drainage direction is unchanged wherever the ground was already
    descending.

    One step is one 16-bit count — 3 mm — because the fill is a device for finding the channel,
    not a claim about the bog's depth. Every consumer of the real heights (the depth mask, the
    shore mask, the water level table) keeps using the unfilled field.
    """
    filled = list(heights)
    closed = [False] * len(heights)
    heap = []
    for cell in range(len(heights)):
        x = cell % samples
        y = cell // samples
        if x == 0 or y == 0 or x == samples - 1 or y == samples - 1:
            closed[cell] = True
            heap.append((filled[cell], cell))
    # A sorted list is already a valid heap, so this seeds the queue without a heapify pass.
    heap.sort()

    while heap:
        level, cell = heapq.heappop(heap)
        x = cell % samples
        y = cell // samples
        for dx, dy in NEIGHBOURS:
            nx = x + dx
            ny = y + dy
            if not (0 <= nx < samples and 0 <= ny < samples):
                continue
            other = ny * samples + nx
            if closed[other]:
                continue
            closed[other] = True
            if filled[other] <= level:
                # Clamped because accumulate() buckets by 16-bit value, so a raised cell has to
                # stay inside the range the heightmap can represent.
                filled[other] = min(65535, level + 1)
            heapq.heappush(heap, (filled[other], other))
    return filled


def choose_outlet(flow, samples=SAMPLES):
    """The boundary cell that collects the most water: where the river leaves the map.

    The outlet used to be the highest-flow cell anywhere. That is only the same thing when the
    field has no sinks, and when it has one the answer is the sink — a cell in the middle of the
    map with no way out, which is not an outlet and cannot serve as one. A river that ends inland
    has not left the valley, so "on the boundary" is part of the definition of an outlet rather
    than a lucky property of the terrain.
    """
    best = -1
    best_flow = -1.0
    for cell, flow_cells in enumerate(flow):
        x = cell % samples
        y = cell // samples
        if x != 0 and y != 0 and x != samples - 1 and y != samples - 1:
            continue
        if flow_cells > best_flow:
            best_flow = flow_cells
            best = cell
    return best


def shore_distance(water, samples=SAMPLES):
    """Cells to the nearest water cell, capped. A BFS, so the falloff is exact rather than a blur."""
    limit = int(SHORE_FALLOFF_M / CELL_SPACING_M) + 1
    distance = [limit + 1] * len(water)
    queue = collections.deque()
    for cell, is_water in enumerate(water):
        if is_water:
            distance[cell] = 0
            queue.append(cell)
    while queue:
        cell = queue.popleft()
        d = distance[cell] + 1
        if d > limit:
            continue
        x = cell % samples
        y = cell // samples
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx = x + dx
            ny = y + dy
            if 0 <= nx < samples and 0 <= ny < samples:
                other = ny * samples + nx
                if distance[other] > d:
                    distance[other] = d
                    queue.append(other)
    return distance, limit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--heightmap", required=True)
    parser.add_argument(
        "--meta",
        default="",
        help="the heightmap's sidecar metadata (default: terrain_meta.json beside it)",
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", default="drowned-greenwood-v1")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    meta_path = args.meta or os.path.join(
        os.path.dirname(os.path.abspath(args.heightmap)), "terrain_meta.json"
    )
    meta = read_meta(meta_path, args.heightmap)
    max_height_m = float(meta["max_height_m"])
    water_level_m = float(meta["water_level_m"])

    heights = read_heightmap(args.heightmap)
    metres = [h / 65535.0 * max_height_m for h in heights]

    # Filled first, then routed. Without the fill the bog and the carved channel are pit fields
    # and the highest-flow cell is a sink; see fill_depressions for what that produced.
    filled = fill_depressions(heights)
    downhill = compute_downhill(filled)
    flow = accumulate(filled, downhill)

    # Water: standing where the land is below the waterline, and a channel where enough ground
    # drains through. Both are needed — a bog is standing water in a flat bowl with almost no
    # catchment, and a river is a channel that is usually above the lake level.
    water = [False] * len(metres)
    depth = [0.0] * len(metres)
    for cell, h_m in enumerate(metres):
        # Water is defined here by exactly the rule the surface-ID map uses: ground below the
        # waterline. It used to also count every high-flow cell as water, which reported 5.80 %
        # water against the surface map's 4.53 % — two answers to one question, which is the same
        # class of disagreement as two classifications for one cell.
        if h_m < water_level_m:
            water[cell] = True
            depth[cell] = min(MAX_MASK_DEPTH_M, water_level_m - h_m)

    # Flow direction as an angle, quantised to 8 bits. 0 means "no flow" — a pit or a cell that
    # holds water flows nowhere — so the angle is encoded 1..255 to keep 0 free. The first version
    # used `(angle + pi) / 2pi * 255 & 0xFF`, which maps due west to 255 and, for the -pi that
    # atan2 can return on a negative zero, to 0: a flowing cell that reported "no flow".
    direction = [0] * len(metres)
    for cell, target in enumerate(downhill):
        if target < 0:
            continue
        dx = (target % SAMPLES) - (cell % SAMPLES)
        dy = (target // SAMPLES) - (cell // SAMPLES)
        angle = math.atan2(dy, dx)
        direction[cell] = 1 + int(round((angle + math.pi) / (2 * math.pi) * 254))

    distance, limit = shore_distance(water)

    os.makedirs(args.out, exist_ok=True)
    products = []

    hydrology_rows = []
    for y in range(SAMPLES):
        row = []
        for x in range(SAMPLES):
            cell = index(x, y)
            encoded_depth = int(round(min(1.0, depth[cell] / MAX_MASK_DEPTH_M) * 255))
            # Direction as a unit VECTOR in two channels, not an angle in one.
            #
            # An angle does not interpolate: a texel at 10 degrees and one at 350 average to 180,
            # which is the opposite direction. A vector does interpolate correctly, so a shader can
            # sample this with ordinary bilinear filtering. And a grey+alpha PNG is not "R and G"
            # — it is luminance plus alpha, and Godot would put the second channel in A — so this
            # is RGB with the third channel unused.
            if direction[cell] == 0:
                # No flow: the neutral vector, which is also what a filtered edge should blend to.
                dx_encoded = 128
                dy_encoded = 128
            else:
                angle = (direction[cell] - 1) / 254.0 * 2.0 * math.pi - math.pi
                dx_encoded = int(round((math.cos(angle) * 0.5 + 0.5) * 255))
                dy_encoded = int(round((math.sin(angle) * 0.5 + 0.5) * 255))
            row.append(encoded_depth)
            row.append(dx_encoded)
            row.append(dy_encoded)
        hydrology_rows.append(row)
    hydrology_path = os.path.join(args.out, "terrain_hydrology_mask.png")
    write_png(hydrology_path, hydrology_rows, bit_depth=8, channels=3)
    products.append(("terrain_hydrology_mask", hydrology_path,
                     {"texture_sizes": {"rgb8": [SAMPLES, SAMPLES]}}))

    shore_rows = []
    for y in range(SAMPLES):
        row = []
        for x in range(SAMPLES):
            cell = index(x, y)
            d = distance[cell]
            if d == 0:
                row.append(255)
            elif d > limit:
                row.append(0)
            else:
                # Linear falloff from the waterline. A shore is a band, and a hard edge would
                # look like a decal rather than like wet ground.
                row.append(int(round(255 * (1.0 - d / float(limit + 1)))))
        shore_rows.append(row)
    shore_path = os.path.join(args.out, "terrain_shore_mask.png")
    write_gray_png(shore_path, shore_rows, bit_depth=8)
    products.append(("terrain_shore_mask", shore_path,
                     {"texture_sizes": {"r8": [SAMPLES, SAMPLES]}}))

    # The river centreline: the main stem, from its headwater down to where it leaves the map.
    #
    # Two earlier attempts were wrong in instructive ways:
    #   1. The highest-flow cell in each row. Not a centreline: where a channel runs across a row
    #      several cells have similar flow and the winner jumps between them, so consecutive
    #      points do not descend. Measured: "477 of 941 segments go uphill".
    #   2. Start from the highest cell with flow above the threshold. That cell is almost always a
    #      PIT, because flow accumulates into sinks — so the trace stopped after one point.
    #
    # So: find the outlet (the single cell that collects the most water), then walk UPSTREAM by
    # repeatedly taking the neighbour that drains into the current cell with the most flow. That
    # finds the main stem by construction, and reversing it gives a path that descends at every
    # step.
    outlet = choose_outlet(flow, SAMPLES)

    path = []
    if outlet >= 0:
        cell = outlet
        for _step in range(SAMPLES * 2):
            path.append(cell)
            x = cell % SAMPLES
            y = cell // SAMPLES
            upstream = -1
            upstream_flow = 0.0
            for dx, dy in NEIGHBOURS:
                nx = x + dx
                ny = y + dy
                if 0 <= nx < SAMPLES and 0 <= ny < SAMPLES:
                    other = ny * SAMPLES + nx
                    if downhill[other] == cell and flow[other] > upstream_flow:
                        upstream_flow = flow[other]
                        upstream = other
            if upstream < 0:
                break
            cell = upstream
        path.reverse()

    # How much of the traced channel is actually wet. This is the number the old gates were
    # missing: a centreline can descend perfectly, carry plenty of points and still run up a
    # hillside, because "descends" says nothing about whether it is on the river. Measured on the
    # published maps before the fill was added, this was 0.0 % of 321 points.
    on_water = sum(1 for cell in path if water[cell])
    above_waterline = len(path) - on_water
    outlet_on_boundary = outlet >= 0 and (
        outlet % SAMPLES in (0, SAMPLES - 1) or outlet // SAMPLES in (0, SAMPLES - 1)
    )

    spline = []
    for cell in path:
        x = cell % SAMPLES
        y = cell // SAMPLES
        spline.append(
            {
                "x": x,
                "y": y,
                "u": round(x / CELLS, 5),
                "v": round(y / CELLS, 5),
                "height_m": round(metres[cell], 2),
                "flow_cells": int(flow[cell]),
            }
        )

    spline_path = os.path.join(args.out, "terrain_river_splines.json")
    with open(spline_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "name": "terrain_river_splines",
                "note": "The main stem: the highest-flow boundary cell's upstream chain, reversed, "
                "so it runs from headwater to outlet and descends at every step. Flow is in "
                "upstream cells. The depressions were filled before the routing, so the chain can "
                "cross the level bog and the near-level channel instead of dying in the first "
                "pit it meets.",
                "samples": SAMPLES,
                "flow_threshold_cells": int(RIVER_FLOW_CELLS),
                "points": spline,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    products.append(("terrain_river_splines", spline_path, {}))

    # The water level table: the surface height at each spline point, so a water shader or a
    # swimming check does not have to re-derive it.
    level_path = os.path.join(args.out, "terrain_water_level_table.json")
    levels = [
        {
            "x": point["x"],
            "y": point["y"],
            "v": point["v"],
            "bed_height_m": point["height_m"],
            # The surface must sit ABOVE the bed, or the water is inside the ground and invisible.
            # This read `height_m - RIVER_DEPTH_M`, which is a sign error: for the first 226 of
            # 655 points the surface was 1.2 m below the riverbed and the upper river did not
            # exist. Where the bed is below the lake level the lake level wins, because the river
            # is then part of the lake.
            "water_surface_m": round(max(water_level_m, point["height_m"] + RIVER_DEPTH_M), 2),
        }
        for point in spline
    ]
    with open(level_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "name": "terrain_water_level_table",
                "note": "The water surface at each river centreline point. The carved bed sits "
                "below the lake level along the whole channel, so max(lake, bed + depth) is the "
                "lake level at every point: one flat water surface, not a river stepping down "
                "its bed. Whether the channel should instead sit above the lake is an open "
                "design question, recorded in reports/phase2.md.",
                "lake_level_m": water_level_m,
                "levels": levels,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    products.append(("terrain_water_level_table", level_path, {}))

    in_hash = input_hash(
        {
            "generator": "hydrology",
            "version": GENERATOR_VERSION,
            "seed": args.seed,
            "heightmap_sha256": sha256_file(args.heightmap),
            "water_level_m": water_level_m,
            "river_flow_cells": RIVER_FLOW_CELLS,
            "max_mask_depth_m": MAX_MASK_DEPTH_M,
        }
    )

    water_cells = sum(1 for w in water if w)
    report = {
        "generator": "hydrology",
        "version": GENERATOR_VERSION,
        "seed": args.seed,
        "input_hash": in_hash,
        "coverage": {
            "samples": SAMPLES,
            "water_cells": water_cells,
            "water_percent": round(100.0 * water_cells / len(water), 2),
            "river_points": len(spline),
            "max_flow_cells": int(max(flow)),
            "shore_cells": sum(1 for d in distance if 0 < d <= limit),
            # The three numbers that decide whether the traced line is a river at all. "Every
            # segment descends" is true of a gully on a hillside, so it was never sufficient.
            "river_on_water_percent": round(100.0 * on_water / len(spline), 2) if spline else 0.0,
            "river_points_above_waterline": above_waterline,
            "outlet_on_boundary": outlet_on_boundary,
            "outlet_flow_cells": int(flow[outlet]) if outlet >= 0 else 0,
            "river_flow_threshold_cells": int(RIVER_FLOW_CELLS),
            "depressions_filled_cells": sum(1 for a, b in zip(heights, filled) if b != a),
            "filled_rise_max_m": round(
                max((b - a for a, b in zip(heights, filled)), default=0) / 65535.0 * max_height_m,
                3,
            ),
        },
        "assets": [],
    }
    for name, path, extra in products:
        report["assets"].append(
            record(
                name,
                path,
                sha256_file(path),
                in_hash,
                "hydrology/" + GENERATOR_VERSION,
                size_kb=os.path.getsize(path) // 1024,
                **extra
            )
        )

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")

    print(
        "hydrology: %.2f%% water, %d river points (%.1f%% on water, %d above the waterline), "
        "outlet %s with %d cells, max flow %d, %d shore cells, %d depressions filled"
        % (
            report["coverage"]["water_percent"],
            report["coverage"]["river_points"],
            report["coverage"]["river_on_water_percent"],
            report["coverage"]["river_points_above_waterline"],
            "on the boundary" if report["coverage"]["outlet_on_boundary"] else "INLAND",
            report["coverage"]["outlet_flow_cells"],
            report["coverage"]["max_flow_cells"],
            report["coverage"]["shore_cells"],
            report["coverage"]["depressions_filled_cells"],
        )
    )
    for asset in report["assets"]:
        print("%s: %s (%d KB)" % (asset["name"], asset["sha256"][:16], asset["size_kb"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
