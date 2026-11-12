# Tool evaluation (Phase 0) — status report

> **This file is a written snapshot, not the live result.** CI regenerates a report from each
> run's logs and uploads it as the `phase0-report` artifact; that generated copy is the current
> truth. This file carries the reasoning the generated tables cannot, and is updated by hand
> when the reasoning changes. If the two disagree, the artifact wins.

**Runs recorded:** `fe39869` through `1aed003`. Every entry comes from those runs' logs.
Anything not measured says so.

## Verdict

Phase 0 is **nearly closed**. The last run reports **37 passed, 1 expected failure, 2 defects**,
and both defects have since been addressed:

| Tool | State | Evidence |
|---|---|---|
| Blender 4.2.23 and 4.5.16 | **USE** | checksums verified, headless startup, glTF export with material intact (2208 tris) |
| Cycles CPU | **USE — official preview renderer** | 640x360, 32 samples, denoise, clipping 0.0 |
| Workbench / EEVEE via Xvfb | available, not depended on | both render under llvmpipe |
| Godot 4.7.2 | **USE — import gate and shader compile gate** | imports and loads Blender's GLB: `tris=2208`; compiles both shader includes |
| gltfpack v1.3 | **USE with `-noq`** | quantized output loads nothing; `-noq` loads `tris=1104` (exactly 50 %) |
| Infinigen | **USE** | installs, imports, asset CLI resolves; commit `53033dd` |
| glTF-Transform | **USE** | installs, runs |
| Poly Haven API | **USE** | asset list, file list, 1k download |
| **Shaders** | **USE — verified** | both includes compile in Godot: wind exposes 6 uniforms, wetness 1 |
| **MPFB2** | **USE for meshes** | builds and exports a human that Godot loads (`meshes=1, tris=36972`); **no armature** yet, and over the 12k–18k budget |
| **Modular Tree** | **USE — verified end to end** | generates a tree and Godot loads it: `meshes=2, surfaces=2, materials=2, tris=35504`. Installed from the prebuilt release because the source ships only C++ |
| Quaternius packs | **MEASURED** | **43 clips, 16 of 41 families covered.** 25 families missing, including every melee weapon, skinning, butchering and the bow |

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
Godot load of the MTree tree    PASS  meshes=2, surfaces=2, materials=2, tris=35504
```

A tree is generated, exported as a GLB, uploaded, downloaded by the Godot job and loaded there.
That is the end-to-end proof the earlier "9 operators registered" never was.

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

1. **`armatures=0, bones=0`.** A mesh was built; no armature was bound. The brief needs a rigged
   character, so MPFB2 is not yet a usable human pipeline — it is a mesh pipeline.
2. **36,972 triangles.** The brief budgets 12k–18k for a player/NPC with gear. The base human
   alone is roughly double the top of that range before any clothing or armor is added, so
   decimation is mandatory, not optional.

The `mpfb_data` probe also still fails, and its error repeats the same extension-path exception
rather than proving the data is missing. Data presence and registration failure are now separate
questions in the report, as they should be.

**Four earlier diagnoses were wrong**: a silent `try/except` around `addon_utils.enable`, a
missing asset pack, `fake_bl_info`, and installing it as a legacy add-on. The traceback took one
run to settle what four speculative fixes could not.

## Modular Tree: registers, but does not generate

`quick_generate` now reaches the operator and fails inside it, with a *different* error than
before — which means the `sys.path` fix worked and exposed the next layer:

```
RuntimeError: Error: Failed to generate tree: cannot import name 'm_tree' from 'm_tree' (unknown location)
```

The extension's package directory is now on `sys.path` (the probe reports
`mtree_syspath added=.../extensions/user_default/modular_tree`), and Python now *finds* something
named `m_tree` — but it is a namespace package with no `__init__.py`, not the module the
generator wants. The extension's own layout puts the importable module somewhere else inside its
package.

**Operator registration is not procedural generation.** MTree is installed and its operators
exist; it has produced no tree, so no GLB, so no Godot import. The report now gates on
`mtree_generate`, `mtree_export` and `godot_scene_tree` precisely so "9 operators registered"
cannot be read as "trees work".

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

1. **No armature.** `armatures=0, bones=0`. A mesh is not a character; rigging is Phase 5 work
   and the probe now attempts MPFB2's own rig operators and reports what they produce.
2. **36,972 triangles** against a 12k–18k budget for a player character. Decimation is
   mandatory, not optional.

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

- **Quaternius coverage**: measured at **43 clips, 16 of 41 families**. The 25 unmatched families
  — every melee weapon, skinning, butchering, the bow, prone, swim, vault, mount and the rest —
  are assigned to the custom `bpy` pipeline. The matcher is a name-keyword heuristic and is
  optimistic: it counts `Pistol_Aim` as a bow aim, so the real usable coverage is lower than 16.
  Retargeting is **not** verified: no clip has been retargeted onto the target skeleton yet.
- **MPFB2 rigging**: a mesh exports, an armature does not. Binding it to
  `char_skeleton_definition.json` is untested.
- **MTree generation**: `cannot import name 'm_tree' from 'm_tree'` — the module is found but is
  an empty namespace package. The extension's real import path inside its own layout is the next
  thing to determine.
- **Godot Mobile renderer**: the probe project uses `gl_compatibility`. Nothing here proves the
  Mobile (Vulkan) path, and per the owner's decision that is a real-device check, not a CI one.
