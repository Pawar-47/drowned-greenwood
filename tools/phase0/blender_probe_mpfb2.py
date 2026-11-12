"""Probe: can MPFB2 register and build a human, installed as an extension?

The history of this probe is worth keeping, because each step was a different way of being
wrong, and only the last one found the actual cause:

  1. `addon_utils.enable("mpfb")` inside a `try/except` — which can never fire, because
     `enable()` returns None on failure and prints to stderr. Three runs reported PASS.
  2. "It needs asset packs" — wrong. `src/mpfb/data/3dobjs/base.obj` is 1.7 MB and ships in
     the repository.
  3. "It defines fake_bl_info, so Blender will not recognise it" — half right, and it led to
     installing it as a *legacy add-on*, which is what broke it.
  4. The real cause, from register()'s own traceback:

         ValueError: The "package" does not name an extension

     MPFB2 ships `src/mpfb/blender_manifest.toml`. It is a Blender 4.2 **extension**, and its
     register() calls `bpy.utils.extension_path_user(__package__)`, which raises unless the
     package is installed in an extensions repository. Installing it into `scripts/addons` as
     a legacy add-on can therefore never work, however many files are present.

So this probe expects MPFB2 to have been installed with
`blender --command extension install-file`, and reports what register() says if it was not.

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_mpfb2.py
"""

import os
import sys
import traceback

import addon_utils
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


def body():
    outdir = os.environ.get("PROBE_OUT", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)

    # An installed extension appears as bl_ext.<repo>.<id>. Find whatever MPFB calls itself.
    candidates = [m.__name__ for m in addon_utils.modules() if "mpfb" in m.__name__.lower()]
    report(step="mpfb_modules", ok=True, candidates=candidates[:10])

    module = None
    import_error = ""
    imported_as = ""
    # The bare name `mpfb` only works for a legacy add-on. An extension is importable only under
    # its full `bl_ext.<repo>.<id>` name, so the first attempt failing is the expected path, not
    # an error. Reporting that failure alongside a PASS put a ModuleNotFoundError traceback in a
    # green row, which reads as a defect that is not there.
    for name in ["mpfb"] + candidates:
        try:
            module = __import__(name, fromlist=["*"])
            imported_as = name
            import_error = ""
            break
        except Exception:  # noqa: BLE001
            import_error = traceback.format_exc()

    report(
        step="mpfb_import",
        ok=module is not None,
        imported_as=imported_as,
        module_file=getattr(module, "__file__", ""),
        version=str(getattr(module, "VERSION", "")),
        # Only meaningful when the import actually failed; on success it is empty by design.
        error=short(import_error) if module is None else "",
        note="" if module is None else "imported under its extension name; the bare 'mpfb' "
        "name only exists for a legacy add-on install",
    )
    if module is None:
        return 1

    # Register through Blender's own loader, which is what sets up the extension context that
    # extension_path_user() needs. Calling register() by hand bypasses that and raises.
    register_error = ""
    enabled = False
    try:
        addon_utils.enable(imported_as, default_set=True, persistent=False)
        enabled = imported_as in bpy.context.preferences.addons
    except Exception:  # noqa: BLE001
        register_error = traceback.format_exc()

    # addon_utils.enable does not raise; check whether it actually took.
    if not enabled:
        try:
            module.register()
            enabled = True
        except Exception:  # noqa: BLE001
            register_error = traceback.format_exc()
    report(step="mpfb_register", ok=enabled, via_addon_utils=imported_as in bpy.context.preferences.addons, error=short(register_error))

    operators = sorted(name for name in dir(bpy.ops.mpfb)) if hasattr(bpy.ops, "mpfb") else []
    report(step="mpfb_operators", ok=len(operators) > 0, count=len(operators), names=operators[:40])

    # Is MPFB's own data present? Check the package directory directly rather than through
    # LocationService: that service raised on every run while the human built perfectly well,
    # so its failure was a probe bug reported as a tool defect. A file that must exist for a
    # human to be built is the honest check.
    data_ok = False
    data_dir = ""
    module_dir = os.path.dirname(getattr(module, "__file__", "") or "")
    base_obj = os.path.join(module_dir, "data", "3dobjs", "base.obj")
    if os.path.isfile(base_obj):
        data_ok = True
        data_dir = base_obj
    else:
        # Fall back to the service, but only to locate the directory, not to judge it.
        try:
            from mpfb.services.locationservice import LocationService

            resolved = str(LocationService.get_mpfb_data("3dobjs"))
            data_dir = resolved
            data_ok = os.path.isdir(resolved) and any(
                name.endswith(".obj") for name in os.listdir(resolved)
            )
        except Exception:  # noqa: BLE001
            data_dir = short(traceback.format_exc(), 300)
    report(step="mpfb_data", ok=data_ok, data_dir=data_dir)

    if not operators:
        return 1

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

    # A mesh is not a character. The brief needs a rigged one, so try the add-on's own rigging
    # operators and report what the result actually contains. Informational, not a gate: rigging
    # is Phase 5 work, but knowing whether MPFB can rig at all changes the plan.
    #
    # Preference order matters. `add_custom_rig` needs a custom rig already selected and fails
    # with "No custom rig selected"; `add_standard_rig` builds one from the add-on's own rig
    # definitions, which is what a generated human needs.
    rig_candidates = [name for name in operators if "rig" in name.lower()]
    rig_priority = ("add_standard_rig", "add_rigify_rig", "generate_rigify_rig")
    rig_operator = next((n for n in rig_priority if n in rig_candidates), None)
    if rig_operator is None and rig_candidates:
        rig_operator = rig_candidates[0]

    rigged = False
    rig_error = ""
    if rig_operator:
        try:
            getattr(bpy.ops.mpfb, rig_operator)()
            rigged = any(o.type == "ARMATURE" for o in bpy.data.objects)
        except Exception:  # noqa: BLE001
            rig_error = short(traceback.format_exc(), 400)
    report(
        step="mpfb_rig",
        ok=rigged,
        candidates=rig_candidates[:10],
        operator=rig_operator or "",
        error=rig_error,
    )

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
