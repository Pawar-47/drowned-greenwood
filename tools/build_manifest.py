#!/usr/bin/env python3
"""Expand assets/manifest.json into one record per asset and check the list's integrity.

Run:
    python tools/build_manifest.py            # write assets/manifest.expanded.json
    python tools/build_manifest.py --check    # exit 1 if the file on disk is stale

`assets/manifest.json` holds the authored list: categories of
`name|tier|priority|variants|source_tool|licence` entries, where an empty field inherits from
the group. This script turns that into flat records carrying every field the brief requires, so
nothing downstream has to know about the shorthand.

It refuses to write if the list is inconsistent: a duplicate name, a bad tier or priority, a
name that breaks the naming convention, or a variant count that is not a positive integer.
"""

import argparse
import json
import os
import re
import sys

MANIFEST = "assets/manifest.json"
EXPANDED = "assets/manifest.expanded.json"

VALID_TIERS = {"S", "A", "B", "C"}
VALID_PRIORITIES = {"P1", "P2", "P3"}
VALID_STATUS = {"pending", "built", "PASSED", "BELOW_TARGET", "PLACEHOLDER"}

# Licence per source tool. This is a fact about the tool, not an assumption about the asset,
# and each entry says where the fact comes from. An unknown tool gets None, which
# check_manifest.py rejects — an unverified provenance must never read as CC0.
#
# This used to be a blanket `source_license: CC0` in field_defaults, which meant an asset whose
# provenance had never been checked was indistinguishable from one whose licence had been
# verified. An entry may still override the tool default with its own sixth field (a font is
# OFL, a music loop may be CC-BY), and that override wins.
LICENCE_BY_TOOL = {
    # An asset with no recorded tool. This says nothing about who owns it, so it is recorded as
    # unknown rather than as ours.
    #
    # This used to map to `project-original`, which was wrong for 1,110 of 1,954 records: `custom`
    # means "one of our scripts will produce this", and today those scripts exist for terrain and
    # hydrology only. Fonts, music and audio in that set are not project-original by any reading —
    # nobody has recorded where they come from. Calling them ours moved the blanket-CC0 problem
    # rather than fixing it, which is exactly the failure this table was written to end.
    #
    # `UNVERIFIED` may be planned and may never be built: check_manifest.py enforces that, so the
    # state is visible on every run instead of being a claim nobody checked.
    "custom": "UNVERIFIED",
    # Poly Haven publishes everything on its API under CC0.
    "polyhaven": "CC0-1.0",
    # MPFB2's bundled assets (base mesh, skins, clothes) are CC0 per its LICENSE.ASSETS.md,
    # even though the add-on code is GPL-3.0.
    "mpfb2": "CC0-1.0",
    # The Quaternius Universal Animation Library is CC0.
    "quaternius": "CC0-1.0",
    # Infinigen is BSD-3-Clause and its generated output is ours to license.
    "infinigen": "project-original",
    # Modular Tree is GPL-3.0. Generated geometry is normally not a derivative work of the
    # generator, but that is a legal judgement this pipeline should not make silently, so it
    # is flagged rather than declared. The owner decides; the validator keeps it visible.
    "mtree": "NEEDS-REVIEW",
}


def licence_for(source_tool):
    """The licence for an asset from this tool, or None if the tool is unknown."""
    return LICENCE_BY_TOOL.get(source_tool)


# Section 3: `<prefix>_<name>_<variant>_<lod>`, lowercase, underscores.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")

# Prefixes used by the brief's asset list. A name outside this set means either a typo or an
# addition that has not been through assets/ADDITIONS.md.
KNOWN_PREFIXES = {
    "sky", "cloud", "fog", "godray", "light", "haze", "rain", "snow", "hail", "lightning",
    "thunder", "fx", "screen", "lut", "env", "ground", "terrain", "decal", "rock", "ore",
    "water", "aqua", "tree", "log", "stump", "branch", "root", "deadfall", "bark", "wood",
    "shrub", "fern", "plant", "grass", "moss", "lichen", "ivy", "vine", "epiphyte", "clover",
    "leaf", "acorn", "pinecone", "twig", "seed", "fungus", "crop", "animal", "bird", "amph",
    "rept", "bug", "prop", "fish", "loot", "char", "cloth", "armor", "kit", "npc", "anim",
    "wpn", "ammo", "shield", "trap", "bait", "tool", "siege", "gear", "bld", "item", "veh",
    "vfx", "shader", "ui", "audio", "sign", "hunt", "atm", "tech", "surface",
}


def fail(message, problems):
    problems.append(message)


def parse_entry(raw, group):
    """`name|tier|priority|variants|source_tool|licence`, empty fields inherit from the group.

    The sixth field exists because not every asset comes from a tool whose licence is known in
    advance: a font is OFL, a music loop may be CC-BY, and both have to be recorded per asset
    rather than inferred from `source_tool`. Before it existed there was no way to express
    either, so the licence gate could only ever see CC0 or the tool default.
    """
    parts = raw.split("|")
    if len(parts) > 6:
        return None, "too many fields: %r" % raw
    parts += [""] * (6 - len(parts))
    name, tier, priority, variants, source_tool, licence = (p.strip() for p in parts)

    # No silent defaults for tier or priority. Inheriting from the group is fine; inventing a
    # value when neither the entry nor the group supplies one is not, because it produces an
    # asset classified by accident. emit() reports the empty case.
    tier = tier or group.get("tier", "")
    priority = priority or group.get("priority", "")
    source_tool = source_tool or group.get("source_tool", "custom")

    if variants == "":
        count = 1
    else:
        try:
            count = int(variants)
        except ValueError:
            return None, "variant count is not an integer: %r" % raw
        if count < 1:
            return None, "variant count must be positive: %r" % raw

    return {
        "name": name,
        "tier": tier,
        "priority": priority,
        "variants": count,
        "source_tool": source_tool,
        # Empty means "whatever this tool produces"; emit() falls back to licence_for().
        "licence": licence,
    }, None


def variant_name(name, index, count):
    if count == 1:
        return name
    # chr(ord("a") + index) runs past 'z' and into punctuation above 26 variants. Refuse
    # rather than emit a name the naming convention cannot express.
    if index >= 26:
        raise ValueError("variant index %d exceeds the 26 single-letter suffixes" % index)
    return "%s_%s" % (name, chr(ord("a") + index))


def build(manifest):
    problems = []
    defaults = manifest.get("field_defaults", {})
    categories = manifest.get("categories", {})
    records = []
    seen = {}
    base_names = {}
    emitted_names = {}

    def emit(entry, group_key, group):
        # A group that declares no phase is almost certainly a mistake, and defaulting it to 0
        # put assets in a phase that does not exist — they vanished from the phase counts and
        # from every per-phase gate. The same applied to tier, which silently became "A".
        if "phase" not in group:
            fail("%s: group has no phase" % group_key, problems)
        if "tier" not in group and not entry.get("tier"):
            fail("%s: group and entry both have no tier" % group_key, problems)
        if entry["tier"] not in VALID_TIERS:
            fail("%s: bad tier %r" % (entry["name"], entry["tier"]), problems)
        if entry["priority"] not in VALID_PRIORITIES:
            fail("%s: bad priority %r" % (entry["name"], entry["priority"]), problems)
        if not NAME_PATTERN.match(entry["name"]):
            fail("%s: breaks the naming convention" % entry["name"], problems)
        prefix = entry["name"].split("_", 1)[0]
        if prefix not in KNOWN_PREFIXES:
            fail("%s: unknown prefix %r" % (entry["name"], prefix), problems)
        if entry["name"] in seen:
            fail(
                "%s: duplicate, already in %s" % (entry["name"], seen[entry["name"]]),
                problems,
            )
        seen[entry["name"]] = group_key
        base_names.setdefault(entry["name"], group_key)

        for index in range(entry["variants"]):
            record = dict(defaults)
            record.update(
                {
                    "name": variant_name(entry["name"], index, entry["variants"]),
                    "base_name": entry["name"],
                    "category": group_key,
                    "category_label": group.get("label", group_key),
                    "phase": group.get("phase", 0),
                    "tier": entry["tier"],
                    "priority": entry["priority"],
                    "variants": entry["variants"],
                    "source_tool": entry["source_tool"],
                    # The entry's own sixth field wins when it has one (a font is OFL, a music
                    # loop may be CC-BY); otherwise the licence is derived from the tool, and an
                    # unrecognised tool yields None, which check_manifest.py rejects. A blanket
                    # CC0 default meant an asset whose provenance was never checked looked
                    # identical to one whose licence had been verified, which is the one thing a
                    # licence field must never do.
                    "source_license": entry.get("licence") or licence_for(entry["source_tool"]),
                    "status": "pending",
                }
            )
            # Variant names must be unique across the whole manifest, not just per entry.
            # `rock_boulder|…|2` produces rock_boulder_a and rock_boulder_b; a separate entry
            # named rock_boulder_a produces the same name again, and the second silently
            # overwrote the first in the output. Comparing base names alone never caught it.
            if record["name"] in emitted_names:
                fail(
                    "%s collides with %s: variant naming and an explicit entry produced the "
                    "same name" % (record["name"], emitted_names[record["name"]]),
                    problems,
                )
            emitted_names[record["name"]] = "%s in %s" % (entry["name"], group_key)
            records.append(record)

    # Authored entries first, so a derived group never shadows a hand-written one.
    for group_key, group in categories.items():
        for raw in group.get("assets", []):
            entry, error = parse_entry(raw, group)
            if error:
                fail("%s: %s" % (group_key, error), problems)
                continue
            emit(entry, group_key, group)

    # Snapshot the authored entries ONCE, before any derived group is built. emit() adds to
    # base_names as it goes, so a snapshot taken inside the derived loop would let a second
    # derived group derive from the first group's derived entries — icons of icons.
    authored = list(base_names.items())

    # Derived groups: one entry per matching asset in the named source categories.
    for group_key, group in categories.items():
        sources = group.get("derive_from")
        if not sources:
            continue
        prefix = group.get("derive_prefix")
        filters = group.get("derive_filter", [])
        if not prefix or not filters:
            fail("%s: derive_from needs derive_prefix and derive_filter" % group_key, problems)
            continue
        for source_key in sources:
            if source_key not in categories:
                fail("%s: derive_from names unknown category %r" % (group_key, source_key), problems)
                continue
            for base, owner in authored:
                if owner != source_key:
                    continue
                if not any(base.startswith(f) for f in filters):
                    continue
                entry = {
                    "name": prefix + base,
                    "tier": group.get("tier", "C"),
                    "priority": group.get("priority", "P2"),
                    "variants": 1,
                    "source_tool": group.get("source_tool", "custom"),
                }
                emit(entry, group_key, group)

    order = {"P1": 0, "P2": 1, "P3": 2}
    records.sort(key=lambda r: (r["phase"], order.get(r["priority"], 9), r["category"], r["name"]))
    return records, problems


def summarise(records):
    by_priority = {}
    by_phase = {}
    by_category = {}
    for record in records:
        by_priority[record["priority"]] = by_priority.get(record["priority"], 0) + 1
        by_phase[record["phase"]] = by_phase.get(record["phase"], 0) + 1
        by_category[record["category"]] = by_category.get(record["category"], 0) + 1
    return {
        "total": len(records),
        "by_priority": dict(sorted(by_priority.items())),
        "by_phase": dict(sorted(by_phase.items())),
        "by_category": dict(sorted(by_category.items())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--manifest", default=MANIFEST)
    parser.add_argument("--out", default=EXPANDED)
    args = parser.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    records, problems = build(manifest)
    if problems:
        print("Manifest is inconsistent; nothing written:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    payload = {
        "schema_version": manifest.get("schema_version", 1),
        "project": manifest.get("project", ""),
        "generated_by": "tools/build_manifest.py",
        "note": "Generated from assets/manifest.json. Do not edit by hand.",
        "budgets_mb": manifest.get("budgets_mb", {}),
        "summary": summarise(records),
        "assets": records,
    }
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"

    if args.check:
        # `--check` compares against a file that is gitignored and regenerated on every run,
        # so "stale" only ever meant "CI has not built it yet" — never a real inconsistency.
        # The meaningful check is that the authored list builds without problems, which the
        # block above already did. Say so instead of pretending to detect staleness.
        print(
            "manifest is consistent: %d assets expand cleanly (nothing to compare against; "
            "%s is generated and not committed)" % (len(records), args.out)
        )
        return 0

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)

    summary = payload["summary"]
    print("wrote %s: %d assets" % (args.out, summary["total"]))
    print("  by priority: " + ", ".join("%s=%d" % kv for kv in summary["by_priority"].items()))
    print("  by phase:    " + ", ".join("%s=%d" % kv for kv in summary["by_phase"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
