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
import os
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
TARGET_MB = 700


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
    elif total > TARGET_MB:
        # Not a failure: the plan may sit above target while it has room. But it is worth
        # saying out loud, because a plan 90 MB over target has only 10 MB of headroom before
        # the hard cap, and nobody should discover that when a category overflows.
        print(
            "warning: category budgets total %d MB, above the %d MB target (hard cap %d MB)"
            % (total, TARGET_MB, HARD_CAP_MB),
            file=sys.stderr,
        )

    # A category needs a budget. An earlier table omitted 4.P entirely, so its declared total
    # was not the real total and nobody would notice until the repository was over its cap with
    # nowhere to point.
    #
    # Categories are named with sub-groups ("4.A.env", "4.G.rig", "4.N.icons") while budgets use
    # section keys ("4.A", "4.G"), so this matches on the section prefix. Exact matching would
    # report every sub-group as unbudgeted, which is a false failure.
    budget_sections = set()
    for key in budgets:
        for part in key.split("+"):
            budget_sections.add(part.strip())

    def covered(category):
        # "4.A.env" -> check "4.A.env", then "4.A".
        candidate = category
        while candidate:
            if candidate in budget_sections:
                return True
            if "." not in candidate:
                return False
            candidate = candidate.rsplit(".", 1)[0]
        return False

    asset_categories = {record["category"] for record in assets}
    unbudgeted = sorted(category for category in asset_categories if not covered(category))
    if unbudgeted:
        problems.append("no budget covers %d categories: %s" % (len(unbudgeted), unbudgeted))

    # Licences must be known and on the allowlist.
    #
    # The builder used to default every record to CC0, which made this check pass trivially:
    # an asset whose provenance was never examined was indistinguishable from one whose licence
    # had been verified. The default is now None (unknown) and the licence is derived from the
    # source tool, so a tool with no recorded licence fails here instead of being called CC0.
    allowed_licences = {
        # Our own generators.
        "project-original",
        # Third-party licences the brief permits.
        "CC0",
        "CC0-1.0",
        "MIT",
        "BSD-3-Clause",
        "BSD-2-Clause",
        "Apache-2.0",
        "OFL-1.1",
        "CC-BY-4.0",
        "CC-BY-3.0",
    }
    # str() around the value matters: sorted() raises TypeError on a set mixing None and str,
    # so a single record with the field absent would crash the validator instead of reporting
    # the missing licence.
    by_licence = {}
    for record in assets:
        by_licence.setdefault(str(record.get("source_license")), []).append(record["name"])

    unknown = by_licence.pop("None", [])
    if unknown:
        problems.append(
            "%d assets have no known licence (source tool has no recorded licence): %s"
            % (len(unknown), unknown[:5])
        )

    # NEEDS-REVIEW marks a real legal question that has not been answered — in this project,
    # whether geometry generated by a GPL-3.0 tool (Modular Tree) inherits that licence. It may
    # be *planned*, so it does not block the build; it may never be *shipped*, so an asset in
    # that state that claims to be built is a failure. That is the precise line: no silent CC0,
    # and no blocking of planning work on a decision only the owner can make.
    review = by_licence.pop("NEEDS-REVIEW", [])
    if review:
        shipped = [
            name
            for name in review
            if next(
                (r["status"] for r in assets if r["name"] == name and r["status"] != "pending"),
                "pending",
            )
            != "pending"
        ]
        if shipped:
            problems.append(
                "%d assets are marked built but their licence needs review: %s"
                % (len(shipped), shipped[:5])
            )
        print(
            "warning: %d planned assets need their licence reviewed before they can ship "
            "(source tool has an unresolved licence question): %s"
            % (len(review), review[:3]),
            file=sys.stderr,
        )

    bad_licences = sorted(set(by_licence) - allowed_licences)
    if bad_licences:
        problems.append(
            "source_license values outside the allowlist: %s" % bad_licences
        )

    # A record that claims to be built must carry the evidence, not just two fields.
    #
    # Path and hash alone are too easy to satisfy: a hand-written path and a copied hex string
    # pass. Reproducibility needs the input hash (what was fed to the generator) and the tool
    # version (what ran), and honesty about quality needs gate_results (what was measured).
    # Without those four, "built" is an assertion rather than a record.
    for record in assets:
        if record.get("status") not in {"built", "PASSED", "BELOW_TARGET"}:
            continue
        required = {
            "path": record.get("path"),
            "sha256": record.get("sha256"),
            "input_hash": record.get("input_hash"),
            "tool_version": record.get("tool_version"),
            "gate_results": record.get("gate_results"),
        }
        missing = sorted(k for k, v in required.items() if not v)
        if missing:
            problems.append(
                "%s: status %s but missing %s"
                % (record["name"], record["status"], ", ".join(missing))
            )

    # How much of the plan depends on generators that do not exist yet.
    #
    # `source_tool: custom` means "one of our own scripts makes this". No script in
    # tools/generators/ exists — that directory is planned, not present — and Phase 0 tested no
    # tool that could produce these assets. So every custom asset is unbuildable today, and the
    # number is large enough that it should be visible on every run rather than discovered in
    # Phase 2. Not a failure: a plan may schedule work that is not written yet. A failure only
    # if one of them claims to be built, which the evidence check above already catches.
    generators_dir = os.path.join("tools", "generators")
    custom = [r["name"] for r in assets if r.get("source_tool") == "custom"]
    if custom and not os.path.isdir(generators_dir):
        print(
            "warning: %d of %d assets (%.0f%%) are `source custom` and no generator exists yet "
            "(%s is not present), so none of them can be built today"
            % (len(custom), len(assets), 100.0 * len(custom) / len(assets), generators_dir),
            file=sys.stderr,
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
