# Quality report

Per-asset quality results against the brief's section 2A. **Empty until assets exist**: Phase 0
built no assets, and Phase 1 is definitions and tooling.

**No workflow writes this file yet.** An earlier version of this header said CI filled in the
tables when a build ran, which was not true — there is no build workflow until Phase 2, so the
tables below are the agreed shape and nothing has ever written to them. The writer lands with the
first generator that produces an asset; until then this file is written by hand, and saying so is
better than a reader assuming the numbers were measured.

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
  (including the shell inside each workflow `run:` block, via `bash -n`), duplicate JSON keys are
  rejected, plus a sampler-hint check against Godot's documented hint list
- `tools/validate/check_manifest.py` — expanded assets, budget coverage, licence allowlist,
  built-record path/hash requirement
- `tools/validate/check_skeletons.py` — bone caps, humanoid hierarchy, Godot profile names, LOD
  counts and the cloth-chain budget recomputed from the bone list, bilateral optional bones,
  species coverage, retarget status

## What the manifest validator does NOT check yet

An audit correctly pointed out that `check_manifest.py` validates the *plan*, not the *product*.
It confirms structure, budget coverage, licence allowlist and that a record claiming `built` has
a path and a SHA-256 — but it does not open the file and check any of it:

| Not yet checked | Why it cannot be, today |
|---|---|
| the referenced file exists | no asset exists yet; every record is `pending` |
| the recorded SHA-256 matches the file | same |
| the recorded size matches the file | same |
| per-asset file-size limits | same |
| actual per-category storage consumption | same |
| triangle counts, texture dimensions, material counts | needs the GLB opened; no GLB exists |
| LOD availability and ratios | same |
| skeleton and animation compatibility | same |

This is Phase 1 work that becomes possible the moment the first asset is built, and it is the
reason `assets/manifest.json` is described as a plan rather than an inventory. Writing the checks
now, against zero files, would produce a validator that passes by finding nothing — the exact
failure mode in `docs/LESSONS.md` #3.

## Checks that are weaker than they look

- **`check_scripts.py` validates syntax, not meaning.** It proves a file parses; it cannot prove
  the logic is right.
- **The shader hint check is a static allowlist.** It catches `hint_black`; it cannot prove a
  shader compiles. Only the Godot shader probe does that, and only for the two includes it knows.
- **The shader gate compiles under the Compatibility renderer, not Mobile.** The probe project is
  `gl_compatibility` because that is the renderer that compiles shaders on a CPU-only runner with
  no GPU. The game ships on Mobile, so a shader that builds in CI can still fail there: that is a
  real-device check, not a CI one, and it is listed here rather than left implied.
- **Quaternius coverage is a name-keyword heuristic.** It counts `Pistol_Aim` as a bow aim, so
  16 of 41 is an optimistic figure, not a measurement of usable clips.
- **`check_skeletons.py` validates definitions, not deformation.** It proves the bone lists are
  consistent and within budget; it cannot prove a skinned mesh deforms correctly.
- **Animal skeletons have no hierarchy to validate.** Those families are flat lists of bone names
  with no parent links, so only caps, duplicates, optional-bone pairing and species coverage are
  checked. The validator now prints that limit instead of letting "skeleton checks passed" imply
  the animal rigs were validated as deeply as the humanoid one.

## Declared budgets versus the target

The category budgets total **790 MB** against a **700 MB target** and an **800 MB hard cap**.
The validator fails only above the hard cap, so the declared plan sits 90 MB over target with
10 MB of headroom. That is deliberate slack for a plan, not a measurement — no asset exists yet,
and actual usage is checked when files are built, not from the table.
