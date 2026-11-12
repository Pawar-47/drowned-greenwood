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
assets/          manifest.json (authored list), LICENSES.md, ADDITIONS.md, skeleton definitions,
                 surface_ids.json, surface_fx_table.json
tools/           build_manifest.py, TOOLS.md, config/materials.json, generators/, phase0/
                 (probes), validate/ (checks)
shaders/         surface_base.gdshader, foliage_base.gdshader, shared includes, SHADER_GLOBALS.md
docs/            HISTORY_PURGE.md, LESSONS.md, POLICY.md
reports/         tool_evaluation.md, quality_report.md, below_target.md, phase2.md
.github/workflows/  phase0-tool-evaluation, validate, history-purge
```

Planned, not present: an APK build workflow (Phase 9) and a `staging` branch. The staging branch
is the intended path for binaries to reach `main`; until it exists, nothing binary is committed at
all, which is why the repository is currently about 0.6 MB of tooling, configs and definitions.

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
python tools/validate/test_tools.py       # unit tests for the manifest builder and report parser
python tools/validate/check_manifest.py   # structure, budgets, licences
python tools/validate/check_skeletons.py  # bone caps, humanoid hierarchy, LOD and cloth budgets, animal coverage
python tools/validate/check_materials.py  # materials, surface ids, FX table, duplicate shader uniforms
```

`assets/ADDITIONS.md` records the six approved additions, all P1 and scheduled: weather
environment presets, hydrology data, the surface-ID map, the shared skeleton and retarget
artifacts, and two animal skeleton families found while writing the validator.

## The shared material system

Every opaque surface and every plant in the game is one of **two shaders** with different
parameters, not its own shader. `shaders/surface_base.gdshader` covers ground, rock, wood and
buildings; `shaders/foliage_base.gdshader` covers leaves, ferns, grass and ivy. Both include the
wetness pass, so no material can be forgotten and left bone dry next to a soaked one.

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
a category overflows. Binaries reach `main` only by merging
the staging branch after the gates pass. A category that overflows its budget moves to a
GitHub Release, one tag per category, and every affected asset records its `pack` and
`sha256`. Prevention first: if history ever has to be rewritten, `docs/HISTORY_PURGE.md` has
the manual steps, and `.github/workflows/history-purge.yml` is the manual-only equivalent —
dry-run by default, inputs never interpolated into shell, backup uploaded before anything is
pushed.

## Phases (stop and report after each)

| Phase | Content | Status |
|---|---|---|
| 0 | Tool smoke tests | **CLOSED — 0 defects, every pin enforced.** The last run reports **56 probes: 55 passed, 1 negative control holding, 0 defects**. Verified end to end: Blender 4.2.23 and 4.5.16 (SHA-256 checked on every job, cache hit or miss), all three renderers, Godot import/load (archive SHA-256 verified), both shader includes compile, **MTree generates a tree that Godot loads**, **MPFB2 builds and rigs a human that Godot loads** (commit-pinned, not tag-pinned), gltfpack `-noq` (archive SHA-256 verified), Infinigen, glTF-Transform, Poly Haven, Quaternius (archive verified, retarget map verified against the pack's real joints), and the report gate (it fails the job on a defect). GitHub Actions are pinned to commit SHAs and the static gate refuses a tag. **Carried into later phases, all measured and all over budget:** MTree's raw tree is hundreds of thousands of triangles and tens of MB against a 10k–16k tri hero budget and a 1.5 MB per-species cap (the exact count varies per generated seed — 1,091,354 / 1,228,966 / 1,840,066 have all been measured — so the current figure lives in `reports/tool_evaluation.md` rather than here); MPFB2's human is **36,972 tris / 137 bones** against 12k–18k and 65. Decimation and bone reduction are Phase 3 and Phase 5 work. Quaternius supplies 43 clips and its rig is **Unreal-mannequin named**, not Mixamo; family coverage is **14 of 41** by clip-name token matching, and that figure is wrong in both directions (a false positive on `anim_bow`, a false negative on `anim_run`). See `reports/tool_evaluation.md` |
| 1 | Repo structure, manifest, workflows, validators, shared PBR material system, **skeleton and retarget definitions** | **in progress — material system done.** Done: repo structure, the 1,954-asset manifest, three workflows with enforced concurrency and SHA-pinned actions, five validators with 15 unit tests, the shared skeleton (56 bones, cloth budget checked) and the verified retarget map, the surface-ID contract and FX table, and the **shared PBR material system**: two shaders, 19 materials, both shaders compiled by the Phase 0 gate. Remaining: nothing named — Phase 1's list is complete, and the open items below are Phase 2+ work |
| 2 | Ground/terrain, rocks, water, sky/atmosphere/weather, **weather env presets, hydrology, surface-ID map** | **in progress.** Built and measured: the 1 km heightmap, biome mask and surface-ID map (1025² each, from one height field so they cannot disagree), plus hydrology — the water-depth/flow mask, shore mask, river centreline (655 points, every segment descending) and water level table. Last run: 49.9 % grass, 21.8 % moss, 16.6 % bare rock, 5.8 % water, height 9–152 m. `validate.yml` runs both generators and gates the composition and the river's descent. Remaining: normalmap, splat set, blend rules, weather presets, rocks and water surfaces, and the terrain mesh. See `reports/phase2.md` |
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
1,954 planned assets — is Phases 1–9.

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
