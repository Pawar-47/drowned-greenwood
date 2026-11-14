# Quality report

Per-asset results against the brief's section 2A. This report is maintained by hand; no workflow
writes it. Generator reports and `assets/built.json` carry the machine-recorded evidence.

The twelve generated terrain products are recorded in `assets/built.json` and are **not committed**:
they are a release pack, listed in `assets/packs.json` with the archive's SHA-256 and a hash and
size for every file. `tools/fetch_packs.py` downloads and verifies them into `assets/terrain/`
before any check or build runs, in CI and in a fresh clone alike, so the paths `built.json` names
are the paths everything reads whether or not git carries the bytes.

Terrain is the first category to make that move (`docs/RELEASES.md`). The publish job cut the pack
from the 1.3.0 generator, verified the upload by downloading it again, recorded the catalogue, and
removed the thirteen committed copies from the index. `main` no longer carries a terrain binary;
what it carries is the catalogue and the evidence.

Terrain products are not a substitute for the asset classes and quality metrics in section 2A.
No production GLB models, characters, animation clips or collision meshes are committed under
`assets/`; Phase 0 probe outputs are not production assets. There is therefore no committed model
geometry, weights, deformation or LOD quality to assess. Do not infer those results from the
terrain maps or the successful checks recorded for them.

## How an asset is recorded

| Field | Source |
|---|---|
| tier, priority | `assets/manifest.json` |
| path, SHA-256, input hash, tool version, gate results | generator report, recorded in `assets/built.json` |
| recorded size | generator report; checked against the file size by `check_assets.py` |
| triangles at LOD0, LOD ratios | measured on an exported `.glb` |
| texel density | measured from UV area against surface area, against the tier's target ±25 % |
| albedo and roughness ranges | measured from the exported material textures |
| detail-band scores | high-pass variance at macro, meso and micro scales, each ≥ 0.02 |
| bones, weights, collision proxy | measured on the exported rig and collision mesh |
| gates | one line per `[HARD-TECH]` rule: pass or the measured failure |

## Current evidence

| Measure | Value |
|---|---|
| Generated terrain products recorded | 12 of 12, from a release pack |
| Terrain products with built-evidence records | 12 of 12 |
| Missing built-evidence records | none |
| Terrain bytes committed to git | 0: the pack is on `assets-terrain-1.3.0`, 4.5 MB across 13 files |
| GLB/model assets with section 2A geometry and deformation measurements | 0 |
| Full per-asset section 2A reports | 0 |
| Tracked repository size | about 2 MB, against the 800 MB cap; measured by `check_scripts.py` on every run |

`tools/validate/check_assets.py` opens every recorded built file and verifies its SHA-256 and
recorded size. For the terrain, it also checks that the heightmap matches its sidecar, the splat
weights sum to 255 and agree with the surface-ID map, the hydrology flow directions decode to unit
vectors, the water masks name the same texels, the river descends, water sits above its bed, and the
water-level table starts at the lake's own level and falls from there. The generator job
checks the declared PNG dimensions and channel layouts and gates terrain composition, height steps,
walkability, river length, the centreline reaching the lake, the river's wet width against its
channel, both water ids existing and splat/ID agreement. These checks validate the generated terrain
data; they do not measure model geometry, visual quality on device or every `[HARD-TECH]` criterion
in section 2A.

The last composition measurements recorded in `reports/phase2.md` — 43.8 % grass, 21.3 % moss, 17.3 %
bare rock, 6.3 % water, a 29.1–135.1 m height range, a 321-point descending centreline and 100 %
splat/ID agreement — describe generator 1.0.0. Generators 1.1.0 and 1.2.0 were measured and failed,
in different ways and on the river. **1.3.0 was measured by the publish run that cut the pack**: the
river gates, the wet-width gate, the two water ids, the splat agreement and the pair check all
passed, and the only failure was in the publishing machinery rather than in the assets. Its
composition numbers live in that job's log and in `assets/built.json`; they are not copied here,
because a figure copied out of a log is a figure that drifts.

## Checks that are weaker than they look

- **`check_scripts.py` validates syntax, not meaning.** It proves a file parses; it cannot prove the
  logic is right.
- **The shader hint check is a static allowlist.** It catches unknown sampler hints; it cannot prove
  a shader compiles. The Godot shader probe compiles under Compatibility, not Mobile.
- **Quaternius coverage is a name-keyword heuristic.** It counts `Pistol_Aim` as a bow aim, so
  16 of 41 is an optimistic figure, not a measurement of usable clips.
- **`check_skeletons.py` validates definitions, not deformation.** Animal parent maps are now checked
  for a single `Root`, missing or unknown parents, cycles, root reachability and bilateral bone
  pairs. The definitions contain no rest transforms, and no generated animal rig exists to validate
  rest poses or skinned deformation.
- **The terrain checks validate data, not its presentation.** Mobile-renderer behaviour, the terrain
  mesh, and the visual quality of generated materials still need their relevant assets and a device.

## Declared budgets versus the target

The category budgets total **790 MB** against a **700 MB target** and an **800 MB hard cap**. The
validator fails only above the hard cap, so the declared plan sits 90 MB over target with 10 MB of
headroom. This is a plan, not measured consumption; actual recorded sizes are checked against files,
and the complete terrain evidence is still missing the two splat records.
