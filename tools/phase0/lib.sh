#!/usr/bin/env bash
# Shared helpers for the Phase 0 tool-evaluation workflow.
#
# Every probe appends its output to one log file, and every probe reports a machine-readable
# "RESULT <name> exit=<code>" line, so a whole run can be read from a single place and a
# failing probe never hides the probes after it.

LOG="${LOG:-${GITHUB_WORKSPACE:-$PWD}/phase0_log.txt}"
mkdir -p "$(dirname "$LOG")"
: >> "$LOG"

# run_capture <name> <command> [args...]
run_capture() {
  local name="$1"
  shift
  set +e
  "$@" >>"$LOG" 2>&1
  local code=$?
  echo "RESULT ${name} exit=${code}" | tee -a "$LOG"
  return 0
}
