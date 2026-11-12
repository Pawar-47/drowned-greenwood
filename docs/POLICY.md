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

### Provenance and licensing

6. **A licence is derived, never defaulted.** `source_license` comes from `source_tool`; an
   unrecognised tool yields `null` and fails validation. A blanket CC0 default made an unchecked
   asset indistinguishable from a verified one.
7. **`NEEDS-REVIEW` may be planned, never shipped.** It marks a real legal question — whether
   GPL-3.0 Modular Tree's output inherits that licence. Assets in that state fail validation the
   moment they are marked built.

### Size and history

8. **No file over 20 MB is committed**, and `.blend`, `.hdr` and `.exr` never are. Enforced in
   CI, not by habit.
9. **Binaries reach `main` only through the staging branch after the gates pass.** History
   rewriting is a last resort with a documented manual path.
10. **A purge backup never contains a credential.** The token-bearing clone URL is rewritten
    before the archive is made, and the archive is scanned before upload.

### Assets

11. **A definition is not an asset, and an asset is not a shipped asset.** The manifest records
    the plan; the build fills paths, hashes and gate results. "Built" requires a path, a hash,
    an input hash, a tool version and gate results.
12. **A tool that runs is not a tool that produces usable output.** MTree registering nine
    operators was not success; generating a tree Godot loads was.

## Not adopted, with reasons

**Per-workflow concurrency groups.** The audit is right that a shared `ci-serial` group lets a
newer queued run replace an older one, so a manual Phase 0 or purge dispatch can be silently
dropped. Giving each workflow its own group fixes that but permits simultaneous runs, which
contradicts the owner's one-run-at-a-time rule. **This is an owner decision**, not an engineering
one: either the rule relaxes, or the queue can drop and we accept it.

**Pinning GitHub Actions to commit SHAs.** Correct in principle. Deferred because it is 14 pins
across three workflows with no behavioural change, and the higher-value work is the asset
pipeline. Recorded in `tools/TOOLS.md` under outstanding pins.

## Deferred, and tracked

These are real and unfixed. They are listed so they are not rediscovered as surprises.

| Item | Why deferred |
|---|---|
| Manifest checks that open the file: hash, size, triangles, LODs, materials | impossible until an asset exists; writing them now produces a validator that passes by finding nothing |
| Animal bone hierarchies and rest poses | Phase 4; inventing rest poses with no generator to test them against produces data that looks complete and is not |
| Humanoid rig remapping (137 bones → 56) and decimation (36,972 → 12k–18k) | Phase 5 |
| Tree decimation, leaf cards, LODs, impostors | Phase 3, the largest single piece |
| Retargeting actually run on a clip | Phase 5; the map is now diffed against real joints, which is the prerequisite |
| Mobile renderer verification | owner's decision: a real-device check, not a CI one |
| Blender 4.2 LTS end of life | 4.2 is pinned because MPFB2 requires ≥ 4.2. Revisit when MPFB2 supports 4.5 |
| Play Asset Delivery | only relevant if published to Google Play, which is not planned yet |
| Unit tests for `build_manifest` and `make_report` | the static gate and the report gate cover the failures seen so far; a test suite is the next step when either grows |
