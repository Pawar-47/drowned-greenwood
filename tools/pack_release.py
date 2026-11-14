#!/usr/bin/env python3
"""Pack a finished asset category into one versioned ZIP, and record it in the catalogue.

Run:
    python tools/pack_release.py --source assets/terrain --category terrain --version 1.3.0 \
        --out /tmp/terrain.zip --entry /tmp/pack.json
    python tools/pack_release.py --record /tmp/pack.json --catalogue assets/packs.json

Why a pack rather than a commit: a binary in git is permanent. Deleting it in a later commit
leaves the blob in history, so the clone stays heavy and the only way back is a force-push
(`docs/HISTORY_PURGE.md`). A pack is one file on a Release, versioned by the generator version that
produced it, and the repository carries only the catalogue entry: a link, a hash and a size.

The ZIP is deterministic. Two runs over the same bytes produce the same archive, so the recorded
SHA-256 is a statement about the content rather than about the moment it was written. That means a
fixed timestamp, sorted entries and no directory entries — an archive whose mtimes came from the
filesystem would hash differently on every runner and make "did this change?" unanswerable.

The catalogue, not the archive, is the contract. Each entry carries the archive's hash and size and
a hash and size for every file inside it, so `tools/fetch_packs.py` can reject a truncated download
and a single corrupted texel separately.
"""

import argparse
import hashlib
import json
import os
import sys
import zipfile

SCHEMA_VERSION = 1

# The earliest timestamp a ZIP can express. Fixed, because the archive must be byte-identical
# across runs and machines.
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# Directory names that never carry an asset. `__pycache__` appears under a generator's output
# directory the moment anything imports from it.
SKIP_DIRS = {"__pycache__", ".git", ".godot"}

DEFAULT_RELEASE_BASE = "https://github.com/Pawar-47/drowned-greenwood/releases/download"

CATALOGUE_DESCRIPTION = (
    "The binary assets this repository carries as versioned ZIP packs on GitHub Releases instead "
    "of in git. Each pack records the archive's SHA-256 and size and a hash and size for every file "
    "inside it, so a download is verified twice: once as an archive and once as the files that land "
    "on disk. The paths inside `dest` are the same paths assets/built.json names, so a packed asset "
    "and a committed one are one path to every consumer — the only difference is who put the bytes "
    "there. tools/fetch_packs.py downloads and verifies; tools/pack_release.py builds a pack and "
    "records it here; tools/validate/check_packs.py holds this file to its contract."
)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect(source):
    """Every file under `source`, as relative paths, sorted.

    Sorted because the archive must be deterministic; relative because the archive holds the
    category's files at its root, not at `assets/terrain/...`, so extracting it into `dest` puts
    them where `built.json` already says they are.
    """
    names = []
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = os.path.join(root, name)
            names.append(os.path.relpath(path, source).replace(os.sep, "/"))
    return sorted(names)


def write_zip(source, names, out):
    """The archive, byte-identical across runs: sorted, fixed timestamp, no directory entries."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            with open(os.path.join(source, name), "rb") as handle:
                archive.writestr(info, handle.read())
    return out


def build_entry(source, names, category, version, dest, release_base, archive):
    """The catalogue entry for an archive.

    The asset name is the archive's own file name, because that is what GitHub serves: `gh release
    upload` names the asset after the file it was given, so a catalogue that invented a different
    name would record a URL that 404s. That is exactly how the first publish run failed — the pack
    was written to `terrain.zip` while the catalogue pointed at `terrain-1.3.0.zip`.
    """
    tag = "assets-%s-%s" % (category, version)
    asset = os.path.basename(archive)
    if not asset:
        raise SystemExit("the archive path %r has no file name to use as the release asset" % archive)
    return {
        "name": "%s-%s" % (category, version),
        "category": category,
        "version": version,
        "tag": tag,
        "asset": asset,
        "url": "%s/%s/%s" % (release_base.rstrip("/"), tag, asset),
        "sha256": sha256_file(archive),
        "size_bytes": os.path.getsize(archive),
        "dest": dest,
        "files": {
            name: {
                "sha256": sha256_file(os.path.join(source, name)),
                "size_bytes": os.path.getsize(os.path.join(source, name)),
            }
            for name in names
        },
    }


def empty_catalogue(release_base):
    return {
        "schema_version": SCHEMA_VERSION,
        "name": "packs",
        "description": CATALOGUE_DESCRIPTION,
        "release_base": release_base,
        "packs": [],
    }


def load_catalogue(path, release_base):
    if not os.path.exists(path):
        return empty_catalogue(release_base)
    with open(path, "r", encoding="utf-8") as handle:
        catalogue = json.load(handle)
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("packs"), list):
        raise SystemExit("%s is not a pack catalogue: it has no `packs` list" % path)
    return catalogue


def merge_pack(catalogue, entry):
    """Replace a pack of the same name, or add it. Sorted by name so the file diffs cleanly."""
    packs = [pack for pack in catalogue["packs"] if pack.get("name") != entry["name"]]
    packs.append(entry)
    catalogue["packs"] = sorted(packs, key=lambda pack: pack.get("name", ""))
    return catalogue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="", help="the directory to pack")
    parser.add_argument("--category", default="", help="the asset category, e.g. terrain")
    parser.add_argument("--version", default="", help="the version the pack is tagged with")
    parser.add_argument("--dest", default="", help="where the pack extracts, default assets/<category>")
    parser.add_argument("--release-base", default=DEFAULT_RELEASE_BASE)
    parser.add_argument("--out", default="", help="the ZIP to write")
    parser.add_argument("--entry", default="", help="write the catalogue entry to this JSON file")
    parser.add_argument("--catalogue", default="assets/packs.json")
    parser.add_argument(
        "--record",
        default="",
        help="merge this entry JSON into the catalogue instead of building an archive",
    )
    args = parser.parse_args()

    if args.record:
        with open(args.record, "r", encoding="utf-8") as handle:
            entry = json.load(handle)
        catalogue = load_catalogue(args.catalogue, args.release_base)
        catalogue["release_base"] = args.release_base.rstrip("/")
        merge_pack(catalogue, entry)
        with open(args.catalogue, "w", encoding="utf-8") as handle:
            json.dump(catalogue, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(
            "recorded %s in %s (%d pack(s))"
            % (entry["name"], args.catalogue, len(catalogue["packs"]))
        )
        return 0

    if not args.source or not args.category or not args.version or not args.out:
        parser.error("--source, --category, --version and --out are required when not recording")
    if not os.path.isdir(args.source):
        raise SystemExit("%s is not a directory" % args.source)

    names = collect(args.source)
    if not names:
        raise SystemExit("%s holds no files, so there is nothing to pack" % args.source)

    write_zip(args.source, names, args.out)
    entry = build_entry(
        args.source,
        names,
        args.category,
        args.version,
        args.dest or ("assets/" + args.category),
        args.release_base,
        args.out,
    )

    if args.entry:
        with open(args.entry, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, indent=2, sort_keys=True)
            handle.write("\n")

    print(
        "packed %s: %d files, %.1f MB, sha256 %s"
        % (entry["name"], len(names), entry["size_bytes"] / (1024 * 1024), entry["sha256"][:16])
    )
    print("url: %s" % entry["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
