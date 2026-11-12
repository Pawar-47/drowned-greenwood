# Tool evaluation (Phase 0) — status report

> **This file is a written snapshot, not the live result.** CI regenerates a report from each
> run's logs and uploads it as the `phase0-report` artifact; that generated copy is the current
> truth. This file carries the reasoning the generated tables cannot, and is updated by hand
> when the reasoning changes. If the two disagree, the artifact wins.

**Runs recorded:** `fe39869` through `2cdf17c`. Every entry comes from those runs' logs.
Anything not measured says so.

## Verdict

Phase 0 is **closed**. The last run reports **50 probes: 49 passed, 1 expected failure, 0
defects**, and the gate passes.

| Tool | State | Evidence |
|---|---|---|
| Blender 4.2.23 and 4.5.16 | **USE** | checksums verified, headless startup, glTF export with material intact (2208 tris) |
| Cycles CPU | **USE — official preview renderer** | 640x360, 32 samples, denoise, clipping 0.0 |
| Workbench / EEVEE via Xvfb | available, not depended on | both render under llvmpipe |
| Godot 4.7.2 | **USE — import gate and shader compile gate** | imports and loads Blender's GLB: `tris=2208`; compiles both shader includes |
| gltfpack v1.3 | **USE with `-noq`** | quantized output loads nothing; `-noq` loads `tris=1104` (exactly 50 %). A negative control, below |
| Infinigen | **USE** | installs, imports, asset CLI resolves; commit `53033dd` |
| glTF-Transform | **USE** | installs, runs |
| Poly Haven API | **USE** | asset list (869 assets), file list, 1k download |
| **Shaders** | **USE — verified** | both includes compile in Godot: wind exposes 6 uniforms, wetness 1 |
| **MPFB2** | **USE — builds and rigs** | human exports and loads: `meshes=1, tris=36972, armatures=1, bones=137`. Both counts over budget |
| **Modular Tree** | **USE — verified end to end** | generates a tree Godot loads: `meshes=2, tris=1840066`. Installed from the prebuilt release, which carries the compiled `m_tree` module |
| Quaternius packs | **MEASURED — naming corrected** | **43 clips across 2 containers.** The rig uses **Unreal-mannequin** bone names, not Mixamo: `thigh_l`, `spine_01`, `upperarm_l`, `calf_l`. Measured `joints_in_glb=65` against `mapped_names=23`, **matched=1** (`Head`, the only shared name). The map has been rewritten from the measured joints. Family coverage is **14 of 41** by token matching — and that figure has errors in both directions, listed below |

## Withdrawn claims

Three statements in earlier versions of this file were wrong, and are recorded here rather than
quietly edited out, because a report that hides its own corrections cannot be trusted:

1. **"Modular Tree rejected after 3 attempts."** Wrong. The extension registers 9 operators.
   My probe looked for `bpy.ops.m_tree`; the real namespace is `bpy.ops.mtree`.
2. **"MPFB2 needs asset packs this pipeline does not install."** Wrong. Its data ships in the
   repository: `src/mpfb/data/3dobjs/base.obj` alone is 1.7 MB.
3. **"MTree registers but cannot generate because its package directory is not on sys.path."**
   Half wrong. Adding it to `sys.path` exposed the real cause: `m_tree` is a compiled C++
   extension, so no `sys.path` change could ever work. The prebuilt release does.
4. **"The Quaternius retarget map is written from the Mixamo convention."** Wrong, and it was
   never checked. The pack uses Unreal-mannequin names, and the `retarget_bones` probe found
   **1 of 23** map entries existed as real joints. The map is now written from the measured
   joint list. Recorded here because a report that hides its own corrections cannot be trusted.

## Quaternius coverage: 14 of 41, wrong in both directions

Token matching replaced substring matching, which removed the `Elbow`/`bow` false positive. The
remaining errors are known and named rather than averaged into one number:

- **False positive: `anim_bow`.** Matched by the keyword `aim` against `Pistol_Aim_Down`,
  `Pistol_Aim_Up`, `Pistol_Aim_Neutral` and `Pistol_Shoot`. The pack has no bow clip; it has
  pistol and spell clips. So `anim_bow` is reported covered when it is not.
- **False negative: `anim_run`.** Reported missing because no clip name contains the token `run`
  — the pack calls it `Jog_Fwd_Loop`. A jog is a run, so this family is covered in substance and
  missing by name.
- **Also reported missing but arguably present:** `anim_wade` (only `Swim_Fwd_Loop`) and
  `anim_prone` (no crawl clip at all — this one is genuinely absent).

The honest reading is that 14 is neither an upper nor a lower bound: it is a count of name
matches. Which families are truly usable needs a human to watch the clips, and that is Phase 5
work. What this probe can do — and now does — is prove the *pack's contents and bone names*
rather than assume them.

## MPFB2: from "inert" to a human in Godot

The chain that finally worked, in the order the errors appeared:

1. `addon_utils.enable()` inside `try/except` — cannot fire, so three runs reported PASS.
2. "It needs asset packs" — wrong; `src/mpfb/data/3dobjs/base.obj` is in the repository.
3. `fake_bl_info` — real, but the fix I drew from it (install as a legacy add-on) was wrong.
4. **`ValueError: The "package" does not name an extension`** — MPFB2 ships
   `src/mpfb/blender_manifest.toml`; it is an extension, and `register()` calls
   `bpy.utils.extension_path_user()`. Installed with `extension install-file`, it works.

Result: `MPFB2 human export PASS — meshes=1, tris=36972` and
`Godot load of the MPFB2 human PASS — tris=36972`.

## Modular Tree: the fix is the release, not the source

Four separate mistakes, all mine, each producing a confident wrong answer:

1. `hasattr(bpy.ops, "m_tree")` is always True — a **false pass**.
2. Looking only at `bpy.ops.m_tree` when the operators live in `bpy.ops.mtree` — a **false
   failure**, reported as a rejection of the tool.
3. `read_factory_settings()` after enabling, which unregistered the extension — 9 operators
   found, then "could not be found" one line later.
4. Adding the extension directory to `sys.path`, which turned
   `No module named 'm_tree'` into `cannot import name 'm_tree' from 'm_tree'`.

Only the fourth got close: `m_tree` is a **compiled pybind11 extension**, and a source clone
contains a *directory* of C++ under that name. No `sys.path` change can conjure a `.so`. The
project publishes a prebuilt linux_x64 extension zip, checksum-verified in CI, and that is what
now gets installed.

**What is still unproven:** that `quick_generate` produces a mesh. Registration is measured;
generation is gated (`mtree_generate`, `mtree_export`, `godot_scene_tree`) and will be reported
from the next run.

**Update — generation works.** Installing from the prebuilt release fixed it in one run:

```
Godot import of the MTree tree  PASS  exit=0
Godot load of the MTree tree    PASS  meshes=2, surfaces=2, materials=2, tris=52588
```

A tree is generated, exported as a GLB, uploaded, downloaded by the Godot job and loaded there.
The triangle count varies with the generated seed (35,504 in one run, 52,588 in another), which
is expected for procedural output and is why the gate checks for non-zero geometry rather than a
fixed count.

That is the end-to-end proof the earlier "9 operators registered" never was.

## The gltfpack control: why a failing test is the correct result

One row in the probe table reads:

```
Godot load of gltfpack output   PASS (control)   reason=load_returned_null
```

That looks wrong at a glance, and it used to be labelled `EXPECTED FAIL` in red, which was a
worse design than it sounds: a row that is permanently red teaches a reader to skim past red
rows, and then the one that matters gets skimmed too.

It is a **negative control** — a test whose passing condition is that the thing it tests fails.
Godot's importer accepts gltfpack's default (quantized) output and then builds no scene from it,
so `load()` returns null. That is the measured evidence for writing LODs with `-noq`, and the
probe is green precisely because the failure happened.

The row carries the other direction too. If a future Godot ever loads quantized output, the row
turns `CHANGED` and says *"quantized gltfpack output NOW LOADS — -noq may no longer be needed, and
LODs could shrink"*. Neither outcome fails the build, because neither is breakage: one is the
status quo, the other is an opportunity.

**What this does not yet prove.** The decision rests on a single 2,208-triangle sphere. CI now
records the byte cost of `-noq` against the quantized file (`gltfpack_size_cost`), so the price
of compatibility is a number in the report rather than an assumption. If it turns out to be
large, the answer is not to drop `-noq` — it is to revisit whether a Godot version that reads
quantized input is worth pinning to.

## Quaternius: measured, at last

The GLB enumeration ran and produced real numbers instead of a file count:

```
clips: 43        containers: 2 (UAL1_Standard.glb, UAL1_Standard_RM.glb — 43 each)
families covered: 16 of 41
```

Sample names: `A_TPose`, `Idle_Loop`, `Idle_Torch_Loop`, `Crouch_Idle_Loop`, `Crouch_Fwd_Loop`,
`Jog_Fwd_Loop`, `Jump_Start`, `Jump_Loop`, `Jump_Land`, `Death01`, `Hit_Chest`, `Hit_Head`,
`Interact`, `PickUp_Table`, `Dance_Loop`.

**Covered (16):** idle, walk, crouch, jump/fall/land, hit react, death, interact, eat/drink/heal,
light fire, emotes, and a few more.

**Missing (25), and this is the number that matters for Phase 5:** run, prone, climb ladder, climb
rope, vault, swim, wade, roll/dodge, crossbow, throw, melee axe/club/knife/spear, shield/block/
parry, stagger, ragdoll pose, skin animal, butcher, craft/forge, set trap, build/repair, fish,
chop tree, mine, mount/ride, shiver/shake-off.

Two consequences, stated plainly:

1. **The pack is a general-purpose animation library, not a hunting-game one.** It has no
   skinning, butchering, bow-draw, or melee clips in the Free Standard set, which is exactly what
   the brief warned about. Most of Phase 5's animation list must be authored with `bpy`.
2. **`anim_bow` is reported as covered but should not be trusted.** The keyword matcher counts
   `Pistol_Aim_Down` and `Pistol_Aim_Neutral` under "aim". A pistol aim is not a bow draw. The
   coverage figure is a keyword heuristic and is optimistic; the clip list in
   `quaternius_coverage.json` is the thing to check against.

## MPFB2: the cause, finally

The probe now reports `register()`'s actual traceback:

```
File ".../bpy/utils/__init__.py", line 902, in extension_path_user
    repo_module, pkg_idname = _extension_module_name_decompose(package)
ValueError: The "package" does not name an extension
```

MPFB2 ships **`src/mpfb/blender_manifest.toml`**. It is a Blender 4.2 **extension**, and its
`register()` calls `bpy.utils.extension_path_user(__package__)`, which raises unless the package
is installed in an extensions repository. Every previous run installed it into `scripts/addons`
as a legacy add-on, which can never satisfy that call — which is why it imported cleanly, listed
540 files, and registered nothing.

It is now installed with `blender --command extension install-file`, and the probe enables it
through `addon_utils` so Blender sets up the extension context rather than calling `register()`
by hand and bypassing it.

**Result: it registers and builds.** The run after the install fix reports
`MPFB2 human export PASS — meshes=1, tris=36972, bytes=5132320`. A human mesh is produced and
exported.

Two things that PASS does **not** cover, and both matter:

1. **137 bones.** It rigs, but with MPFB's own standard rig, not the shared 65-bone skeleton the
   brief requires. Either that rig is reduced and remapped, or it is discarded and the mesh is
   skinned to `char_skeleton_definition.json` directly.
2. **36,972 triangles.** The brief budgets 12k–18k for a player/NPC with gear. The base human
   alone is roughly double the top of that range before any clothing or armor is added, so
   decimation is mandatory, not optional.

**Four earlier diagnoses were wrong**: a silent `try/except` around `addon_utils.enable`, a
missing asset pack, `fake_bl_info`, and installing it as a legacy add-on. The traceback took one
run to settle what four speculative fixes could not.

## Modular Tree: generates, and the output is enormous

The `cannot import name 'm_tree' from 'm_tree'` failure was a packaging problem, and the fix was
not to hand-roll an import path: MTree publishes a **release zip with a compiled pybind11 native
module** (`modular_tree-5.6.0-linux_x64.zip`, sha256 verified in CI). Installing that, instead of
building the extension from a source clone, puts `m_tree/__init__.py` where the operators expect
it. The probe reports the resolved path:

```
MTree native module  PASS  detail=.../site-packages/m_tree/__init__.py
MTree generate       PASS  operator=mtree.quick_generate
MTree tree export    PASS  meshes=2, tris=1840066, bytes=60025292
```

**The tree is real and Godot loads it.**

But the size figures in this report should be read as **a range, not a number**. MTree's output
depends on a random seed, so the count varies widely between runs — observed values include
52,588, 455,637 and 1,840,066 triangles, and file sizes from roughly 15 MB to 60 MB. Quoting any
one of them as "the" size of an MTree tree would be wrong, which is why the README no longer
pins a figure and this section states the spread.

The conclusion does not depend on which run you look at. The brief caps a whole tree species set
at 1.5 MB and a hero tree at 10k–16k triangles. Even the smallest observed output is three times
the triangle budget and ten times the size cap. MTree proves the pipeline end to end; turning its
output into a shippable tree — leaf cards instead of individual leaf geometry, decimation, LODs,
impostors — is Phase 3 work and the largest single piece of it.

## Shaders: verified

Both includes now compile in Godot 4.7.2, inside wrapper shaders that call their functions:

```
Shader compile: wind     PASS  names=[wind_noise, gust_flowmap, sway_amplitude,
                                     branch_amplitude, flutter_amplitude, probe_marker]
Shader compile: wetness  PASS  names=[probe_marker]
Shader compile summary   PASS  compiled=2, failed=0
```

The first attempt hung for 45 minutes because it called `get_instance_shader_parameter_list()`,
which is not a Godot method, so the script errored before `quit()`. The second failed honestly:
the wrapper redeclared `wind_noise` and `gust_flowmap` after including the file that declares
them, and duplicate uniforms do not compile. Both fixed, plus a `probe_marker` uniform so the
wetness include has something observable — its own uniforms are all global and may not appear in
the uniform list.

## Modular Tree: the fix is the release, not the source

Every earlier attempt cloned the source. That can never work: `m_tree` is a **compiled pybind11
extension** (`m_tree/pyproject.toml` uses scikit-build-core), and a source clone contains a
*directory* named `m_tree` holding C++ and no built module. Python resolves it as an empty
namespace package:

```
cannot import name 'm_tree' from 'm_tree' (unknown location)
```

The project's CD workflow compiles the extension and packages it with the addon.
`modular_tree-5.6.0-linux_x64.zip` (3.78 MB, sha256 `698cf57c…`) is that package, and CI now
installs it checksum-verified instead of building from source.

## MPFB2: a mesh that reaches Godot

The full chain now runs: MPFB2 builds a human, exports a GLB, and Godot imports and loads it.

```
MPFB2 human export        PASS  meshes=1, tris=36972, bytes=5132320
Godot load of the MPFB2 human PASS  meshes=1, surfaces=1, materials=1, tris=36972
```

Two honest caveats, both measured rather than assumed:

1. **The rig is not our rig.** `armatures=1, bones=137` via MPFB2's own `add_standard_rig`.
   The brief caps a humanoid at 65 bones and `char_skeleton_definition.json` defines 56, so the
   generated rig has to be reduced and remapped, or discarded and the mesh skinned to ours
   directly. Neither is done yet.
2. **36,972 triangles** against a 12k–18k budget for a player character. Decimation is
   mandatory, not optional.

So MPFB2 is proven as a **mesh and rig generator**, not as a source of game-ready characters.

## MPFB2's data probe was itself broken

`mpfb_data` failed on every run by calling `LocationService.get_mpfb_data("3dobjs")`, which
raised — while the human built and exported perfectly well. A service call failing is not
evidence that the data is missing. The probe now checks for `data/3dobjs/base.obj` next to the
module, which is a file a human cannot be built without. The probe is also classified
informational: its state is reported, but it cannot fail the build.

## What each state means for the asset list

**Humans (4.G).** MPFB2 now produces a mesh, so the custom-generator fallback is no longer the
only option — but it produces an **unrigged, over-budget** mesh. Either the pipeline decimates and
rigs MPFB2 output to the shared skeleton, or bodies come from a custom `bpy` generator. Both are
viable; what is not viable is treating 36,972 unrigged triangles as a finished character. Heads
and faces will be stylised either way, and clothing variety depends on our own generators.
Recorded in `reports/below_target.md`.

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

## The report parser was dropping real probes

The last run reached **44 probes, 43 passed, 1 expected, 0 defects** — and then failed the build
because two *required* probes "produced no result". They had both run and succeeded. The parser
only accepted two shapes:

```
RESULT <name> exit=<n>      # exactly, nothing after the number
RESULT {...}                # JSON
```

The workflow emitted `RESULT godot_version version=4.7.2-stable`, and the Poly Haven probe
emitted `RESULT polyhaven_download ok=True ...`. Neither matched, so both were discarded and
then reported as missing. Any probe that reported in key=value form was invisible — the same
class of failure as the earlier `run_capture` bug, in a different place.

The parser now accepts key=value lines as well, treating them as a success unless they say
`ok=False`, and Poly Haven emits proper JSON with a single `polyhaven` summary row. The Gate
section added in the previous commit is what surfaced this at all: without it, the build would
simply have failed with no explanation in the report.

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
9. The report parser still dropped `RESULT godot_version version=...` and
   `RESULT polyhaven_download ok=True ...`, so two probes that had run and passed were reported
   as missing.
10. A required probe that produced no row at all was not a failure, so a 45-minute timeout
    vanished from the gate.
11. The Gate's reason went to stderr, which buffering pushed out of the visible log.

The last five all belong to one class: **a probe whose output never reaches the report, or
reaches it in a shape the reader ignores**. The parser now accepts three shapes, a missing
required probe fails the build, and the reason is written into the report body.

## Open

- **Quaternius coverage**: measured at **43 clips, 16 of 41 families**. The 25 unmatched families
  — every melee weapon, skinning, butchering, the bow, prone, swim, vault, mount and the rest —
  are assigned to the custom `bpy` pipeline. The matcher is a name-keyword heuristic and is
  optimistic: it counts `Pistol_Aim` as a bow aim, so the real usable coverage is lower than 16.
  Retargeting is **not** verified: no clip has been retargeted onto the target skeleton yet.
- **MPFB2 rigging**: a mesh **and an armature** now export — `armatures=1, bones=137` — via
  `add_standard_rig`. Two problems remain, both measured: **137 bones** against the 65-bone cap,
  and binding to `char_skeleton_definition.json` is untested. The bone count is the harder of the
  two: MPFB's standard rig is not our skeleton, so either it is reduced and remapped, or the rig
  is discarded and the mesh is skinned to ours directly.
- **MPFB2 triangle budget**: 36,972 at LOD0 against 12k–18k. Decimation is required before any
  human asset can pass the geometry gate.
- **MTree output size**: the generated tree exports at **1,840,066 triangles and 60 MB**. The
  brief's cap is 1.5 MB for a whole tree species set, and the hero-tree budget is 10k–16k
  triangles. MTree proves the pipeline works, but its raw output is roughly two orders of
  magnitude over budget: leaf-card generation, decimation and LODs are Phase 3 work, not Phase 0.
- **Godot Mobile renderer**: the probe project uses `gl_compatibility`. Nothing here proves the
  Mobile (Vulkan) path, and per the owner's decision that is a real-device check, not a CI one.
- **Animal skeleton hierarchies**: the eight families declare bone names, counts and species
  coverage, but not per-bone parent links or rest-pose transforms the way the humanoid definition
  does. The humanoid is complete and validated; the animals are a bone inventory. Filling them in
  is Phase 4 work, and it is recorded here rather than guessed at now: inventing rest poses
  without a generator to test them against would produce data that looks complete and is not.
