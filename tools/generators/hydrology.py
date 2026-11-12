#!/usr/bin/env python3
"""Derive hydrology from the 1 km heightmap: water depth, flow direction, shore and river lines.

Run:
    python tools/generators/hydrology.py --heightmap artifacts/terrain/terrain_heightmap_master_1km.png \
        --out artifacts/terrain

Why derive rather than author: water has to obey the land. A river drawn by hand runs uphill
somewhere, and a bog basin painted on a slope drains. This reads the heightmap that the terrain
was built from, so the water is where gravity puts it by construction rather than by care.

The method is D8 flow accumulation, the standard approach and the reason it is standard:

  1. For each cell, find the steepest of its eight neighbours that is lower.
  2. Process cells from highest to lowest, adding each cell's accumulated area to the cell it
     drains into. Because every upstream cell is higher, it has already been processed by the time
     a cell is reached, so one pass gives the full upstream area.
  3. Where the accumulated area is large, there is a channel. Where the height is below the water
     level, there is standing water.

Outputs:
  terrain_hydrology_mask   LA8, 1025², R = water depth (0..8 m), G = flow direction (0..360°)
  terrain_shore_mask       R8,  1025², 255 at the waterline falling to 0 over 4 m
  terrain_river_splines    JSON, one centreline point per row where the channel is wide enough
  terrain_water_level_table JSON, the water surface height and flow at each of those points
"""

import argparse
import collections
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

    downhill = compute_downhill(heights)
    flow = accumulate(heights, downhill)

    # Water: standing where the land is below the waterline, and a channel where enough ground
    # drains through. Both are needed — a bog is standing water in a flat bowl with almost no
    # catchment, and a river is a channel that is usually above the lake level.
    water = [False] * len(metres)
    depth = [0.0] * len(metres)
    for cell, h_m in enumerate(metres):
        if h_m < water_level_m:
            water[cell] = True
            depth[cell] = min(MAX_MASK_DEPTH_M, water_level_m - h_m)
        elif flow[cell] >= RIVER_FLOW_CELLS:
            water[cell] = True
            # Deeper where more ground drains through, saturating at the channel depth.
            share = min(1.0, flow[cell] / (RIVER_FLOW_CELLS * 20.0))
            depth[cell] = RIVER_DEPTH_M * (0.5 + 0.5 * share)

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
            row.append(encoded_depth)
            row.append(direction[cell])
        hydrology_rows.append(row)
    hydrology_path = os.path.join(args.out, "terrain_hydrology_mask.png")
    write_png(hydrology_path, hydrology_rows, bit_depth=8, channels=2)
    products.append(("terrain_hydrology_mask", hydrology_path,
                     {"texture_sizes": {"la8": [SAMPLES, SAMPLES]}}))

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
    outlet = -1
    best_flow = -1.0
    for cell, flow_cells in enumerate(flow):
        if flow_cells > best_flow:
            best_flow = flow_cells
            outlet = cell

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
                "note": "The main stem: the highest-flow cell's upstream chain, reversed, so it "
                "runs from headwater to outlet and descends at every step. Flow is in upstream "
                "cells.",
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
            "water_surface_m": round(max(water_level_m, point["height_m"] - RIVER_DEPTH_M), 2),
        }
        for point in spline
    ]
    with open(level_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "name": "terrain_water_level_table",
                "note": "The water surface at each river centreline point. A single lake level "
                "plus a carved channel, so the surface is level across the bog and steps down "
                "the river.",
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
        "hydrology: %.2f%% water, %d river points, max flow %d cells, %d shore cells"
        % (
            report["coverage"]["water_percent"],
            report["coverage"]["river_points"],
            report["coverage"]["max_flow_cells"],
            report["coverage"]["shore_cells"],
        )
    )
    for asset in report["assets"]:
        print("%s: %s (%d KB)" % (asset["name"], asset["sha256"][:16], asset["size_kb"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
