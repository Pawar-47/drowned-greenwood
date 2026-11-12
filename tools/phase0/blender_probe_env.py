"""Phase 0 probe: Blender runs headless, has a usable glTF exporter, and can export a GLB.

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_env.py -- --out artifacts/phase0

Prints RESULT lines that the workflow collects into phase0_log.txt.
"""

import json
import os
import sys

import bpy


def arg_value(flag, default=None):
    argv = sys.argv
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    if flag in rest:
        i = rest.index(flag)
        if i + 1 < len(rest):
            return rest[i + 1]
    return default


def result(**fields):
    print("RESULT " + json.dumps(fields, sort_keys=True))


def main():
    outdir = arg_value("--out", "/tmp/phase0")
    os.makedirs(outdir, exist_ok=True)

    result(
        step="blender_env",
        ok=True,
        blender=bpy.app.version_string,
        python=sys.version.split()[0],
        gltf_exporter=hasattr(bpy.ops.export_scene, "gltf"),
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)

    # A sphere with a real material: enough to prove materials survive the export.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    obj = bpy.context.active_object
    obj.name = "probe_sphere"
    bpy.ops.object.shade_smooth()

    mat = bpy.data.materials.new("probe_material")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.22, 0.33, 0.16, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.45
        bsdf.inputs["Metallic"].default_value = 0.0
    obj.data.materials.append(mat)

    obj.data.calc_loop_triangles()
    tris = len(obj.data.loop_triangles)

    glb = os.path.join(outdir, "probe_sphere.glb")
    ok = True
    error = ""
    try:
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False)
    except Exception as exc:  # noqa: BLE001 - the point of the probe is to report the failure
        ok = False
        error = str(exc)[:300]

    result(
        step="gltf_export",
        ok=ok and os.path.exists(glb),
        path=glb,
        bytes=os.path.getsize(glb) if os.path.exists(glb) else 0,
        tris=tris,
        error=error,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
