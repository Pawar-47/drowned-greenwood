# Lessons from Phase 0: how to write a probe that does not lie

Every rule below comes from a specific bug in this repository's own probe code during Phase 0.
They are not general advice; each one cost a CI run or a wrong conclusion. Later phases add
probes too — asset validators are probes — so these apply to everything in `tools/validate/`
as much as to `tools/phase0/`.

## 1. A green job is not a passing probe

`continue-on-error: true` means a failed probe leaves the job green. So "all jobs passed" says
nothing about the probes. Always read the report's own outcome line.

**Consequence:** the report must state a defect count explicitly. It now prints
`Defects (something is actually broken): N`, and N was 0 for the first time only after four
rounds of fixing.

## 2. Never trust an exit code for a probe that knows better

Blender exits 0 when the add-on it was told to enable registered nothing. `hasattr(bpy.ops, x)`
is always True because `bpy.ops` resolves names lazily. Both produced **false passes**.

**Rule:** the probe prints its own verdict as a JSON `RESULT` line, and the harness uses that.
The exit code is a fallback for shell commands only.

## 3. Absence of evidence is not evidence of absence

The mirror error, and it cost more runs. `dir(bpy.ops.m_tree)` was empty, so the probe
concluded Modular Tree was inert. It registers 9 operators — in `bpy.ops.mtree`. The name was
wrong, not the tool.

**Rule:** discover names, do not assume them. Scan namespaces, list candidates, and report
what was found before concluding anything.

## 4. Do not wrap a call that does not raise

`addon_utils.enable()` returns `None` whether it worked or not and prints the traceback to
stderr. Three runs reported `mpfb_enable PASS` because a `try/except` around it could never
fire.

**Rule:** before writing `try/except`, know that the call can raise. When it cannot, call the
inner function directly (`module.register()`) so the exception surfaces.

## 5. Every probe needs a unique result name

All three renders reported `step="render"`, so Cycles and Workbench were overwritten by EEVEE.
Both installer calls reported `addon_install`, so MPFB2's install row was replaced by MTree's.

**Rule:** result names are identifiers, not descriptions. Put the varying part in the name.

## 6. Do not overwrite a probe's own output with a summary of it

`run_capture` added `RESULT <name> exit=0` beside a probe's detailed JSON row. Same name, later
line, so the detail vanished. The dedup that fixed it then matched the wrong names and let
`mtree_exit` survive as a "defect".

**Rule:** if a command printed its own `RESULT`, the wrapper stays silent.

## 7. Report where it looked, not just that it failed

`ModuleNotFoundError: No module named 'mpfb'` is true and useless. The diagnostic that solved
it was `sys_path_addons=[...]`, which showed Blender scanning `addons_core` and the user-config
`addons/modules` but not the installation's `scripts/addons`.

**Rule:** on failure, dump the search paths, the discovered modules and the candidate names.

## 8. A file count is not a clip count

The Quaternius archive holds 4 files, which the inventory reported as 4 "clips" while coverage
said 0 of 40 families. Both numbers were wrong: those 4 files are whole animation libraries in
single containers. Counting by filename cannot see inside a GLB.

**Rule:** measure the thing the pipeline needs. "How many animations are in this GLB" needs the
file opened, not its name inspected.

## 9. Separate decisions from defects

A control run that is *supposed* to fail — quantized gltfpack output not loading, which is why
LODs use `-noq` — was counted as a defect. A tool rejected after three attempts kept failing
and was reported as if the pipeline were broken. Nine "failures" were 0 defects.

**Rule:** the report has three states: PASS, EXPECTED FAIL (with the reason), DEFECT. A report
that cannot distinguish them trains its reader to ignore it.

## 10. State the range of a conclusion

"MTree is rejected" was wrong. "MPFB2 needs asset packs it does not install" was also wrong:
`src/mpfb/data/3dobjs/base.obj` is 1.7 MB and in the repository. Both were stated with more
confidence than the evidence carried.

**Rule:** say what was measured, what was inferred, and what would change the answer. A
conclusion that names its own weakest link is worth more than a confident one that does not.

## 11. Read the validator against its own data

`check_skeletons.py` was written and committed without executing. Reading it against
`animal_skeleton_definitions.json` found three bugs before CI did — a duplicated family, an
over-collecting species check, and a species covered by no family. CI then found the same three
plus nothing else.

**Rule:** when nothing can be executed locally, hand-trace the check against the real data. It
catches structural errors, though not syntax.

## 12. Prefer prevention to purging

Binaries reach `main` only by merging staging after the gates pass; a file over 20 MB becomes a
Release asset instead of a commit. `docs/HISTORY_PURGE.md` exists because a rewritten history
force-pushes and breaks every clone, but it should never be needed.

**Rule:** make the bad state unreachable rather than recoverable.

## Applying these

The asset validators in Phase 2 onward are probes with the same failure modes. In particular:

- A validator that passes because it found nothing to check is the same bug as #3. Count what
  was examined and print it: `animals: 117 species declared, 103 covered` is a useful line;
  `checks passed` alone is not.
- A validator that fails because it misidentified its input is #9. Separate "the asset is
  wrong" from "the validator cannot read the asset".
- Every `[TARGET-VISUAL]` score needs its measurement printed, not just its verdict, for the
  same reason as #7.
