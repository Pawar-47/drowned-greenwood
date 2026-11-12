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
| Blender | `4.2.23` LTS, linux-x64 | present in `download.blender.org/release/Blender4.2/` index; **SHA-256 verified in CI** | conversion hub: bake, realise instances, LODs, glTF export, previews |
| Godot | `4.7.2-stable`, linux.x86_64 | `api.github.com/repos/godotengine/godot/releases/latest`; **`--version` confirmed in CI** | headless import gate, software-render previews, later Android export |
| gltfpack (meshoptimizer) | `v1.3`, `gltfpack-ubuntu.zip` | `api.github.com/repos/zeux/meshoptimizer/releases/latest` | LOD simplification (`-si`), cleanup. **No `-cc`, no `-tc`** until Godot accepts them |
| glTF-Transform CLI | `@gltf-transform/cli@4` (exact version recorded from run) | npm | dedup, prune, weld, resample animations, texture resize |
| Python | `3.11` | `actions/setup-python` | Infinigen (its supported interpreter), pipeline scripts |
| MPFB2 | commit recorded from first run | `git clone` of `makehumancommunity/mpfb2`; **enables but registers 0 operators — cause pending** | human bodies, heads, base clothing, auto-rig |
| Modular Tree (MTree) | commit `faf77c1538ce8af3d70aed036b8a540058521347` | resolved by CI run 43207155426; **no `bl_info`, looks like a 4.2+ extension** | procedural trees |
| Infinigen | commit recorded in the Phase 0 log | resolved by CI; **install, import and CLI all pass** | rocks, plants, mushrooms, clouds, materials |
| Poly Haven API | live, asset IDs recorded per download | `api.polyhaven.com` | CC0 PBR textures, HDRIs, scanned models |
| Quaternius animation libraries | pack version recorded per clip | quaternius.com / OpenGameArt | CC0 humanoid animation clips |

## Why Blender 4.2 LTS and not a newer major

MPFB2 2.x requires Blender >= 4.2 (stated in its README). 4.2 is the oldest LTS that
satisfies it, and its glTF exporter is the one the rest of the pipeline is written against.
A second Blender version may be added per job later if MTree or Infinigen demand it; each job
pins exactly one Blender version.

## Decisions taken on the Phase 0 evidence (owner-approved)

| Question | Decision |
|---|---|
| Preview rendering | **Cycles CPU is the official preview renderer.** Low samples with denoise, contact sheets at roughly 640×360. Each report states which engine actually produced the pixels. Workbench and EEVEE under Xvfb + llvmpipe are probed but are not depended on. |
| Godot visual checks | Not in CI. The Godot headless **import and load** check stays; anything that needs pixels happens on a real device. |
| Infinigen | Approved as planned: `generate_individual_assets` only, CPU, small shards, never full scenes. |
| Modular Tree | Approved. If the fork does not load in Blender 4.2, trees come from the Infinigen plant factories plus custom generators, and the quality loss is recorded in `reports/tool_evaluation.md`. A separate Blender version per job is allowed. |
| Quaternius animations | Whatever clips can be fetched legally by script. The free Standard ZIPs are downloaded manually by the owner and uploaded to the Release `third-party-quaternius`, outside git; CI fetches them from there. Every missing clip is authored with `bpy`. **No clip count is promised**: `reports/tool_evaluation.md` records the real number once the pack is present. |
| fps | Not measured in CI. Static budgets only (triangles, draw calls, materials, texture memory); `tech_perf_overlay_stub` is P1 so real-device measurement is possible. |

## Release packs

A category that overflows its size budget moves to a GitHub Release, **one tag per
category** (`pack-4e-flora`, and so on). Every asset in a pack records `pack` and its
`sha256` in the manifest, so the build can verify what it downloads. The APK workflow fetches
packs with `GITHUB_TOKEN` and `contents: write`.

## History

`main` stays at roughly 700 MB; 800 MB is the absolute cap. Binaries reach `main` only by
merging the staging branch after the gates pass, never by direct push. Purging is
prevention-first; if it is ever needed, `docs/HISTORY_PURGE.md` has the manual steps and
`.github/workflows/history-purge.yml` is the manual-only, force-pushing equivalent that must
not be run without the owner's explicit approval.

