"""Phase 0 probe: can MPFB2 register and build a human?

MPFB2's data IS in the repository: `src/mpfb/data/3dobjs/base.obj` alone is 1.7 MB, plus
`data/rigs`, `data/targets`, `data/poses` and `data/textures`. So "it needs asset packs this
pipeline does not install" was wrong, and three earlier runs chased that wrong explanation.

The real reason this probe never saw the failure: **`addon_utils.enable()` does not raise.**
It returns None whether the add-on registered or not, and prints the traceback to stderr. A
`try/except` around it can therefore never fire, which is why `mpfb_enable` reported PASS for
three runs while the add-on registered nothing.

This probe calls `register()` itself so the exception surfaces, and records:

  * the actual exception and traceback from registration
  * how many classes the add-on's ClassManager registered
  * whether MPFB's data directory resolves
  * the operators available afterwards
  * whether a human can then be built and exported

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_mpfb2.py
"""

import json
import os
import sys
import traceback

import addon_utils
import bpy


def result(**fields):
    print("RESULT " + json.dumps(fields, sort_keys=True))


def short(text, limit=700):
    return text.replace("\n", " | ")[-limit:]


def main():
    outdir = os.environ.get("PROBE_OUT", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)

    # Put every plausible addons directory on sys.path before anything is imported.
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

    # Import the module directly. This is the step that actually fails when MPFB cannot
    # initialise, and it reports why.
    module = None
    import_error = ""
    try:
        import mpfb

        module = mpfb
    except Exception:  # noqa: BLE001
        import_error = traceback.format_exc()
    result(
        step="mpfb_import",
        ok=module is not None,
        module_file=getattr(module, "__file__", ""),
        version=str(getattr(module, "VERSION", "")),
        sys_path_added=added,
        error=short(import_error),
    )

    if module is None:
        result(step="mpfb_diagnostics", ok=False, note="import failed; nothing else can run")
        return 1

    # Call register() directly. addon_utils.enable() swallows this exception, which is the
    # single reason three earlier runs could not explain the failure.
    register_error = ""
    try:
        module.register()
    except Exception:  # noqa: BLE001
        register_error = traceback.format_exc()
    result(step="mpfb_register", ok=not register_error, error=short(register_error))

    # What did the add-on actually put into the operator namespace?
    names = sorted(name for name in dir(bpy.ops.mpfb)) if hasattr(bpy.ops, "mpfb") else []
    result(step="mpfb_operators", ok=len(names) > 0, count=len(names), names=names[:40])

    # MPFB resolves its data through a service; ask it, rather than guessing at a path.
    data_ok = False
    data_detail = ""
    try:
        from mpfb.services.locationservice import LocationService

        data_dir = LocationService.get_mpfb_data("3dobjs")
        data_ok = bool(data_dir) and os.path.isdir(str(data_dir))
        data_detail = str(data_dir)
    except Exception:  # noqa: BLE001
        data_detail = short(traceback.format_exc(), 300)
    result(step="mpfb_data", ok=data_ok, data_dir=data_detail)

    if not names:
        # Report the ClassManager count: a register() that "succeeds" but registers no classes
        # means the failure is inside a submodule import, not in register() itself.
        manager = getattr(module, "ClassManager", None)
        result(
            step="mpfb_diagnostics",
            ok=False,
            classmanager=str(manager),
            note="register() returned but registered no operators",
        )
        return 1

    # Build a human with whichever create operator this build exposes.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    creator = None
    for candidate in ("create_human", "human_create", "create"):
        if candidate in names:
            creator = candidate
            break
    if creator is None:
        result(step="mpfb_create_human", ok=False, reason="no_create_operator", names=names[:40])
        return 1

    created = False
    create_error = ""
    try:
        getattr(bpy.ops.mpfb, creator)()
        created = True
    except Exception:  # noqa: BLE001
        create_error = traceback.format_exc()
    result(step="mpfb_create_human", ok=created, operator=creator, error=short(create_error, 400))

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
    except Exception:  # noqa: BLE001
        export_error = short(traceback.format_exc(), 300)

    result(
        step="mpfb_export",
        ok=exported and tris > 0,
        meshes=len(meshes),
        armatures=len(armatures),
        bones=bones,
        tris=tris,
        bytes=os.path.getsize(glb) if os.path.exists(glb) else 0,
        error=export_error,
    )
    return 0 if exported and tris > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
