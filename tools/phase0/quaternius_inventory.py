#!/usr/bin/env python3
"""Inventory the Quaternius animation packs.

Run:
    python3 tools/phase0/quaternius_inventory.py --dir artifacts/phase0/quaternius

The owner uploads the free Standard ZIPs to the release `third-party-quaternius`; CI fetches
them from there, outside git. This unzips them and reports what is really inside, so the
manifest can state a measured clip count instead of a promised one.

An earlier version of this file reported `animation_files=4` and `families_covered=0` at the
same time, which is self-contradictory: if any clip exists, at least one family should match.
It also counted the downloaded ZIP itself as a file and walked the archive alongside its own
extracted copy. Both are fixed here: archives are excluded from the inventory, the extraction
directory is skipped while walking, and every animation file's name is reported so a zero
coverage result can be explained rather than guessed at.
"""

import argparse
import collections
import json
import os
import sys
import zipfile

ANIMATION_SUFFIXES = {".fbx", ".glb", ".gltf", ".bvh", ".blend"}

# The brief's animation families, in the words the manifest uses. A clip counts as covering a
# family when its file name contains one of the family's keywords, case-insensitively. This is
# a heuristic to steer Phase 5, not a validator: a clip called "Climb" matches both the ladder
# and the rope family.
FAMILIES = {
    "anim_idle": ["idle"],
    "anim_walk": ["walk"],
    "anim_run": ["run"],
    "anim_sprint": ["sprint"],
    "anim_crouch": ["crouch"],
    "anim_prone": ["prone", "crawl"],
    "anim_jump_fall_land": ["jump", "fall", "land"],
    "anim_climb_ladder": ["climb", "ladder"],
    "anim_climb_rope": ["climb", "rope"],
    "anim_vault": ["vault"],
    "anim_swim": ["swim"],
    "anim_wade": ["wade"],
    "anim_roll_dodge": ["roll", "dodge"],
    "anim_bow": ["bow", "aim", "draw", "shoot"],
    "anim_crossbow": ["crossbow"],
    "anim_throw": ["throw"],
    "anim_melee_sword": ["sword"],
    "anim_melee_axe": ["axe"],
    "anim_melee_spear": ["spear"],
    "anim_melee_club": ["club"],
    "anim_melee_knife": ["knife", "dagger"],
    "anim_shield_block_parry_shove": ["block", "parry", "shove", "shield"],
    "anim_hit_react": ["hit", "react", "flinch"],
    "anim_stagger": ["stagger"],
    "anim_death": ["death", "die"],
    "anim_interact_open_pickup_loot": ["open", "pick", "pickup", "loot"],
    "anim_skin_animal": ["skin", "skinning"],
    "anim_butcher": ["butcher"],
    "anim_craft_forge": ["craft", "forge", "hammer"],
    "anim_eat_drink_heal": ["eat", "drink", "heal"],
    "anim_light_fire": ["torch", "fire", "light"],
    "anim_set_trap": ["trap", "snare"],
    "anim_build_repair": ["build", "repair"],
    "anim_fish": ["fish"],
    "anim_chop_tree": ["chop", "axe"],
    "anim_mine": ["mine", "pickaxe"],
    "anim_mount_ride": ["mount", "ride", "horse"],
    "anim_sit_sleep": ["sit", "sleep"],
    "anim_shiver_shakeoff": ["shiver", "shake"],
    "anim_emotes": ["wave", "cheer", "taunt", "kneel", "salute", "point", "pray", "dance"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print("RESULT " + json.dumps({"step": "quaternius_inventory", "ok": False, "reason": "directory_missing"}))
        return 1

    root_dir = os.path.abspath(args.dir)
    extract_dir = os.path.join(root_dir, "extracted")

    # Unzip anything still packed, so the inventory sees files rather than archives.
    archives = []
    for root, _dirs, files in os.walk(root_dir):
        for name in files:
            if name.lower().endswith(".zip"):
                archives.append(os.path.join(root, name))
    for archive in archives:
        target = os.path.join(extract_dir, os.path.basename(archive)[:-4])
        os.makedirs(target, exist_ok=True)
        try:
            zipfile.ZipFile(archive).extractall(target)
            print("unzipped %s -> %s" % (os.path.basename(archive), target))
        except zipfile.BadZipFile:
            print("RESULT " + json.dumps({"step": "quaternius_unzip", "ok": False, "archive": archive}))

    # Inventory the extracted content only. Walking the root would count the downloaded ZIP
    # as a file and see every clip twice, once packed and once extracted.
    by_suffix = collections.Counter()
    animation_files = []
    total = 0
    for root, _dirs, files in os.walk(extract_dir):
        for name in files:
            suffix = os.path.splitext(name)[1].lower()
            by_suffix[suffix] += 1
            total += 1
            if suffix in ANIMATION_SUFFIXES:
                animation_files.append(name.lower())

    clips = len(animation_files)
    print("RESULT " + json.dumps({
        "step": "quaternius_packs",
        "ok": clips > 0,
        "archives": len(archives),
        "extracted_files": total,
        "animation_files": clips,
        "suffixes": dict(sorted(by_suffix.items())),
        # Named so a zero-coverage result can be explained instead of guessed at.
        "sample_clips": sorted(animation_files)[:15],
    }))

    covered = {}
    for family, keywords in FAMILIES.items():
        covered[family] = sum(1 for name in animation_files if any(k in name for k in keywords))
    present = sorted(f for f, n in covered.items() if n > 0)
    missing = sorted(f for f, n in covered.items() if n == 0)

    # Coverage is only meaningful once clips exist. With none, the honest answer is "unknown",
    # not "0 of 40 covered": a pack that failed to extract has not proved anything about the
    # clips inside it.
    ok = clips > 0
    print("RESULT " + json.dumps({
        "step": "quaternius_coverage",
        "ok": ok,
        "reason": "" if ok else "no_animation_files_found_after_extraction",
        "families_total": len(FAMILIES),
        "families_covered": len(present),
        "families_missing": len(missing),
        "missing_sample": missing[:12],
    }))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "archives": [os.path.basename(a) for a in archives],
                    "clips": clips,
                    "coverage": covered,
                    "present": present,
                    "missing": missing,
                    "sample_clips": sorted(animation_files)[:50],
                },
                handle,
                indent=2,
                sort_keys=True,
            )
        print("wrote %s" % args.out)

    print("clips found: %d across %d archives" % (clips, len(archives)))
    print("families covered %d of %d" % (len(present), len(FAMILIES)))
    if missing:
        print("missing families: " + ", ".join(missing))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
