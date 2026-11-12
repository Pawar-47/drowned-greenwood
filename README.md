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
assets/          manifest.json (authored list), LICENSES.md, ADDITIONS.md, skeleton definitions
tools/           build_manifest.py, TOOLS.md, phase0/ (probes), validate/ (checks)
shaders/         shared shader includes and SHADER_GLOBALS.md
docs/            HISTORY_PURGE.md, LESSONS.md
reports/         tool_evaluation.md, quality_report.md, below_target.md
.github/workflows/  phase0-tool-evaluation, validate, history-purge
```

Planned, not present: `tools/generators/` and `tools/config/` (Phase 2 onward), an APK build
workflow (Phase 9), and a `staging` branch. The staging branch is the intended path for binaries
to reach `main`; until it exists, nothing binary is committed at all, which is why the repository
is currently about 260 KB of tooling and definitions.

## The asset list

`assets/manifest.json` is the authored source: categories of `name|tier|priority|variants|source_tool`
entries, where an empty field inherits from the group. `tools/build_manifest.py` expands it into
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
python tools/validate/check_scripts.py    # every script, shader and workflow parses
python tools/validate/check_manifest.py   # structure, budgets, licences
python tools/validate/check_skeletons.py  # bone caps, hierarchy, LOD counts
```

`assets/ADDITIONS.md` records the six approved additions, all P1 and scheduled: weather
environment presets, hydrology data, the surface-ID map, the shared skeleton and retarget
artifacts, and two animal skeleton families found while writing the validator.

## Size and history

`main` stays around 700 MB; 800 MB is the absolute cap. Binaries reach `main` only by merging
the staging branch after the gates pass. A category that overflows its budget moves to a
GitHub Release, one tag per category, and every affected asset records its `pack` and
`sha256`. Prevention first: if history ever has to be rewritten, `docs/HISTORY_PURGE.md` has
the manual steps, and `.github/workflows/history-purge.yml` is the manual-only equivalent —
dry-run by default, inputs never interpolated into shell, backup uploaded before anything is
pushed.

## Phases (stop and report after each)

| Phase | Content | Status |
|---|---|---|
| 0 | Tool smoke tests | **CLOSED — 0 defects.** Verified end to end: Blender 4.2.23 and 4.5.16 (checksums), all three renderers, Godot import/load, both shader includes compile, **MTree generates a tree that Godot loads**, **MPFB2 builds and rigs a human that Godot loads**, gltfpack `-noq`, Infinigen, glTF-Transform, Poly Haven, and the report gate (it fails the job on a defect). **Carried into later phases, all measured and all over budget:** MTree's raw tree is hundreds of thousands of triangles and tens of MB against a 10k–16k tri hero budget and a 1.5 MB per-species cap (the exact count varies per generated seed, so the current figure lives in `reports/tool_evaluation.md` rather than here); MPFB2's human is **36,972 tris / 137 bones** against 12k–18k and 65. Decimation and bone reduction are Phase 3 and Phase 5 work. Quaternius supplies 43 clips covering **16 of 41** families. See `reports/tool_evaluation.md` |
| 1 | Repo structure, manifest, workflows, validators, shared PBR material system, **skeleton and retarget definitions** | in progress |
| 2 | Ground/terrain, rocks, water, sky/atmosphere/weather, **weather env presets, hydrology, surface-ID map** | pending |
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

**One CI run at a time.** A new push is made only after the previous run has finished.

This is enforced, not just a habit: every workflow shares the concurrency group `ci-serial`
with `cancel-in-progress: false`, so a run that arrives while another is executing waits its
turn rather than starting alongside it. GitHub keeps only the most recent waiting run per
group and drops older ones, which is the behaviour we want — no pile-up, and never two runs
racing to write the same report.

The rule covers workflow **runs**. Jobs *inside* one run still execute in parallel (the Phase 0
workflow's four jobs, for example), because they are one run, not two.

### The rule is not retroactive

A run's concurrency group is read from the workflow file **at the commit that run executes**.
So the rule only governs runs created from a commit that already contains it. Runs created
from earlier commits keep running side by side and cannot be recalled.

That is exactly what happened on this repository: commits `173958e` and `fe39869` both
predate the rule, so both Phase 0 runs executed at once and each ran its own 120-minute
Infinigen job — duplicated work on the free runner pool. Nothing can cancel them from here;
the fix is to let them finish and never push again mid-run.

The practical rule that follows: **before pushing, check that no run is in progress.** The
concurrency group protects later runs from each other, not from a push made while an
unsynchronised run is still going.

Consequence worth knowing: because the group is repository-wide, a short run such as the
manifest check will queue behind a long one such as Phase 0. That is the intended cost of the
rule.

## CI

All building happens on GitHub-hosted runners (CPU only, no GPU, no display). Nothing is
generated on a workstation. Pinned versions and the owner's decisions on the toolchain:
`tools/TOOLS.md`.

- **Previews** are Cycles CPU renders: low samples, denoise, contact sheets at roughly 640×360.
- **Godot** runs a headless import-and-load gate in CI. Anything that needs pixels happens on a
  real device.
- **fps** is not measured in CI. Static budgets only; `tech_perf_overlay_stub` is P1 so real
  measurement is possible later.
