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
| Blender | `4.2.23` LTS, linux-x64 (main job) and `4.5.16` LTS (MTree job) | both present in their release indexes; **SHA-256 verified in CI** | conversion hub: bake, realise instances, LODs, glTF export, previews |
| Godot | `4.7.2-stable`, linux.x86_64 | `--version` confirmed in CI | headless import gate, later Android export |
| gltfpack (meshoptimizer) | `v1.3`, `gltfpack-ubuntu.zip` | release API; **`-si` verified end to end** | LOD simplification. **`-noq` is mandatory**: Godot imports quantized output but loads no geometry from it |
| glTF-Transform CLI | `@gltf-transform/cli@4` (exact version recorded from run) | npm | dedup, prune, weld, resample animations, texture resize |
| Python | `3.11` | `actions/setup-python` | Infinigen (its supported interpreter), pipeline scripts |
| MPFB2 | commit recorded from first run | `git clone` of `makehumancommunity/mpfb2`; **enables but registers 0 operators — cause pending** | human bodies, heads, base clothing, auto-rig |
| Modular Tree (MTree) | commit `faf77c1538ce8af3d70aed036b8a540058521347`, v5.6.0 | resolved by CI; **`blender_version_min = 4.5.0`**, so it needs the 4.5 job | procedural trees |
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
| Quaternius animations | Whatever clips the packs supply. The owner uploads the free Standard ZIPs to the Release `third-party-quaternius`, outside git; CI fetches them from there, unzips them and reports a **measured** clip count and coverage of the brief's animation families. Every clip the packs do not supply is authored with `bpy`. |
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

