"""Phase 0 probe: does Modular Tree register in this Blender, and can it make and export a tree?

Modular Tree is a Blender 4.2+ **extension** (`type = "add-on"`, id `modular_tree`) whose
manifest declares `blender_version_min = "4.5.0"`, so it cannot register in Blender 4.2. The
workflow installs it as an extension under a Blender 4.5 LTS install, which the brief allows
("a separate Blender version per job").

`hasattr(bpy.ops, "anything")` is always True because `bpy.ops` resolves names lazily, so an
earlier probe reported a pass for an add-on that was never loaded. This one judges on
`dir(bpy.ops.m_tree)` having entries, and discovers the module name rather than assuming it.

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


def module_candidates():
    """Every add-on or extension module whose name mentions a tree."""
    names = []
    for module in addon_utils.modules():
        name = module.__name__
        if "tree" in name.lower():
            names.append(name)
    return names


def try_enable(name):
    try:
        addon_utils.enable(name, default_set=True, persistent=False)
        return ""
    except Exception:  # noqa: BLE001 - the failure itself is the finding
        return traceback.format_exc()[-600:].replace("\n", " | ")


def main():
    result(step="mtree_blender", ok=True, blender=bpy.app.version_string)

    candidates = module_candidates()
    result(step="mtree_modules", ok=True, candidates=candidates[:10])

    errors = []
    for name in ["modular_tree"] + [c for c in candidates if c != "modular_tree"]:
        error = try_enable(name)
        errors.append("%s: %s" % (name, error[:200] if error else "enabled"))
        if not error and len(dir(bpy.ops.m_tree)) > 0:
            break

    names = sorted(name for name in dir(bpy.ops.m_tree))
    # The extension registers (Blender reports it enabled) yet `m_tree` has no operators, so
    # the namespace it actually uses must be something else. Scan every operator namespace for
    # anything tree-shaped rather than assuming the name.
    tree_namespaces = {}
    for namespace in dir(bpy.ops):
        if "tree" in namespace.lower() or "mtree" in namespace.lower():
            try:
                tree_namespaces[namespace] = sorted(n for n in dir(getattr(bpy.ops, namespace)))[:20]
            except Exception:  # noqa: BLE001
                tree_namespaces[namespace] = ["<unreadable>"]
    if not names and tree_namespaces:
        first = next(iter(tree_namespaces.values()))
        names = first
    result(
        step="mtree_operators",
        ok=len(names) > 0,
        count=len(names),
        names=names[:40],
        namespaces=tree_namespaces,
        attempts=errors[:6],
    )

    if not names:
        result(
            step="mtree_diagnostics",
            ok=False,
            script_paths=list(bpy.utils.script_paths()),
            extensions_repo=sorted(os.listdir(bpy.utils.user_resource("EXTENSIONS", create=True)))
            if os.path.isdir(bpy.utils.user_resource("EXTENSIONS", create=True))
            else [],
        )
        return 1

    # Generate a tree with the operator the namespace actually exposes.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    generator = None
    for candidate in ("add_tree", "add_tree_operator", "generate_tree"):
        if hasattr(bpy.ops.m_tree, candidate):
            generator = candidate
            break
    if generator is None:
        result(step="mtree_add_tree", ok=False, reason="no_generator_operator", names=names[:40])
        return 1

    created = False
    create_error = ""
    try:
        getattr(bpy.ops.m_tree, generator)()
        created = True
    except Exception:  # noqa: BLE001
        create_error = traceback.format_exc()[-400:].replace("\n", " | ")
    result(step="mtree_add_tree", ok=created, operator=generator, error=create_error[:400])

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
