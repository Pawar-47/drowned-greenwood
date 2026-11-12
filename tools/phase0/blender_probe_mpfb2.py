"""Probe: can MPFB2 register and build a human?

The history of this probe is worth keeping, because every step was a different way of being
wrong:

  1. `addon_utils.enable("mpfb")` inside a `try/except` — which can never fire, because
     `enable()` returns None on failure and prints the traceback to stderr. Three runs
     reported PASS while nothing registered.
  2. "It needs asset packs" — wrong. `src/mpfb/data/3dobjs/base.obj` is 1.7 MB and ships in
     the repository.
  3. The real blocker for the add-on loader: MPFB2 defines `fake_bl_info`, not `bl_info`, and
     Blender needs `bl_info` to recognise a legacy add-on. The official package has it
     injected by a build outside the repo.

So this probe does not use `addon_utils` at all. It imports the package and calls
`register()` directly — which is what an add-on loader does internally, needs no `bl_info`,
and surfaces the exception instead of swallowing it.

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_mpfb2.py
"""

import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_probe_common import (  # noqa: E402
    clear_scene,
    count_mesh_geometry,
    export_glb,
    guard,
    report,
    short,
)


def add_addons_to_path():
    """Put every plausible addons directory on sys.path, and say which ones were added."""
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
    return added


def body():
    outdir = os.environ.get("PROBE_OUT", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)

    added = add_addons_to_path()

    # 1. Import the package.
    module = None
    import_error = ""
    try:
        import mpfb

        module = mpfb
    except Exception:  # noqa: BLE001
        import_error = traceback.format_exc()
    report(
        step="mpfb_import",
        ok=module is not None,
        module_file=getattr(module, "__file__", ""),
        version=str(getattr(module, "VERSION", "")),
        sys_path_added=added,
        error=short(import_error),
    )
    if module is None:
        return 1

    # 2. Register it. This is the call addon_utils.enable() makes and hides.
    register_error = ""
    try:
        module.register()
    except Exception:  # noqa: BLE001
        register_error = traceback.format_exc()
    report(step="mpfb_register", ok=not register_error, error=short(register_error))

    # 3. What appeared? A non-empty operator list is the only proof of registration.
    operators = sorted(name for name in dir(bpy.ops.mpfb)) if hasattr(bpy.ops, "mpfb") else []
    report(step="mpfb_operators", ok=len(operators) > 0, count=len(operators), names=operators[:40])

    # 4. Can MPFB find its own data? Ask its service rather than guessing at a path.
    data_ok = False
    data_dir = ""
    try:
        from mpfb.services.locationservice import LocationService

        resolved = LocationService.get_mpfb_data("3dobjs")
        data_dir = str(resolved)
        data_ok = bool(resolved) and os.path.isdir(data_dir)
    except Exception:  # noqa: BLE001
        data_dir = short(traceback.format_exc(), 300)
    report(step="mpfb_data", ok=data_ok, data_dir=data_dir)

    if not operators:
        return 1

    # 5. Build a human. clear_scene() replaces read_factory_settings(), which would
    #    unregister the add-on that was just registered.
    clear_scene()
    creator = next((name for name in ("create_human", "human_create") if name in operators), None)
    if creator is None:
        report(step="mpfb_create_human", ok=False, reason="no_create_operator", names=operators[:40])
        return 1

    created = False
    create_error = ""
    try:
        getattr(bpy.ops.mpfb, creator)()
        created = True
    except Exception:  # noqa: BLE001
        create_error = traceback.format_exc()
    report(step="mpfb_create_human", ok=created, operator=creator, error=short(create_error, 500))
    if not created:
        return 1

    # 6. Export it.
    geometry = count_mesh_geometry()
    glb = os.path.join(outdir, "probe_human.glb")
    exported, size, export_error = export_glb(glb)
    report(
        step="mpfb_export",
        ok=exported and geometry["tris"] > 0,
        bytes=size,
        error=export_error,
        **geometry,
    )
    return 0 if exported and geometry["tris"] > 0 else 1


if __name__ == "__main__":
    sys.exit(guard("mpfb", body))
