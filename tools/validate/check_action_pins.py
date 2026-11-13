#!/usr/bin/env python3
"""Resolve every pinned GitHub Action through the API, so a wrong SHA cannot sit there looking pinned.

Run:
    GH_TOKEN=<token> python tools/validate/check_action_pins.py

`check_scripts.py` proves that a `uses:` line names a 40-character commit, not that the commit
exists. A typo — or a SHA someone typed from memory — passes every static check and then fails
every job at setup, which reads like an infrastructure outage rather than a bad pin. That is the
worst failure mode this repository has: silent until it is expensive.

What this does:

  * finds every `uses: owner/repo@<40 hex>` in `.github/workflows/*.yml`
  * asks the API whether that commit exists in that repository
  * fails on 404 (no such commit) and 422 (not a commit SHA)
  * warns, and does not fail, on rate limits and server errors, because a network problem is not
    a bad pin

A run that resolves nothing is a failure. A checker whose walker found no pins is the "a check
that finds nothing" bug from docs/LESSONS.md #3.
"""

import os
import re
import sys
import urllib.error
import urllib.request

WORKFLOW_DIR = os.path.join(".github", "workflows")

# `- uses: owner/repo@<sha>` or `uses: owner/repo@<sha>`, with any indentation. The optional `-`
# covers step lists; the rest is what a workflow actually looks like.
USES = re.compile(
    r"^[ \t]*-?[ \t]*uses:[ \t]*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([0-9a-f]{40})\b",
    re.MULTILINE,
)

API = "https://api.github.com/repos/%s/commits/%s"
TIMEOUT_S = 20


def pinned_actions():
    """Every (repo, sha) in the workflows, with the first file and line that uses it."""
    found = {}
    if not os.path.isdir(WORKFLOW_DIR):
        return found
    for name in sorted(os.listdir(WORKFLOW_DIR)):
        if not name.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(WORKFLOW_DIR, name)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        for match in USES.finditer(text):
            repo, sha = match.group(1), match.group(2)
            line = text[: match.start()].count("\n") + 1
            found.setdefault((repo, sha), []).append("%s:%d" % (path, line))
    return found


def resolve(repo, sha, token):
    """'ok', or ('bad', reason), or ('unknown', reason) when the API could not answer."""
    request = urllib.request.Request(
        API % (repo, sha),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "drowned-greenwood-action-pin-check",
        },
    )
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            response.read(1)
        return "ok"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ("bad", "no such commit (404)")
        if exc.code == 422:
            return ("bad", "not a commit SHA (422)")
        return ("unknown", "HTTP %d" % exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return ("unknown", str(exc))


def main():
    found = pinned_actions()
    if not found:
        print(
            "no pinned actions found; the workflow walker is looking in the wrong place",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        print(
            "warning: GH_TOKEN is not set, so the API is asked unauthenticated and may rate-limit",
            file=sys.stderr,
        )

    bad = []
    unknown = []
    ok = 0
    for (repo, sha), where in sorted(found.items()):
        result = resolve(repo, sha, token)
        if result == "ok":
            ok += 1
            print("ok      %s@%s" % (repo, sha[:12]))
        elif result[0] == "bad":
            bad.append(
                "%s@%s (used at %s) — %s" % (repo, sha, ", ".join(where), result[1])
            )
        else:
            unknown.append("%s@%s — %s" % (repo, sha, result[1]))

    print(
        "%d pinned actions: %d resolved, %d bad, %d unanswered"
        % (len(found), ok, len(bad), len(unknown))
    )
    for line in bad:
        print("FAIL " + line, file=sys.stderr)
    for line in unknown:
        print("warning: " + line, file=sys.stderr)

    if bad:
        return 1
    # The API answered for none of them, so this run proved nothing. That is a failure, not a
    # green with warnings — it is the exact "absences of evidence" trap in docs/LESSONS.md #3.
    if ok == 0:
        print(
            "the API resolved none of the pins, so this check verified nothing",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
