#!/usr/bin/env python3
"""Zip a Blender 4.2+ extension so `blender --command extension install-file` accepts it.

    python3 tools/phase0/zip_extension.py <source_dir> <output.zip>

`install-file` requires the archive to hold exactly one top-level folder containing
`blender_manifest.toml`. Repositories lay themselves out differently — Modular Tree keeps the
manifest at its root, MPFB2 keeps it at `src/mpfb/` — so the manifest is found rather than
assumed, and the folder inside the zip is named after the manifest's `id`, which is the name
Blender will install it under.

Why this exists as a script: the same logic was duplicated as an inline heredoc in the workflow
for one extension, and would have been pasted again for the second. One implementation means one
place for it to be wrong.
"""

import os
import re
import sys
import zipfile


def find_manifest(source_dir):
    """Shallowest blender_manifest.toml under source_dir."""
    candidates = []
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
        if "blender_manifest.toml" in files:
            depth = root[len(source_dir):].count(os.sep)
            candidates.append((depth, root))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def read_id(manifest_path):
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(r'^\s*id\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def main():
    if len(sys.argv) != 3:
        print("usage: zip_extension.py <source_dir> <output.zip>", file=sys.stderr)
        return 2

    source_dir, output = sys.argv[1], sys.argv[2]
    if not os.path.isdir(source_dir):
        print("source directory missing: %s" % source_dir, file=sys.stderr)
        return 1

    extension_root = find_manifest(source_dir)
    if extension_root is None:
        print("no blender_manifest.toml under %s" % source_dir, file=sys.stderr)
        return 1

    manifest = os.path.join(extension_root, "blender_manifest.toml")
    extension_id = read_id(manifest)
    if not extension_id:
        print("no id in %s" % manifest, file=sys.stderr)
        return 1

    if os.path.exists(output):
        os.remove(output)

    count = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(extension_root):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
            for name in files:
                path = os.path.join(root, name)
                relative = os.path.relpath(path, extension_root)
                archive.write(path, os.path.join(extension_id, relative))
                count += 1

    print(
        "zipped %s (id=%s) -> %s: %d files, %d bytes"
        % (extension_root, extension_id, output, count, os.path.getsize(output))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
