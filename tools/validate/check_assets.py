#!/usr/bin/env python3
"""Audit the content of what is committed, not just its headers.

Run:
    python tools/validate/check_assets.py

Two failures motivated this. The terrain maps passed every gate — right size, right bit depth,
right hash, sensible value ranges — while containing a 20 m cliff, a 200 m trench with a dry floor
and a splat map that disagreed with the surface-ID map on 54 % of cells. And the surface FX table
named fifty-odd assets (`audio_step_mud`, `vfx_step_soft`) that the manifest had never declared,
which is a contract broken on paper that would only have surfaced in Phase 4.

What this checks:

  * every asset named in surface_fx_table.json is a manifest entry, or deliberately null
  * every built record in assets/built.json hashes to its recorded SHA-256 and size — the file is
    opened, not trusted
  * the committed terrain maps are consistent with each other: the heightmap hash and grid match
    the sidecar, splat channels sum to 255, the dominant splat matches the surface-ID map, the two
    water rules agree, flow vectors are unit length, and the river descends with water above its bed
  * the water in the surface-ID map stands below the waterline in the heightmap beside it, so a
    regenerated heightmap and a stale surface map cannot be committed as a pair
  * every value in the surface-ID map is an id surface_ids.json still declares
  * the biome mask only sets its five declared bits, and is single-channel
  * every normal-map texel decodes to a unit vector, the same contract the flow vectors meet
"""

import argparse
import importlib.util
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TERRAIN = os.path.join("assets", "terrain")
BUILT = os.path.join("assets", "built.json")
MANIFEST = os.path.join("assets", "manifest.json")
FX = os.path.join("assets", "surface_fx_table.json")

WATER_IDS = (8, 9)
# A decoded normal is unit length to within one 8-bit count per channel: the generator normalises
# (nx, ny, 1) before encoding, so the only error is rounding, at 1/255 of 2.0 per channel. 0.05 is
# a wide margin for that and still far too tight to accept a heightfield or an ORM map wearing a
# normal map's filename.
NORMAL_LENGTH_TOLERANCE = 0.05
# Exact products emitted in the three terrain generator reports. terrain_meta.json is sidecar
# metadata for the heightmap, not a manifest asset or a built-evidence record.
TERRAIN_ASSETS = {
    "terrain_heightmap_master_1km",
    "terrain_biome_mask",
    "terrain_surface_id_map",
    "terrain_hydrology_mask",
    "terrain_shore_mask",
    "terrain_river_splines",
    "terrain_water_level_table",
    "terrain_normalmap_master",
    "terrain_splat_0",
    "terrain_splat_1",
    "terrain_macro_noise_texture",
    "terrain_height_blend_rules",
}


def load_module(name, relative_path):
    path = os.path.join(ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    directory = os.path.dirname(path)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    spec.loader.exec_module(module)
    return module


def read_json(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as handle:
        return json.load(handle)


def check_fx_contract(problems):
    """Every asset the FX table names must be one the manifest declares."""
    manifest = read_json(MANIFEST)
    records, build_problems = build_manifest.build(manifest)
    if build_problems:
        problems.append("manifest does not build: %s" % build_problems[0])
        return 0
    # A reference may name a record or the base name of a variant group. `decal_leaf_pile` with
    # four variants expands to decal_leaf_pile_a..d, and the runtime picks one at random, so the
    # family is the right thing for a table like this to name.
    declared = {record["name"] for record in records}
    declared |= {record["base_name"] for record in records if record.get("variants", 1) > 1}

    fx = read_json(FX)
    fields = ("footstep_audio", "footstep_vfx", "impact_vfx", "decal", "ambient")
    checked = 0
    for surface_id, row in fx.get("table", {}).items():
        for field in fields:
            if field not in row:
                problems.append("surface %s: row has no %s (null is allowed, absent is not)" % (surface_id, field))
                continue
            name = row[field]
            if name is None:
                if not row.get("missing"):
                    problems.append(
                        "surface %s: %s is null but the row does not say why" % (surface_id, field)
                    )
                continue
            checked += 1
            if name not in declared:
                problems.append(
                    "surface %s: %s names %r, which the manifest does not declare"
                    % (surface_id, field, name)
                )
    return checked


def check_built_hashes(problems):
    """A built record is only evidence if the file still hashes to what was recorded."""
    if not os.path.exists(os.path.join(ROOT, BUILT)):
        problems.append("assets/built.json is missing: nothing is recorded as built")
        return 0
    built = read_json(BUILT).get("built", {})
    checked = 0
    for name, entry in sorted(built.items()):
        path = os.path.join(ROOT, entry["path"])
        if not os.path.exists(path):
            problems.append("%s: recorded path %s does not exist" % (name, entry["path"]))
            continue
        actual = common.sha256_file(path)
        if actual != entry["sha256"]:
            problems.append(
                "%s: %s hashes to %s but assets/built.json records %s"
                % (name, entry["path"], actual[:16], entry["sha256"][:16])
            )
            continue
        recorded_size = entry.get("size_kb")
        actual_size = os.path.getsize(path) // 1024
        if recorded_size != actual_size:
            problems.append(
                "%s: recorded size is %r KB but the file is %d KB"
                % (name, recorded_size, actual_size)
            )
            continue
        checked += 1
    return checked


def check_required_terrain_evidence(problems):
    """Fail a publish unless every generated terrain product has its own manifest evidence."""
    built = read_json(BUILT).get("built", {})
    missing = sorted(TERRAIN_ASSETS - set(built))
    if missing:
        problems.append(
            "terrain publish has no built evidence for %d generated asset(s): %s"
            % (len(missing), missing)
        )
    not_built = sorted(
        name for name in TERRAIN_ASSETS & set(built)
        if built[name].get("status") != "built"
    )
    if not_built:
        problems.append("terrain evidence is not marked built: %s" % not_built)


def read_terrain(name):
    path = os.path.join(ROOT, TERRAIN, name)
    if not os.path.exists(path):
        return None
    return common.read_png(path)


def check_terrain(problems):
    """The committed maps must agree with each other, not just be well-formed."""
    meta = read_json(os.path.join(TERRAIN, "terrain_meta.json"))
    samples = meta["samples"]
    height_path = os.path.join(ROOT, TERRAIN, "terrain_heightmap_master_1km.png")
    if not os.path.exists(height_path):
        problems.append("the heightmap is not committed")
        return
    if common.sha256_file(height_path) != meta.get("heightmap_sha256"):
        problems.append("terrain_meta.json describes a different heightmap than the one committed")

    width, height, _, rows = read_terrain("terrain_heightmap_master_1km.png")
    if (width, height) != (samples, samples):
        problems.append("heightmap is %dx%d, meta says %d squared" % (width, height, samples))
    max_height = meta["max_height_m"]
    flattened = [value for row in rows for value in row]
    metres = [value / 65535.0 * max_height for value in flattened]
    if max(metres) > max_height + 0.01:
        problems.append("a height decodes above max_height_m")
    if min(metres) < 0.0:
        problems.append("a height decodes below zero")

    sid = read_terrain("terrain_surface_id_map.png")
    splat0 = read_terrain("terrain_splat_0.png")
    splat1 = read_terrain("terrain_splat_1.png")
    if sid is None or splat0 is None or splat1 is None:
        problems.append("the surface-ID map or a splat map is not committed")
        return
    if sid[2] != 1:
        problems.append("the surface-ID map is not single-channel")
    ids = sid[3]
    s0 = splat0[3]
    s1 = splat1[3]

    # Derived from the generator's own channel table rather than copied. The first version of this
    # line was a literal {1: 4, 3: 1, 4: 2, 5: 3, 6: 5, 12: 0, 13: 6}: reordering SPLAT_LAYERS in
    # terrain_surfaces.py would have left this checking the previous layout and reporting agreement
    # against the wrong channels, which reads as a small percentage drop, not as a broken check.
    layer_for_id = {
        surface_id: index
        for index, (_name, surface_id) in enumerate(terrain_surfaces.SPLAT_LAYERS)
        if surface_id != 0
    }
    land_agreed = 0
    land_total = 0
    bad_sums = 0
    for y in range(samples):
        for x in range(samples):
            base = x * 4
            weights = s0[y][base : base + 4] + s1[y][base : base + 4]
            if sum(weights) != 255:
                bad_sums += 1
            layer = layer_for_id.get(ids[y][x])
            if layer is None:
                continue
            land_total += 1
            if max(range(8), key=lambda i: weights[i]) == layer:
                land_agreed += 1

    if bad_sums:
        problems.append("%d splat texels do not sum to 255" % bad_sums)
    if land_total:
        agreement = 100.0 * land_agreed / land_total
        if agreement < 90.0:
            problems.append(
                "the committed splats match the committed surface-ID map on only %.1f%% of land "
                "cells" % agreement
            )

    # Water is ground below the waterline in every generator, so the surface map and the
    # heightmap are two committed files that answer that one question. They are regenerated
    # together but committed separately, so a stale pair is possible: a new heightmap beside an
    # old surface map would put a lake on a hillside, and every header check would still pass.
    water_level = meta["water_level_m"]
    wet_but_high = 0
    wet_but_high_at = None
    for y in range(samples):
        for x in range(samples):
            if ids[y][x] not in WATER_IDS:
                continue
            height_m = metres[y * samples + x]
            if height_m > water_level + 0.05:
                wet_but_high += 1
                if wet_but_high_at is None:
                    wet_but_high_at = (x, y, height_m)
    if wet_but_high:
        problems.append(
            "%d cells of the surface-ID map are water but stand above the %.1f m waterline "
            "(first at x=%d y=%d, %.2f m): the heightmap and the surface map are not from one run"
            % (
                wet_but_high,
                water_level,
                wet_but_high_at[0],
                wet_but_high_at[1],
                wet_but_high_at[2],
            )
        )

    # An id is a contract. A value in the committed map that surface_ids.json no longer declares
    # is a surface the FX table cannot answer for and a footstep with no sound.
    live_ids = set()
    for row in read_json(os.path.join("assets", "surface_ids.json")).get("surfaces", []):
        if isinstance(row, dict) and "id" in row:
            live_ids.add(row["id"])
    if live_ids:
        used = {value for row in ids for value in row}
        retired = sorted(used - live_ids)
        if retired:
            problems.append(
                "the surface-ID map paints ids that surface_ids.json does not declare: %s"
                % retired
            )


def check_biome_mask(problems):
    """The biome mask is a bit field, so every texel must be a combination of declared bits.

    A single undefined bit is not a cosmetic problem: it is a surface the scatter pass will never
    find and a texel whose meaning nobody can reconstruct. The five bits are 1 bog, 2 forest,
    4 ridge, 8 riverbed and 16 clearing, so anything above 31 is a value that escaped.
    """
    mask = read_terrain("terrain_biome_mask.png")
    if mask is None:
        problems.append("the biome mask is missing")
        return
    _width, _height, channels, rows = mask
    if channels != 1:
        problems.append("the biome mask is not single-channel")
    defined = 1 | 2 | 4 | 8 | 16
    stray = 0
    for row in rows:
        for value in row:
            if value & ~defined:
                stray += 1
    if stray:
        problems.append(
            "%d biome-mask texels set a bit outside the five declared (1 bog, 2 forest, 4 ridge, "
            "8 riverbed, 16 clearing)" % stray
        )


def check_normal_map(problems):
    """A normal-map texel must decode to a unit vector whatever the slope it describes.

    The hydrology flow vectors have been checked this way since the mask was made RGB, and the
    normal map has the same contract and had no check at all. It is worth having because the
    failure is silent: a map whose channels are not a normal either still compiles and still
    renders, and only reads as "the lighting is odd on the hills" — which is indistinguishable
    from an art problem. Sampled on a stride, because a million square roots is a second of CI
    for a property that does not vary texel to texel.
    """
    texture = read_terrain("terrain_normalmap_master.png")
    if texture is None:
        problems.append("the normal map is missing")
        return
    width, height, channels, rows = texture
    if channels != 3:
        problems.append("the normal map is not RGB")
        return
    worst = 0.0
    worst_at = (0, 0)
    for y in range(0, height, 2):
        row = rows[y]
        for x in range(0, width, 2):
            r, g, b = row[x * 3 : x * 3 + 3]
            length = math.sqrt(
                (r / 255.0 * 2.0 - 1.0) ** 2
                + (g / 255.0 * 2.0 - 1.0) ** 2
                + (b / 255.0 * 2.0 - 1.0) ** 2
            )
            error = abs(length - 1.0)
            if error > worst:
                worst = error
                worst_at = (x, y)
    if worst > NORMAL_LENGTH_TOLERANCE:
        problems.append(
            "a normal-map texel at x=%d y=%d decodes to length %.4f, which is off unit length by "
            "%.3f: the RGB channels are not a tangent-space normal" % (worst_at[0], worst_at[1], worst, worst)
        )


def check_hydrology(problems):
    mask = read_terrain("terrain_hydrology_mask.png")
    if mask is None:
        problems.append("the hydrology mask is missing")
        return
    width, height, channels, rows = mask
    if channels != 3:
        problems.append("the hydrology mask is not RGB")
    off_unit = 0
    water = 0
    sampled = 0
    for y in range(0, height, 3):
        row = rows[y]
        for x in range(0, width, 3):
            r, g, b = row[x * 3 : x * 3 + 3]
            sampled += 1
            if r > 0:
                water += 1
            dx = g / 255.0 * 2.0 - 1.0
            dy = b / 255.0 * 2.0 - 1.0
            length = math.hypot(dx, dy)
            if length > 0.01 and abs(length - 1.0) > 0.05:
                off_unit += 1
    if off_unit:
        problems.append("%d sampled direction texels do not decode to unit length" % off_unit)

    return 100.0 * water / sampled if sampled else 0.0


def check_water_agreement(problems, water_percent):
    """Both generators must count water the same way."""
    sid = read_terrain("terrain_surface_id_map.png")
    if sid is None:
        return
    _, _, _, rows = sid
    total = 0
    water = 0
    for row in rows:
        for value in row:
            total += 1
            if value in WATER_IDS:
                water += 1
    percent = 100.0 * water / total if total else 0.0
    if abs(percent - water_percent) > 0.5:
        problems.append(
            "the surface map says %.2f%% water and the hydrology mask says %.2f%%: "
            "the same question is being answered twice" % (percent, water_percent)
        )


def check_river(problems):
    spline = read_json(os.path.join(TERRAIN, "terrain_river_splines.json")).get("points", [])
    levels = read_json(os.path.join(TERRAIN, "terrain_water_level_table.json")).get("levels", [])
    if not spline:
        problems.append("the river centreline is empty")
        return
    climbs = sum(1 for a, b in zip(spline, spline[1:]) if b["height_m"] > a["height_m"])
    if climbs:
        problems.append("%d of %d river segments climb" % (climbs, len(spline) - 1))
    submerged = [level for level in levels if level["water_surface_m"] <= level["bed_height_m"]]
    if submerged:
        problems.append(
            "%d of %d river points have the water surface at or below the bed" % (len(submerged), len(levels))
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-terrain-evidence",
        action="store_true",
        help="require built records for every generated terrain product (publish job only)",
    )
    args = parser.parse_args()

    problems = []
    fx = check_fx_contract(problems)
    built = check_built_hashes(problems)
    check_terrain(problems)
    check_biome_mask(problems)
    check_normal_map(problems)
    water = check_hydrology(problems)
    check_water_agreement(problems, water)
    check_river(problems)
    if args.require_terrain_evidence:
        check_required_terrain_evidence(problems)

    if problems:
        print("asset content checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print(
        "assets: %d FX names match the plan, %d built files hash to their records, terrain maps "
        "agree with each other, water %.2f%% in both, biome bits and normal vectors are in range"
        % (fx, built, water)
    )
    return 0


build_manifest = load_module("build_manifest", os.path.join("tools", "build_manifest.py"))
common = load_module("generator_common", os.path.join("tools", "generators", "common.py"))
# The splat channel order is the generator's decision, so the agreement check reads it there
# rather than holding a second copy that can drift.
terrain_surfaces = load_module(
    "terrain_surfaces", os.path.join("tools", "generators", "terrain_surfaces.py")
)


if __name__ == "__main__":
    sys.exit(main())
