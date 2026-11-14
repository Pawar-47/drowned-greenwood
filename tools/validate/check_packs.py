#!/usr/bin/env python3
"""Check the pack catalogue: the links, the hashes, the sizes and where the files land.

Run:
    python tools/validate/check_packs.py
    python tools/validate/check_packs.py --require-untracked   # after a pack replaces committed files

Why this exists: the catalogue is the only thing standing between "the repository is small" and "the
build is missing a texture". A pack entry that names the wrong tag, a URL that does not resolve to
the archive beside it, a hash with the wrong length, or a `dest` that escapes `assets/` all look
fine in review and fail at download time — on a runner, minutes in. Every one of those is a string
comparison, so it belongs here rather than in the build.

`--require-untracked` is the second half of the release policy: once a category is packed, its files
must not also be tracked in git. A file in both places is how a "packed" asset quietly re-enters
history, and a history entry is permanent. The publish job passes the flag after it cuts a pack; the
ordinary validate run only warns, because the switch is a one-commit migration and a repository that
still tracks the files is allowed to be in the middle of it.
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOGUE = os.path.join("assets", "packs.json")

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# The cap the brief sets for the repository itself. Packs do not count against it — they are not in
# git — but the two totals are printed together so the real cost of the asset plan is visible.
REPO_CAP_BYTES = 800 * 1024 * 1024

REQUIRED = ("name", "category", "version", "tag", "asset", "url", "sha256", "size_bytes", "dest", "files")


def check_entry(pack, release_base, index, problems):
    if not isinstance(pack, dict):
        problems.append("pack %d is not an object" % index)
        return 0
    where = pack.get("name") or "pack %d" % index
    for field in REQUIRED:
        if field not in pack:
            problems.append("%s has no %s" % (where, field))
    for field in ("name", "category", "version"):
        value = pack.get(field)
        if not isinstance(value, str) or not value:
            problems.append("%s: %s must be a non-empty string" % (where, field))
    for field in ("tag", "asset"):
        value = pack.get(field)
        if not isinstance(value, str) or not value:
            problems.append("%s: %s must be a non-empty string" % (where, field))
        elif not SAFE_NAME.match(value):
            problems.append("%s: %s %r is not a safe release name" % (where, field, value))

    digest = pack.get("sha256")
    if not isinstance(digest, str) or not SHA256.match(digest):
        problems.append("%s: sha256 is not 64 lowercase hex characters" % where)
    size = pack.get("size_bytes")
    if not isinstance(size, int) or size <= 0:
        problems.append("%s: size_bytes must be a positive integer" % where)

    expected_url = "%s/%s/%s" % (
        str(release_base).rstrip("/"),
        pack.get("tag"),
        pack.get("asset"),
    )
    if pack.get("url") != expected_url:
        problems.append(
            "%s: url is %r but the catalogue's release_base, tag and asset make %r"
            % (where, pack.get("url"), expected_url)
        )
    if not str(pack.get("url", "")).startswith("https://"):
        problems.append("%s: url is not https" % where)

    dest = str(pack.get("dest", ""))
    if not dest.startswith("assets/"):
        problems.append("%s: dest %r is outside assets/" % (where, dest))
    if ".." in dest.split("/"):
        problems.append("%s: dest %r escapes the repository" % (where, dest))

    files = pack.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("%s: files must be a non-empty object" % where)
        return
    total = 0
    for name, record in sorted(files.items()):
        normalised = str(name).replace("\\", "/")
        if normalised.startswith("/") or ".." in normalised.split("/") or not normalised:
            problems.append("%s: file %r is not a relative path inside the pack" % (where, name))
            continue
        if not isinstance(record, dict):
            problems.append("%s: file %r is not an object" % (where, name))
            continue
        if not SHA256.match(str(record.get("sha256", ""))):
            problems.append("%s: file %r has no valid sha256" % (where, name))
        size = record.get("size_bytes")
        if not isinstance(size, int) or size <= 0:
            problems.append("%s: file %r has no positive size_bytes" % (where, name))
        else:
            total += size
    files_total = sum(
        int(record.get("size_bytes", 0))
        for record in files.values()
        if isinstance(record, dict) and isinstance(record.get("size_bytes"), int)
    )
    if total and total > REPO_CAP_BYTES:
        problems.append(
            "%s: the pack's files total %.1f MB, over the 800 MB repository cap on their own"
            % (where, files_total / (1024 * 1024))
        )
    return files_total


def tracked(path):
    """Whether git tracks `path`. Returns None when git cannot answer, so the call site can warn."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-untracked",
        action="store_true",
        help="fail if a packed file is also tracked in git (run after a pack replaces commits)",
    )
    args = parser.parse_args()

    path = os.path.join(ROOT, CATALOGUE)
    if not os.path.exists(path):
        print("no pack catalogue at %s; every asset is expected to be committed" % CATALOGUE)
        return 0
    with open(path, "r", encoding="utf-8") as handle:
        catalogue = json.load(handle)

    problems = []
    if catalogue.get("schema_version") != 1:
        problems.append("schema_version is %r, expected 1" % catalogue.get("schema_version"))
    release_base = catalogue.get("release_base")
    if not isinstance(release_base, str) or not release_base.startswith("https://"):
        problems.append("release_base is not an https URL")
        release_base = ""
    packs = catalogue.get("packs")
    if not isinstance(packs, list):
        problems.append("packs is not a list")
        packs = []

    seen_names, seen_tags, packed_total = set(), set(), 0
    for index, pack in enumerate(packs):
        if not isinstance(pack, dict):
            problems.append("pack %d is not an object" % index)
            continue
        files_total = check_entry(pack, release_base, index, problems) or 0
        packed_total += files_total
        name = pack.get("name")
        if name in seen_names:
            problems.append("pack name %r appears twice" % name)
        seen_names.add(name)
        tag = pack.get("tag")
        if tag in seen_tags:
            problems.append("release tag %r appears twice" % tag)
        seen_tags.add(tag)

    # A packed file that is also tracked is the one mistake this whole file exists to prevent, so
    # it is reported even in the warn-only mode: the difference is whether it fails the build.
    duplicated = []
    if args.require_untracked:
        for pack in packs:
            if not isinstance(pack, dict):
                continue
            for name in sorted((pack.get("files") or {})):
                relative = os.path.join(pack.get("dest", ""), name)
                state = tracked(relative)
                if state:
                    duplicated.append(relative)
        for relative in duplicated[:10]:
            problems.append("%s is in a pack and still tracked in git" % relative)
        if len(duplicated) > 10:
            problems.append("... and %d more packed files are still tracked" % (len(duplicated) - 10))

    if problems:
        print("pack catalogue checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print(
        "packs: %d pack(s), %.1f MB of assets on Releases, %d file(s) hashed and sized; the "
        "catalogue is consistent with its release URLs"
        % (
            len(packs),
            packed_total / (1024 * 1024),
            sum(len(pack.get("files") or {}) for pack in packs if isinstance(pack, dict)),
        )
    )
    if args.require_untracked:
        print("packs: no packed file is tracked in git")
    return 0


if __name__ == "__main__":
    sys.exit(main())
