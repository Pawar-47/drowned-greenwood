#!/usr/bin/env python3
"""Inventory a Quaternius animation pack directory.

Run:
    python3 tools/phase0/quaternius_inventory.py --dir artifacts/phase0/quaternius

The owner downloads the free Standard ZIPs manually and uploads them to the Release
`third-party-quaternius`; CI fetches them from there. This prints what is really in the packs
so the report can state a real clip count instead of a promised one.
"""

import argparse
import collections
import os
import sys

ANIMATION_SUFFIXES = {".fbx", ".glb", ".gltf", ".bvh", ".blend"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print("RESULT quaternius_inventory ok=False reason=directory_missing")
        return 1

    by_suffix = collections.Counter()
    by_pack = collections.Counter()
    total = 0
    for root, _dirs, files in os.walk(args.dir):
        for name in files:
            suffix = os.path.splitext(name)[1].lower()
            by_suffix[suffix] += 1
            by_pack[os.path.basename(root)] += 1
            total += 1

    clips = sum(count for suffix, count in by_suffix.items() if suffix in ANIMATION_SUFFIXES)
    print(
        "RESULT quaternius_inventory ok=True files=%d animation_files=%d"
        % (total, clips)
    )
    for suffix, count in sorted(by_suffix.items()):
        print("  %-8s %d" % (suffix or "(none)", count))
    for pack, count in sorted(by_pack.items()):
        print("  %-40s %d" % (pack, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
