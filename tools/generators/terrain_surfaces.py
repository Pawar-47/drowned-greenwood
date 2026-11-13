#!/usr/bin/env python3
"""Derive the terrain's material maps: normal map, splat weights, macro noise, blend rules.

Run:
    python tools/generators/terrain_surfaces.py \
        --heightmap artifacts/terrain/terrain_heightmap_master_1km.png --out artifacts/terrain

Why the splat weights are computed rather than blurred: the obvious way to turn a surface-ID map
into splat weights is a hard mask per surface followed by a blur. A blur is expensive in pure
Python at 1025² and, worse, it smears weights across a cliff edge where the transition should be
sharp. Instead the weights are continuous functions of the same quantities the classifier used —
slope and height — so they blend smoothly by construction and sharply where the terrain itself is
sharp. A rock face and a meadow meet along a slope threshold, not along a Gaussian.

Outputs:
  terrain_normalmap_master   RGB8, 1025², tangent-space normals from the heightmap
  terrain_splat_0            RGBA8, 1025², weights for grass, moss, rock, gravel
  terrain_splat_1            RGBA8, 1025², weights for mud, sand, clay, (unused)
  terrain_macro_noise_texture R8,  1025², tiling low-frequency noise for large-scale variation
  terrain_height_blend_rules JSON,  the thresholds the weights were built from
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
    read_png,
    record,
    sha256_file,
    write_gray_png,
    write_png,
)

CELLS = 1024
SAMPLES = CELLS + 1
CELL_SPACING_M = 1000.0 / CELLS

# The splat channels, in order. Two RGBA maps hold eight surfaces; seven are used, and the eighth
# is reserved rather than repurposed, because a later surface should not have to renumber the
# shader's channel mapping.
SPLAT_LAYERS = [
    ("grass", 12),
    ("moss", 3),
    ("rock", 4),
    ("gravel", 5),
    ("mud", 1),
    ("sand", 6),
    ("clay", 13),
    ("unused", 0),
]

# Slope thresholds, matching terrain_maps.py. These are the boundaries the weights ramp across.
SLOPE_ROCK = 0.70
SLOPE_SCREE = 0.40
# A shallow band where moss gives way to grass: moss holds the damp hollows, grass the open ground.
SLOPE_MOSS_EDGE = 0.18
# How far above the waterline the shore's sand gives way to grass, in metres.
SHORE_BAND_M = 2.5
# The bog's mud fades out over this height above the waterline.
BOG_BAND_M = 6.0
# The macro-noise map is tiled, so it is a power of two rather than one texel wider than one: a
# 1025-wide tile repeats its first column at the seam and doubles a texel wherever it wraps.
MACRO_SIZE = 1024


def smoothstep(edge0, edge1, x):
    """0 below edge0, 1 above edge1, smooth between. The weights ramp, they do not switch."""
    if edge1 == edge0:
        return 0.0 if x < edge0 else 1.0
    t = (x - edge0) / (edge1 - edge0)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


def read_meta(path, heightmap_path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except OSError as exc:
        raise SystemExit("cannot read %s (%s)" % (path, exc))
    for field in ("max_height_m", "water_level_m", "samples"):
        if field not in meta:
            raise SystemExit("%s has no %s" % (path, field))
    if meta["samples"] != SAMPLES:
        raise SystemExit("%s was written at %d samples" % (path, meta["samples"]))
    recorded = meta.get("heightmap_sha256")
    actual = sha256_file(heightmap_path)
    if recorded and recorded != actual:
        raise SystemExit("%s describes a different heightmap; the sidecar is stale" % path)
    return meta


def read_heightmap(path):
    width, height, channels, rows = read_png(path)
    if channels != 1:
        raise SystemExit("%s must be single-channel" % path)
    if (width, height) != (SAMPLES, SAMPLES):
        raise SystemExit("%s is %dx%d, expected %dx%d" % (path, width, height, SAMPLES, SAMPLES))
    flat = []
    for row in rows:
        flat.extend(row)
    return flat


def gradient_at(metres, x, y):
    """True gradient in metres per metre, central difference, clamped at the edges."""
    x0 = x - 1 if x > 0 else 0
    x1 = x + 1 if x < SAMPLES - 1 else SAMPLES - 1
    y0 = y - 1 if y > 0 else 0
    y1 = y + 1 if y < SAMPLES - 1 else SAMPLES - 1
    run_x = (x1 - x0) * CELL_SPACING_M
    run_y = (y1 - y0) * CELL_SPACING_M
    dx = metres[y * SAMPLES + x1] - metres[y * SAMPLES + x0]
    dy = metres[y1 * SAMPLES + x] - metres[y0 * SAMPLES + x]
    return (dx / run_x if run_x else 0.0), (dy / run_y if run_y else 0.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--heightmap", required=True)
    parser.add_argument("--meta", default="")
    parser.add_argument(
        "--surface-map",
        default="",
        help="the surface-ID map from terrain_maps.py (default: terrain_surface_id_map.png "
        "beside the heightmap). The splat weights are anchored to it, so the two cannot disagree",
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", default="drowned-greenwood-v1")
    parser.add_argument("--normal-strength", type=float, default=1.0)
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

    # The surface-ID map is the authority for which surface a cell is. The splat weights are a
    # smooth rendering of the same decision, anchored to it — they used to be computed from slope
    # and height independently, and the dominant splat disagreed with the ID map on 54 % of land
    # cells, so a footstep would have sounded like grass over visible gravel.
    surface_map_path = args.surface_map or os.path.join(
        os.path.dirname(os.path.abspath(args.heightmap)), "terrain_surface_id_map.png"
    )
    width, height, channels, id_rows = read_png(surface_map_path)
    if channels != 1:
        raise SystemExit("%s must be single-channel" % surface_map_path)
    if (width, height) != (SAMPLES, SAMPLES):
        raise SystemExit(
            "%s is %dx%d, expected %dx%d" % (surface_map_path, width, height, SAMPLES, SAMPLES)
        )
    surface_ids = [value for row in id_rows for value in row]
    if len(surface_ids) != SAMPLES * SAMPLES:
        raise SystemExit(
            "%s has %d cells, expected %d" % (surface_map_path, len(surface_ids), SAMPLES * SAMPLES)
        )

    # Which splat layer holds each surface id, taken from SPLAT_LAYERS itself so the two cannot
    # drift. Water and paths have no layer of their own — the shader draws water and a path is a
    # decal — so those cells keep the smooth weights and are not counted in the agreement figure.
    LAYER_FOR_ID = {
        surface_id: index
        for index, (_name, surface_id) in enumerate(SPLAT_LAYERS)
        if surface_id != 0
    }

    # Large-scale variation, so the terrain does not read as one uniform material at distance.
    # Generated at 256 and upsampled: macro noise is by definition low frequency.
    # Generated at MACRO_SIZE, not at SAMPLES: this map is tiled, and a 1025-wide tile repeats its
    # first column at the seam, so the texture doubles a texel wherever it wraps.
    macro = bilinear_upsample(fbm_field(256, args.seed + ":macro", octaves=4, base_size=5), MACRO_SIZE)
    # A second, independent field splits moss from grass so that boundary is not a contour line.
    patchiness = bilinear_upsample(
        fbm_field(256, args.seed + ":patch", octaves=4, base_size=9), SAMPLES
    )

    os.makedirs(args.out, exist_ok=True)
    products = []

    normal_rows = []
    splat0_rows = []
    splat1_rows = []
    land_agreed = 0
    land_total = 0
    for y in range(SAMPLES):
        normal_row = []
        splat0 = []
        splat1 = []
        for x in range(SAMPLES):
            cell = y * SAMPLES + x
            gx, gy = gradient_at(metres, x, y)

            # Tangent-space normal: the surface tilts against the gradient. The 1.0 in z is the
            # "flat" reference; scaling it by the strength is what makes the map express the
            # terrain's steepness rather than a normalised version of it.
            nx = -gx * args.normal_strength
            ny = -gy * args.normal_strength
            length = math.sqrt(nx * nx + ny * ny + 1.0)
            normal_row.extend(
                (
                    int(round((nx / length * 0.5 + 0.5) * 255)),
                    int(round((ny / length * 0.5 + 0.5) * 255)),
                    int(round((1.0 / length * 0.5 + 0.5) * 255)),
                )
            )

            gradient = math.hypot(gx, gy)
            above_water = metres[cell] - water_level_m

            # Rock where it is steep. This is the sharp edge in the map, and it is sharp because
            # the terrain is: a cliff face does not have a soft border.
            rock = smoothstep(SLOPE_SCREE, SLOPE_ROCK, gradient)
            loose = smoothstep(SLOPE_MOSS_EDGE, SLOPE_SCREE, gradient) * (1.0 - rock)
            soil = (1.0 - rock) * (1.0 - loose)

            # Mud in the bog, fading out above the waterline.
            bog = (1.0 - smoothstep(0.0, BOG_BAND_M, above_water)) * (1.0 - rock)
            # Sand and gravel on the shore band, above the waterline.
            shore = (1.0 - smoothstep(0.0, SHORE_BAND_M, above_water)) * (1.0 - rock) * soil

            # What is left over is moss or grass, split by the patchiness field rather than by
            # height, so the boundary wanders.
            green = soil * (1.0 - bog) * (1.0 - shore)
            moss_share = smoothstep(0.35, 0.65, patchiness[y][x])
            moss = green * moss_share
            grass = green * (1.0 - moss_share)

            mud = bog * 0.75
            clay = bog * 0.25
            sand = shore * 0.45
            gravel = shore * 0.55 + loose * 0.8
            # `loose` ground that is not gravel still needs to be assigned somewhere.
            grass += loose * 0.2

            weights = [grass, moss, rock, gravel, mud, sand, clay, 0.0]
            total = sum(weights)
            if total <= 0.0:
                weights = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            else:
                weights = [w / total for w in weights]

            # Anchor the smooth weights to the surface-ID map. The map is the decision; this is its
            # rendering. 85 % of the weight goes to the map's own layer, so the dominant splat is
            # the surface the map names, and the remaining 15 % keeps the boundary soft.
            layer = LAYER_FOR_ID.get(surface_ids[cell])
            if layer is not None:
                weights = [w * 0.15 for w in weights]
                weights[layer] += 0.85
                total = sum(weights)
                weights = [w / total for w in weights]
                land_total += 1
                if max(range(8), key=lambda i: weights[i]) == layer:
                    land_agreed += 1

            # Bytes have to sum to 255 exactly. They summed to 253-258 because each channel was
            # rounded on its own after normalising in floats; the residual goes on the dominant
            # channel, which is the one an error there is least visible in.
            scaled = [int(round(w * 255)) for w in weights]
            dominant = max(range(8), key=lambda i: weights[i])
            scaled[dominant] = max(0, min(255, scaled[dominant] + 255 - sum(scaled)))

            splat0.extend(scaled[0:4])
            splat1.extend(scaled[4:8])

        normal_rows.append(normal_row)
        splat0_rows.append(splat0)
        splat1_rows.append(splat1)

    normal_path = os.path.join(args.out, "terrain_normalmap_master.png")
    write_png(normal_path, normal_rows, bit_depth=8, channels=3)
    products.append(
        ("terrain_normalmap_master", normal_path, {"texture_sizes": {"rgb8": [SAMPLES, SAMPLES]}})
    )

    splat0_path = os.path.join(args.out, "terrain_splat_0.png")
    write_png(splat0_path, splat0_rows, bit_depth=8, channels=4)
    products.append(
        (
            "terrain_splat_0",
            splat0_path,
            {"texture_sizes": {"rgba8": [SAMPLES, SAMPLES]},
             "tags": ["splat", "channels:" + ",".join(name for name, _id in SPLAT_LAYERS[0:4])]},
        )
    )

    splat1_path = os.path.join(args.out, "terrain_splat_1.png")
    write_png(splat1_path, splat1_rows, bit_depth=8, channels=4)
    products.append(
        (
            "terrain_splat_1",
            splat1_path,
            {"texture_sizes": {"rgba8": [SAMPLES, SAMPLES]},
             "tags": ["splat", "channels:" + ",".join(name for name, _id in SPLAT_LAYERS[4:8])]},
        )
    )

    macro_rows = [[int(round(v * 255)) for v in row] for row in macro]
    macro_path = os.path.join(args.out, "terrain_macro_noise_texture.png")
    write_gray_png(macro_path, macro_rows, bit_depth=8)
    products.append(
        ("terrain_macro_noise_texture", macro_path,
         {"texture_sizes": {"r8": [MACRO_SIZE, MACRO_SIZE]}})
    )

    # The blend rules, as data. The shader could hardcode these, but then the weights and the
    # shader could disagree — and a splat map whose thresholds do not match the shader that reads
    # it is a very quiet kind of wrong.
    rules = {
        "name": "terrain_height_blend_rules",
        "note": "The thresholds the splat weights were built from. Read by the terrain shader so "
        "the two cannot drift.",
        "slope_rock": SLOPE_ROCK,
        "slope_scree": SLOPE_SCREE,
        "slope_moss_edge": SLOPE_MOSS_EDGE,
        "shore_band_m": SHORE_BAND_M,
        "bog_band_m": BOG_BAND_M,
        "water_level_m": water_level_m,
        "splat_layers": [{"channel": index, "name": name, "surface_id": surface_id}
                         for index, (name, surface_id) in enumerate(SPLAT_LAYERS)],
        "splat_maps": ["terrain_splat_0", "terrain_splat_1"],
        "normal_strength": args.normal_strength,
        "blend_order": [
            "rock takes the steep ground first, because a 35 degree face holds nothing else",
            "loose gravel takes the moderate slopes",
            "bog mud takes the flat ground near the waterline",
            "shore sand and gravel take the narrow band above it",
            "the remainder is moss or grass, split by a noise field so the boundary wanders",
        ],
    }
    rules_path = os.path.join(args.out, "terrain_height_blend_rules.json")
    with open(rules_path, "w", encoding="utf-8") as handle:
        json.dump(rules, handle, indent=2, sort_keys=True)
        handle.write("\n")
    products.append(("terrain_height_blend_rules", rules_path, {}))

    in_hash = input_hash(
        {
            "generator": "terrain_surfaces",
            "version": GENERATOR_VERSION,
            "seed": args.seed,
            "heightmap_sha256": sha256_file(args.heightmap),
            "normal_strength": args.normal_strength,
            "slope_rock": SLOPE_ROCK,
            "slope_scree": SLOPE_SCREE,
            "shore_band_m": SHORE_BAND_M,
            "bog_band_m": BOG_BAND_M,
            "splat_layers": SPLAT_LAYERS,
        }
    )

    report = {
        "generator": "terrain_surfaces",
        "version": GENERATOR_VERSION,
        "seed": args.seed,
        "input_hash": in_hash,
        "assets": [],
    }
    for name, path, extra in products:
        report["assets"].append(
            record(
                name,
                path,
                sha256_file(path),
                in_hash,
                "terrain_surfaces/" + GENERATOR_VERSION,
                size_kb=os.path.getsize(path) // 1024,
                **extra
            )
        )

    # The agreement figure the CI gate reads. Built from the same loop that wrote the channels, so
    # it measures what was written rather than a re-derivation that could disagree with it.
    report["coverage"] = {
        "splat_id_agreement_percent": round(100.0 * land_agreed / land_total, 2)
        if land_total
        else 0.0,
        "land_cells_compared": land_total,
        "splat_sum": 255,
    }

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")

    for asset in report["assets"]:
        print("%s: %s (%d KB)" % (asset["name"], asset["sha256"][:16], asset["size_kb"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
