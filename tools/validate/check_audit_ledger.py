#!/usr/bin/env python3
"""Check that every clause of an audit is accounted for.

Run:
    python tools/validate/check_audit_ledger.py

Why this exists: three audit reports in a row were answered partially. The findings that were easy
or interesting got fixed, the rest were quietly dropped, and a "re-run the audit" pass four rounds
later still found items nobody had touched. The failure was not knowledge — it was bookkeeping.
A 99-clause report read in prose loses clauses; a 99-row ledger cannot lose one without the row
being visibly empty.

The ledger (`reports/audit_ledger.json`) is the list of every clause with a state and something
behind it. This checks the ledger, not the code:

  * every clause has a known state, and no state means "not looked at yet"
  * a DONE clause names files that exist, and says what changed
  * a REJECTED clause carries the evidence that the finding was wrong
  * a CONFIRMED clause carries the evidence that the finding was right and needs no work
  * a DEFERRED clause names what would unblock it
  * a NOT_DONE clause says why it is not done
  * clause ids run S<section>.<n> with no gaps, so a deleted row is visible
  * `clauses_total` matches the rows that are actually there

A ledger that has lost a row fails here. That is the whole point: silence becomes a build failure
instead of a thing a person has to notice.
"""

import json
import os
import re
import sys

LEDGER = os.path.join("reports", "audit_ledger.json")

STATES = ("DONE", "REJECTED", "CONFIRMED", "DEFERRED", "NOT_DONE")

# What each state must carry for it to mean anything.
REQUIRED = {
    # A change that names no file is a claim, not a change.
    "DONE": ("files", "evidence"),
    # Rejecting a finding is an assertion of fact and needs the proof beside it.
    "REJECTED": ("evidence",),
    # Agreeing with a finding without checking it is how a wrong fix gets shipped.
    "CONFIRMED": ("evidence",),
    # Deferred with no trigger is abandoned with nicer wording.
    "DEFERRED": ("unblock",),
    # Not done, unblocked, and still not done — say why.
    "NOT_DONE": ("why",),
}

# Ids may carry the audit's own label: S4.H1, S5.M6, S9.3.
CLAUSE_ID = re.compile(r"^S(\d+)\.([A-Z]?)(\d+)$")


def check_entry(where, entry, problems):
    state = entry.get("state")
    if state not in STATES:
        problems.append(
            "%s: state %r is not one of %s — an unstated state is the omission this check exists "
            "to catch" % (where, state, ", ".join(STATES))
        )
        return
    for field in REQUIRED[state]:
        value = entry.get(field)
        if not value:
            problems.append("%s: state %s but no %s" % (where, state, field))
    if state == "DONE":
        for path in entry.get("files") or []:
            if not os.path.exists(path):
                problems.append(
                    "%s: DONE names a file that does not exist: %s" % (where, path)
                )
    for index, sub in enumerate(entry.get("sub") or [], start=1):
        if not isinstance(sub, dict) or not sub.get("clause"):
            problems.append("%s: sub-item %d has no clause text" % (where, index))
            continue
        check_entry("%s sub %d (%s)" % (where, index, sub["clause"]), sub, problems)


def main():
    if not os.path.exists(LEDGER):
        print("no ledger at %s; nothing was transcribed" % LEDGER, file=sys.stderr)
        return 1

    with open(LEDGER, encoding="utf-8") as handle:
        ledger = json.load(handle)

    clauses = ledger.get("clauses") or []
    if not clauses:
        print("the ledger has no clauses; it accounts for nothing", file=sys.stderr)
        return 1

    problems = []

    declared = ledger.get("clauses_total")
    if declared != len(clauses):
        problems.append(
            "clauses_total says %r but the ledger holds %d clauses — either a row was lost or the "
            "count was never updated" % (declared, len(clauses))
        )

    seen = set()
    by_section = {}
    for entry in clauses:
        clause_id = entry.get("id", "")
        match = CLAUSE_ID.match(clause_id)
        if not match:
            problems.append("%r is not a clause id of the form S<section>.<n>" % clause_id)
            continue
        if clause_id in seen:
            problems.append("%s appears twice" % clause_id)
        seen.add(clause_id)
        section = int(match.group(1))
        number = int(match.group(3))
        if entry.get("section") != section:
            problems.append(
                "%s: id says section %d, field says %r" % (clause_id, section, entry.get("section"))
            )
        by_section.setdefault(section, []).append(number)
        if not entry.get("clause"):
            problems.append("%s has no clause text" % clause_id)
        check_entry(clause_id, entry, problems)

    # Contiguous numbering, so a deleted row is a failure rather than a silent shrink.
    for section, numbers in sorted(by_section.items()):
        expected = list(range(1, len(numbers) + 1))
        if numbers != expected:
            problems.append(
                "section %d is numbered %s; a gap or a duplicate means a row was lost"
                % (section, numbers)
            )

    if problems:
        print("audit ledger failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    counts = {state: 0 for state in STATES}
    for entry in clauses:
        counts[entry["state"]] += 1
    print(
        "audit ledger: %d clauses accounted for — %s"
        % (
            len(clauses),
            ", ".join("%s %d" % (state, counts[state]) for state in STATES if counts[state]),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
