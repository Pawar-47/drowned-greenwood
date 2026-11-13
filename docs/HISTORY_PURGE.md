# Purging a bad binary from git history

**Read this before running anything here.** Rewriting history force-pushes and invalidates
every clone, fork and open pull request. It is the last resort, not the first.

## Prevention (this is what normally applies)

1. Binaries never reach `main` by direct push. They are built on `staging`, pass the gates,
   and arrive on `main` only by merging the staging branch.
2. Every binary is committed **once**. It is re-committed only when its generator script,
   config or seed changes — which is what the `input_hash` field in the manifest records.
3. A file that would exceed 20 MB is not committed at all. It becomes a Release asset, and
   the manifest records its `pack` and `sha256` instead.
4. `git count-objects -vH` and `du -sh assets/*` are reported after every phase, against the
   budget table, so growth is visible while it is still cheap to fix.

If those four hold, this document is never needed.

## When it is needed

A binary over the limit, a `.blend`, a 4K texture, a ZIP or an HDR has been committed. A
single offending blob makes the clone permanently heavy even after a later commit deletes it.

## The workflow

`.github/workflows/history-purge.yml` is **manual only** (`workflow_dispatch`) and has three
inputs: the paths to purge, a `mode` of `dry-run` or `apply`, and a confirmation string.

**It is a dry run by default.** In `dry-run` it validates the paths, clones, rewrites history
in the runner, uploads the backup and stops without pushing anything. To actually apply, you
dispatch again with `mode=apply` and `confirm=FORCE-PUSH`, having downloaded and checked the
backup from the dry run.

Safety properties worth knowing:

- Inputs are passed through `env:`, never interpolated into shell source. An earlier version
  used `${{ inputs.paths }}` directly inside `run:`, which on a `contents: write` workflow with
  force-push steps is a shell-injection hole.
- Paths are validated against `^[A-Za-z0-9._/-]+$`, must be relative, and must not contain `..`.
  Anything else is rejected rather than escaped.
- **The access token never reaches the backup.** `git clone` writes the token-bearing URL into
  `.git/config`, and the backup step tars the whole directory — so the credential would have
  been archived and uploaded for 90 days. The remote URL is rewritten to a token-free one
  immediately after cloning, the config is grepped for token patterns, and the finished archive
  is scanned again before upload. Any hit aborts the run.
- The backup is uploaded as a 90-day artifact **before** the push step, so it outlives the
  runner.
- `git-filter-repo` is pinned to an exact version, so a purge behaves the same next year.

**What a dry run does and does not give you.** It uploads `purge-backup.tar.gz`: the mirror as it
was *before* the rewrite, plus its checksum. That is the rollback material. The rewritten mirror
is **not** uploaded — it would double the artifact cost and nothing can be restored from it.

An apply run makes its **own** fresh backup and pushes from its own mirror. It does not reuse the
dry run's artifact, so approving a dry run is a judgement that the path list is correct, not a
guarantee that apply operates on identical bytes.

## Three things an apply run needs before it can work

None is configured, and the workflow refuses rather than failing halfway.
**1. A token that may push workflow files.** `GITHUB_TOKEN` is not permitted to push commits
touching `.github/workflows/`. Rewriting history rewrites *every* commit, and this repository's
history contains workflow commits from its first commit — so an apply run with `GITHUB_TOKEN`
will always stop at the guard before the push step. Nothing is changed on the remote when it does.

To proceed: create a fine-grained PAT with **Contents: write** and **Workflows: write** on this
repository and store it as the `HISTORY_PURGE_TOKEN` secret. No workflow change is needed — the
push step reads that secret when it is present and falls back to `GITHUB_TOKEN` when it is not,
printing which one it used rather than leaving you to infer it from a later failure. The
deliberate act is storing the secret: the pipeline never obtains a scoped token for itself.

**2. A protected environment with a required reviewer.** The job declares
`environment: history-purge`. Three caveats, all real:

- Declaring the name gates **nothing** on its own; it only creates the environment on first use.
  It must be configured in **Settings → Environments → history-purge**.
- It gates the **whole job, dry run included**, because GitHub environments are job-level. A dry
  run therefore needs approval too. That is accepted: approving a run of a history-rewriting
  workflow is cheap, and a dry run nobody looked at is not a safeguard.
- **"Prevent self-review" is an option, and it is off unless ticked.** When it is on, the person
  who dispatched a run cannot approve it — which on a single-maintainer repository deadlocks this
  workflow. When it is off (the default), one account can dispatch and approve, so required
  reviewers are usable here. Decide which you want before adding yourself as the reviewer:
  do not configure it and then wonder why an apply run never starts.

**3. Nothing else running, and you are the only purge in flight.** This workflow declares **no
concurrency group**, deliberately: a group keeps one running and one pending run, and a third
arrival replaces the pending one, so a dropped `apply` would leave the remote untouched while
looking like it did nothing. Every dispatch therefore executes.

The cost is that two applies could in principle run at once and push conflicting histories. The
force-push step now refuses if another history-purge run is already running **or queued**, checked
through the API immediately before the irreversible push. **That narrows the window, it does not
close it**: two dispatches starting within the same few seconds could both see an empty queue. The
typed `FORCE-PUSH` confirmation is still the real gate, and so is not dispatching twice.

## Rehearse it on a throwaway fork first

This workflow has never run end to end. Before using it on this repository, fork it, add a
deliberately committed junk blob, and run `dry-run` then `apply` there — with a PAT, since the
workflow-file guard applies to the fork too. That exercise is what turns "the steps look right"
into "the steps ran".

## Manual steps (what the workflow does, so it can be done by hand)

```bash
# 1. Fresh mirror clone. Never work in a clone you care about.
git clone --mirror https://github.com/Pawar-47/drowned-greenwood.git purge-work
cd purge-work

# 2. Back up first, and keep it off the machine you are about to rewrite.
cp -r . ../purge-backup && tar -czf ../purge-backup.tar.gz ../purge-backup

# 3. Install the pinned tool.
pip install git-filter-repo==2.45.0

# 4. Remove the paths. Repeat --path for each one.
git filter-repo --force --invert-paths \
  --path assets/flora/tree_greatfir_ancient_lod0.glb \
  --path some/other/blob

# 5. Check the damage before pushing.
git count-objects -vH
git log --oneline -5

# 6. Force-push every ref back. This is the irreversible step.
git push --force --all
git push --force --tags
```

## After a purge

- Every collaborator must re-clone. Their old clones will try to re-push the purged blobs.
- Open pull requests from forks may be unmergeable; recreate them.
- GitHub may keep unreferenced objects reachable for a while. Ask GitHub Support to run
  garbage collection on the repository if the size does not drop.
- Record what was purged and why in `reports/quality_report.md` under the phase it happened
  in, so the cause gets fixed in the generator rather than recurring.
