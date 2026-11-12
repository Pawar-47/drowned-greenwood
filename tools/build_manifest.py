#!/usr/bin/env python3
"""Expand assets/manifest.json into one record per asset and check the list's integrity.

Run:
    python tools/build_manifest.py            # write assets/manifest.expanded.json
    python tools/build_manifest.py --check    # exit 1 if the file on disk is stale

`assets/manifest.json` holds the authored list: categories of
`name|tier|priority|variants|source_tool` entries, where an empty field inherits from the
group. This script turns that into flat records carrying every field the brief requires, so
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
    """`name|tier|priority|variants|source_tool`, empty fields inherit from the group."""
    parts = raw.split("|")
    if len(parts) > 5:
        return None, "too many fields: %r" % raw
    parts += [""] * (5 - len(parts))
    name, tier, priority, variants, source_tool = (p.strip() for p in parts)

    tier = tier or group.get("tier", "A")
    priority = priority or group.get("priority", "P2")
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
    }, None


def variant_name(name, index, count):
    if count == 1:
        return name
    return "%s_%s" % (name, chr(ord("a") + index))


def build(manifest):
    problems = []
    defaults = manifest.get("field_defaults", {})
    records = []
    seen = {}

    for group_key, group in manifest.get("categories", {}).items():
        for raw in group.get("assets", []):
            entry, error = parse_entry(raw, group)
            if error:
                fail("%s: %s" % (group_key, error), problems)
                continue

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
                        "status": "pending",
                    }
                )
                records.append(record)

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
        if not os.path.exists(args.out):
            print("%s is missing; run tools/build_manifest.py" % args.out, file=sys.stderr)
            return 1
        with open(args.out, "r", encoding="utf-8") as handle:
            current = handle.read()
        if current != text:
            print("%s is stale; run tools/build_manifest.py" % args.out, file=sys.stderr)
            return 1
        print("manifest up to date: %d assets" % len(records))
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
