# Pinned toolchain

Third-party tool source code is never copied in; it is fetched at a pinned version and recorded
here. **Not every pin is enforced yet** — the outstanding ones are listed below rather than
implied to be done.

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

This is the **only** pin table. An earlier version had two, and they disagreed about
glTF-Transform (`4.2.1` in one, `@4` in the other), which is exactly the kind of drift a pin
table exists to prevent.

| Tool | Pin | Enforced / verified how | State | Used for |
|---|---|---|---|---|
| Blender 4.2 | `4.2.23` LTS, linux-x64 | SHA-256 verified in the main job | **working** | conversion hub: bake, realise instances, LODs, glTF export, previews |
| Blender 4.5 | `4.5.16` LTS, linux-x64 | SHA-256 verified in the tools job | **working** | MTree, which needs `blender_version_min = 4.5.0` |
| Godot | `4.7.2-stable`, linux.x86_64 | `--version` confirmed in CI | **working** | headless import gate, shader compile gate |
| gltfpack | `v1.3`, `gltfpack-ubuntu.zip` | `-si` verified end to end | **working — `-noq` mandatory** | LOD simplification. Godot imports quantized output but loads no geometry from it |
| glTF-Transform | `4.2.1` exact | exact version in CI | **working** | dedup, prune, weld, resample animations, texture resize |
| git-filter-repo | `2.45.0` | exact version in `pip install` | **working** | history purge only |
| Python | `3.11` | `actions/setup-python` | **working** | Infinigen, pipeline scripts |
| Infinigen | commit `53033dd55c7191cbc436be6ffbb63c026935a509` | exact commit fetched in CI | **working** | rocks, plants, mushrooms, clouds, materials |
| Poly Haven API | live, asset IDs recorded per download | `api.polyhaven.com` | **working** | CC0 PBR textures, HDRIs, scanned models |
| Quaternius | release `third-party-quaternius`, sha256 `cc73fc4e495b82958207316596317a3f40b9fa38065bde1027937452da537724` | fetched from the release by CI | **measured: 43 clips, 16 of 41 families** | CC0 humanoid animation clips |
| Modular Tree | commit `faf77c1538ce8af3d70aed036b8a540058521347`, v5.6.0 | exact commit fetched in CI | **installs and registers 9 operators; generation fails** (`cannot import name 'm_tree' from 'm_tree'`) | procedural trees |
| MPFB2 | tag `v2.0.18` | exact tag cloned in CI, installed with `extension install-file` | **registers and exports a 36,972-tri human — over the 12k–18k budget, and with no armature** | human bodies, heads, base clothing |

## Outstanding pins

An unpinned dependency can change a generated asset without the repository changing.

| Item | State |
|---|---|
| Godot archive checksum | **not verified** — the URL is version-specific, the bytes are not checked |
| gltfpack archive checksum | **not verified** — same |
| GitHub Actions | **major tags** (`@v4`, `@v5`), not immutable commit SHAs |
| Blender 4.2 in the tools job | downloaded without the checksum check the main job performs |

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
| Quaternius animations | The release supplies `UAL1_Standard.glb` and `UAL1_Standard_RM.glb`: whole animation libraries in single containers. **Measured: 43 clips, 16 of 41 families covered.** The 25 unmatched families — every melee weapon, skinning, butchering, the bow among them — are authored with `bpy`. Coverage matching is a name-keyword heuristic and is optimistic: it counts `Pistol_Aim` as a bow aim. |
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

