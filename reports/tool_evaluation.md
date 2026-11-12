# Tool evaluation (Phase 0)

**Run recorded:** `fe39869` (Phase 0 workflow, run 43207155426). Every entry below comes from
that run's logs. Nothing here is estimated, and anything not measured says so.

> CI regenerates this file from its own logs on every run (`tools/phase0/make_report.py`).
> This version is the written-up result of the first complete run, kept because the raw
> generator output does not carry the reasoning.

## Outcome

15 of 17 probes passed. The two failures are the two most expensive tools, and both have a
fallback the brief already defines.

| Tool | Result | Measured detail | Decision |
|---|---|---|---|
| Blender 4.2.23 download | PASS | SHA-256 matched the vendor's published checksum | pinned, use as is |
| Blender headless startup | PASS | `-b --factory-startup` | conversion hub confirmed |
| Blender glTF 2.0 exporter | PASS | probe sphere: 2208 tris, 53,608 bytes, material survived | the export path works |
| Cycles CPU render | PASS | 640×360, 32 samples, denoise, clipped black 0.0, clipped white 0.0 | **official preview renderer** |
| Workbench via Xvfb + llvmpipe | PASS | same scene, software GL | usable, not depended on |
| EEVEE Next via Xvfb + llvmpipe | PASS | mean luma 0.339, clipping 0.0 | usable, not depended on |
| Godot 4.7.2-stable | PASS | `--version` reports 4.7.2-stable | import gate tool confirmed |
| Godot import and load of the GLB | **NOT MEASURED** | job failed before the probe: the artifact arrived re-nested, so `cp` found no GLB | harness bug, fixed; re-run needed |
| gltfpack `-si` simplification | **NOT MEASURED** | the step aborted on `gltfpack -h`'s non-zero exit, so neither probe emitted a result | harness bug, fixed; re-run needed |
| Infinigen install | PASS | installs and imports on Python 3.11 in 12m 32s total job time | use as planned |
| Infinigen asset generator CLI | PASS | `generate_individual_assets --help` resolves | use as planned |
| glTF-Transform CLI | PASS | installs, `--version` runs | use as planned |
| Poly Haven API | PASS | asset list, file list, 1k map download | use as planned |
| MPFB2 enable | PASS | Blender accepts the add-on | — |
| MPFB2 operators | **FAIL** | `count=0` — enabled but registered no operators | see below |
| MPFB2 create_human | **FAIL** | `could not be found` | see below |
| MTree install | **FAIL** | `no __init__.py containing bl_info`; the repo root has an `__init__.py` without `bl_info` | see below |
| Quaternius packs | NOT RUN | step added after this run; the release does not exist yet | open task on the owner |

## Two failures, with the cause

**MPFB2 registers zero operators.** `addon_utils.enable()` returns success and the module
still exposes no `bpy.ops.mpfb` namespace, which means the add-on's own import failed and
Blender swallowed the error. The probe now imports the module directly to capture the real
traceback, so the next run says *why* rather than only *that*.

**MTree does not install as a legacy add-on.** Commit
`faf77c1538ce8af3d70aed036b8a540058521347`. Its `__init__.py` has no `bl_info` block, which is
the signature of a Blender 4.2+ **extension** rather than an add-on. Copying files into
`scripts/addons` cannot register an extension; it has to be installed as one, or run under the
Blender version the fork targets. Per the owner's decision, a separate Blender version per job
is allowed, so this is worth one more attempt before falling back.

## Harness bugs found and fixed

These were mine, not the tools', and they are why this run could not answer two of its own
questions:

1. **Multi-path artifact upload re-nests on download.** A multi-path upload roots the artifact
   at the least common ancestor of its paths, so the Godot job received the GLBs one directory
   deeper than it looked. Each job now uploads one directory, with its log copied in first.
2. **`gltfpack -h` aborts its step.** GitHub's default shell is `bash -e`, so a non-zero exit
   killed the step before the simplification probe ran. The call is now guarded.
3. **Probes shared one result name.** All three renders reported `step="render"`, so Cycles and
   Workbench were overwritten by EEVEE and never appeared. Each now reports its own name.
4. **The add-on installer aborted its step.** It exited 1 on a layout it did not recognise,
   taking the probe with it. It now always exits 0 and reports the layout it found.

## What the next run must answer

- Does Godot import and load the Blender GLB, and the gltfpack-simplified one?
- Does `gltfpack -si` produce output Godot accepts? This decides the LOD pipeline.
- What is the real MPFB2 import error?
- Is MTree a 4.2 extension that can be installed, or does it need another Blender version?

## Consequences already decided

- **Preview rendering** is Cycles CPU, as agreed. Workbench and EEVEE also work under
  llvmpipe, which is a bonus, not a dependency.
- **Infinigen** is usable on the free runners: install, import and CLI all pass, in a
  12m 32s job rather than the 120-minute ceiling I budgeted. Small shards remain the plan.
- **Humans and trees** are not yet decided: both depend on the two failures above, and both
  fall back to custom generators if the next run does not clear them.
