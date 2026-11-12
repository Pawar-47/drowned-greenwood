"""Probe: does Modular Tree register, and can it generate and export a tree?

Modular Tree is a Blender 4.2+ **extension** (`type = "add-on"`, id `modular_tree`) declaring
`blender_version_min = "4.5.0"`, so it cannot register in Blender 4.2. The workflow installs it
as an extension under Blender 4.5, which the brief allows.

Three earlier versions of this probe were wrong, and each produced a confident false answer:

  * `hasattr(bpy.ops, "m_tree")` is always True, because bpy.ops resolves names lazily. That
    gave a **false pass**.
  * The operators are not in `m_tree` at all. They are in `bpy.ops.mtree` — `add_leaves`,
    `generate_leaf`, `quick_generate`, the preset appliers. Looking only at `m_tree` gave a
    **false failure**, which was then reported as a rejection of the tool.
  * `bpy.ops.wm.read_factory_settings()` was called between enabling the extension and using
    it, which **unregisters the extension**: it resets the preferences where the enabled
    add-on list lives. The last run showed 9 operators found and then "could not be found"
    for `add_tree` on the very next step. That is this bug, and `clear_scene()` replaces it.

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_mtree.py
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
    find_operator_namespace,
    guard,
    report,
    short,
)


def try_enable(name):
    try:
        addon_utils.enable(name, default_set=True, persistent=False)
        return ""
    except Exception:  # noqa: BLE001
        return short(traceback.format_exc(), 400)


def body():
    outdir = os.environ.get("PROBE_OUT", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)

    report(step="mtree_blender", ok=True, blender=bpy.app.version_string)

    candidates = [m.__name__ for m in addon_utils.modules() if "tree" in m.__name__.lower()]
    report(step="mtree_modules", ok=True, candidates=candidates[:10])

    # Try the documented name first, then whatever Blender says it can see.
    attempts = []
    for name in ["modular_tree"] + [c for c in candidates if c != "modular_tree"]:
        error = try_enable(name)
        attempts.append("%s: %s" % (name, error[:120] if error else "enabled"))
        if not error and find_operator_namespace("tree")[1]:
            break

    namespace, operators = find_operator_namespace("tree")
    report(
        step="mtree_operators",
        ok=len(operators) > 0,
        namespace=namespace or "",
        count=len(operators),
        names=operators[:40],
        attempts=attempts[:6],
    )
    if not operators:
        report(step="mtree_diagnostics", ok=False, script_paths=list(bpy.utils.script_paths()))
        return 1

    # clear_scene(), not read_factory_settings(): the latter would unregister the extension
    # that was just enabled, which is exactly what the previous run tripped over.
    clear_scene()
    ops = getattr(bpy.ops, namespace)
    generator = next(
        (n for n in ("quick_generate", "add_tree", "generate_tree") if n in operators), None
    )
    if generator is None:
        report(step="mtree_generate", ok=False, reason="no_generator_operator", names=operators[:40])
        return 1

    created = False
    create_error = ""
    try:
        getattr(ops, generator)()
        created = True
    except Exception:  # noqa: BLE001
        create_error = short(traceback.format_exc(), 500)
    report(step="mtree_generate", ok=created, operator="%s.%s" % (namespace, generator), error=create_error)
    if not created:
        return 1

    geometry = count_mesh_geometry()
    glb = os.path.join(outdir, "probe_tree.glb")
    exported, size, export_error = export_glb(glb)
    report(
        step="mtree_export",
        ok=exported and geometry["tris"] > 0,
        bytes=size,
        error=export_error,
        **geometry,
    )
    return 0 if exported and geometry["tris"] > 0 else 1


if __name__ == "__main__":
    sys.exit(guard("mtree", body))
