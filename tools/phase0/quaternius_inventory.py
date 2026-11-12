#!/usr/bin/env python3
"""Inventory the Quaternius animation packs.

Run:
    python3 tools/phase0/quaternius_inventory.py --dir artifacts/phase0/quaternius

The owner uploads the free Standard ZIPs to the release `third-party-quaternius`; CI fetches
them from there, outside git. This unzips them and reports what is really inside, so the
manifest can state a measured clip count instead of a promised one.

It also reports coverage against the brief's animation list, because "how many clips" is a far
less useful number than "which of the clips we need are missing".
"""

import argparse
import collections
import json
import os
import sys
import zipfile

ANIMATION_SUFFIXES = {".fbx", ".glb", ".gltf", ".bvh", ".blend"}

# The brief's animation families, in the words the manifest uses. A clip counts as covering a
# family when its file name contains one of the family's keywords, case-insensitively.
# This is an approximation and says so: a clip called "Climb" matches both the ladder and the
# rope family. It is a coverage map to steer Phase 5, not a validator.
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


def extract(archive, destination):
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print("RESULT " + json.dumps({"step": "quaternius_inventory", "ok": False, "reason": "directory_missing"}))
        return 1

    # Unzip anything still packed, so the inventory sees files rather than archives.
    archives = []
    for root, _dirs, files in os.walk(args.dir):
        for name in files:
            if name.lower().endswith(".zip"):
                archives.append(os.path.join(root, name))
    for archive in archives:
        target = os.path.join(args.dir, "extracted", os.path.basename(archive)[:-4])
        os.makedirs(target, exist_ok=True)
        try:
            extract(archive, target)
            print("unzipped %s -> %s" % (os.path.basename(archive), target))
        except zipfile.BadZipFile:
            print("RESULT " + json.dumps({"step": "quaternius_unzip", "ok": False, "archive": archive}))

    by_suffix = collections.Counter()
    animation_files = []
    total = 0
    for root, _dirs, files in os.walk(args.dir):
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
        "files": total,
        "animation_files": clips,
        "suffixes": dict(sorted(by_suffix.items())),
    }))

    # Which of the brief's families the packs actually cover.
    covered = {}
    for family, keywords in FAMILIES.items():
        hits = sum(1 for name in animation_files if any(k in name for k in keywords))
        covered[family] = hits
    present = sorted(f for f, n in covered.items() if n > 0)
    missing = sorted(f for f, n in covered.items() if n == 0)

    print("RESULT " + json.dumps({
        "step": "quaternius_coverage",
        "ok": len(present) > 0,
        "families_total": len(FAMILIES),
        "families_covered": len(present),
        "families_missing": len(missing),
        "missing_sample": missing[:12],
    }))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"coverage": covered, "clips": clips, "present": present, "missing": missing},
                      handle, indent=2, sort_keys=True)
        print("wrote %s" % args.out)

    print("clips found: %d across %d archives" % (clips, len(archives)))
    print("families covered %d of %d" % (len(present), len(FAMILIES)))
    if missing:
        print("missing families: " + ", ".join(missing))
    return 0 if clips > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
