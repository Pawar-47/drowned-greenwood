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
| **MPFB2** | **REJECT** | 3 attempts, still `ModuleNotFoundError: No module named 'mpfb'` |
| **Modular Tree** | **REJECT** | 3 attempts, registers 0 operators under Blender 4.5.16 |
| Quaternius packs | **PARTIAL** | owner published `Universal.Animation.Library.Standard.zip` (15.9 MB, sha256 `cc73fc4e…`); CI fetches it, but the archive yielded only **4 animation files** (2 `.fbx`, 2 `.glb`) — see below |

## Quaternius: the pack is much smaller than expected

The first successful inventory of `Universal.Animation.Library.Standard.zip` found **4 animation
files** in a 15.9 MB archive (`suffixes={'.fbx': 2, '.glb': 2, '.png': 3, '.txt': 2, '.zip': 1}`).
Two `.fbx` and two `.glb` is most likely two animations in two formats, not a library.

The brief's expectation for this pack was "120+ animations", with the free Standard download
covering only part of that. Four files is below even that. Two possibilities, and the next run
distinguishes them because it now logs `unzip -l` and the clip file names:

1. **The upload is a sample or a teaser**, not the Standard pack. The fix is on the owner: upload
   the full Standard ZIP from the pack page.
2. **The pack really is this small.** Then Phase 5 authors nearly every clip with `bpy`, which
   the brief already permits, and the animation coverage report will say so plainly.

Either way, **no clip count is being claimed**. The inventory reports `coverage unknown` rather
than "0 of 40 covered", because a pack that yields no clips has not proved anything about the
clips it might contain.

## What the rejections mean for the asset list

**Humans (4.G).** The brief already expects the lowest fidelity here and says so. Without MPFB2,
human bodies come from a custom `bpy` generator: a parametric base mesh with the shared skeleton
from `char_skeleton_definition.json`, no MPFB2 skin/hair/clothing library. Consequence, stated
plainly: heads and faces will be stylised rather than realistic, and clothing variety depends
entirely on our own generators. Recorded in `reports/below_target.md` when the assets are built.

**Trees (4.E).** Without MTree, trees come from Infinigen's plant/bush factories plus custom
`bpy` generators, as the owner approved. Infinigen is verified working, so the giant-tree
silhouettes and leaf cards are still reachable; what is lost is MTree's node-based branch
control, which means more generator code for the same variety.

**Neither rejection blocks Phase 1.** Skeleton definitions, the manifest, workflows and
validators are independent of both.

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
