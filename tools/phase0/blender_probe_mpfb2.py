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

    # Blender's own diagnostics put the user config addons directory on sys.path but not the
    # Blender installation's addons directory, which is where an earlier install went. Add
    # every plausible addons directory before asking Blender to enable anything, so a
    # correctly installed add-on cannot fail merely because Blender did not look there.
    candidates = [
        os.path.join(os.path.expanduser("~"), ".config", "blender", "4.2", "scripts", "addons")
    ]
    for script_path in bpy.utils.script_paths():
        candidates.append(os.path.join(script_path, "addons"))
    added = []
    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
            added.append(path)

    try:
        addon_utils.enable("mpfb", default_set=True, persistent=False)
        enabled = True
        error = ""
    except Exception as exc:  # noqa: BLE001 - the failure itself is the finding
        enabled = False
        error = str(exc)[:300]
    result(step="mpfb_enable", ok=enabled, error=error, sys_path_added=added)

    if not enabled:
        return 1

    # addon_utils.enable() swallows an import error and returns as if it worked, so a
    # zero-operator add-on looks like a success. Import the module directly to get the real
    # traceback: that is what tells the report why MPFB2 is unusable, not just that it is.
    import traceback

    import_error = ""
    module_file = ""
    try:
        import mpfb  # noqa: F401

        module_file = getattr(mpfb, "__file__", "")
    except Exception:  # noqa: BLE001
        import_error = traceback.format_exc()[-800:]
    result(
        step="mpfb_import",
        ok=not import_error,
        module_file=module_file,
        sys_path_added=added,
        error=import_error.replace("\n", " | ")[:500],
    )

    has_namespace = hasattr(bpy.ops, "mpfb")
    names = sorted(name for name in dir(bpy.ops.mpfb)) if has_namespace else []
    result(
        step="mpfb_operators",
        ok=has_namespace and len(names) > 0,
        count=len(names),
        names=names[:60],
    )

    # When the module cannot be imported, report where Blender was actually looking. A bare
    # ModuleNotFoundError says the path is wrong but not which path, and guessing at that has
    # already cost two runs.
    if import_error:
        discovered = [m.__name__ for m in addon_utils.modules() if "mpfb" in m.__name__.lower()]
        script_paths = [p for p in bpy.utils.script_paths() if "addons" in p or "scripts" in p]
        addon_dirs = []
        for path in script_paths:
            if os.path.isdir(path):
                addon_dirs.extend(sorted(os.listdir(path))[:20])
        result(
            step="mpfb_diagnostics",
            ok=False,
            discovered_modules=discovered,
            script_paths=script_paths,
            installed_addons=addon_dirs[:40],
            sys_path_addons=[p for p in sys.path if "addons" in p],
        )
        return 1

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
