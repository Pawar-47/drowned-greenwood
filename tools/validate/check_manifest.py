#!/usr/bin/env python3
"""Structural checks on the expanded manifest.

Run after tools/build_manifest.py:
    python tools/validate/check_manifest.py

`tools/build_manifest.py` already rejects duplicates, bad tiers, bad priorities and names
that break the convention. This checks the properties that only make sense on the expanded
list: required fields present and of the right type, phase and priority in range, the size
budget table within the hard cap, and the P1 set non-empty per built phase.
"""

import json
import sys

EXPANDED = "assets/manifest.expanded.json"

REQUIRED = {
    "name": str,
    "base_name": str,
    "category": str,
    "phase": int,
    "tier": str,
    "priority": str,
    "source_tool": str,
    "status": str,
    "path": (str, type(None)),
    "tris": int,
    "lod_tris": list,
    "texture_sizes": dict,
    "bones": int,
    "anims": list,
    "tags": list,
    "tool_version": str,
    "source_license": str,
    "input_hash": str,
    "sha256": (str, type(None)),
    "pack": (str, type(None)),
    "size_kb": (int, float),
    "gate_results": dict,
}

HARD_CAP_MB = 800


def main():
    with open(EXPANDED, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    problems = []
    assets = manifest.get("assets", [])
    if not assets:
        problems.append("no assets in the expanded manifest")

    for record in assets:
        name = record.get("name", "<unnamed>")
        for field, expected in REQUIRED.items():
            if field not in record:
                problems.append("%s: missing field %s" % (name, field))
                continue
            if not isinstance(record[field], expected):
                problems.append(
                    "%s: field %s is %s, expected %s"
                    % (name, field, type(record[field]).__name__, expected)
                )
        if record.get("phase") not in range(0, 10):
            problems.append("%s: phase out of range" % name)
        if record.get("status") not in {
            "pending", "built", "PASSED", "BELOW_TARGET", "PLACEHOLDER"
        }:
            problems.append("%s: unknown status %r" % (name, record.get("status")))
        if record.get("pack") is not None and not record.get("sha256"):
            problems.append("%s: pack set but no sha256" % name)

    budgets = manifest.get("budgets_mb", {})
    total = sum(budgets.values())
    if total > HARD_CAP_MB:
        problems.append(
            "category budgets total %d MB, over the %d MB hard cap" % (total, HARD_CAP_MB)
        )

    p1_by_phase = {}
    for record in assets:
        if record.get("priority") == "P1":
            p1_by_phase[record["phase"]] = p1_by_phase.get(record["phase"], 0) + 1
    for phase in sorted({r["phase"] for r in assets}):
        if phase == 0:
            continue
        if p1_by_phase.get(phase, 0) == 0:
            problems.append("phase %d has no P1 assets" % phase)

    if problems:
        print("Manifest checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    summary = manifest.get("summary", {})
    print(
        "manifest checks passed: %d assets, budgets %d MB of %d MB"
        % (len(assets), total, HARD_CAP_MB)
    )
    print("  by priority: " + ", ".join("%s=%d" % kv for kv in summary.get("by_priority", {}).items()))
    print("  by phase:    " + ", ".join("%s=%d" % kv for kv in summary.get("by_phase", {}).items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
