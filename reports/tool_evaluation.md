# Tool evaluation (Phase 0) — status report

> **This file is a written snapshot, not the live result.** CI regenerates a report from each
> run's logs and uploads it as the `phase0-report` artifact; that generated copy is the current
> truth. This file carries the reasoning the generated tables cannot, and is updated by hand
> when the reasoning changes. If the two disagree, the artifact wins.

**Runs recorded:** `fe39869` through `ecca637`. Every entry comes from those runs' logs.
Anything not measured says so.

## Verdict

Phase 0 is **setup complete, verification incomplete**. It is not "closed with zero defects":
several claims earlier versions of this file made have since been withdrawn, and three checks
had never been run at all until an audit pointed at them.

| Tool | State | Evidence |
|---|---|---|
| Blender 4.2.23 and 4.5.16 | **USE** | checksums verified, headless startup, glTF export with material intact (2208 tris) |
| Cycles CPU | **USE — official preview renderer** | 640x360, 32 samples, denoise, clipping 0.0 |
| Workbench / EEVEE via Xvfb | available, not depended on | both render under llvmpipe |
| Godot 4.7.2 | **USE — import gate and shader compile gate** | imports and loads Blender's GLB: `meshes=1, tris=2208` |
| gltfpack v1.3 | **USE with `-noq`** | quantized output loads nothing; `-noq` loads `tris=1104` (exactly 50 %) |
| Infinigen | **USE** | installs, imports, asset CLI resolves; commit `53033dd` |
| glTF-Transform | **USE** | installs, runs |
| Poly Haven API | **USE** | asset list, file list, 1k download |
| **MPFB2** | **UNDER REPAIR** | imports and registers, but exposes 0 operators. See below |
| **Modular Tree** | **USE — correction** | 9 operators register in `bpy.ops.mtree`; an earlier rejection was my probe looking in `bpy.ops.m_tree`. Tree generation not yet proven |
| Quaternius packs | **UNVERIFIED** | 4 files that are whole animation libraries; clip count needs GLB enumeration |

## Withdrawn claims

Two statements in earlier versions of this file were wrong, and are recorded here rather than
quietly edited out, because a report that hides its own corrections cannot be trusted:

1. **"Modular Tree rejected after 3 attempts."** Wrong. The extension registers 9 operators.
   My probe looked for `bpy.ops.m_tree`; the real namespace is `bpy.ops.mtree`.
2. **"MPFB2 needs asset packs this pipeline does not install."** Wrong. Its data ships in the
   repository: `src/mpfb/data/3dobjs/base.obj` alone is 1.7 MB.

## The MPFB2 failure, precisely

What is established: the module imports from the installed path
(`…/addons/mpfb/__init__.py`), `register()` is called, and **zero operators appear**.

What is not established: why. Three candidate causes were chased and two were wrong. The
remaining structural fact is that MPFB2 defines `fake_bl_info`, not `bl_info` — Blender needs
`bl_info` to recognise a legacy add-on, and the official package has it injected by a build
outside the repository. The current probe bypasses the add-on loader entirely and calls
`register()` directly, which needs no `bl_info`, and reports the exception if one is raised.


## Modular Tree: I was wrong, and the correction matters

For several runs the report said Modular Tree registered zero operators. It does not. The
extension registers fine; my probe asked for `bpy.ops.m_tree` when the operators live in
`bpy.ops.mtree`. Two separate mistakes, both mine:

1. `hasattr(bpy.ops, "m_tree")` is always True, because `bpy.ops` resolves names lazily. That
   produced a **false pass** once.
2. Looking only at `m_tree` produced a **false failure** afterwards, because the real namespace
   is `mtree`.

The probe now discovers the namespace instead of assuming it, and picks the generator from what
it finds (`quick_generate` in this build). The rejection is retracted: Modular Tree is available
for 4.E trees, which restores the node-based branch control the brief wanted.

**What is still unproven:** that `quick_generate` actually produces a mesh and exports. The
namespace discovery is measured; tree generation is the next run's job.

## Quaternius: four files, and they are libraries

The archive `Universal.Animation.Library.Standard.zip` contains `ual1_standard.fbx`,
`ual1_standard.glb`, `ual1_standard_rm.fbx`, `ual1_standard_rm.glb`, plus a texture set and
readme. These are **single containers holding a whole animation library**, which is how the
Quaternius Universal Animation Library is distributed — not one file per clip.

So `families_covered=0` was a limitation of the inventory, not a fact about the pack: counting
clips by file name cannot work when one file holds a hundred of them. The inventory now reads
the GLB container directly — a GLB is a header plus length-prefixed chunks whose first chunk is
JSON, so the animation names are readable with the standard library alone, no Blender needed. It
reports the real clip count, deduplicated across the FBX and GLB copies of the same library, and
which of the brief's animation families those names cover.

## MPFB2: what is established and what is not

What is established: the module imports from the installed path
(`…/addons/mpfb/__init__.py`), `register()` is called, and **zero operators appear**.

What is not established: why. Three candidate causes were chased and two were wrong — a missing
`bl_info` and a `try/except` that could never fire. The probe now bypasses the add-on loader and
calls `register()` directly, so any exception surfaces with a real traceback, and it reports the
data directory, the operators that appeared, and whether a human builds and exports.

**This is a repair of the measurement, not a fourth attempt.** The brief's three attempts were
spent on three wrong diagnoses. If `register()` succeeds, MPFB2 was never broken. If it raises,
the traceback finally says what is wrong.

## What each state means for the asset list

**Humans (4.G).** MPFB2 is under repair, not verified. If `register()` raises, human bodies come
from a custom `bpy` generator: a parametric base mesh bound to the shared skeleton from
`char_skeleton_definition.json`, with no MPFB2 skin, hair or clothing library. Consequence,
stated plainly: heads and faces will be stylised rather than realistic, and clothing variety
depends entirely on our own generators. Recorded in `reports/below_target.md`.

**Trees (4.E).** Modular Tree is available after the correction above, so trees use it for the
branch structure the brief wanted, with Infinigen's plant factories and custom `bpy` generators
for the species MTree cannot express. What remains unproven is that `quick_generate` produces an
exportable mesh; the Godot job now imports the generated tree, so that is measured rather than
assumed.

## The import gate

The pipeline's spine is verified end to end, and it is the part every later phase depends on:

```
Blender 4.2.23 --glTF--> probe.glb --> Godot 4.7.2 headless import --> load --> 2208 tris
```

## Harness bugs found and fixed (all mine)

Every one of these produced a confident wrong answer, which is why they are listed:

1. Multi-path artifact upload re-nested on download; the Godot job looked in the wrong place.
2. `gltfpack -h` exits non-zero and GitHub's default shell is `bash -e`, aborting its step.
3. All three renders shared the result name `render`; Cycles and Workbench were overwritten.
4. `run_capture` overwrote a probe's detailed JSON row with a bare exit-code row.
5. A probe that printed a negative result still exited 0; the harness trusted the exit code.
6. `hasattr(bpy.ops, ...)` as a registration test — always true, so MTree passed falsely once.
7. The installer printed `key=value`, which the report parser drops — two runs were blind to it.
8. Both installer calls shared one step name, so MPFB2's install row was overwritten by MTree's.

The last four all belong to one class: **a probe whose output never reaches the report**. The
harness now treats a missing or malformed RESULT line as a failure worth naming, and every
probe name is unique.

## Open

- **Quaternius clip count and coverage**: the packs are now in the release and CI inventories
  them, reporting both the real clip count and which of the brief's 39 animation families they
  cover. The measured numbers are in the latest run's log and
  `artifacts/phase0/quaternius_coverage.json`; they are deliberately not copied here, because a
  number typed from memory is exactly the kind of claim this report exists to prevent.
- MPFB2 under Blender 4.5: not attempted, and not planned. The brief ties MPFB2 to 4.2; its
  manifest declares `blender_version_min` 4.2.0, so a 4.5 run would not explain the failure.
