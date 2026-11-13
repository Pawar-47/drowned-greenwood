# How an audit is processed, and how an edit is made

Two failure modes this file exists to stop, both of them observed here rather than imagined:

1. **Partial audits.** Three reports in a row were answered by fixing the findings that were easy
   or interesting. The rest were dropped without a word, and a re-audit four passes later still
   found untouched clauses. Reading a 99-clause report as prose loses clauses; nothing about
   knowing better prevents it.
2. **Fixes that break things.** Joining two YAML lines, dropping a blank line between paragraphs,
   merging two table rows, and quoting a count that had changed — all while fixing something else,
   all caught by CI afterwards instead of before.

Both are bookkeeping problems, so both get a written procedure plus whatever can be checked by a
machine. Procedure alone is what failed the first time.

## Processing an audit

**1. Transcribe before touching anything.** The audit becomes `reports/audit_ledger.json` first:
one row per clause, every clause, including the sections that are not findings (summaries, fix
orders, "could not verify" lists). No code is changed until that file exists.

**2. One state per clause, from a closed set.** `DONE`, `REJECTED`, `CONFIRMED`, `DEFERRED`,
`NOT_DONE`. There is deliberately no "pending": a clause with no state is the omission the whole
mechanism exists to catch.

**3. Every state carries something.**
- `DONE` names files that exist, and says what changed in them.
- `REJECTED` carries the evidence that the finding was wrong. Rejecting without proof is just a
  different way of ignoring it.
- `CONFIRMED` carries the evidence that the finding is right and needs no work — usually because
  a document already says so and the auditor did not look.
- `DEFERRED` names what would unblock it. Deferred with no trigger is abandoned with nicer wording.
- `NOT_DONE` says why, plainly.

**4. A finding is a claim, and claims get tested.** An audit's statement about the code is not
more reliable than the code. H2 claimed a pinned action SHA might not exist; the API says it does,
PGP-verified. M2 claimed the foliage comment contradicted the code; Godot's documentation says the
comment was right and the proposed fix would have deleted the cut-out. Both are recorded as
`REJECTED` with the proof beside them, and checking them turned up a real bug in the same area.

**5. Distinguish written from executed.** A change that has never run is `DONE` with a `NOT_DONE`
sub-item saying so, not `DONE` and silent. The vertex-colour probe is exactly that today: written,
reasoned, and unrun.

**6. The ledger is checked in CI.** `tools/validate/check_audit_ledger.py` fails the build on an
unknown state, a missing field, a `DONE` row naming a file that does not exist, a gap in the
numbering, or a `clauses_total` that disagrees with the rows. It prints the count per state, so
"37 done, 4 rejected, 14 open" is visible on every run instead of reconstructed from memory.

## Making an edit

Every mistake listed at the top of this file came from a replace that touched a boundary.

**1. Anchor on something unique and small.** One function, one step, one line — not a paragraph
whose edges you have not looked at.

**2. If the anchor ends with a newline, the replacement does too.** Three documents lost a paragraph
break because `old_content` ended with `\n` and `new_content` did not. The result is two paragraphs
joined, or a clause merged into the line above it.

**3. Re-read the edited region in the same round.** Not later, not from memory: read the lines back
and check that the surrounding structure survived. Every merge so far was visible on screen and
would have been caught by one read.

**4. Never let a replacement change indentation of a line you did not mean to touch.** YAML block
scalars end at the first dedented line; a stray space silently truncates a `run:` block.

**5. After editing a workflow, look for merged keys.** A `- name:` line that also carries `run:` is
invalid YAML and fails fast — which is the good case. Check before pushing, not after.

**6. Never state a count you did not derive from the file.** "15 unit tests" survived three
revisions. "35 unit tests" survived one. The number is derivable, so derive it, and let
`check_docs.py` hold the document to it.

**7. Push, then read the result.** CI takes seconds for the static gate; the run is the review. A
red static job is cheaper to read than a wrong claim is to defend.

## What is enforced by a machine

- every workflow parses as YAML, and every `run:` block passes `bash -n` (`check_scripts.py`)
- every sampler declares `repeat_enable` unless allowlisted (`check_scripts.py`)
- every pinned action SHA resolves through the GitHub API (`check_action_pins.py`)
- README counts match the manifest, materials and test suite (`check_docs.py`)
- markdown tables have a consistent column count (`check_docs.py`)
- every audit clause has a state and evidence (`check_audit_ledger.py`)

## What is not, and cannot be

Anchoring well, re-reading after an edit, and reading the audit before acting on it. The checks
catch the consequences; they cannot catch the decision to skip a step. That part is the discipline
above, and the ledger exists so that skipping it is at least visible.
