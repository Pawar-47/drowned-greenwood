"""Shared helpers for Blender probes.

Two things in here exist because they were got wrong, repeatedly, in Phase 0:

**`clear_scene()` instead of `bpy.ops.wm.read_factory_settings()`.**
Calling `read_factory_settings()` *after* an add-on is enabled **unregisters that add-on**: it
resets Blender's preferences, which is where the enabled add-on list lives. Both probes did this
and then reported "operator could not be found" — MTree registered 9 operators, then lost them
one line later. `clear_scene()` removes objects and collections without touching preferences,
so an enabled add-on stays enabled.

**`report()` writes one JSON RESULT line, always.**
The harness reads `RESULT {...}` and nothing else. A probe that raises before its first
`report()` is indistinguishable from one that never ran, so `main()` in each probe is wrapped
and any escaped exception is reported as a failure with its traceback.

Conventions every probe follows:
  * a result name is unique to the probe (`mpfb_register`, not `register`)
  * `ok` is the probe's own verdict, never an exit code
  * on failure, the detail says where it looked, not only that it failed
"""

import json
import traceback

import bpy


def report(**fields):
    """Print one machine-readable result line."""
    print("RESULT " + json.dumps(fields, sort_keys=True, default=str))


def short(text, limit=700):
    return text.replace("\n", " | ")[-limit:]


def clear_scene():
    """Empty the scene without resetting preferences.

    This is the replacement for `bpy.ops.wm.read_factory_settings(use_empty=True)`, which
    silently disables every add-on that was enabled before it.

    Orphan purging is best-effort: `outliner.orphans_purge` expects a UI context that a
    `-b` background session does not have, so a failure there is swallowed rather than
    allowed to abort a probe that has already done the real work.
    """
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    try:
        bpy.ops.outliner.orphans_purge(
            do_local_ids=True, do_linked_ids=True, do_recursive=True
        )
    except Exception:  # noqa: BLE001 - no UI context in background mode; not fatal
        pass


def find_operator_namespace(keyword):
    """Return (namespace, operators) for the first bpy.ops namespace matching a keyword.

    `hasattr(bpy.ops, "anything")` is always True because bpy.ops resolves names lazily, so
    presence of a name proves nothing. Only a non-empty operator list does.
    """
    for namespace in dir(bpy.ops):
        if keyword.lower() not in namespace.lower():
            continue
        try:
            operators = sorted(name for name in dir(getattr(bpy.ops, namespace)))
        except Exception:  # noqa: BLE001 - an unreadable namespace is simply not a candidate
            continue
        if operators:
            return namespace, operators
    return None, []


def count_mesh_geometry():
    """Total meshes, armatures, bones and triangles currently in the file."""
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    tris = 0
    for mesh in meshes:
        mesh.data.calc_loop_triangles()
        tris += len(mesh.data.loop_triangles)
    bones = sum(len(a.data.bones) for a in armatures)
    return {
        "meshes": len(meshes),
        "armatures": len(armatures),
        "bones": bones,
        "tris": tris,
    }


def export_glb(path):
    """Export the whole scene as a GLB. Returns (ok, bytes, error).

    `export_vertex_color="ACTIVE"` is not a style choice. The wind include reads its per-vertex
    mask from the alpha of the vertex colour, and Blender's exporter drops COLOR_0 unless a
    material actually samples it — so the mask vanished on export and every tree would have
    looked rigid. ACTIVE writes the active colour attribute whether or not a material uses it.
    Older exporters have no such option and raise TypeError, so the first attempt falls back
    rather than failing a probe over a keyword.
    """
    import os

    options = {
        "filepath": path,
        "export_format": "GLB",
        "use_selection": False,
        "export_vertex_color": "ACTIVE",
    }
    try:
        bpy.ops.export_scene.gltf(**options)
    except TypeError:
        options.pop("export_vertex_color", None)
        try:
            bpy.ops.export_scene.gltf(**options)
        except Exception:  # noqa: BLE001
            return False, 0, short(traceback.format_exc(), 300)
    except Exception:  # noqa: BLE001
        return False, 0, short(traceback.format_exc(), 300)
    if not os.path.exists(path):
        return False, 0, "export reported success but wrote no file"
    return True, os.path.getsize(path), ""


def guard(step_prefix, body):
    """Run a probe body, reporting any escaped exception as a named failure.

    Without this, an exception before the first report() leaves the harness with no result at
    all, which reads as "the probe did not run" rather than "the probe crashed here".
    """
    try:
        return body()
    except Exception:  # noqa: BLE001
        report(step=step_prefix + "_crash", ok=False, error=short(traceback.format_exc(), 900))
        return 1
