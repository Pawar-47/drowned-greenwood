# Third-party tools and assets

Allowed licenses: CC0, MIT, BSD, Apache-2.0, OFL (fonts), CC-BY (attribution recorded).
Not allowed: CC-NC, "personal use only", unknown license, anything ripped from a commercial
game. Only assets that permit commercial use enter this repository.

## Tools used (never copied into this repository)

| Tool | License | Role |
|---|---|---|
| Blender | GPL-2.0-or-later | external conversion hub: bake, LODs, glTF export |
| Godot Engine | MIT | import gate, renderer, later the game |
| Infinigen | BSD-3-Clause | procedural nature: rocks, plants, fungi, clouds, materials |
| MPFB2 | code GPL-3.0, bundled assets CC0 | human bodies, heads, base clothing, rigging |
| Modular Tree (MTree) | GPL-3.0 | procedural trees |
| gltfpack / meshoptimizer | MIT | mesh simplification, cleanup |
| glTF-Transform | MIT | dedup, prune, animation resample, texture resize |
| polydown | MIT | Poly Haven downloader |
| Terrain3D | MIT | terrain validation helper (not a generator) |
| ProtonScatter | MIT | scatter validation helper (not a generator) |

## How a licence is decided

The manifest no longer defaults every asset to CC0. That default made an asset whose provenance
had never been checked look identical to one whose licence had been verified, which is the one
thing a licence field must never do.

`tools/build_manifest.py` derives `source_license` from `source_tool`:

| Source tool | Licence recorded | Why |
|---|---|---|
| `custom` | `project-original` | the generators are ours and the geometry they emit is ours |
| `polyhaven` | `CC0-1.0` | Poly Haven publishes its API assets as CC0 |
| `mpfb2` | `CC0-1.0` | bundled base mesh, skins and clothes are CC0 per `LICENSE.ASSETS.md` |
| `quaternius` | `CC0-1.0` | the Universal Animation Library is CC0 |
| `infinigen` | `project-original` | BSD-3-Clause tool; generated output is ours |
| `mtree` | `NEEDS-REVIEW` | see below |
| anything else | none | `check_manifest.py` rejects it |

An authored entry may override the tool default with a sixth field, because not every asset's
licence follows from the tool that fetched it — a font is OFL, a music loop may be CC-BY:

    audio_ambience_rain|C|P2|1|none|CC-BY-4.0

The override is checked against the same allowlist as the derived value, so it cannot be used to
smuggle in a licence the brief forbids.

## Open question: Modular Tree output

Modular Tree is **GPL-3.0**. Geometry it generates is normally not a derivative work of the
generator — a program's output is not covered by the program's copyright unless it embeds part
of the program — but that is a legal judgement, and this pipeline should not make it silently.

So MTree-sourced assets carry `NEEDS-REVIEW`, which:

- does **not** block planning: the assets stay in the manifest and the build stays green;
- **does** block shipping: `check_manifest.py` fails if any asset in that state is ever marked
  built.

**This needs the owner's decision before Phase 3 commits any tree geometry.** The options are
to accept that generated output is unencumbered, to use a permissively licensed generator
instead, or to accept GPL-3.0 for the tree assets specifically.

## Assets

Every third-party asset id (Poly Haven texture/model, Quaternius clip) is recorded here when
it enters the pipeline, with the license and the commit or pack version it came from.

| Asset id | Source | License | Used for |
|---|---|---|---|
| _(none yet — Phase 0 records a single sample download only)_ | | | |
