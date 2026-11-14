# Release packs: how a binary reaches a build without reaching git

A finished asset category is published as **one versioned ZIP on a GitHub Release**. The repository
carries the catalogue that describes it, never the bytes. This document is the policy, the
mechanics and the failure modes.

## Why

A binary in git is permanent. Deleting it in a later commit does not remove it from history — the
blob stays reachable, the clone stays heavy, and the only remedy is a force-push described in
`docs/HISTORY_PURGE.md`. The brief's cap is 800 MB for `main`, and the plan's category budgets total
790 MB. Committing categories at that scale would pass the cap and then keep every superseded
version forever.

So the rule is: **bytes live on a Release, hashes live in the repository.** The catalogue is small,
diffable and reviewable; the archive is one file that can be replaced (under a new version) without
growing history.

## What the catalogue holds

`assets/packs.json`:

```json
{
  "schema_version": 1,
  "release_base": "https://github.com/Pawar-47/drowned-greenwood/releases/download",
  "packs": [
    {
      "name": "terrain-1.3.0",
      "category": "terrain",
      "version": "1.3.0",
      "tag": "assets-terrain-1.3.0",
      "asset": "terrain-1.3.0.zip",
      "url": "https://github.com/.../releases/download/assets-terrain-1.3.0/terrain-1.3.0.zip",
      "sha256": "…64 hex characters…",
      "size_bytes": 5123456,
      "dest": "assets/terrain",
      "files": {
        "terrain_heightmap_master_1km.png": { "sha256": "…", "size_bytes": 1825792 }
      }
    }
  ]
}
```

Three properties matter:

1. **The archive is hashed and sized.** A truncated download or a wrong URL is caught before
   anything is extracted.
2. **Every file inside is hashed and sized separately.** A corrupted member is caught even when the
   archive was replaced wholesale, and a missing member fails instead of leaving a stale file on
   disk.
3. **`dest` is a path inside `assets/`.** Extraction is confined there, and an archive entry that is
   absolute, contains `..`, or is otherwise unsafe is refused before a byte is written.

`assets/built.json` keeps naming the same paths it always did (`assets/terrain/…`). A packed asset
and a committed one are one path to every consumer; the only difference is which mechanism put the
bytes there.

## The lifecycle of a pack

1. **Build.** The publish job in `validate.yml` generates the category, gates it and records the
   built evidence exactly as before.
2. **Pack.** `tools/pack_release.py --source assets/terrain --category terrain --version <v> --out
   <zip> --entry <json>` writes a deterministic archive: sorted entries, fixed timestamps, no
   directory entries. Two runs over the same bytes produce the same SHA-256.
3. **Upload.** `gh release create <tag> <zip>` publishes it under the version the generator reports.
4. **Verify the upload by downloading it.** The job fetches the asset back from its own URL and
   compares the hash. Nothing is removed from git until that round trip matches.
5. **Record.** The entry is merged into `assets/packs.json`, and `check_packs.py` re-validates the
   catalogue.
6. **Remove from the index.** `git rm -r --cached --ignore-unmatch assets/terrain` takes the files
   out of the tree. `.gitignore` already ignores them, so they cannot be added back by accident.
7. **Push to `staging`.** Only `built.json` and `packs.json` are committed. `main` stays free of
   binaries, and reaches them only by merging `staging` after the gates pass.
8. **Fetch.** Every CI job runs `tools/fetch_packs.py` before it needs an asset. It is a no-op on an
   empty catalogue, so the same workflow holds before and after a category is packed.

## Versions are immutable

A tag names one archive. Re-running the publish job with **the same** content reuses the release and
verifies it. Re-running it with **different** content under the same tag fails:

```
release assets-terrain-1.3.0 holds different bytes (… != …).
Bump GENERATOR_VERSION or delete the release before republishing.
```

That is deliberate. A version that means two different byte sets is worse than a red build: every
hash recorded in `built.json` becomes ambiguous. `GENERATOR_VERSION` in
`tools/generators/common.py` is already bumped whenever the output changes, so in practice each
release is one generator version.

## Adding a new category

The tooling is generic; only the workflow step is specific, because terrain is the only category
with a generator today. For a new one:

```bash
python tools/pack_release.py --source assets/flora --category flora --version 1.0.0 \
    --out /tmp/flora.zip --entry /tmp/flora.json
gh release create assets-flora-1.0.0 /tmp/flora.zip
curl -sSL --fail -o /tmp/check.zip <url>
sha256sum /tmp/check.zip          # must equal the entry's sha256
python tools/pack_release.py --record /tmp/flora.json --catalogue assets/packs.json
```

Then remove the files from the index the way the publish job does, and let `fetch_packs.py` put
them back.

## Checks

`tools/validate/check_packs.py` runs in the manifest job and in the publish job:

- every pack has the required fields, a 64-hex SHA-256, a positive size, an https URL that resolves
  from `release_base`, `tag` and `asset` alone, and a `dest` inside `assets/`;
- every file has a hash and a size, and no name escapes its directory;
- pack names and release tags are unique;
- the total packed size is reported against the 800 MB cap.

With `--require-untracked`, used by the publish job after it cuts a pack, a packed file that is
**also** tracked in git fails the build. That is the one mistake this whole mechanism exists to
prevent: a file in both places is how a packed asset quietly re-enters history, and a history entry
is permanent.

`tools/validate/check_scripts.py` keeps the existing guards: no file over 20 MB, and `.blend`,
`.hdr` and `.exr` never committed.

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| `fetch_packs.py` prints `answered 404` | the release has not been published yet, or the catalogue was merged before the upload | run the publish job (or create the release) before merging the catalogue |
| a file fails its hash after extraction | the archive was replaced without a version bump, or the download was corrupted | re-download; if it persists, the catalogue and the release disagree and the release must be re-cut under a new version |
| `check_packs.py --require-untracked` fails | a packed file is still in the git index | `git rm --cached <path>` and commit |
| the repository is over 800 MB | something large was committed | `docs/HISTORY_PURGE.md`, and fix the generator or the workflow so it cannot recur |

## If a release is lost

The catalogue cannot be rebuilt from the repository alone — that is the cost of keeping bytes out of
git. A lost or deleted release is regenerated from the pinned sources: the generators are
deterministic from the seed and the input hash, so `python tools/generators/…` reproduces the same
bytes, and the recorded SHA-256 proves it. Then re-publish under the same tag. If the archive no
longer reproduces, the generator changed without a version bump — which is the failure the
`input_hash` field exists to make visible.

## History

A binary that was never committed cannot need a purge. The terrain maps were committed for a while
before packs existed; removing them from the index stops future growth, and taking them out of
history is the separate, manual operation in `docs/HISTORY_PURGE.md` — one path per file, applied to
every commit, with a dry run and a typed confirmation. Doing that is optional for ~5 MB; it is
mandatory once a category of any size has been committed by mistake.
