"""Phase 0 probe: does Modular Tree register in this Blender?

Modular Tree is a Blender 4.2+ **extension** whose manifest declares
`blender_version_min = "4.5.0"`, so it cannot register in Blender 4.2 at all. The workflow
therefore runs this probe under a Blender 4.5 LTS install, which the brief allows
("a separate Blender version per job").

`hasattr(bpy.ops, "anything")` is always True because `bpy.ops` resolves names lazily, so the
earlier probe reported a pass for an add-on that was not loaded. The real test is whether the
namespace contains any operator, which is what `dir()` reports.

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


def main():
    result(step="mtree_blender", ok=True, blender=bpy.app.version_string)

    enabled = False
    error = ""
    try:
        addon_utils.enable("modular_tree", default_set=True, persistent=False)
        enabled = True
    except Exception:  # noqa: BLE001 - the failure itself is the finding
        error = traceback.format_exc()[-600:].replace("\n", " | ")
    result(step="mtree_enable", ok=enabled, error=error[:500])

    names = sorted(name for name in dir(bpy.ops.m_tree))
    result(step="mtree_operators", ok=len(names) > 0, count=len(names), names=names[:40])

    if not names:
        # Report what Blender could see, so a failure names its own cause next time.
        result(
            step="mtree_diagnostics",
            ok=False,
            addon_modules=[m.__name__ for m in addon_utils.modules() if "tree" in m.__name__],
            script_paths=list(bpy.utils.script_paths()),
        )
        return 1

    bpy.ops.wm.read_factory_settings(use_empty=True)
    created = False
    create_error = ""
    try:
        bpy.ops.m_tree.add_tree()
        created = True
    except Exception:  # noqa: BLE001
        create_error = traceback.format_exc()[-400:].replace("\n", " | ")
    result(step="mtree_add_tree", ok=created, error=create_error[:400])

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
    try:
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False)
        exported = os.path.exists(glb)
    except Exception:  # noqa: BLE001
        pass
    result(
        step="mtree_export",
        ok=exported and tris > 0,
        meshes=len(meshes),
        tris=tris,
        bytes=os.path.getsize(glb) if os.path.exists(glb) else 0,
    )
    return 0 if exported and tris > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
