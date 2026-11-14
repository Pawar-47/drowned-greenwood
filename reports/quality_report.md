# Quality report

Per-asset results against the brief's section 2A. This report is maintained by hand; no workflow
writes it. Generator reports and `assets/built.json` carry the machine-recorded evidence.

The repository contains 12 generated terrain products in `assets/terrain/`. At this revision,
`assets/built.json` has records for 10 of the 12: `terrain_splat_0` and `terrain_splat_1` exist as
files but were not individually recorded because the manifest previously represented them as one
combined entry. The authored manifest now declares them separately, and the publish job is changed
to require evidence for all 12. That pipeline change has not run yet, so the two splat records remain
unverified here.

Terrain is also the first category to move to a **release pack** (`docs/RELEASES.md`). The pack is
cut by the publish job and listed in `assets/packs.json`, with the archive's SHA-256 and every file's;
`tools/fetch_packs.py` puts the bytes back into `assets/terrain/` before any check or build runs, and
the publish job removes them from the git index only after the upload has been verified by
downloading it again. Until that run lands, `main` still carries the twelve products as committed
files from the 1.0.0 generator, and everything below describes `main` rather than what the generator
now produces.

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
| Generated terrain products present | 12 of 12 |
| Terrain products with built-evidence records | 10 of 12 |
| Missing built-evidence records | `terrain_splat_0`, `terrain_splat_1` |
| GLB/model assets with section 2A geometry and deformation measurements | 0 |
| Full per-asset section 2A reports | 0 |
| Complete committed asset-size total | Not established by the current evidence: two terrain records are missing |

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

The last measurements recorded in `reports/phase2.md` — 43.8 % grass, 21.3 % moss, 17.3 % bare
rock, 6.3 % water, a 29.1–135.1 m height range, a 321-point descending centreline and 100 %
splat/ID agreement — describe generator 1.0.0. Generator 1.1.0 was measured and its river failed:
1.4 % of 971 centreline points on water, 66 % of the map raised by the depression fill. Generator
1.2.0 gave the river its own descending surface and was measured too; it failed differently, with
5 of 591 centreline segments climbing where the channel met the lake, and with the river's surface
2 m below the lake along the reach they share. Generator 1.3.0 — which makes the two bodies meet at
one height, widens the channel to 80 m and deepens it to 2.6 m — has not been run, so there are no
current measurements to quote and none are quoted here.

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
