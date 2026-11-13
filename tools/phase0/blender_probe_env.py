"""Phase 0 probe: Blender runs headless, has a usable glTF exporter, and can export a GLB.

Run:
    blender -b --factory-startup -P tools/phase0/blender_probe_env.py -- --out artifacts/phase0

Prints RESULT lines that the workflow collects into phase0_log.txt.
"""

import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_probe_common import export_glb  # noqa: E402


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

    # Vertex colours, deliberately, and this is the point of the control mesh. The wind include
    # takes its per-vertex mask from the ALPHA of COLOR_0, so a sphere with no colours cannot
    # answer the question the whole LOD decision rests on: does gltfpack keep them? A probe on a
    # mesh without them passes while every tree in the game would be rigid.
    #
    # The attribute is wired into the material as well as exported, because Blender's exporter
    # omits COLOR_0 unless a material samples it — which is exactly how the wind mask went
    # missing once already.
    mesh = obj.data
    colours = mesh.color_attributes.new(name="wind_mask", type="FLOAT_COLOR", domain="POINT")
    for entry in colours.data:
        # Alpha 0 means "this vertex carries wind data"; 1 means "unauthored". Every vertex gets
        # 0 so a dropped colour channel is visible rather than looking like an untouched default.
        entry.color = (1.0, 1.0, 1.0, 0.0)
    try:
        mesh.color_attributes.active_color = colours
    except (AttributeError, TypeError):
        # Older Blender names this differently; the material link below still forces the export.
        pass

    mat = bpy.data.materials.new("probe_material")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.22, 0.33, 0.16, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.45
        bsdf.inputs["Metallic"].default_value = 0.0
        vertex_colour = mat.node_tree.nodes.new("ShaderNodeVertexColor")
        vertex_colour.layer_name = "wind_mask"
        mat.node_tree.links.new(vertex_colour.outputs["Color"], bsdf.inputs["Base Color"])
    obj.data.materials.append(mat)

    obj.data.calc_loop_triangles()
    tris = len(obj.data.loop_triangles)

    glb = os.path.join(outdir, "probe_sphere.glb")
    # The shared exporter, not a direct call: it is the one that asks for vertex colours, and a
    # second copy of that decision here is a second place for it to be wrong.
    ok, size, error = export_glb(glb)

    result(
        step="gltf_export",
        ok=ok,
        path=glb,
        bytes=size,
        tris=tris,
        vertex_colours=len(mesh.vertices),
        error=error,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
