"""Phase 0 probe: can this runner produce pixels from Blender, and with which engine?

Run:
    PROBE_ENGINE=CYCLES PROBE_OUT=artifacts/phase0/render_cycles.png \
        blender -b --factory-startup -P tools/phase0/blender_probe_render.py

Engines tried by the workflow:
    CYCLES              - CPU path tracing, expected to work with no GPU and no display
    BLENDER_WORKBENCH   - needs an OpenGL context, so only under xvfb + llvmpipe
    BLENDER_EEVEE_NEXT  - needs a GPU context, so only under xvfb + llvmpipe

Also measures the 2A.9 clipping metric (share of pixels at pure black / pure white) on the
rendered image, which proves the metric is computable inside the pipeline.
"""

import json
import os
import sys

import bpy


def result(**fields):
    print("RESULT " + json.dumps(fields, sort_keys=True))


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    sphere = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    mat = bpy.data.materials.new("probe_material")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.22, 0.33, 0.16, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.35
        bsdf.inputs["Metallic"].default_value = 0.0
    sphere.data.materials.append(mat)

    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, -1.0))
    ground = bpy.context.active_object
    gmat = bpy.data.materials.new("probe_ground")
    gmat.use_nodes = True
    gbsdf = gmat.node_tree.nodes.get("Principled BSDF")
    if gbsdf is not None:
        gbsdf.inputs["Base Color"].default_value = (0.09, 0.07, 0.05, 1.0)
        gbsdf.inputs["Roughness"].default_value = 0.55
    ground.data.materials.append(gmat)

    cam_data = bpy.data.cameras.new("probe_cam")
    cam = bpy.data.objects.new("probe_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (3.2, -3.2, 2.2)
    target = bpy.data.objects.new("probe_target", None)
    scene.collection.objects.link(target)
    target.location = (0.0, 0.0, 0.0)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam

    sun_data = bpy.data.lights.new("probe_sun", type="SUN")
    sun_data.energy = 3.5
    sun = bpy.data.objects.new("probe_sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.85, 0.1, 0.6)

    world = bpy.data.worlds.new("probe_world")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.05, 0.06, 0.05, 1.0)
        background.inputs[1].default_value = 1.0

    return scene


def main():
    engine = os.environ.get("PROBE_ENGINE", "CYCLES")
    out = os.environ.get("PROBE_OUT", "/tmp/phase0/render.png")
    samples = int(os.environ.get("PROBE_SAMPLES", "8"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    scene = build_scene()
    scene.render.engine = engine
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out

    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False

    bpy.ops.render.render(write_still=True)

    exists = os.path.exists(out)
    stats = {}
    if exists:
        import numpy as np

        img = bpy.data.images.load(out)
        pixels = np.array(img.pixels[:], dtype="float32").reshape(-1, 4)[:, :3]
        stats = {
            "clipped_black": round(float((pixels.max(axis=1) <= 0.002).mean()), 6),
            "clipped_white": round(float((pixels.min(axis=1) >= 0.998).mean()), 6),
            "mean_luma": round(float(pixels.mean()), 6),
        }

    result(
        step="render",
        engine=engine,
        ok=exists,
        path=out,
        bytes=os.path.getsize(out) if exists else 0,
        **stats,
    )
    return 0 if exists else 1


if __name__ == "__main__":
    sys.exit(main())
