# Pinned toolchain

Nothing in this repository depends on an unpinned tool. Third-party tool source code is
never copied in; it is fetched at a pinned version and recorded here.

## Pin policy

**Resolve, then pin.** A version that cannot be verified from the vendor's own index is not
written here from memory. On the first successful Phase 0 run, the workflow records the
resolved version / commit of each tool in `phase0_log.txt` (lines starting with `RESULT` or
`*_commit=`); those values are then written into the table below as the pin, and the workflow
is switched from "resolve" to "verify".

## Verified pins

| Tool | Pin | How verified | Used for |
|---|---|---|---|
| Blender | `4.2.23` LTS, linux-x64 | present in `download.blender.org/release/Blender4.2/` index; checksum fetched and checked at build time | conversion hub: bake, realise instances, LODs, glTF export, previews |
| Godot | `4.7.2-stable`, linux.x86_64 | `api.github.com/repos/godotengine/godot/releases/latest` | headless import gate, software-render previews, later Android export |
| gltfpack (meshoptimizer) | `v1.3`, `gltfpack-ubuntu.zip` | `api.github.com/repos/zeux/meshoptimizer/releases/latest` | LOD simplification (`-si`), cleanup. **No `-cc`, no `-tc`** until Godot accepts them |
| glTF-Transform CLI | `@gltf-transform/cli@4` (exact version recorded from run) | npm | dedup, prune, weld, resample animations, texture resize |
| Python | `3.11` | `actions/setup-python` | Infinigen (its supported interpreter), pipeline scripts |
| MPFB2 | commit recorded from first run | `git clone` of `makehumancommunity/mpfb2` | human bodies, heads, base clothing, auto-rig |
| Modular Tree (MTree) | commit recorded from first run | `git clone` of `GoodPie/modular_tree` | procedural trees |
| Infinigen | commit recorded from first run | `git clone` of `princeton-vl/infinigen` | rocks, plants, mushrooms, clouds, materials |
| Poly Haven API | live, asset IDs recorded per download | `api.polyhaven.com` | CC0 PBR textures, HDRIs, scanned models |
| Quaternius animation libraries | pack version recorded per clip | quaternius.com / OpenGameArt | CC0 humanoid animation clips |

## Why Blender 4.2 LTS and not a newer major

MPFB2 2.x requires Blender >= 4.2 (stated in its README). 4.2 is the oldest LTS that
satisfies it, and its glTF exporter is the one the rest of the pipeline is written against.
A second Blender version may be added per job later if MTree or Infinigen demand it; each job
pins exactly one Blender version.

## Rules that apply to every tool

1. Licenses are recorded in `assets/LICENSES.md`. GPL tools (Blender add-ons) are used only
   as external tools; their code is never copied into this repository.
2. Free GitHub runners are CPU-only with no display. Renders use Cycles CPU, or
   xvfb + Mesa `llvmpipe`. The Mobile (Vulkan) renderer cannot be assumed to software-render;
   if it cannot, previews use the Compatibility renderer and the report says so.
3. Every download is cached with `actions/cache`; every build step is resumable and keyed by
   input hash, so a re-run does not redo finished work.
