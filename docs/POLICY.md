# Policy

Rules this repository enforces, and the ones it deliberately does not. Each entry says what
happens when it is broken, because a rule with no consequence is a comment.

## Adopted

### Verification

1. **A probe reports its own verdict.** A `RESULT` line carries `ok`; the harness never infers
   success from an exit code. Blender exits 0 when an add-on registers nothing.
2. **A missing required result is a failure.** A probe that produces no row is indistinguishable
   from one that crashed, so both fail the build. This exists because a 45-minute timeout once
   vanished from the gate.
3. **A failing build explains itself in the report body**, not only on stderr, which CI
   buffering pushes out of view.
4. **A negative control is green when it fails.** A permanently red row trains a reader to skim
   past red, which is how the one that matters gets missed.
5. **Cheap checks run first.** `check_scripts.py` parses every Python, shell, JSON, shader and
   workflow file in seconds and gates the expensive jobs on it.
6. **A pin that is not verified must not read as verified.** An empty checksum variable makes the
   probe report `ok=False reason=unpinned` and print the measured hash, instead of passing
   silently. A cache hit must not skip a checksum either: the Blender cache holds the *archive*,
   keyed by its expected hash, so the check runs on every job. Godot, gltfpack, Blender, Modular
   Tree, Quaternius and MPFB2 are all pinned and verified now; GitHub Actions is not. See
   `tools/TOOLS.md`.
7. **A probe that reports and then crashes is a failure.** The bare `<name>_exit` row is no
   longer discarded: a non-zero exit after a result means the result may be partial.
8. **A check that cannot be enforced must say what it does not cover.** The animal skeleton
   validator prints "hierarchy NOT validated"; the shader gate records that it compiles under
   Compatibility and not Mobile. Silence has read as coverage twice in this project.

### Concurrency

9. **One CI run at a time, repository-wide**, enforced by every workflow sharing the `ci-serial`
   group with `cancel-in-progress: false`. `check_scripts.py` now fails if any workflow declares
   a different group or turns cancellation on, so the rule is checked rather than assumed.

### Provenance and licensing

10. **A licence is derived, never defaulted.** `source_license` comes from `source_tool`; an
    unrecognised tool yields `null` and fails validation. A blanket CC0 default made an unchecked
    asset indistinguishable from a verified one. An entry may override it with its own sixth
    field, checked against the same allowlist.
11. **`NEEDS-REVIEW` may be planned, never shipped.** It marks a real legal question — whether
    GPL-3.0 Modular Tree's output inherits that licence. Assets in that state fail validation the
    moment they are marked built.

### Size and history

12. **No file over 20 MB is committed**, and `.blend`, `.hdr` and `.exr` never are. Enforced in
    `check_scripts.py` on every run, not by habit.
13. **Binaries reach `main` only through the staging branch after the gates pass.** History
    rewriting is a last resort with a documented manual path.
14. **A purge backup never contains a credential.** The token-bearing clone URL is rewritten
    before the archive is made, and the archive is scanned before upload.

### Assets

15. **A definition is not an asset, and an asset is not a shipped asset.** The manifest records
    the plan; the build fills paths, hashes and gate results. "Built" requires a path, a hash,
    an input hash, a tool version and gate results.
16. **A tool that runs is not a tool that produces usable output.** MTree registering nine
    operators was not success; generating a tree Godot loads was.
17. **A mapping written from a convention is a guess until it is diffed against the data.** The
    retarget map was written from Mixamo-style names and is now diffed against the pack's real
    skin joints on every run, as a required probe.
18. **A third-party action is referenced by commit SHA, never by tag.** A tag is mutable, so `@v4`
    is code nobody reviewed running with this repository's token. `check_scripts.py` fails on a
    bare tag.
19. **A green row must not contain an error.** A probe that falls back to a working path used to
    report the failed first attempt's traceback in a PASS row, so `ModuleNotFoundError` appeared
    next to PASS. Detail fields are cleared when they no longer apply.

## Not adopted, with reasons

**Per-workflow concurrency groups.** The audit is right that a shared `ci-serial` group lets a
newer queued run replace an older one, so a manual Phase 0 or purge dispatch can be silently
dropped. Giving each workflow its own group fixes that but permits simultaneous runs, which
contradicts the owner's one-run-at-a-time rule. **This is an owner decision**, not an engineering
one: either the rule relaxes, or the queue can drop and we accept it. Until the owner decides,
the rule is enforced and this consequence is documented in `README.md`.

**Sparse checkout.** Deferred because the asset directory layout does not exist yet, so any
`sparse-checkout` pattern today would be a guess that silently omits a directory later — and a
checkout that omits files makes a validator pass by finding nothing, which is the failure mode
this repository keeps having to remove. The trigger is the first committed binary: at that point
the layout is known and the pattern can be written from it. Until then every job checks out the
whole tree, which is currently about 0.4 MB.

## Deferred, and tracked

These are real and unfixed. They are listed so they are not rediscovered as surprises.

| Item | Why deferred |
|---|---|
| Manifest checks that open the file: hash, size, triangles, LODs, materials | impossible until an asset exists; writing them now produces a validator that passes by finding nothing |
| Animal bone hierarchies and rest poses | Phase 4; inventing rest poses with no generator to test them against produces data that looks complete and is not |
| Humanoid rig remapping (137 bones → 56) and decimation (36,972 → 12k–18k) | Phase 5 |
| Tree decimation, leaf cards, LODs, impostors | Phase 3, the largest single piece |
| Retargeting actually run on a clip | Phase 5. The map is now diffed against real joints and that diff is gated, which is the prerequisite; running a clip is the next step |
| Mobile renderer verification | owner's decision: a real-device check, not a CI one. The CI shader gate compiles under Compatibility |
| Blender 4.2 LTS end of life | 4.2 is pinned because MPFB2 requires ≥ 4.2. Revisit when MPFB2 supports 4.5 and drop to one Blender for every job |
| Play Asset Delivery | only relevant if published to Google Play, which is not planned yet |
| Sparse checkout | see above; trigger is the first committed binary |
| 1,110 assets with `source custom` and no generator | the largest open question in the manifest: `tools/generators/` does not exist, and Phase 0 tested no tool that produces them. Phase 2 onward |
