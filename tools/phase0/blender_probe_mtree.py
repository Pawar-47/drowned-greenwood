"""Phase 0 probe: does Modular Tree register, and can it generate and export a tree?

Modular Tree is a Blender 4.2+ **extension** (`type = "add-on"`, id `modular_tree`) whose
manifest declares `blender_version_min = "4.5.0"`, so it cannot register in Blender 4.2. The
workflow installs it as an extension under a Blender 4.5 LTS install, which the brief allows.

Two earlier versions of this probe were wrong in ways worth recording, because both produced a
confident false negative:

  * `hasattr(bpy.ops, "m_tree")` is always True, because `bpy.ops` resolves names lazily.
  * The operators are not in `bpy.ops.m_tree` at all. They are in `bpy.ops.mtree`:
    `add_leaves`, `generate_leaf`, `quick_generate`, and the preset appliers. The probe now
    discovers the namespace instead of assuming the name, and picks the generator from what it
    actually found.

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_mtree.py
"""

import json
import os
import sys
import traceback

import addon_utils
import bpy


def result(**fields):
    print("RESULT " + json.dumps(fields, sort_keys=True))


def try_enable(name):
    try:
        addon_utils.enable(name, default_set=True, persistent=False)
        return ""
    except Exception:  # noqa: BLE001 - the failure itself is the finding
        return traceback.format_exc()[-600:].replace("\n", " | ")


def find_tree_namespace():
    """Return (namespace, operators) for the first namespace holding tree operators."""
    for namespace in dir(bpy.ops):
        if "tree" not in namespace.lower():
            continue
        operators = sorted(name for name in dir(getattr(bpy.ops, namespace)))
        if operators:
            return namespace, operators
    return None, []


def main():
    result(step="mtree_blender", ok=True, blender=bpy.app.version_string)

    candidates = [m.__name__ for m in addon_utils.modules() if "tree" in m.__name__.lower()]
    result(step="mtree_modules", ok=True, candidates=candidates[:10])

    attempts = []
    for name in ["modular_tree"] + [c for c in candidates if c != "modular_tree"]:
        error = try_enable(name)
        attempts.append("%s: %s" % (name, error[:120] if error else "enabled"))
        if not error and find_tree_namespace()[1]:
            break

    namespace, operators = find_tree_namespace()
    result(
        step="mtree_operators",
        ok=len(operators) > 0,
        namespace=namespace or "",
        count=len(operators),
        names=operators[:40],
        attempts=attempts[:6],
    )

    if not operators:
        result(step="mtree_diagnostics", ok=False, script_paths=list(bpy.utils.script_paths()))
        return 1

    # Generate a tree with the operator this build actually exposes, in preference order.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ops = getattr(bpy.ops, namespace)
    generator = None
    for candidate in ("quick_generate", "add_tree", "generate_tree", "node_function"):
        if candidate in operators:
            generator = candidate
            break
    if generator is None:
        result(step="mtree_add_tree", ok=False, reason="no_generator_operator", names=operators[:40])
        return 1

    created = False
    create_error = ""
    try:
        getattr(ops, generator)()
        created = True
    except Exception:  # noqa: BLE001
        create_error = traceback.format_exc()[-400:].replace("\n", " | ")
    result(step="mtree_add_tree", ok=created, operator="%s.%s" % (namespace, generator), error=create_error[:400])

    if not created:
        return 1

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    tris = 0
    for mesh in meshes:
        mesh.data.calc_loop_triangles()
        tris += len(mesh.data.loop_triangles)

    outdir = os.environ.get("PROBE_OUT", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)
    glb = os.path.join(outdir, "probe_tree.glb")
    exported = False
    export_error = ""
    try:
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False)
        exported = os.path.exists(glb)
    except Exception:  # noqa: BLE001
        export_error = traceback.format_exc()[-300:].replace("\n", " | ")

    result(
        step="mtree_export",
        ok=exported and tris > 0,
        meshes=len(meshes),
        tris=tris,
        bytes=os.path.getsize(glb) if os.path.exists(glb) else 0,
        error=export_error[:300],
    )
    return 0 if exported and tris > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
