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

```
assets/          manifest.json (authored list), LICENSES.md, ADDITIONS.md, and the built asset tree
tools/           generators/ config/ validate/ phase0/ build_manifest.py TOOLS.md
docs/            HISTORY_PURGE.md
reports/         tool_evaluation.md, quality_report.md, below_target.md, scene_tests/, previews/
.github/workflows/  phase0-tool-evaluation, validate, history-purge
```

## The asset list

`assets/manifest.json` is the authored source: categories of `name|tier|priority|variants|source_tool`
entries, where an empty field inherits from the group. `tools/build_manifest.py` expands it into
`assets/manifest.expanded.json` — one record per asset, carrying every field the brief requires
(`tier`, `priority`, `path`, `tris`, `lod_tris`, texture sizes, `bones`, `anims`, `tags`,
`source_tool`, `tool_version`, `source_license`, `input_hash`, `sha256`, `pack`, `size_kb`,
`status`, `gate_results`) — and refuses to write if the list is inconsistent.

```bash
python tools/build_manifest.py          # expand
python tools/validate/check_manifest.py # structural checks
```

`assets/ADDITIONS.md` records the four approved additions, all P1 and scheduled: weather
environment presets, hydrology data, the surface-ID map, and the shared skeleton / retarget
artifacts.

## Size and history

`main` stays around 700 MB; 800 MB is the absolute cap. Binaries reach `main` only by merging
the staging branch after the gates pass. A category that overflows its budget moves to a
GitHub Release, one tag per category, and every affected asset records its `pack` and
`sha256`. Prevention first: if history ever has to be rewritten, `docs/HISTORY_PURGE.md` has
the manual steps, and `.github/workflows/history-purge.yml` is the manual-only equivalent that
force-pushes and must not be run without explicit approval.

## Phases (stop and report after each)

| Phase | Content | Status |
|---|---|---|
| 0 | Tool smoke tests: Blender headless render, glTF export, Godot import, gltfpack, glTF-Transform, MPFB2, MTree, Infinigen, Poly Haven API, Quaternius packs | in progress |
| 1 | Repo structure, manifest, workflows, validators, shared PBR material system, **skeleton and retarget definitions** | pending |
| 2 | Ground/terrain, rocks, water, sky/atmosphere/weather, **weather env presets, hydrology, surface-ID map** | pending |
| 3 | Flora: trees, dead wood, shrubs, ferns, ground cover, fungi, crops | pending |
| 4 | Fauna, hunting loot, animal sign | pending |
| 5 | Humans, clothing, armor, clan kits, animations | pending |
| 6 | Weapons, hunting gear, traps, siege | pending |
| 7 | Settlements, forts, props, vehicles | pending |
| 8 | VFX, shaders, UI | pending |
| 9 | Biome scatter, audio, final 1 km test world, debug APK | pending |

## CI rules

**One CI run at a time.** A new push is made only after the previous run has finished.

This is enforced, not just a habit: every workflow shares the concurrency group `ci-serial`
with `cancel-in-progress: false`, so a run that arrives while another is executing waits its
turn rather than starting alongside it. GitHub keeps only the most recent waiting run per
group and drops older ones, which is the behaviour we want — no pile-up, and never two runs
racing to write the same report.

The rule covers workflow **runs**. Jobs *inside* one run still execute in parallel (the Phase 0
workflow's four jobs, for example), because they are one run, not two.

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
