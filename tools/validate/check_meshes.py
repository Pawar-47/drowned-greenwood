#!/usr/bin/env python3
"""Check every committed model against the container, the rig and the budget the manifest set.

Run:
    python tools/validate/check_meshes.py

Why this exists: a GLB is a binary container, and its failure modes are quiet in the same way a
.tres property name is. A file with the wrong magic still has the right size; a mesh whose indices
count is not a multiple of three still drops into a viewer; a model with no TEXCOORD_0 still renders,
in flat white; a model at twice its triangle budget still opens. None of those fail anything, and
all of them reach the device. This is the gate the first real rock, tree and animal will pass
through, so it exists and is tested before there is a model to test.

What it checks, per file:
  * the GLB container: magic, version, declared length against the file's own size
  * the JSON chunk parses and declares glTF 2.0
  * at least one mesh and one primitive, with a POSITION accessor that has real bounds
  * the triangle count from the index accessor (or the position accessor when there is none), and
    that it is a whole number of triangles
  * every primitive's material index resolves
  * TEXCOORD_0 wherever the material samples a base-colour texture, because a textured material
    without UVs draws flat white and nothing else notices
  * the triangle budget from the expanded manifest, when one is recorded

What it cannot check: whether the model looks like the thing it is named after, the quality of its
UVs, or its skinned deformation. Those need a render and a rig, and are Phase 3+ work.
"""

import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPANDED = os.path.join("assets", "manifest.expanded.json")
ASSETS = os.path.join("assets")

MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
HEADER = struct.Struct("<4sII")
CHUNK = struct.Struct("<II")


def parse_glb(data):
    """The GLB's JSON document, or a list of the reasons it is not one."""
    problems = []
    if len(data) < HEADER.size:
        return None, ["is %d bytes, shorter than a GLB header" % len(data)]
    magic, version, length = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        return None, ["does not start with the glTF magic (found %r)" % magic]
    if version != 2:
        problems.append("declares glTF version %d, and only 2 is a GLB this pipeline writes" % version)
    if length != len(data):
        problems.append(
            "declares %d bytes and the file is %d — truncated or padded after the fact"
            % (length, len(data))
        )

    offset = HEADER.size
    document = None
    while offset + CHUNK.size <= len(data):
        chunk_length, chunk_type = CHUNK.unpack_from(data, offset)
        start = offset + CHUNK.size
        end = start + chunk_length
        if end > len(data):
            problems.append("a chunk declares %d bytes past the end of the file" % chunk_length)
            break
        if chunk_type == JSON_CHUNK and document is None:
            try:
                document = json.loads(data[start:end].decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                problems.append("the JSON chunk does not parse (%s)" % exc)
        offset = end
    if document is None and not problems:
        problems.append("has no JSON chunk")
    return document, problems


def read_glb(path):
    """The GLB at a path, or a list of the reasons it is not one."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return None, ["cannot read: %s" % exc]
    return parse_glb(data)


def accessor_count(document, index):
    accessors = document.get("accessors") or []
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        return None
    count = accessors[index].get("count")
    return count if isinstance(count, int) and count > 0 else None


def check_document(document, budget, problems):
    """Everything that can be said about the model from its own JSON, for one file."""
    asset = document.get("asset") or {}
    if asset.get("version") != "2.0":
        problems.append("asset.version is %r, expected '2.0'" % asset.get("version"))

    meshes = document.get("meshes") or []
    if not meshes:
        problems.append("declares no meshes")
        return 0

    materials = document.get("materials") or []
    triangles = 0
    for mesh_index, mesh in enumerate(meshes):
        primitives = mesh.get("primitives") or []
        if not primitives:
            problems.append("mesh %d has no primitives" % mesh_index)
        for primitive_index, primitive in enumerate(primitives):
            where = "mesh %d primitive %d" % (mesh_index, primitive_index)
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes:
                problems.append("%s has no POSITION attribute" % where)
                continue

            position = attributes["POSITION"]
            count = accessor_count(document, position)
            if count is None:
                problems.append("%s: the POSITION accessor has no count" % where)
                continue

            accessors = document.get("accessors") or []
            bounds = accessors[position]
            low, high = bounds.get("min"), bounds.get("max")
            if not (isinstance(low, list) and isinstance(high, list) and len(low) == 3 and len(high) == 3):
                problems.append("%s: the POSITION accessor has no 3-component min/max" % where)
            elif not any(abs(high[axis] - low[axis]) > 1e-6 for axis in range(3)):
                problems.append("%s: every vertex is at the same point" % where)

            indices = primitive.get("indices")
            if isinstance(indices, int):
                index_count = accessor_count(document, indices)
                if index_count is None:
                    problems.append("%s: the index accessor has no count" % where)
                    continue
                if index_count % 3 != 0:
                    problems.append(
                        "%s: %d indices is not a whole number of triangles" % (where, index_count)
                    )
                triangles += index_count // 3
            else:
                if count % 3 != 0:
                    problems.append(
                        "%s: %d vertices without indices is not a whole number of triangles"
                        % (where, count)
                    )
                triangles += count // 3

            material_index = primitive.get("material")
            if isinstance(material_index, int) and not 0 <= material_index < len(materials):
                problems.append("%s: names material %d, which does not exist" % (where, material_index))
            if isinstance(material_index, int) and 0 <= material_index < len(materials):
                pbr = (materials[material_index] or {}).get("pbrMetallicRoughness") or {}
                if "baseColorTexture" in pbr and "TEXCOORD_0" not in attributes:
                    problems.append(
                        "%s: the material samples a base-colour texture but the primitive has no "
                        "TEXCOORD_0, so it draws flat white" % where
                    )

    if isinstance(budget, int) and budget > 0 and triangles > budget:
        problems.append(
            "%d triangles against a budget of %d — %.1fx over, and every one of them costs the "
            "phone the same draw" % (triangles, budget, triangles / budget)
        )
    return triangles


def budgets():
    """Per-asset triangle budgets from the expanded manifest, when it has been built."""
    path = os.path.join(ROOT, EXPANDED)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    return {
        record.get("name"): record.get("tris")
        for record in manifest.get("assets", [])
        if record.get("name")
    }


def models():
    found = []
    for root, dirs, files in os.walk(os.path.join(ROOT, ASSETS)):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"})
        for name in sorted(files):
            if name.lower().endswith((".glb", ".gltf")):
                found.append(os.path.relpath(os.path.join(root, name), ROOT))
    return sorted(found)


def main():
    problems = []
    by_name = budgets()
    found = models()

    total = 0
    for relative in found:
        if not relative.lower().endswith(".glb"):
            problems.append(
                "%s is a .gltf with external buffers; only self-contained GLB ships" % relative
            )
            continue
        document, file_problems = read_glb(os.path.join(ROOT, relative))
        for problem in file_problems:
            problems.append("%s: %s" % (relative, problem))
        if document is None:
            continue
        asset_name = os.path.splitext(os.path.basename(relative))[0]
        triangles = check_document(document, by_name.get(asset_name), problems)
        total += triangles

    if problems:
        print("mesh checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    if found:
        print(
            "meshes: %d model(s), %d triangles, container, indices, UVs, materials and budgets "
            "all checked" % (len(found), total)
        )
    else:
        # Not a pass on nothing: the rules are exercised by tools/validate/test_tools.py against a
        # synthetic GLB, so this line says the gate is ready rather than that it found no faults.
        print(
            "meshes: no models committed yet; the container, index, UV and budget rules are "
            "covered by the unit tests and will run on the first real model"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
