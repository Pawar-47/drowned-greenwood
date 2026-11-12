# Tool evaluation (Phase 0)

**Runs recorded:** `fe39869` (43207155426) and `60a1104` (43209599382). Every entry comes
from those runs' logs. Anything not measured says so.

> CI regenerates this file from its own logs on every run (`tools/phase0/make_report.py`).
> This version is the written-up result, kept because the raw generator output does not carry
> the reasoning.

## The import gate passes

This was the question that mattered most, and it is answered:

| Probe | Result | Meaning |
|---|---|---|
| Godot 4.7.2-stable | PASS | the pinned engine runs headless |
| Import of Blender's GLB | PASS | Godot accepts the exporter's output |
| **Load of Blender's GLB** | **PASS** | meshes and triangles arrive in a scene |
| Import of gltfpack output | PASS | the file parses |
| Load of gltfpack output | **FAIL** | imports, then yields no geometry |

So the pipeline's spine works: Blender to `.glb` to Godot, verified in CI on every run. The
LOD question is narrowed but not closed — see below.

## Everything else measured

| Tool | Result | Detail |
|---|---|---|
| Blender 4.2.23 | PASS | SHA-256 matches the vendor's checksum; headless startup; glTF export (2208 tris, 53,608 bytes, material intact) |
| Cycles CPU render | PASS | 640x360, 32 samples, denoise, clipping 0.0 |
| Workbench via Xvfb | PASS | software GL, mean luma 0.474 |
| EEVEE Next via Xvfb | PASS | software GL, mean luma 0.339 |
| Infinigen | PASS | installs, imports and exposes its asset CLI; job took 11m 41s |
| glTF-Transform | PASS | installs, `--version` runs |
| Poly Haven API | PASS | asset list, file list, 1k download |
| gltfpack | PASS | runs; `-si` writes a file |
| **MPFB2** | **FAIL** | `ModuleNotFoundError: No module named 'mpfb'` |
| **MTree** | **FAIL** | was reported PASS; that was a false pass (below) |

## Three failures, each with its cause

**MPFB2 — the add-on was installed under the wrong name.** The installer copied the repository
as `mpfb2`, but the package holding `bl_info` is `src/mpfb`, and Blender imports an add-on by
its package name. `import mpfb` therefore failed while the files sat there. Two fixes: install
under the discovered package name, and install into the Blender installation's own
`4.2/scripts/addons` rather than the user config directory, which `--factory-startup` may not
pick up.

**MTree — a false pass I created.** The probe printed `mtree_ops False` and exited 0, and the
harness judged it on the exit code alone, so the report said PASS. It is now judged on whether
`bpy.ops.m_tree` exists. The fork at `faf77c1` also has no `bl_info`, which is the shape of a
Blender 4.2+ extension rather than a legacy add-on, so this needs one more attempt with the
correct install route before the fallback applies.

**gltfpack output loads as nothing.** Import succeeds, then `load()` finds no mesh nodes —
which is what `--headless`'s dummy renderer does for meshopt-compressed geometry. The brief
warns about exactly this (`-cc`). A control run with `-noq` now separates "Godot cannot load
gltfpack output" from "Godot cannot load quantized attributes". If `-noq` loads, gltfpack stays
with quantization off; if it does not, gltfpack is dropped and LODs come from Blender's
Decimate modifier, as the brief allows.

## Harness bugs found and fixed

All mine, and all of the kind that produces a confident wrong answer:

1. **Multi-path artifact upload re-nests on download** — the Godot job received the GLBs one
   directory deeper than it looked.
2. **`gltfpack -h` aborts its step** — GitHub's default shell is `bash -e`, so a non-zero exit
   killed the step before the simplification probe ran.
3. **Probes shared one result name** — all three renders reported `step="render"`, so Cycles
   and Workbench were overwritten by EEVEE; `run_capture` then added a bare exit-code row over
   the Python probe's detailed one, discarding the numbers.
4. **The add-on installer aborted its step** on a layout it did not recognise.
5. **A probe that printed a negative result still exited 0**, and the harness trusted the exit
   code. GDScript and Python probes now emit their own JSON RESULT and the wrapper leaves it
   alone.

## Still open

- Does MPFB2 build and export a rigged human once installed under the right name and location?
- Is MTree a 4.2 extension that can be installed, or does it need another Blender version?
- Does `-noq` make gltfpack output loadable in Godot?
- Quaternius: the `third-party-quaternius` release does not exist yet, so no clip count can be
  reported. That is an open task on the owner.

## Decisions that stand

- **Previews** are Cycles CPU. Workbench and EEVEE also work under llvmpipe — a bonus, not a
  dependency.
- **Infinigen** is usable on free runners in about twelve minutes per job. Small shards remain
  the plan.
- **Godot import gate** stays in CI and now verifies real geometry, not just file parsing.
