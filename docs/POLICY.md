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
   Tree, Quaternius and MPFB2 are all pinned and verified now. GitHub Actions is pinned by commit
   SHA, and `tools/validate/check_action_pins.py` resolves every one of those SHAs through the API
   on every run, so a pin that does not exist fails in seconds instead of at setup in every job.
   See `tools/TOOLS.md`.
7. **A probe that reports and then crashes is a failure.** The bare `<name>_exit` row is no
   longer discarded: a non-zero exit after a result means the result may be partial.
8. **A check that cannot be enforced must say what it does not cover.** The animal skeleton
   validator checks parent-map structure — one `Root`, resolved parents, root reachability, no cycles
   and bilateral pairs — but not rest poses or deformation, because the definitions contain no
   transforms or generated rigs. The shader gate records that it compiles under Compatibility and
   not Mobile. Silence has read as coverage twice in this project.

### Concurrency

9. **Never silently drop a run. Prefer a slow queue to a vanished dispatch.** A concurrency group
   is the mechanism that drops runs: GitHub keeps one running and one pending per group, and a
   third arrival replaces the pending one. So no group is shared between workflows, and the one
   workflow whose every dispatch must execute declares none at all. The policy is per workflow,
   held in `CONCURRENCY_POLICY` in `check_scripts.py`, which fails the static gate if a workflow
   has no policy, if two workflows share a group, or if `cancel-in-progress` disagrees with the
   policy. **This replaced rule 9's predecessor**, "one CI run at a time, repository-wide", which
   was the owner's original instruction and caused the very dropping it was meant to prevent: a
   push-triggered validate could replace a queued manual Phase 0 or purge dispatch.

### Provenance and licensing

10. **A licence is derived, never defaulted.** `source_license` comes from `source_tool`; an
    unrecognised tool yields `null` and fails validation. A blanket CC0 default made an unchecked
    asset indistinguishable from a verified one. An entry may override it with its own sixth
    field, checked against the same allowlist.
    **`source_tool: custom` maps to `UNVERIFIED`, not to `project-original`.** `custom` says a
    script will make the asset, which is true for terrain and hydrology and says nothing about the
    fonts, music and audio that share the label — 1,110 of the then-current 1,954 records.
    `UNVERIFIED` may be
    planned and may never be built, so `check_manifest.py` reports the count on every run and fails
    the moment one of them claims to be built. Calling them ours was the blanket CC0 problem with
    a different word.
11. **`NEEDS-REVIEW` may be planned, never shipped.** It marks a real legal question — whether
    GPL-3.0 Modular Tree's output inherits that licence. Assets in that state fail validation the
    moment they are marked built.

### Size and history

12. **No file over 20 MB is committed**, and `.blend`, `.hdr` and `.exr` never are. Enforced in
    `check_scripts.py` on every run, not by habit. `main` as a whole stays under 800 MB, against a
    700 MB target.
13. **A binary never enters git. Finished categories are versioned ZIP packs on a GitHub Release,
    and the repository carries the catalogue.** `assets/packs.json` holds each pack's link, the
    archive's SHA-256 and size, and a hash and size for every file inside it.
    `tools/fetch_packs.py` downloads and verifies them into the paths `built.json` names, and every
    CI job runs it before it checks anything; `tools/pack_release.py` builds a deterministic
    archive. The publish job uploads a pack, **downloads it again and compares the hash**, and only
    then removes the files from the index, refusing to push a commit that still tracks a packed
    file. A tag is immutable: re-publishing different bytes under an existing tag fails rather than
    replacing it. This replaced "binaries reach main only through the staging branch", which was
    true and not enough — staging still put the bytes in history.
14. **An asset's path does not depend on where its bytes came from.** A packed asset and a committed
    one are the same path to every consumer, so moving a category to a pack is a `git rm --cached`
    and a catalogue entry, not a change to `built.json` or to whatever reads it.
15. **Removing a committed binary needs a purge, not a delete.** Deleting the file in a later commit
    leaves the blob in history. `docs/HISTORY_PURGE.md` is the only route, and it is manual.
16. **A purge backup never contains a credential.** The token-bearing clone URL is rewritten
    before the archive is made, and the archive is scanned before upload.

### Assets

17. **A definition is not an asset, and an asset is not a shipped asset.** The manifest records
    the plan; the build fills paths, hashes and gate results. "Built" requires a path, a hash,
    an input hash, a tool version and gate results.
18. **A tool that runs is not a tool that produces usable output.** MTree registering nine
    operators was not success; generating a tree Godot loads was.
19. **A mapping written from a convention is a guess until it is diffed against the data.** The
    retarget map was written from Mixamo-style names and is now diffed against the pack's real
    skin joints on every run, as a required probe.
20. **A third-party action is referenced by commit SHA, never by tag.** A tag is mutable, so `@v4`
    is code nobody reviewed running with this repository's token. `check_scripts.py` fails on a
    bare tag.
21. **A green row must not contain an error.** A probe that falls back to a working path used to
    report the failed first attempt's traceback in a PASS row, so `ModuleNotFoundError` appeared
    next to PASS. Detail fields are cleared when they no longer apply.

22. **An audit is answered by a ledger, not from memory.** Every finding an audit makes goes into
    `reports/audit_ledger.json` with a state and evidence, or a reason, before any code changes.
    `check_audit_ledger.py` fails the build on a clause with no state or no evidence, so "I dealt
    with that" is a row rather than a recollection. `docs/AUDIT_PROTOCOL.md` states the protocol.

**What to configure on GitHub, since a local hook cannot exist here.** The 20 MB guard runs in CI,
which is after a push, and there is no terminal on the device this repository is worked from, so a
pre-push hook is not available. The substitute is a ruleset: **Settings → Rules → Rulesets**, target
`main`, and require a pull request before merging, the `validate` status check to pass, and branches
to be up to date; leave no admin bypass. That moves the guard to before the merge instead of after
the commit, which is where the size check is actually useful. It is a repository setting, so nothing
in this repository enforces it — recorded here because it is the decision a `pre-push` hook would
otherwise have made for us. `docs/HISTORY_PURGE.md` remains the recovery path if something large
still lands.

## Not adopted, with reasons

**Sparse checkout.** The first committed terrain products have made the asset layout known, so the
original trigger has occurred. Sparse checkout remains deferred until a measured checkout cost
justifies maintaining patterns that could omit files and make a validator pass by finding nothing.
The full repository is currently about 11 MB; the existing workflow cost does not yet justify that
added risk.

## Deferred, and tracked

These are real and unfixed. They are listed so they are not rediscovered as surprises.

| Item | Why deferred |
|---|---|
| Generic model-quality checks: triangles, LODs, UV density, materials, weights and collision proxies | no production GLB models are committed yet (Phase 0 probe outputs are not production assets); terrain data has its own file-evidence and content checks, and model checks need actual models to measure |
| Animal rest-pose validation | Phase 4, when generated animal rigs or measured transforms exist; parent-map structure is validated now, but names alone cannot establish a rest pose |
| Humanoid rig remapping (137 bones → 56) and decimation (36,972 → 12k–18k) | Phase 5 |
| Tree decimation, leaf cards, LODs, impostors | Phase 3, the largest single piece |
| Retargeting actually run on a clip | Phase 5. The map is now diffed against real joints and that diff is gated, which is the prerequisite; running a clip is the next step |
| Mobile renderer verification | owner's decision: a real-device check, not a CI one. The CI shader gate compiles under Compatibility |
| Blender 4.2 LTS end of life | 4.2 is pinned because MPFB2 requires ≥ 4.2. Revisit when MPFB2 supports 4.5 and drop to one Blender for every job |
| Play Asset Delivery | only relevant if published to Google Play, which is not planned yet |
| Texture compression for Android (ETC2 / ASTC) | no Godot export preset or import setting exists yet, so there is nothing to gate. The trigger is the first export preset; the gate is then a check that every texture set declares its target format and that its compressed size is counted against the budget |
| Sparse checkout | see above; layout is known from committed terrain products, but defer until a measured checkout cost justifies the maintenance and omission risk |
| 1,110 assets with `source custom` | the largest open question in the manifest. `tools/generators/` now exists but covers terrain and hydrology only; the rest are `UNVERIFIED` — planned, never shippable — until each entry records where it comes from. Phase 2 onward |
| Generator performance: 1,025² grids in pure stdlib Python | the three generator steps share a 10-minute job and finish in seconds today. Pinned numpy would remove the ceiling but adds the first third-party dependency to the generators. Revisit when a generator run approaches the limit, and record wall time at that point |
