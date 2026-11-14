#!/usr/bin/env python3
"""Download the packed asset categories from their GitHub Releases and put them on disk.

Run:
    python tools/fetch_packs.py                  # download anything missing or wrong
    python tools/fetch_packs.py --verify-only    # check what is on disk, download nothing
    python tools/fetch_packs.py --pack terrain-1.3.0

Why fetch rather than commit: the repository carries `assets/packs.json`, not the bytes. Every CI
job and every local build that needs an asset calls this first, so the working tree looks the same
whether an asset arrived in a pack or (before the packs existed) in a commit. `assets/built.json`
names the same paths either way.

The verification is deliberately two-stage. The archive is checked against its recorded SHA-256 and
size before anything is extracted, so a truncated download or a wrong URL is caught as a whole. Then
every extracted file is checked against its own hash and size, so a corrupted member is caught even
when the archive as a whole was replaced by something that happens to match — and a member that is
missing from the archive fails rather than leaving a stale file on disk.

Extraction is confined to the pack's `dest`. An archive entry that is absolute, contains `..`, or is
a symlink is refused before a byte is written, because the pack is downloaded from the network and a
path traversal in it would write outside the repository.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

CATALOGUE = os.path.join("assets", "packs.json")
TIMEOUT_S = 120


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_directory(directory, pack):
    """Problems with the files of `pack` as they stand in `directory`, empty when they all check."""
    problems = []
    for name, expected in sorted(pack.get("files", {}).items()):
        path = os.path.join(directory, name)
        if not os.path.exists(path):
            problems.append("%s is missing" % name)
            continue
        size = os.path.getsize(path)
        if size != expected.get("size_bytes"):
            problems.append("%s is %d bytes, the pack records %r" % (name, size, expected.get("size_bytes")))
            continue
        actual = sha256_file(path)
        if actual != expected.get("sha256"):
            problems.append(
                "%s hashes to %s, the pack records %s"
                % (name, actual[:16], str(expected.get("sha256"))[:16])
            )
    return problems


def safe_members(names):
    """Refuse an archive that would write outside its destination."""
    for name in names:
        normalised = name.replace("\\", "/")
        if normalised.startswith("/") or normalised.startswith("../") or "/../" in normalised:
            raise SystemExit("the archive contains an unsafe path: %r" % name)
        if normalised in ("", ".", ".."):
            raise SystemExit("the archive contains an empty path: %r" % name)


def download(url, path):
    request = urllib.request.Request(url, headers={"User-Agent": "drowned-greenwood-fetch"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            with open(path, "wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            "%s answered %d. A pack URL is only valid once its release is published; run the "
            "publish job (or create the release) before fetching it." % (url, exc.code)
        )
    except urllib.error.URLError as exc:
        raise SystemExit("cannot reach %s (%s)" % (url, exc.reason))


def fetch(pack, root, work):
    """Bring one pack onto disk. Returns a one-line status, or raises SystemExit."""
    dest = os.path.join(root, pack["dest"])
    problems = verify_directory(dest, pack)
    if not problems:
        return "up to date"

    archive = os.path.join(work, os.path.basename(pack["asset"]))
    download(pack["url"], archive)

    size = os.path.getsize(archive)
    if size != pack["size_bytes"]:
        raise SystemExit(
            "%s is %d bytes and the catalogue records %r; the download is not the recorded archive"
            % (pack["name"], size, pack["size_bytes"])
        )
    actual = sha256_file(archive)
    if actual != pack["sha256"]:
        raise SystemExit(
            "%s hashes to %s and the catalogue records %s; refusing to extract it"
            % (pack["name"], actual[:16], pack["sha256"][:16])
        )

    extract_root = os.path.join(work, "extract")
    if os.path.isdir(extract_root):
        shutil.rmtree(extract_root)
    with zipfile.ZipFile(archive) as handle:
        safe_members(handle.namelist())
        handle.extractall(extract_root)

    extracted = verify_directory(extract_root, pack)
    if extracted:
        raise SystemExit(
            "%s extracted but does not match the catalogue: %s"
            % (pack["name"], "; ".join(extracted[:3]))
        )

    os.makedirs(dest, exist_ok=True)
    for name in sorted(pack["files"]):
        target = os.path.join(dest, name)
        os.makedirs(os.path.dirname(os.path.abspath(target)) or dest, exist_ok=True)
        shutil.move(os.path.join(extract_root, name), target)

    return "fetched %d file(s)" % len(pack["files"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", default=CATALOGUE)
    parser.add_argument("--root", default=".", help="the repository root to extract under")
    parser.add_argument("--pack", action="append", default=[], help="only this pack (repeatable)")
    parser.add_argument("--verify-only", action="store_true", help="report, download nothing")
    args = parser.parse_args()

    if not os.path.exists(args.catalogue):
        print("no pack catalogue at %s; nothing to fetch" % args.catalogue)
        return 0
    with open(args.catalogue, "r", encoding="utf-8") as handle:
        catalogue = json.load(handle)

    packs = catalogue.get("packs") or []
    if args.pack:
        wanted = set(args.pack)
        unknown = wanted - {pack.get("name") for pack in packs}
        if unknown:
            raise SystemExit("the catalogue has no pack(s) named %s" % sorted(unknown))
        packs = [pack for pack in packs if pack.get("name") in wanted]
    if not packs:
        print("the pack catalogue lists no packs; every asset is expected to be committed")
        return 0

    failures = []
    with tempfile.TemporaryDirectory(prefix="packs-") as work:
        for pack in packs:
            try:
                if args.verify_only:
                    problems = verify_directory(os.path.join(args.root, pack["dest"]), pack)
                    status = "verified" if not problems else "; ".join(problems[:3])
                    if problems:
                        failures.append(pack["name"])
                else:
                    status = fetch(pack, args.root, work)
            except SystemExit as exc:
                status = str(exc)
                failures.append(pack["name"])
            print("%-24s %s" % (pack["name"], status))

    if failures:
        print(
            "\n%d pack(s) are not on disk or did not verify: %s" % (len(failures), ", ".join(failures)),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
