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

## 13. `read_factory_settings()` unregisters every enabled add-on

The one that cost the most. Both probes enabled an add-on and then called
`bpy.ops.wm.read_factory_settings(use_empty=True)` to get an empty scene. That resets
Blender's *preferences*, and the enabled add-on list lives in preferences — so the add-on was
disabled again, and the very next line reported "operator could not be found".

The last run before this was fixed shows it plainly: MTree registered **9 operators**, then
failed to find `add_tree` one step later. The tool was fine; the probe was sabotaging itself.

**Rule:** use `clear_scene()` (remove objects and collections) when a probe needs a clean
scene. Never `read_factory_settings` after enabling anything.

## 14. Do not use a slow job as your test loop

Phase 0 spent over two hours of runner time, much of it re-running a 10-minute Infinigen
install that had already passed four times, while the actual changes were a few lines in a
probe.

**Rules:**
- Run the cheapest check that can catch the mistake first. `check_scripts.py` parses every
  Python, shell, JSON and workflow file in seconds; a syntax error should never reach Blender.
- Make an expensive probe conditional when it has already passed and the change cannot affect
  it. Infinigen now runs only when `run_infinigen` is set.
- Cache large downloads (`actions/cache` on the Blender directory) instead of re-downloading
  ~350 MB per job per run.
- Batch changes. One push with everything audited beats six pushes with one fix each.

## 15. Every probe reports or it did not run

A probe that raises before its first `RESULT` line leaves the harness with nothing, which is
indistinguishable from a probe that was never invoked.

**Rule:** wrap the probe body so an escaped exception becomes a named result
(`mpfb_crash`, `mtree_crash`) carrying its traceback. Then "no result" always means a harness
bug, never a silent crash.

## 16. The reader must accept every shape a writer may produce

The report parser accepted exactly two forms — `RESULT <name> exit=<n>` and JSON — and silently
dropped everything else. The workflow emitted `RESULT godot_version version=4.7.2-stable` and
the Poly Haven probe emitted `RESULT polyhaven_download ok=True ...`. Both had run and passed;
both were reported as "required probe produced no result", and the build failed on two
non-problems.

This is the third instance of one class: **a probe whose output never reaches the report**, after
`run_capture` overwriting a probe's row and the installer printing a shape the parser dropped.

**Rule:** a reader tolerates more than the writer is documented to send. Accept JSON, exit codes
and key=value. Then a probe cannot vanish because of its punctuation.

**But a missing verdict is not a pass.** The first fix for this went too far the other way: an
unrecognised key=value line was treated as success unless it contained `ok=False`, so a probe
emitting `RESULT something reason=...` — no verdict at all — counted as green. Silence is not
agreement. Every shape must now carry its own `ok`; a line without one is a failure that says so.
The same applies to JSON: a payload with no `ok` field, a truncated object, or a JSON array is a
failure, not a line to skip.

## 18. A convention is not a measurement

The retarget map was written from the Mixamo naming convention — `LeftUpLeg`, `Spine1`,
`LeftArm` — because that is the convention most CC0 animation libraries use. Quaternius's
Universal Animation Library does not. It uses Unreal-mannequin names: `thigh_l`, `spine_01`,
`upperarm_l`, `calf_l`, `clavicle_l`.

The probe measured 65 joints in the pack against 23 mapped names and matched exactly **one** of
them — `Head`, the only name both conventions happen to share. Every other entry pointed at a bone
that does not exist. Nothing failed, because nothing was comparing the map to the data: the map
was a document, and documents do not run.

This is the same shape as #1 and #11. A plausible-looking artefact that no check opens is not
evidence of anything.

**Rule:** when a file claims a mapping, a convention or a name scheme, something must diff it
against the real data on every run, and the diff must be able to fail the build. Write the map
from the measured names, never from what the convention "should" be — and keep the full measured
list in the log, not a 25-name sample, because the sample is what forced the second guess.

## 19. Check the whole file, not the part you changed

A one-line addition — a `git commit -m` message with a second paragraph — silently broke a
workflow file. A YAML literal block scalar (`run: |`) ends at the first line indented less than
the block, so a continuation line at column 0 terminated the `run:` block, and everything after
it became invalid YAML. The static gate caught it on the next run, which is the system working:
the failure was found in seconds by a check, not in minutes by a runner.

**Rule:** after editing a structured file, re-read the region around the edit *and* let the
cheapest check parse the whole file. Prose inside code is code.

## 17. A gate that fails must say why, in the body

stderr is unbuffered; stdout is block-buffered. On a piped CI log that means the one line
explaining the failure is written hundreds of lines before the report it belongs to — and was
truncated out of the run view entirely. The build failed and the reason was invisible.

**Rule:** anything that fails a build is written into the artefact the build produces, not only
to stderr. The report now ends with a Gate section naming every missing or failed required probe.

## 20. A concurrency group is a mechanism for dropping runs

The rule for a long time was "one CI run at a time, repository-wide", enforced by every workflow
sharing one concurrency group. It read as a safeguard. It was the opposite.

GitHub keeps one **running** and one **pending** run per group, and a third arrival **replaces the
pending one**. So the shared group meant a push-triggered `validate` could replace a queued manual
Phase 0 or history-purge dispatch — and that run was never created. Not cancelled, not failed,
just absent, with an empty queue afterwards and no trace that anything had been requested. Sharing
one group across three unrelated workflows made it much more likely, because they all competed for
a single pending slot.

**Rule:** ask what a mechanism does when it is under load, not what it is called. A group is a
*replacement* mechanism. If every run must happen, declare no group and solve the collision some
other way — for `history-purge` that is an explicit in-flight check before the force-push, which
narrows the window and is documented as narrowing rather than closing it.

**And never claim a guarantee the platform does not give.** The honest statement is: a push can no
longer replace a queued manual dispatch, but two runs of the same workflow from the same event on
the same ref can still collide. Saying that out loud is worth more than a rule that sounds
stronger and silently loses work.

## Applying these

The asset validators in Phase 2 onward are probes with the same failure modes. In particular:

- A validator that passes because it found nothing to check is the same bug as #3. Count what
  was examined and print it: `animals: 117 species declared, 103 covered` is a useful line;
  `checks passed` alone is not.
- A validator that fails because it misidentified its input is #9. Separate "the asset is
  wrong" from "the validator cannot read the asset".
- Every `[TARGET-VISUAL]` score needs its measurement printed, not just its verdict, for the
  same reason as #7.
