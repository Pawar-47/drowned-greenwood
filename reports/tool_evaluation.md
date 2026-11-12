# Tool evaluation (Phase 0) — closing report

**Runs recorded:** `fe39869`, `60a1104`, `bd6f622`, `896769e`, `00f8443`. Every entry comes
from those runs' logs. Anything not measured says so.

## Verdict

Phase 0 is **closed with two tools rejected**. The brief allows three improvement attempts per
class before a fallback; MPFB2 and Modular Tree have each had three, and both are still inert.
Both fall back exactly as the brief prescribes.

| Tool | Verdict | Evidence |
|---|---|---|
| Blender 4.2.23 | **USE** | SHA-256 verified, headless, glTF export with material intact (2208 tris) |
| Cycles CPU | **USE — official preview renderer** | 640x360, 32 samples, denoise, clipping 0.0 |
| Workbench / EEVEE via Xvfb | available, not depended on | both render under llvmpipe |
| Godot 4.7.2 | **USE — import gate** | imports and loads Blender's GLB: `meshes=1, tris=2208` |
| gltfpack v1.3 | **USE with `-noq`** | quantized output loads nothing; `-noq` loads `tris=1104` (exactly 50%) |
| Infinigen | **USE** | installs, imports, asset CLI resolves; commit `53033dd5` |
| glTF-Transform | **USE** | installs, runs |
| Poly Haven API | **USE** | asset list, file list, 1k download |
| **MPFB2** | **under repair** | Root cause found. Its data ships with the source (`src/mpfb/data/3dobjs/base.obj` alone is 1.7 MB), so "needs asset packs" was wrong. The real cause is that the module defines **`fake_bl_info`, not `bl_info`**, which Blender needs to recognise a legacy add-on, and `addon_utils.enable()` returns `None` on failure instead of raising — so three runs reported "enable PASS" while nothing registered. |
| **Modular Tree** | **USE — correction** | 3 attempts. Final run: extension installs, **9 operators** register in `bpy.ops.mtree` (`add_leaves`, `generate_leaf`, `quick_generate`, preset appliers). An earlier rejection was a **false negative in my probe**, which looked for `bpy.ops.m_tree` and concluded the extension was inert. See below. |
| Quaternius packs | **PARTIAL** | the archive contains **4 files, not 4 clips**: `ual1_standard.{fbx,glb}` and `ual1_standard_rm.{fbx,glb}`. Each is a whole animation library in one container, so the clip count cannot be read from file names. See below. |

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

So `families_covered=0` is a limitation of my inventory, not a fact about the pack: counting
clips by file name cannot work when one file holds 120 of them. The honest next step is to
**open the GLB and enumerate its animations**, which needs Blender or glTF-Transform in CI. That
is a Phase 5 task, and until it runs, the animation coverage is **unknown**, not zero.

## MPFB2: the cause, and the fix

Three runs said "MPFB2 needs asset packs it does not install". That was wrong, and the
repository says so plainly: `src/mpfb/data/3dobjs/base.obj` alone is 1.7 MB, alongside
`data/rigs`, `data/targets`, `data/poses` and `data/textures`. The data ships with the source.

The actual cause is two facts about Blender that combined into a silent failure:

1. **MPFB2 defines `fake_bl_info`, not `bl_info`.** Blender's add-on loader looks for `bl_info`
   to recognise a legacy add-on. The official MPFB package has the real `bl_info` injected by
   its build process, which lives outside this repository — the release `v2.0.18` carries no
   downloadable assets, and there is no `blender_manifest.toml` either. So a raw clone
   installed into `scripts/addons` is never recognised, however many files are present.
2. **`addon_utils.enable()` does not raise.** It returns `None` whether the add-on registered or
   not, and prints the traceback to stderr. A `try/except` around it can never fire, so the
   probe reported `mpfb_enable PASS` for three runs.

**The fix: do not use `addon_utils` at all.** The module imports perfectly well — the probe's own
output shows `module_file=…/addons/mpfb/__init__.py`. So the probe now imports `mpfb` and calls
`mpfb.register()` directly. That is what an add-on loader does internally, it needs no
`bl_info`, and any exception surfaces with a real traceback instead of vanishing.

The probe now reports, in order: the module import, the `register()` exception if any, the
operators that appeared, whether MPFB's own `LocationService` can find its data directory, and
whether a human can be built and exported. Whichever of those fails, the report will name it.

**This is a repair of the measurement, not a fourth attempt.** The brief's three attempts were
spent on three wrong diagnoses. If `register()` now succeeds, MPFB2 was never broken and the
rejection is retracted the same way Modular Tree's was. If it raises, the traceback finally says
what is actually wrong — which is what every previous run failed to obtain.

## What the rejections mean for the asset list

**Humans (4.G).** The brief already expects the lowest fidelity here and says so. Without MPFB2,
human bodies come from a custom `bpy` generator: a parametric base mesh with the shared skeleton
from `char_skeleton_definition.json`, no MPFB2 skin/hair/clothing library. Consequence, stated
plainly: heads and faces will be stylised rather than realistic, and clothing variety depends
entirely on our own generators. Recorded in `reports/below_target.md` when the assets are built.

**Trees (4.E).** Modular Tree is available after the correction above, so trees use it for the
branch structure the brief wanted, with Infinigen's plant factories and custom `bpy` generators
for the species MTree cannot express. What remains unproven is that `quick_generate` produces an
exportable mesh; the next run answers that, and if it fails the fallback is the original plan:
Infinigen plus custom generators, with the loss recorded.

**MPFB2 does not block humans (4.G).** Its data is in the source, its module imports, and the
probe now registers it directly. Skeleton definitions, the manifest, workflows and validators
are independent of it regardless, so Phase 1 proceeds either way.

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
