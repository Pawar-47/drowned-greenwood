"""Phase 0 probe: MPFB2 loads in headless Blender and can build and export a human.

Run (the workflow installs the add-on into Blender's user addons directory first):
    blender -b --factory-startup -P tools/phase0/blender_probe_mpfb2.py

MPFB2 needs its asset packs (base meshes, skins, clothes) beyond the add-on source itself.
This probe reports exactly how far it gets, so the report can say whether the packs are the
only missing piece.
"""

import json
import os
import sys

import addon_utils
import bpy


def result(**fields):
    print("RESULT " + json.dumps(fields, sort_keys=True))


def main():
    outdir = os.environ.get("PROBE_OUT", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)

    try:
        addon_utils.enable("mpfb", default_set=True, persistent=False)
        enabled = True
        error = ""
    except Exception as exc:  # noqa: BLE001 - the failure itself is the finding
        enabled = False
        error = str(exc)[:300]
    result(step="mpfb_enable", ok=enabled, error=error)

    if not enabled:
        return 1

    has_namespace = hasattr(bpy.ops, "mpfb")
    names = sorted(name for name in dir(bpy.ops.mpfb)) if has_namespace else []
    result(step="mpfb_operators", ok=has_namespace, count=len(names), names=names[:60])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    created = False
    create_error = ""
    try:
        bpy.ops.mpfb.create_human()
        created = True
    except Exception as exc:  # noqa: BLE001
        create_error = str(exc)[:300]
    result(step="mpfb_create_human", ok=created, error=create_error)

    if not created:
        return 1

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    tris = 0
    for mesh in meshes:
        mesh.data.calc_loop_triangles()
        tris += len(mesh.data.loop_triangles)
    bones = sum(len(a.data.bones) for a in armatures)

    glb = os.path.join(outdir, "probe_human.glb")
    exported = False
    export_error = ""
    try:
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False)
        exported = os.path.exists(glb)
    except Exception as exc:  # noqa: BLE001
        export_error = str(exc)[:300]

    result(
        step="mpfb_export",
        ok=exported,
        meshes=len(meshes),
        armatures=len(armatures),
        bones=bones,
        tris=tris,
        bytes=os.path.getsize(glb) if os.path.exists(glb) else 0,
        error=export_error,
    )
    return 0 if exported else 1


if __name__ == "__main__":
    sys.exit(main())
