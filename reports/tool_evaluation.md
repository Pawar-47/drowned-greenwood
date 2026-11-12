# Tool evaluation (Phase 0)

**Status: pending the first workflow run.**

Every entry in this report is a probe that ran on a GitHub-hosted runner. Nothing is filled
in from memory or from a vendor's marketing page. Until the workflow has run, this file says
only that the probes are defined.

Run it from the Actions tab: **phase0-tool-evaluation → Run workflow**. It runs automatically
on any push that touches `tools/phase0/**`.

The workflow overwrites this file from its logs and posts the same content as the job summary.

## What is probed

| Probe | Question it answers |
|---|---|
| `blender_checksum`, `blender_env` | Does the pinned Blender download verify, start headless, and expose the glTF exporter? |
| `gltf_export` | Does a material-carrying mesh survive export to `.glb`? |
| `render_cycles` | Can this runner produce pixels with no GPU and no display? |
| `render_workbench`, `render_eevee` | Does software OpenGL under Xvfb + llvmpipe work, and with which engine? |
| `gltfpack_simplify` | Does `-si` simplification run, and does Godot still import the result? |
| `godot_import`, `godot_load` | Does Godot accept Blender's GLB, and does the mesh arrive in a scene? |
| `mpfb2` | Does MPFB2 load headless and build and export a rigged human? |
| `mtree_register` | Does Modular Tree register in the pinned Blender? |
| `infinigen_install`, `infinigen_cli` | Does Infinigen install on Python 3.11 and expose individual-asset generation? |
| `gltf_transform_*` | Does the glTF-Transform CLI install and run? |
| `polyhaven` | Is the Poly Haven API reachable and does a CC0 1k map download? |
