#!/usr/bin/env python3
"""Validate the shared PBR material system: materials, surface ids and their FX table.

Run:
    python tools/validate/check_materials.py

Why this exists: a material table is the kind of file that looks right and is wrong. A surface id
that no longer exists, a tiling value that makes a texture visibly repeat, a foliage material that
forgot its wind amplitude, or a shader that redeclares a uniform its include already declares —
each of those compiles, renders, and looks subtly broken on a device rather than failing a gate.

That last one is not hypothetical: the Phase 0 shader probe failed exactly that way, declaring
`wind_noise` again after including the file that declares it. A duplicate uniform is a compile
error, and nothing but this check would catch it before Godot does.

What it checks:
  * surface_ids: ids unique and inside 1..254, names unique, reserved ids unused, water surfaces
    marked as belonging to a different shader system
  * surface_fx_table: exactly one row per non-retired surface, every field present (null is a
    deliberate "nothing", an absent field is a mistake)
  * materials: required fields, name convention, unique names, shader exists on disk, surface id
    exists and is not retired, tiling inside the clamp, every range inside the shader's hint range
  * foliage materials use the foliage shader and declare the wind amplitudes; opaque ones do not
  * every opaque surface has at least one material
  * no shader redeclares a uniform that an include it uses already declares
"""

import json
import os
import re
import sys

SURFACES = "assets/surface_ids.json"
FX_TABLE = "assets/surface_fx_table.json"
MATERIALS = "tools/config/materials.json"

SHADER_ROOT = "shaders"

# Ranges mirror the hint_range() in the shaders. A value outside its hint range is silently
# clamped at render time, so the number in the config would not be the number in use.
RANGES = {
    "wetness_darken": (0.0, 0.8),
    "moss_strength": (0.0, 1.0),
    "normal_strength": (0.0, 2.0),
    "alpha_cutoff": (0.0, 1.0),
    "translucency": (0.0, 1.0),
    "sway_amplitude": (0.0, 0.5),
    "branch_amplitude": (0.0, 0.5),
    "flutter_amplitude": (0.0, 0.1),
}

MATERIAL_REQUIRED = {
    "name": str,
    "shader": str,
    "surface_id": int,
    "texture_set": str,
    "tiling_m": (int, float),
    "wetness_darken": (int, float),
    "tier": str,
    "used_by": list,
}

# Fields only the foliage shader has. Declaring one on an opaque material is a typo that would
# silently do nothing, because surface_base has no such uniform.
FOLIAGE_FIELDS = (
    "alpha_cutoff",
    "translucency",
    "sway_amplitude",
    "branch_amplitude",
    "flutter_amplitude",
)

NAME_PATTERN = re.compile(r"^mat_[a-z][a-z0-9_]*$")
VALID_TIERS = {"S", "A", "B", "C"}

INCLUDE_RE = re.compile(r'#include\s+"res://([^"]+)"')
UNIFORM_RE = re.compile(r"^\s*(?:global\s+)?uniform\s+\w+\s+(\w+)")


def load(path, problems):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        problems.append("%s: cannot read (%s)" % (path, exc))
    except json.JSONDecodeError as exc:
        problems.append("%s:%s: %s" % (path, exc.lineno, exc.msg))
    return None


def shader_path(relative):
    """A `res://` path from the config to a path on disk."""
    if relative.startswith("res://"):
        relative = relative[len("res://"):]
    return relative


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def uniforms_declared(text):
    """Every uniform name a shader source declares, including `global uniform`."""
    names = set()
    for line in text.splitlines():
        code = line.split("//", 1)[0]
        match = UNIFORM_RE.match(code)
        if match:
            names.add(match.group(1))
    return names


def check_shader_includes(problems):
    """A shader must not redeclare a uniform one of its includes already declares.

    This is the exact failure that cost a Phase 0 run: the shader probe's wrapper declared
    `wind_noise` and `gust_flowmap` after including the file that declares them, and a duplicate
    uniform is a compile error. Nothing caught it until Godot did.
    """
    shaders = sorted(
        name for name in os.listdir(SHADER_ROOT) if name.endswith((".gdshader", ".gdshaderinc"))
    )
    for name in shaders:
        path = os.path.join(SHADER_ROOT, name)
        text = read_text(path)
        if text is None:
            problems.append("%s: cannot read" % path)
            continue

        declared = uniforms_declared(text)
        for relative in INCLUDE_RE.findall(text):
            include_path = shader_path(relative)
            include_text = read_text(include_path)
            if include_text is None:
                problems.append("%s: includes %s, which does not exist" % (path, include_path))
                continue
            inherited = uniforms_declared(include_text)
            clash = sorted(declared & inherited)
            if clash:
                problems.append(
                    "%s: declares %s, which %s already declares — a duplicate uniform is a "
                    "compile error" % (path, clash, include_path)
                )

    print("shaders: %d checked for duplicate uniforms across includes" % len(shaders))


def check_surfaces(surfaces, problems):
    """Ids unique, inside range, and water marked as a different shader system."""
    if not isinstance(surfaces, dict):
        problems.append("%s: not an object" % SURFACES)
        return {}
    rows = surfaces.get("surfaces")
    if not isinstance(rows, list) or not rows:
        problems.append("%s: no surfaces list" % SURFACES)
        return {}

    by_id = {}
    seen_names = {}
    for row in rows:
        if not isinstance(row, dict):
            problems.append("%s: a surface row is not an object" % SURFACES)
            continue
        sid = row.get("id")
        name = row.get("name")
        if not isinstance(sid, int) or isinstance(sid, bool):
            problems.append("%s: surface %r has no integer id" % (SURFACES, name))
            continue
        # 0 and 255 are reserved for "unknown" and "out of bounds"; they are not surfaces.
        if not 1 <= sid <= 254:
            problems.append("%s: id %d is outside 1..254 (0 and 255 are reserved)" % (SURFACES, sid))
        if sid in by_id:
            problems.append(
                "%s: id %d is used by both %r and %r" % (SURFACES, sid, by_id[sid], name)
            )
        if not isinstance(name, str) or not name:
            problems.append("%s: surface with id %d has no name" % (SURFACES, sid))
            continue
        if name in seen_names:
            problems.append("%s: surface name %r appears twice" % (SURFACES, name))
        seen_names[name] = sid
        by_id[sid] = name

    print("surfaces: %d ids, %d..%d" % (len(by_id), min(by_id or [0]), max(by_id or [0])))
    return by_id


def check_fx_table(fx, surfaces_doc, by_id, problems):
    """Exactly one row per non-retired surface, with every field present."""
    if not isinstance(fx, dict):
        problems.append("%s: not an object" % FX_TABLE)
        return
    table = fx.get("table")
    if not isinstance(table, dict):
        problems.append("%s: no table object" % FX_TABLE)
        return

    retired = {
        row["id"]
        for row in surfaces_doc.get("surfaces", [])
        if isinstance(row, dict) and row.get("retired")
    }
    wanted = {sid for sid in by_id if sid not in retired}

    # The table is keyed by the id written as a string, because JSON object keys are strings.
    present = {int(key) for key in table if str(key).isdigit()}
    missing = sorted(wanted - present)
    extra = sorted(present - wanted)
    if missing:
        problems.append(
            "%s: no row for surface id(s) %s" % (FX_TABLE, missing)
        )
    if extra:
        problems.append(
            "%s: rows for id(s) %s, which are not live surfaces" % (FX_TABLE, extra)
        )

    # A field set to null is a deliberate "nothing happens". A field that is absent is a
    # different thing: it means whoever wrote the row did not think about it.
    required_fields = ("surface", "footstep_audio", "footstep_vfx", "impact_vfx", "decal", "ambient")
    for key, row in table.items():
        if not isinstance(row, dict):
            problems.append("%s: row %s is not an object" % (FX_TABLE, key))
            continue
        absent = [field for field in required_fields if field not in row]
        if absent:
            problems.append(
                "%s: row %s is missing %s (set null to mean deliberately nothing)"
                % (FX_TABLE, key, absent)
            )
        sid = int(key) if str(key).isdigit() else None
        if sid is not None and sid in by_id and row.get("surface") != by_id[sid]:
            problems.append(
                "%s: row %s names surface %r but surface_ids says %r"
                % (FX_TABLE, key, row.get("surface"), by_id[sid])
            )

    print("surface fx: %d rows for %d live surfaces" % (len(table), len(wanted)))


def check_materials(doc, by_id, surfaces_doc, problems):
    if not isinstance(doc, dict):
        problems.append("%s: not an object" % MATERIALS)
        return
    declared_shaders = doc.get("shaders")
    if not isinstance(declared_shaders, dict) or not declared_shaders:
        problems.append("%s: no shaders object" % MATERIALS)
        return

    for name, path in declared_shaders.items():
        if not os.path.isfile(shader_path(path)):
            problems.append("%s: shader %r points at %s, which does not exist" % (MATERIALS, name, path))

    tiling = doc.get("tiling_policy", {})
    clamp = tiling.get("clamp", "")
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", clamp)]
    low, high = (numbers[0], numbers[1]) if len(numbers) >= 2 else (0.0, 1e9)

    retired = {
        row["id"]
        for row in surfaces_doc.get("surfaces", [])
        if isinstance(row, dict) and row.get("retired")
    }
    # A surface drawn by another shader system (water) has no material row, and saying so in the
    # data is better than an allowlist in this file that nobody would find.
    water = {
        row["id"]
        for row in surfaces_doc.get("surfaces", [])
        if isinstance(row, dict) and row.get("shader_system") == "water"
    }

    rows = doc.get("materials")
    if not isinstance(rows, list) or not rows:
        problems.append("%s: no materials list" % MATERIALS)
        return

    seen = {}
    covered = set()
    for row in rows:
        if not isinstance(row, dict):
            problems.append("%s: a material row is not an object" % MATERIALS)
            continue
        name = row.get("name", "<unnamed>")

        for field, expected in MATERIAL_REQUIRED.items():
            if field not in row:
                problems.append("%s: %s is missing %s" % (MATERIALS, name, field))
                continue
            if not isinstance(row[field], expected):
                problems.append(
                    "%s: %s field %s is %s" % (MATERIALS, name, field, type(row[field]).__name__)
                )

        if not NAME_PATTERN.match(str(name)):
            problems.append(
                "%s: %r does not follow mat_<category>_<name>" % (MATERIALS, name)
            )
        if name in seen:
            problems.append("%s: duplicate material name %r" % (MATERIALS, name))
        seen[name] = True

        shader_name = row.get("shader")
        if shader_name not in declared_shaders:
            problems.append(
                "%s: %s uses shader %r, which is not declared" % (MATERIALS, name, shader_name)
            )

        if row.get("tier") not in VALID_TIERS:
            problems.append("%s: %s has tier %r" % (MATERIALS, name, row.get("tier")))

        sid = row.get("surface_id")
        if isinstance(sid, int) and not isinstance(sid, bool):
            if sid not in by_id:
                problems.append(
                    "%s: %s names surface id %d, which is not in surface_ids" % (MATERIALS, name, sid)
                )
            elif sid in retired:
                problems.append(
                    "%s: %s names retired surface id %d" % (MATERIALS, name, sid)
                )
            elif sid in water:
                problems.append(
                    "%s: %s names water surface %d, which another shader system draws"
                    % (MATERIALS, name, sid)
                )
            else:
                covered.add(sid)

        tiling_value = row.get("tiling_m")
        if isinstance(tiling_value, (int, float)) and not isinstance(tiling_value, bool):
            if not low <= tiling_value <= high:
                problems.append(
                    "%s: %s tiling_m is %s m, outside the %s..%s m clamp"
                    % (MATERIALS, name, tiling_value, low, high)
                )

        for field, (low_bound, high_bound) in RANGES.items():
            if field not in row:
                continue
            value = row[field]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append("%s: %s field %s is not a number" % (MATERIALS, name, field))
                continue
            if not low_bound <= value <= high_bound:
                problems.append(
                    "%s: %s %s is %s, outside the shader's hint range %s..%s"
                    % (MATERIALS, name, field, value, low_bound, high_bound)
                )

        # Foliage and opaque are not interchangeable: the wind amplitudes only exist on the
        # foliage shader, and declaring them elsewhere would silently do nothing.
        is_foliage = shader_name == "foliage"
        if is_foliage:
            for field in FOLIAGE_FIELDS:
                if field not in row:
                    problems.append(
                        "%s: foliage material %s has no %s" % (MATERIALS, name, field)
                    )
        else:
            present = [field for field in FOLIAGE_FIELDS if field in row]
            if present:
                problems.append(
                    "%s: %s uses the %r shader but declares %s, which that shader does not have"
                    % (MATERIALS, name, shader_name, present)
                )

        if not isinstance(row.get("used_by"), list) or not row.get("used_by"):
            problems.append("%s: %s has no used_by list" % (MATERIALS, name))

    missing_materials = sorted(set(by_id) - retired - water - covered)
    if missing_materials:
        problems.append(
            "%s: no material covers surface id(s) %s"
            % (MATERIALS, missing_materials)
        )

    print(
        "materials: %d rows, %d shaders, %d of %d opaque surfaces covered"
        % (len(rows), len(declared_shaders), len(covered), len(set(by_id) - retired - water))
    )


def main():
    problems = []

    surfaces_doc = load(SURFACES, problems)
    fx = load(FX_TABLE, problems)
    materials = load(MATERIALS, problems)

    check_shader_includes(problems)

    if surfaces_doc is not None:
        by_id = check_surfaces(surfaces_doc, problems)
        if fx is not None:
            check_fx_table(fx, surfaces_doc, by_id, problems)
        if materials is not None:
            check_materials(materials, by_id, surfaces_doc, problems)

    if problems:
        print("material checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print("material checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
