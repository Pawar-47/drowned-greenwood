#!/usr/bin/env python3
"""Inventory the Quaternius animation packs by reading the animations inside them.

Run:
    python3 tools/phase0/quaternius_inventory.py --dir artifacts/phase0/quaternius

Why this reads GLB internals instead of counting files:

An earlier version counted files ending in .fbx/.glb/.gltf as "clips". That was wrong in both
directions. The Quaternius archive holds `ual1_standard.glb` and `ual1_standard_rm.glb` — whole
animation libraries in single containers — so a file count reports 4 for a pack containing
hundreds of clips, and the FBX and GLB copies of the same library are counted twice.

A GLB is a binary container: a 12-byte header, then length-prefixed chunks whose first is JSON.
So the animation list is readable with the standard library alone, no Blender and no glTF
dependency. This reports:

  * the actual animation names in every GLB, deduplicated across format variants
  * which of the brief's animation families those names cover
  * the clip count, which is the number the project actually needs

FBX is not parsed: its binary layout is not worth hand-decoding, and the GLB in the same pack
carries the same clips. FBX is reported as present-but-unread, never as a clip count.
"""

import argparse
import collections
import json
import os
import struct
import sys
import zipfile

# Keywords per animation family, used to decide whether a clip covers it. This is a *lookup*,
# not the list of families: the list is read from the manifest (see load_families), because a
# hardcoded list drifts. It already did — the inventory once carried 40 families while the
# manifest had 41, so one family was silently never measured.
#
# A family with no entry here falls back to keywords derived from its own name, so adding an
# animation to the manifest is enough for it to be measured.
FAMILY_KEYWORDS = {
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
    "anim_ragdoll_pose": ["ragdoll"],
    "anim_interact_open_pickup_loot": ["open", "pick", "pickup", "loot"],
    "anim_skin_animal": ["skin", "skinning"],
    "anim_butcher": ["butcher"],
    "anim_craft_forge": ["craft", "forge", "hammer"],
    "anim_eat_drink_heal": ["eat", "drink", "heal"],
    "anim_light_fire": ["torch", "fire", "light"],
    "anim_set_trap": ["trap", "snare"],
    "anim_build_repair": ["build", "repair"],
    "anim_fish": ["fish"],
    "anim_chop_tree": ["chop"],
    "anim_mine": ["mine", "pickaxe"],
    "anim_mount_ride": ["mount", "ride", "horse"],
    "anim_sit_sleep": ["sit", "sleep"],
    "anim_shiver_shakeoff": ["shiver", "shake"],
    "anim_emotes": ["wave", "cheer", "taunt", "kneel", "salute", "point", "pray", "dance"],
}

MANIFEST = "assets/manifest.json"


def load_families(manifest_path=MANIFEST):
    """Read the animation families from the manifest and attach keywords to each.

    Returns (families, notes). `families` maps family name -> keyword list. `notes` describes
    anything that fell back or failed, so a silent gap becomes a visible one.
    """
    notes = []
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        notes.append("manifest unreadable (%s); using the keyword table alone" % exc)
        return dict(FAMILY_KEYWORDS), notes

    declared = []
    for group in manifest.get("categories", {}).values():
        for raw in group.get("assets", []):
            name = raw.split("|")[0]
            if name.startswith("anim_") and name not in declared:
                declared.append(name)

    if not declared:
        notes.append("no anim_* assets in the manifest; using the keyword table alone")
        return dict(FAMILY_KEYWORDS), notes

    families = {}
    for family in declared:
        keywords = FAMILY_KEYWORDS.get(family)
        if not keywords:
            # anim_melee_sword -> ["melee", "sword"]: better than not measuring it at all.
            keywords = [part for part in family.split("_") if part != "anim"]
            notes.append("%s has no keywords; derived %s from its name" % (family, keywords))
        families[family] = keywords

    # A keyword entry with no matching manifest asset is stale: it measures nothing.
    unused = sorted(set(FAMILY_KEYWORDS) - set(declared))
    if unused:
        notes.append("keyword entries with no manifest family: %s" % unused)

    return families, notes


GLB_MAGIC = b"glTF"
CHUNK_JSON = 0x4E4F534A


def glb_animation_names(path):
    """Return the animation names in a GLB, or None if it cannot be parsed.

    GLB layout: 12-byte header (magic, version, total length), then chunks of
    (uint32 length, uint32 type, data). The first chunk is the glTF JSON.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(12)
            if len(header) < 12:
                return None
            magic, _version, _total = struct.unpack("<4sII", header)
            if magic != GLB_MAGIC:
                return None

            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                return None
            chunk_length, chunk_type = struct.unpack("<II", chunk_header)
            if chunk_type != CHUNK_JSON:
                return None

            payload = handle.read(chunk_length)
            document = json.loads(payload.decode("utf-8").rstrip("\x00 "))
    except (OSError, ValueError, struct.error):
        return None

    animations = document.get("animations") or []
    names = []
    for index, animation in enumerate(animations):
        names.append(animation.get("name") or "unnamed_%d" % index)
    return names


def extract_archives(root_dir, extract_dir):
    """Unzip anything still packed. Returns the archives found."""
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
    return archives


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument(
        "--extract-dir",
        default="",
        help="where to unzip; keep this OUTSIDE the artifact directory so the libraries "
        "are not uploaded (default: <dir>/extracted)",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print("RESULT " + json.dumps(
            {"step": "quaternius_inventory", "ok": False, "reason": "directory_missing"}))
        return 1

    root_dir = os.path.abspath(args.dir)
    extract_dir = os.path.abspath(args.extract_dir) if args.extract_dir else os.path.join(root_dir, "extracted")
    archives = extract_archives(root_dir, extract_dir)

    # Read the animations out of every GLB. GLB only: FBX is not parsed, and reporting an FBX
    # file as "one clip" is the mistake this script exists to stop making.
    clips_by_source = {}
    fbx_files = []
    for root, _dirs, files in os.walk(extract_dir):
        for name in files:
            path = os.path.join(root, name)
            lower = name.lower()
            if lower.endswith(".glb") or lower.endswith(".gltf"):
                names = glb_animation_names(path)
                if names is None:
                    print("could not parse %s; not counted" % name)
                    continue
                clips_by_source[name] = names
            elif lower.endswith(".fbx"):
                fbx_files.append(name)

    # A pack ships the same library as .glb and as _rm.glb; the animation sets are identical.
    # Deduplicate by name so the clip count is a count of clips, not of containers.
    all_clips = set()
    for names in clips_by_source.values():
        all_clips.update(names)
    clip_list = sorted(all_clips)

    print("RESULT " + json.dumps({
        "step": "quaternius_packs",
        "ok": len(clip_list) > 0,
        "archives": len(archives),
        "glb_containers": len(clips_by_source),
        "fbx_files_unread": len(fbx_files),
        "clips": len(clip_list),
        "per_container": {k: len(v) for k, v in sorted(clips_by_source.items())},
        "sample_clips": clip_list[:20],
    }))

    # Families come from the manifest, not from a hardcoded list, so adding an animation to
    # the manifest is enough for it to be measured here. `family_notes` reports anything that
    # fell back to derived keywords, so a gap is visible rather than silent.
    families, family_notes = load_families()
    for note in family_notes:
        print("note: " + note)

    covered = {}
    for family, keywords in families.items():
        covered[family] = sum(1 for name in clip_list if any(k in name.lower() for k in keywords))
    present = sorted(f for f, n in covered.items() if n > 0)
    missing = sorted(f for f, n in covered.items() if n == 0)

    # "PASS" was too generous: it only meant at least one clip existed, so 16 of 41 families
    # reported PASS. Coverage gets its own three-state answer, and the probe passes only when
    # the measurement itself worked — the state says how complete the pack is.
    if len(clip_list) == 0:
        coverage_state = "unknown"
        reason = "no_clips_found_in_any_glb"
    elif len(missing) == 0:
        coverage_state = "complete"
        reason = ""
    else:
        coverage_state = "partial"
        reason = ""

    print("RESULT " + json.dumps({
        "step": "quaternius_coverage",
        "ok": len(clip_list) > 0,
        "coverage": coverage_state,
        "reason": reason,
        "families_total": len(families),
        "families_covered": len(present),
        "families_missing": len(missing),
        "missing": missing,
        "note": "name-keyword matching, not semantic: Pistol_Aim counts as a bow aim",
    }))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "archives": [os.path.basename(a) for a in archives],
                    "clips": len(clip_list),
                    "clip_names": clip_list,
                    "per_container": {k: len(v) for k, v in sorted(clips_by_source.items())},
                    "fbx_unread": fbx_files,
                    "coverage_state": coverage_state,
                    "coverage": covered,
                    "present": present,
                    "missing": missing,
                },
                handle,
                indent=2,
                sort_keys=True,
            )
        print("wrote %s" % args.out)

    print("clips found: %d across %d GLB containers" % (len(clip_list), len(clips_by_source)))
    print("coverage %s: %d of %d families" % (coverage_state, len(present), len(families)))
    if missing:
        print("missing families: " + ", ".join(missing))
    return 0 if len(clip_list) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
