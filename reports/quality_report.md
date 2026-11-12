# Quality report

Per-asset quality results against the brief's section 2A. **Empty until assets exist**: Phase 0
built no assets, and Phase 1 is definitions and tooling.

CI writes the machine-generated tables into this file when a build runs. This header and the
sections below are the shape that output takes, so the file is never a broken link and the
structure is agreed before the first asset is judged.

## How an asset is recorded

| Field | Source |
|---|---|
| tier, priority | `assets/manifest.json` |
| triangles at LOD0 | measured on the exported `.glb` |
| LOD ratios | LOD1/LOD0 and LOD2/LOD0, target 50 % ±10 and 25 % ±10 |
| texel density | measured from UV area against surface area, against the tier's target ±25 % |
| albedo range | sRGB luminance min/max, must sit inside 30–240 |
| roughness range | min/max and standard deviation, must not be uniform |
| detail-band scores | high-pass variance at macro, meso and micro scales, each ≥ 0.02 |
| bones, weights | bone count against the class cap; max weights per vertex |
| collision proxy | triangle count of `<asset>_col` |
| size | bytes, against the per-asset cap in section 2B |
| gates | one line per `[HARD-TECH]` rule: pass or the measured failure |

## Current status

| Measure | Value |
|---|---|
| Assets built | 0 |
| Assets passing every `[HARD-TECH]` rule | 0 |
| Assets `BELOW_TARGET` | 0 (see `below_target.md`) |
| Committed asset size | 0 MB of a 700 MB target, 800 MB hard cap |

## Phase 0 and Phase 1 checks

The checks that do run are the tool and definition gates, and their results live in
`reports/tool_evaluation.md` rather than here, because they measure tools and definitions, not
assets:

- `tools/validate/check_scripts.py` — every Python, shell, JSON, shader and workflow file parses
- `tools/validate/check_manifest.py` — 1,953 expanded assets, budget coverage, licence allowlist
- `tools/validate/check_skeletons.py` — bone caps, hierarchy, Godot profile names, LOD counts,
  bilateral optional bones, species coverage
