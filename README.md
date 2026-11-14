# The Drowned Greenwood — asset pipeline

Open-world hunting + clan-war game. Dark-age tribal world in a permanently damp temperate
rainforest. Android, Godot 4 (Mobile renderer).

**This repository is in the ASSETS phase.** It contains the tooling, generators, validators,
reports and (once built) the 3D/2D assets. There is no gameplay, AI, networking, input or UI
logic here, by design.

Source of truth = scripts + configs + seeds + pinned tool versions. Binaries are build
products, rebuilt in GitHub Actions and committed per category per milestone only after the
gates pass.

## Layout

What exists now, and what is planned. Anything marked *planned* does not exist yet; it is
listed so the intended shape is visible without being mistaken for present.

```
assets/          manifest.json (authored list), built.json (built evidence), packs.json (release
                 packs), LICENSES.md, ADDITIONS.md, skeleton definitions, surface_ids.json,
                 surface_fx_table.json, terrain/ (the maps, downloaded from their pack)
tools/           build_manifest.py, pack_release.py, fetch_packs.py, TOOLS.md,
                 config/materials.json, generators/, phase0/ (probes), validate/ (checks)
shaders/         surface_base, foliage_base, water_base, shared includes, SHADER_GLOBALS.md
docs/            RELEASES.md, HISTORY_PURGE.md, LESSONS.md, POLICY.md, AUDIT_PROTOCOL.md
reports/         tool_evaluation.md, quality_report.md, below_target.md, phase2.md
.github/workflows/  phase0-tool-evaluation, validate, history-purge
```

Planned, not present: an APK build workflow (Phase 9). The `staging` branch now exists: the publish
job in `validate.yml` regenerates the terrain maps on each push to `main`, uploads them as one
versioned pack on a GitHub Release, and commits the catalogue entry and the built evidence to
`staging` only when the bytes changed; they reach `main` by merging it. The tracked repository is
about 2 MB and carries no terrain binary at all — only the catalogue that says where they are and
what they should hash to, with the 4.5 MB pack on its release beside it. `tools/fetch_packs.py` puts
them back on disk for any job that needs them.

`tools/generators/` holds the asset generators. They are pure standard-library Python — no numpy,
no Pillow — so there is no third-party dependency to pin, and a heightmap is written by a PNG
writer in `common.py` rather than by a library. The first one, `terrain_maps.py`, produces the
1 km heightmap, biome mask and surface-ID map from one height field so the three cannot disagree.

## The asset list

`assets/manifest.json` is the authored source: categories of
`name|tier|priority|variants|source_tool|licence` entries, where an empty field inherits from the
group and an empty `licence` falls back to the source tool's licence. `tools/build_manifest.py` expands it into
`assets/manifest.expanded.json` — one record per asset, carrying every field the brief requires
(`tier`, `priority`, `path`, `tris`, `lod_tris`, texture sizes, `bones`, `anims`, `tags`,
`source_tool`, `tool_version`, `source_license`, `input_hash`, `sha256`, `pack`, `size_kb`,
`status`, `gate_results`) — and refuses to write if the list is inconsistent.

**Those fields are placeholders until an asset exists.** The expander sets `status: pending`
and leaves paths, sizes, hashes and gate results empty; they are filled by the build that
produces the file, not by the list that plans it. A record claiming `built` without a path and
a SHA-256 now fails `check_manifest.py`.

```bash
python tools/build_manifest.py            # expand
python tools/validate/check_scripts.py    # every script, shader, workflow and run block parses
python tools/validate/test_tools.py       # unit tests for generators, shaders and validation contracts
python tools/validate/check_manifest.py   # structure, budgets, licences
python tools/validate/check_skeletons.py  # bone caps, humanoid hierarchy and left/right symmetry, retarget-map evidence, LOD and cloth budgets, animal hierarchies and coverage
python tools/validate/check_materials.py  # materials, surface ids, FX table, duplicate shader uniforms
python tools/validate/check_environment.py  # weather presets, property names and transition curves
python tools/validate/check_action_pins.py  # every pinned action SHA resolves through the GitHub API (needs network)
python tools/fetch_packs.py               # download and verify the packed asset categories from their Releases
python tools/pack_release.py              # build a deterministic ZIP pack and record it in assets/packs.json
python tools/validate/check_packs.py      # the pack catalogue: links, hashes, sizes, destinations, no tracked duplicates
python tools/validate/check_docs.py        # numbers quoted in the docs, the river constants, and markdown table shapes
python tools/validate/check_audit_ledger.py  # every audit clause has a state and something behind it
python tools/validate/check_assets.py       # committed assets: FX contract, built hashes and sizes, terrain consistency, normal-map and biome-mask ranges
```

`assets/ADDITIONS.md` records the six approved additions, all P1 and scheduled: weather
environment presets, hydrology data, the surface-ID map, the shared skeleton and retarget
artifacts, and two animal skeleton families found while writing the validator.

## The shared material system

Every opaque surface and every plant in the game is one of **two shaders** with different
parameters, not its own shader. `shaders/surface_base.gdshader` covers ground, rock, wood and
buildings; `shaders/foliage_base.gdshader` covers leaves, ferns, grass and ivy. Both include the
wetness pass, so no material can be forgotten and left bone dry next to a soaked one. Water is a
third, `shaders/water_base.gdshader`: it is transparent, so it belongs on the transparent pipeline,
and it decodes the terrain's hydrology mask — depth in R, flow in G and B — instead of a texture set.

A material is a row in `tools/config/materials.json`: a texture set, a tiling in metres, a
`wetness_darken`, and — for foliage — its wind amplitudes. `tools/validate/check_materials.py`
checks it, and the Phase 0 workflow **compiles both shaders** in Godot, so a material system
nothing compiles cannot ship.

The three inputs that make it coherent:

- `assets/surface_ids.json` — the closed set of surface types and their numbers. Every consumer
  agrees on these: the surface-ID map's texels, a prop's `surface:<id>` tag in its GLB extras, and
  the FX table. An id is a contract, so ids are never reused or renumbered.
- `assets/surface_fx_table.json` — what happens when something touches a surface: footstep audio
  and VFX, impact VFX, decal, ambient loop. One row per live surface id.
- `shaders/SHADER_GLOBALS.md` — the five globals the weather system drives. Everything else is
  deliberately per material.

## Size and history

`main` stays under 800 MB, the absolute cap. The plan's category budgets total **790 MB** against
a **700 MB** target, so the headroom is 10 MB and it is meant to be visible: `check_manifest.py`
warns above the target and fails above the cap, rather than letting the overrun be discovered when
a category overflows.

**A binary never enters git.** Finished asset categories are published as versioned ZIP packs on
GitHub Releases, and the repository carries only `assets/packs.json`: the link, the archive's
SHA-256 and size, and a hash and size for every file inside it. `tools/fetch_packs.py` downloads
and verifies them into the paths `assets/built.json` already names, and every CI job does that
before it checks or builds anything, so a packed asset and a committed one are the same path to
every consumer. `tools/pack_release.py` builds a deterministic archive — sorted entries, fixed
timestamps — and records it; the publish job uploads it, **downloads it again and compares the
hash**, and only then removes the files from the git index. A version is immutable: re-running the
publish job with changed bytes under an existing tag fails rather than replacing it, because a
version that means two byte sets is worse than a red build. See `docs/RELEASES.md`.

That is also the answer to history: a binary that was never committed cannot need a purge. If one
does land, `docs/HISTORY_PURGE.md` has the manual steps, and
`.github/workflows/history-purge.yml` is the manual-only equivalent — dry-run by default, inputs
never interpolated into shell, backup uploaded before anything is pushed, and `--path` takes the
files out of every commit rather than only the latest one.

## Phases (stop and report after each)

| Phase | Content | Status |
|---|---|---|
| 0 | Tool smoke tests | **CLOSED — 0 defects, every pin enforced.** Last run on `c179cac`: **60 probes: 59 passed, 1 negative control holding, 0 defects.** Verified end to end: Blender 4.2.23 and 4.5.16 (SHA-256 checked on every job, cache hit or miss), all three renderers, Godot import/load (archive SHA-256 verified), both shader includes compile, **MTree generates a tree that Godot loads**, **MPFB2 builds and rigs a human that Godot loads** (commit-pinned, not tag-pinned), gltfpack `-noq` (archive SHA-256 verified), Infinigen, glTF-Transform, Poly Haven, Quaternius (archive verified; **retarget map measured against the pack: 23 of 23 names match, no unmatched entries**; **rest pose measured from the GLB's own transforms: T-pose, arm elevation −0.0° on both sides**), the **hydrology mask loaded in Godot** (format RGB8, 1025², every direction texel decodes to unit length), and the report gate (it fails the job on a defect). GitHub Actions are pinned to commit SHAs and the static gate refuses a tag. **Two findings the new vertex-colour control produced, both Phase 3 blockers for foliage:** the sphere arrives with `vertex_colours=1223, wind_mask_vertices=0`, so Blender's exporter keeps the RGB channels and drops the ALPHA that carries the wind flag; and the gltfpack `-noq` output arrives with `vertex_colours=0`, so gltfpack drops the attribute entirely and foliage LODs cannot carry a mask. **Carried into later phases, all measured and all over budget:** MTree's raw tree is hundreds of thousands of triangles and tens of MB against a 10k–16k tri hero budget and a 1.5 MB per-species cap (the exact count varies per generated seed — 1,091,354 / 1,228,966 / 1,840,066 have all been measured — so the current figure lives in `reports/tool_evaluation.md` rather than here); MPFB2's human is **36,972 tris / 137 bones** against 12k–18k and 65. Decimation and bone reduction are Phase 3 and Phase 5 work. Quaternius supplies 43 clips and its rig is **Unreal-mannequin named**, not Mixamo; family coverage is **14 of 41** by clip-name token matching, and that figure is wrong in both directions (a false positive on `anim_bow`, a false negative on `anim_run`). See `reports/tool_evaluation.md` |
| 1 | Repo structure, manifest, workflows, validators, shared PBR material system, **skeleton and retarget definitions** | **in progress — material system done.** Done: repo structure, the 1,955-asset manifest, three workflows with enforced concurrency and SHA-pinned actions, ten validator scripts and 52 unit tests, the shared skeleton (56 bones, cloth budget checked) and the verified retarget map, the surface-ID contract and FX table, and the **shared PBR material system**: two shaders, 19 materials, both shaders compiled by the Phase 0 gate. Remaining: nothing named — Phase 1's list is complete, and the open items below are Phase 2+ work |
| 2 | Ground/terrain, rocks, water, sky/atmosphere/weather, **weather env presets, hydrology, surface-ID map** | **in progress.** The 12 terrain products are all recorded in `built.json` and their bytes are a release pack (`assets/packs.json`), fetched into `assets/terrain/` by `tools/fetch_packs.py`; git carries the catalogue and the evidence, not the maps. The 1 km heightmap, biome mask and surface-ID map come from one height field (1025² each, so the three cannot disagree). **Water is two bodies**: a lake in the bog at 34.0 m, and a river 80 m wide and 2.6 m deep whose surface falls from that lake to 26.6 m at its mouth, so it flows — the first version had one flat waterline, which flooded the whole channel to a single level. The two meet at one height by construction: the river's bed holds one depth below the lake from the lake's outlet upwards, so the seam is continuous rather than a 2 m step. Hydrology derives the depth/flow mask, the shore mask, the centreline and the water level table from the heightmap. `validate.yml` runs all three generators and gates composition, the river's descent, the fall of the water surface, the head of the centreline reaching the lake's outlet, the river's wet width against the channel it fills, both water ids existing, the fraction of the map the depression fill had to raise, the river lying on water, the outlet leaving the map, channel counts, the blend-rule contract, the largest height step between neighbouring texels, walkability of the valley floor, and splat/ID agreement over both all land and the texels whose neighbourhood is one surface. Remaining: rocks and water surfaces, sky panoramas, and the terrain mesh. See `reports/phase2.md` |
| 3 | Flora: trees, dead wood, shrubs, ferns, ground cover, fungi, crops | pending |
| 4 | Fauna, hunting loot, animal sign | pending |
| 5 | Humans, clothing, armor, clan kits, animations | pending |
| 6 | Weapons, hunting gear, traps, siege | pending |
| 7 | Settlements, forts, props, vehicles | pending |
| 8 | VFX, shaders, UI | pending |
| 9 | Biome scatter, audio, final 1 km test world, debug APK | pending |

**Phase 0 closing means the tooling works, not that the game has assets.** The distinction
matters and is easy to blur: a tool that runs is not an asset, an asset that exists is not one
that meets the brief, and one that meets the brief is not one that runs on a phone. Phase 0
established the first of those for every tool and the second for two of them (a tree and a
human, both over budget). Everything else — decimation, LODs, rig remapping, retargeting, the
1,955 planned assets — is Phases 1–9.

## CI rules

**A dropped run is worse than a slow one.** That is the rule now. It replaced an earlier one
("one CI run at a time, repository-wide") that caused the failure it was meant to prevent.

### What was wrong with a shared concurrency group

A concurrency group is the mechanism that **drops** runs. GitHub keeps one running and one
**pending** run per group, and a third arrival replaces the pending one. So the old arrangement —
every workflow sharing `ci-serial` — let a push-triggered `validate` replace a queued manual
Phase 0 or history-purge dispatch. That run was never created: not cancelled, not failed, just
silently absent, and the queue looked empty afterwards.

Sharing one group across three unrelated workflows made that far more likely than it needed to
be, because they were all competing for a single pending slot.

### The policy now

Each workflow has its own concurrency decision, and `tools/validate/check_scripts.py` **fails the
static gate** if a workflow has none, if two workflows share a group, or if `cancel-in-progress`
does not match the decision. A new workflow cannot inherit a default by accident.

| Workflow | Group | Cancel in progress? | Why |
|---|---|---|---|
| `validate` | `validate-<event>-<ref>` | **yes** | It answers one question — does this tree pass? A run superseded by a newer commit on the same branch has no value. Cancelling shows as "cancelled", which is not the same as a pending run vanishing. |
| `phase0-tool-evaluation` | `phase0-<event>-<ref>` | **no** | It is a gate, and a run killed half way is a run wasted — which is how 120 minutes were burned. A running Phase 0 always finishes. |
| `history-purge` | **none** | — | Every dispatch must execute. A dropped `apply` would leave the remote untouched while looking like it did nothing. |

The event name is part of both groups, so a **manual dispatch and a push never share a group**: a
push cannot replace a queued manual run, which was the specific failure worth fixing.

### What is still not guaranteed, stated plainly

Two runs of the **same** workflow, from the **same** event, on the **same** ref can still collide:
GitHub keeps one pending, and a third arrival replaces it. Nothing in a workflow file can change
that — it is how concurrency groups work. So:

- **A queued manual Phase 0 dispatch can still be replaced** by a second manual Phase 0 dispatch on
  the same branch. Dispatch when the queue is empty.
- **`validate` cancels its own superseded runs**, deliberately, as above.
- **`history-purge` has no group at all**, so no dispatch is ever dropped. The safety a group would
  have given — never two rewrites at once — comes instead from an explicit in-flight check in the
  workflow, immediately before the force-push. That check narrows the window rather than closing
  it: two dispatches starting within the same few seconds could both see an empty queue. The typed
  `FORCE-PUSH` confirmation remains the real gate.

The rule covers workflow **runs**. Jobs *inside* one run still execute in parallel (the Phase 0
workflow's four jobs, for example), because they are one run, not two.

### The old rule was not retroactive either

A run's concurrency group is read from the workflow file **at the commit that run executes**. Runs
created from earlier commits kept the shared group and still ran side by side — which is why
commits `173958e` and `fe39869` each ran their own 120-minute Infinigen job at the same time.
Nothing could cancel them from here.

## CI

All building happens on GitHub-hosted runners (CPU only, no GPU, no display). Nothing is
generated on a workstation. Pinned versions and the owner's decisions on the toolchain:
`tools/TOOLS.md`.

- **Previews** are Cycles CPU renders: low samples, denoise, contact sheets at roughly 640×360.
- **Godot** runs a headless import-and-load gate in CI. Anything that needs pixels happens on a
  real device. The gate's probe project is set to the **Compatibility** renderer, not the Mobile
  one the game ships with: Compatibility is the renderer that compiles shaders deterministically
  in a container with no GPU, and it is what makes the shader gate possible at all. Mobile-renderer
  shader compilation is part of the real-device check, and the report says so.
- **fps** is not measured in CI. Static budgets only; `tech_perf_overlay_stub` is P1 so real
  measurement is possible later.
