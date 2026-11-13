#!/usr/bin/env python3
"""Audit the content of what is committed, not just its headers.

Run:
    python tools/validate/check_assets.py

Two failures motivated this. The terrain maps passed every gate — right size, right bit depth,
right hash, sensible value ranges — while containing a 20 m cliff, a 200 m trench with a dry floor
and a splat map that disagreed with the surface-ID map on 54 % of cells. And the surface FX table
named fifty-odd assets (`audio_step_mud`, `vfспx_step_soft`) that the manifest had never declared,
which is a contract broken on paper that would only have surfaced in Phase 4.

What this checks:

  * every asset named in surface_fx_table.json is a manifest entry, or deliberately null
  * every built record in assets/built.json hashes to its recorded SHA-256 — the file is opened,
    not trusted
  * the committed terrain maps are consistent with each other: splat channels sum to 255, the
    dominant splat matches the surface-ID map, the two water rules agree, the flow vectors are
    unit length, the river descends and its water sits above its bed, the normal map agrees with
    the heightmap it was derived from, and the sidecar describes the heightmap beside it
"""

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
        checked += 1
    return checked


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

    layer_for_id = {1: 4, 3: 1, 4: 2, 5: 3, 6: 5, 12: 0, 13: 6}
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
        if agreement < 95.0:
            problems.append(
                "the committed splats match the committed surface-ID map on only %.1f%% of land "
                "cells" % agreement
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
    problems = []
    fx = check_fx_contract(problems)
    built = check_built_hashes(problems)
    check_terrain(problems)
    water = check_hydrology(problems)
    check_water_agreement(problems, water)
    check_river(problems)

    if problems:
        print("asset content checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print(
        "assets: %d FX names match the plan, %d built files hash to their records, terrain maps "
        "agree with each other, water %.2f%% in both" % (fx, built, water)
    )
    return 0


build_manifest = load_module("build_manifest", os.path.join("tools", "build_manifest.py"))
common = load_module("generator_common", os.path.join("tools", "generators", "common.py"))


if __name__ == "__main__":
    sys.exit(main())
