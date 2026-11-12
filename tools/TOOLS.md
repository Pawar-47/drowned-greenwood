# Pinned toolchain

Nothing in this repository depends on an unpinned tool. Third-party tool source code is
never copied in; it is fetched at a pinned version and recorded here.

## Pin policy

A build must not change because upstream changed. Every entry below states how the workflow
enforces the pin; where it does not yet, it says so rather than implying otherwise.

| Tool | Pin | Enforced how |
|---|---|---|
| Blender 4.2 | `4.2.23` LTS | SHA-256 verified against Blender's published checksum |
| Blender 4.5 | `4.5.16` LTS | SHA-256 verified against Blender's published checksum |
| Godot | `4.7.2-stable` | URL is version-specific; **archive checksum not yet verified** |
| gltfpack | `v1.3` | URL is version-specific; **archive checksum not yet verified** |
| git-filter-repo | `2.45.0` | exact version in `pip install` |
| Modular Tree | commit `faf77c1` | exact commit fetched in CI (`fetch --depth 1 <sha>`) |
| MPFB2 | tag `v2.0.18` | exact tag cloned in CI |
| Infinigen | commit `53033dd` | exact commit fetched in CI |
| glTF-Transform | `4.2.1` | exact version in CI (`@gltf-transform/cli@4.2.1`) |
| GitHub Actions | `@v4` / `@v5` | **major tags, not commit SHAs**; pinning outstanding |

The outstanding pins are listed honestly: an unpinned dependency can change a generated asset
without the repository changing. They are Phase 1 work, not forgotten.

## Verified pins

| Tool | Pin | How verified | Used for |
|---|---|---|---|
| Blender | `4.2.23` LTS, linux-x64 (main job) and `4.5.16` LTS (MTree job) | both present in their release indexes; **SHA-256 verified in CI** | conversion hub: bake, realise instances, LODs, glTF export, previews |
| Godot | `4.7.2-stable`, linux.x86_64 | `--version` confirmed in CI | headless import gate, later Android export |
| gltfpack (meshoptimizer) | `v1.3`, `gltfpack-ubuntu.zip` | release API; **`-si` verified end to end** | LOD simplification. **`-noq` is mandatory**: Godot imports quantized output but loads no geometry from it |
| glTF-Transform CLI | `@gltf-transform/cli@4` (exact version recorded from run) | npm | dedup, prune, weld, resample animations, texture resize |
| Python | `3.11` | `actions/setup-python` | Infinigen (its supported interpreter), pipeline scripts |
| MPFB2 | commit recorded from first run | `git clone` of `makehumancommunity/mpfb2`; **enables but registers 0 operators — cause pending** | human bodies, heads, base clothing, auto-rig |
| Modular Tree (MTree) | commit `faf77c1538ce8af3d70aed036b8a540058521347`, v5.6.0, run under Blender 4.5.16 | **verified in CI**: extension installs, 9 operators register in `bpy.ops.mtree` | procedural trees |
| Infinigen | commit `53033dd55c7191cbc436be6ffbb63c026935a509` | resolved by CI; install, import and CLI all pass | rocks, plants, mushrooms, clouds, materials |
| Poly Haven API | live, asset IDs recorded per download | `api.polyhaven.com` | CC0 PBR textures, HDRIs, scanned models |
| Quaternius animation libraries | release `third-party-quaternius`, asset `Universal.Animation.Library.Standard.zip`, sha256 `cc73fc4e495b82958207316596317a3f40b9fa38065bde1027937452da537724` | fetched from the release by CI, outside git | CC0 humanoid animation clips |

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
| Quaternius animations | The release `third-party-quaternius` supplies `ual1_standard.{fbx,glb}` and `ual1_standard_rm.{fbx,glb}`: **whole animation libraries in single containers**, not one file per clip. Clip counts are therefore unknown until a GLB's animations are enumerated, which is a Phase 5 task. Every clip the packs do not supply is authored with `bpy`. |
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

