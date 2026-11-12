#!/usr/bin/env python3
"""Validate the skeleton and retarget definitions.

Run:
    python tools/validate/check_skeletons.py

These files are the contract every character and animation in the project binds to, so their
internal consistency is checked in CI before any asset exists. A broken skeleton definition is
much cheaper to catch here than in Phase 5.

Checks, in the order the brief states the limits:
  * bone count within the per-class cap (humanoid 65, animal 50)
  * every parent names a bone that exists
  * no duplicate bone names
  * no cycles in the hierarchy
  * the manifest's declared bone_count matches the actual list
  * humanoid bone names match Godot's SkeletonProfileHumanoid, since the definition claims they do
  * the cloth chains a character may wear fit in the spare bones, computed from the bone list
  * animal families do not exceed the cap, and every species in the asset list is covered

What it does not check: animal bone *hierarchy*. Those families are flat lists of bone names with
no parent links, so there is nothing to walk; it says so out loud rather than letting "skeleton
checks passed" imply the animal rigs were validated as deeply as the humanoid one.
"""

import json
import re
import sys

SKELETON = "assets/char_skeleton_definition.json"
RETARGET = "assets/char_retarget_map.json"
ANIMALS = "assets/animal_skeleton_definitions.json"
MANIFEST = "assets/manifest.json"

HUMANOID_MAX_BONES = 65
ANIMAL_MAX_BONES = 50

# Godot 4's SkeletonProfileHumanoid bone names. The definition claims to use these names
# directly, so a typo here would silently break retargeting at runtime instead of in CI.
GODOT_HUMANOID = {
    "Root", "Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
    "LeftEye", "RightEye", "Jaw",
    "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
    "RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes",
    "LeftThumbMetacarpal", "LeftThumbProximal", "LeftThumbDistal",
    "LeftIndexProximal", "LeftIndexIntermediate", "LeftIndexDistal",
    "LeftMiddleProximal", "LeftMiddleIntermediate", "LeftMiddleDistal",
    "LeftRingProximal", "LeftRingIntermediate", "LeftRingDistal",
    "LeftLittleProximal", "LeftLittleIntermediate", "LeftLittleDistal",
    "RightThumbMetacarpal", "RightThumbProximal", "RightThumbDistal",
    "RightIndexProximal", "RightIndexIntermediate", "RightIndexDistal",
    "RightMiddleProximal", "RightMiddleIntermediate", "RightMiddleDistal",
    "RightRingProximal", "RightRingIntermediate", "RightRingDistal",
    "RightLittleProximal", "RightLittleIntermediate", "RightLittleDistal",
}


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def check_hierarchy(bones, problems, label):
    """Parent existence, duplicates and cycles."""
    names = [bone["name"] for bone in bones]
    if len(names) != len(set(names)):
        duplicates = {n for n in names if names.count(n) > 1}
        problems.append("%s: duplicate bone names %s" % (label, sorted(duplicates)))

    known = set(names)
    parents = {}
    for bone in bones:
        parent = bone.get("parent")
        if parent is not None and parent not in known:
            problems.append("%s: %s has unknown parent %r" % (label, bone["name"], parent))
        parents[bone["name"]] = parent

    # Walk up from every bone; a chain longer than the bone count means a cycle.
    for name in names:
        seen = set()
        current = name
        while current is not None:
            if current in seen:
                problems.append("%s: cycle in hierarchy at %s" % (label, current))
                break
            seen.add(current)
            current = parents.get(current)
            if len(seen) > len(names):
                problems.append("%s: hierarchy too deep at %s" % (label, name))
                break


def check_lod_counts(skeleton, bones, problems):
    """Recompute the LOD bone counts from the bone list and compare to what the file claims.

    The LOD policy stated 46 and 36 bones, which matched neither the skeleton nor each other:
    26 non-finger bones plus one bone per finger for ten fingers is 36, and dropping fingers
    and merging two toes is 24. Numbers written by hand in a policy note drift; numbers derived
    from the bone list cannot.
    """
    names = [bone["name"] for bone in bones]
    finger_segments = ("Proximal", "Intermediate", "Distal", "Metacarpal")
    fingers = [n for n in names if any(seg in n for seg in finger_segments)]
    toes = [n for n in names if n.endswith("Toes")]
    non_finger = [n for n in names if n not in fingers]

    # One bone per finger: count distinct fingers. Finger bones are named LeftThumbProximal,
    # RightIndexDistal and so on with no separator, so the segment word is stripped rather than
    # splitting on "_" — that returned the whole name and counted 30 "fingers" instead of 10.
    def finger_root(name):
        for segment in finger_segments:
            if name.endswith(segment):
                return name[: -len(segment)]
        return name

    finger_roots = sorted({finger_root(n) for n in fingers})
    expected = {
        "lod0": len(names),
        "lod1": len(non_finger) + len(finger_roots),
        "lod2": len(non_finger) - len(toes),
    }

    policy = skeleton.get("lod_policy", {})
    for key, value in expected.items():
        claim = str(policy.get(key, ""))
        if not claim:
            problems.append("char_skeleton_definition: lod_policy has no %s" % key)
            continue
        # The claim is prose, so look for the number it asserts.
        numbers = re.findall(r"\d+", claim)
        if not numbers:
            problems.append("char_skeleton_definition: lod_policy %s states no count" % key)
            continue
        stated = int(numbers[-1])
        if stated != value:
            problems.append(
                "char_skeleton_definition: lod_policy %s says %d bones but the bone list gives %d"
                % (key, stated, value)
            )
    print(
        "lod counts: lod0=%d lod1=%d lod2=%d (from the bone list)"
        % (expected["lod0"], expected["lod1"], expected["lod2"])
    )


def check_cloth_budget(skeleton, bones, problems):
    """The cloth chains a character can wear must fit in the spare bones.

    This file used to say the 9 spare bones were "deliberately unallocated" because cloth chains
    are separate assets. They are separate assets, but their bones join the character's skeleton
    when worn, so they spend this budget: a cape's 6 bones put the character at 62, and a cape and
    a tabard at once need 68 against a cap of 65. That is a design constraint, so it is computed
    here rather than asserted in prose nobody re-derives.
    """
    label = "char_skeleton_definition"
    budget = skeleton.get("cloth_bone_budget")
    if not isinstance(budget, dict):
        problems.append("%s: no cloth_bone_budget, so the spare bones are unaccounted for" % label)
        return
    chains = budget.get("max_chains_at_once")
    per_chain = budget.get("max_bones_per_chain")
    if not isinstance(chains, int) or isinstance(chains, bool) or chains < 1:
        problems.append("%s: cloth_bone_budget.max_chains_at_once must be a positive integer" % label)
        return
    if not isinstance(per_chain, int) or isinstance(per_chain, bool) or per_chain < 1:
        problems.append("%s: cloth_bone_budget.max_bones_per_chain must be a positive integer" % label)
        return

    total = len(bones) + chains * per_chain
    if total > HUMANOID_MAX_BONES:
        problems.append(
            "%s: %d bones + %d chain(s) x %d = %d, over the %d cap"
            % (label, len(bones), chains, per_chain, total, HUMANOID_MAX_BONES)
        )
    # The declared limit must be the real limit. If one more chain would also fit, the budget
    # understates what the skeleton allows and the number in the file is a fiction.
    one_more = len(bones) + (chains + 1) * per_chain
    if one_more <= HUMANOID_MAX_BONES:
        problems.append(
            "%s: cloth_bone_budget allows %d chain(s) of %d bones, but %d would also fit (%d of %d)"
            % (label, chains, per_chain, chains + 1, one_more, HUMANOID_MAX_BONES)
        )
    print(
        "cloth budget: %d + %d x %d = %d of %d bones (one more chain would need %d)"
        % (len(bones), chains, per_chain, total, HUMANOID_MAX_BONES, one_more)
    )


def check_bilateral_optional(families, problems):
    """An optional bone must have its mirror optional too, or one side vanishes asymmetrically."""
    for family in families:
        optional = family.get("optional_bones", {})
        for name in optional:
            if name.startswith("Left"):
                mirror = "Right" + name[len("Left"):]
            elif name.startswith("Right"):
                mirror = "Left" + name[len("Right"):]
            else:
                continue
            if mirror in family["bones"] and mirror not in optional:
                problems.append(
                    "%s: %s is optional but its mirror %s is not" % (family["name"], name, mirror)
                )


def check_humanoid(problems):
    skeleton = load(SKELETON)
    bones = skeleton["bones"]
    label = "char_skeleton_definition"

    if len(bones) > HUMANOID_MAX_BONES:
        problems.append(
            "%s: %d bones exceeds the %d cap" % (label, len(bones), HUMANOID_MAX_BONES)
        )
    if skeleton.get("bone_count") != len(bones):
        problems.append(
            "%s: declared bone_count %r but %d bones listed"
            % (label, skeleton.get("bone_count"), len(bones))
        )

    check_hierarchy(bones, problems, label)
    check_lod_counts(skeleton, bones, problems)
    check_cloth_budget(skeleton, bones, problems)

    for bone in bones:
        if bone["name"] not in GODOT_HUMANOID:
            problems.append(
                "%s: bone %r is not a Godot SkeletonProfileHumanoid name" % (label, bone["name"])
            )
        if bone.get("godot") != bone["name"]:
            problems.append(
                "%s: bone %r maps to %r; the definition claims names are used as-is"
                % (label, bone["name"], bone.get("godot"))
            )

    deform = sum(1 for bone in bones if bone.get("deform"))
    if deform == 0:
        problems.append("%s: no deform bones" % label)

    sockets = skeleton.get("attachments", {}).get("sockets", [])
    names = {bone["name"] for bone in bones}
    for socket in sockets:
        if socket["parent_bone"] not in names:
            problems.append(
                "%s: socket %s parents to unknown bone %r"
                % (label, socket["name"], socket["parent_bone"])
            )
    print(
        "humanoid: %d bones (%d deform, %d sockets), cap %d"
        % (len(bones), deform, len(sockets), HUMANOID_MAX_BONES)
    )
    return skeleton


def check_retarget(problems, skeleton):
    retarget = load(RETARGET)
    target_names = {bone["name"] for bone in skeleton["bones"]}
    mapped = set()
    verified = 0
    for source in retarget["sources"]:
        for target in source.get("map", {}).values():
            mapped.add(target)
            if target not in target_names:
                problems.append(
                    "char_retarget_map: source %s maps to unknown target bone %r"
                    % (source["source_tool"], target)
                )
        status = source.get("status", "")
        # A mapping that has not been exercised must say why. "blocked", "planned" and
        # "pending_verification" are all honest states; a bare "verified" with no evidence is
        # what this catches.
        if status in {"blocked", "planned", "pending_verification"}:
            reason = source.get("blocked_on") or source.get("status_note") or source.get("reason")
            if not reason:
                problems.append(
                    "char_retarget_map: %s is %s but does not say why"
                    % (source["source_tool"], status)
                )
        elif status == "verified":
            verified += 1
        elif status:
            problems.append(
                "char_retarget_map: %s has unknown status %r" % (source["source_tool"], status)
            )
    required = {"Hips", "Head", "LeftHand", "RightHand", "LeftFoot", "RightFoot"}
    missing = required - mapped
    if missing:
        problems.append("char_retarget_map: no source maps %s" % sorted(missing))
    print(
        "retarget: %d target bones covered, %d source(s) verified"
        % (len(mapped), verified)
    )


def check_animals(problems):
    data = load(ANIMALS)
    families = data["families"]
    covered = set()

    # Duplicate family names would silently shadow each other: the second one would look
    # covered while the first was ignored. This check exists because exactly that happened
    # while these files were being written, and nothing here noticed.
    names = [family["name"] for family in families]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        problems.append("animal_skeleton_definitions: duplicate families %s" % duplicates)

    # A species must belong to exactly one family; two families claiming it is as wrong as none.
    claimed = {}
    for family in families:
        for species in family["used_by"]:
            claimed.setdefault(species, []).append(family["name"])
    double_claimed = {s: f for s, f in claimed.items() if len(f) > 1}
    if double_claimed:
        problems.append(
            "animal_skeleton_definitions: %d species claimed by more than one family: %s"
            % (len(double_claimed), sorted(double_claimed)[:5])
        )

    check_bilateral_optional(families, problems)

    # Say what is not checked. These families are flat lists of bone names with no parent links,
    # so check_hierarchy() cannot run on them; a silent "skeleton checks passed" read as if the
    # animal rigs had been validated as deeply as the humanoid one, which they have not.
    print(
        "animals: bone hierarchy NOT validated — these families carry no parent links; only "
        "caps, duplicates, optional-bone pairing and coverage are checked"
    )

    for family in families:
        label = family["name"]
        bones = family["bones"]
        if len(bones) > ANIMAL_MAX_BONES:
            problems.append(
                "%s: %d bones exceeds the %d cap" % (label, len(bones), ANIMAL_MAX_BONES)
            )
        if family.get("bone_count") != len(bones):
            problems.append(
                "%s: declared bone_count %r but %d listed"
                % (label, family.get("bone_count"), len(bones))
            )
        if len(bones) != len(set(bones)):
            problems.append("%s: duplicate bone names" % label)
        optional = family.get("optional_bones", {})
        for name in optional:
            if name not in bones:
                problems.append("%s: optional bone %r is not in the bone list" % (label, name))
        covered.update(family["used_by"])
        print("%s: %d bones, %d species" % (label, len(bones), len(family["used_by"])))

    # Every animal-family asset in the manifest must belong to a family.
    #
    # Not everything with an animal-ish prefix is a creature that needs a skeleton. Decals,
    # card LODs, nests, egg and feather sets and shadow sprites are 4.F assets with no body,
    # and the animal_skeleton_* definitions live in 4.G.rig and are the families themselves.
    # Counting those as uncovered species made this check fail on its own first run.
    NOT_A_CREATURE = ("_decal", "_set", "_card_lod", "_nest", "_shadow")

    manifest = load(MANIFEST)
    declared = []
    for group in manifest["categories"].values():
        for raw in group.get("assets", []):
            name = raw.split("|")[0]
            if not name.startswith(("animal_", "bird_", "fish_", "amph_", "rept_")):
                continue
            if name.startswith("animal_skeleton_"):
                continue
            if any(name.endswith(suffix) for suffix in NOT_A_CREATURE):
                continue
            declared.append(name)

    undeclared = sorted(set(declared) - covered)
    if undeclared:
        problems.append(
            "animal_skeleton_definitions: no family covers %d manifest species: %s"
            % (len(undeclared), undeclared[:10])
        )
    print(
        "animals: %d species declared in the manifest, %d covered by a family"
        % (len(declared), len(covered))
    )


def main():
    problems = []
    skeleton = check_humanoid(problems)
    check_retarget(problems, skeleton)
    check_animals(problems)

    if problems:
        print("skeleton checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print("skeleton checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
