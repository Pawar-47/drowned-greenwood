# Tool evaluation (Phase 0)

**Runs recorded:** `fe39869`, `60a1104`, `bd6f622` (run 43211981875). Every entry comes from
those runs' logs. Anything not measured says so.

> CI regenerates this file from its own logs on every run (`tools/phase0/make_report.py`).
> This version is the written-up result, kept because the raw generator output does not carry
> the reasoning.

## The two decisions that mattered are now settled

**1. The import gate works.** Blender → `.glb` → Godot is verified in CI, with real geometry:
`meshes=1, surfaces=1, materials=1, tris=2208`. Every asset from here on runs through it.

**2. gltfpack works, but only with quantization off.** This is a measured result, not a guess:

| Variant | Import | Load | Triangles |
|---|---|---|---|
| gltfpack `-si 0.5` (default, quantized) | PASS | **FAIL** — `load_returned_null` | — |
| gltfpack `-si 0.5 -noq` | PASS | **PASS** | 1104 |

1104 is exactly 50 % of 2208, so `-si` did its job and the mesh is intact. Godot's headless
import accepts the quantized file and then produces nothing from it. **Decision: LODs use
`gltfpack -noq`.** `-cc` and `-tc` remain off, as the brief requires.

## Measured, passing

| Tool | Detail |
|---|---|
| Blender 4.2.23 | SHA-256 verified; headless; glTF export (2208 tris, 53,608 bytes, material intact) |
| Cycles CPU render | 640x360, 32 samples, denoise, clipping 0.0 — the official preview renderer |
| Workbench via Xvfb | software GL, mean luma 0.474 |
| EEVEE Next via Xvfb | software GL, mean luma 0.339 |
| Infinigen | installs, imports, exposes its asset CLI; commit `53033dd5`; 12m 9s job |
| glTF-Transform | installs, `--version` runs |
| Poly Haven API | asset list, file list, 1k download |
| Godot 4.7.2-stable | headless import and load of Blender's GLB |

## The two remaining failures

**MPFB2 — the package name.** Confirmed from the repository's own tree: the add-on package is
`src/mpfb`, not the repository root. Blender imports an add-on by *package* name, so installing
the clone as `mpfb2` makes `import mpfb` fail while every file sits there. The installer now
searches to depth 5 and names the installed directory after the package holding `bl_info`. This
is the second attempt at MPFB2; if it fails again the fallback applies.

**MTree — the wrong Blender, and a false pass I wrote.** Its
`blender_manifest.toml` declares:

```
id = "modular_tree"
version = "5.6.0"
blender_version_min = "4.5.0"
```

It is a Blender 4.2+ **extension** requiring **4.5.0**, so it can never register in 4.2. The
previous run reported `has_m_tree_ops=True` — a false positive, because `bpy.ops` resolves
names lazily and `hasattr(bpy.ops, "anything")` is always true. The probe now judges on
`dir(bpy.ops.m_tree)` having entries, installs the extension properly
(`blender --command extension install-file`), runs it under Blender **4.5.16** (checksum
verified, from the 4.5 release index), and then actually generates a tree and exports it. The
brief allows one pinned Blender per job, so this is within the rules.

## Harness bugs found and fixed

All mine, and all of the kind that produces a confident wrong answer:

1. Multi-path artifact upload re-nested on download, so the Godot job looked in the wrong place.
2. `gltfpack -h` exits non-zero and GitHub's default shell is `bash -e`, so the step aborted.
3. All three renders shared the result name `render`; Cycles and Workbench were overwritten.
4. `run_capture` overwrote a probe's detailed JSON row with a bare exit-code row.
5. A probe that printed a negative result still exited 0, and the harness trusted the exit code.
6. `hasattr(bpy.ops, ...)` as a registration test — always true.

## Still open

- Does MPFB2 build and export a rigged human once installed under the right package name?
- Does MTree register and generate a tree under Blender 4.5?
- Quaternius: the `third-party-quaternius` release does not exist, so no clip count can be
  reported. That is an open task on the owner.

## Decisions that stand

- **Previews**: Cycles CPU. Workbench and EEVEE also work under llvmpipe — a bonus.
- **Infinigen**: usable on free runners, about twelve minutes per job. Small shards.
- **LODs**: `gltfpack -noq`, or Blender's Decimate modifier if MTree/MPFB2 work needs it.
- **Godot import gate**: stays in CI, verifies geometry rather than file parsing.
