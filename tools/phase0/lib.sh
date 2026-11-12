#!/usr/bin/env bash
# Shared helpers for the Phase 0 tool-evaluation workflow.
#
# Every probe appends its output to one log file, and every probe reports a machine-readable
# "RESULT ..." line, so a whole run can be read from a single place and a failing probe never
# hides the probes after it.

LOG="${LOG:-${GITHUB_WORKSPACE:-$PWD}/phase0_log.txt}"
mkdir -p "$(dirname "$LOG")"
: >> "$LOG"

# run_capture <name> <command> [args...]
#
# Runs the command, copies its output into the log, and records the exit code as
# "RESULT <name> exit=<code>".
#
# If the command already printed its own RESULT line (the Python and GDScript probes do, with
# far more detail than an exit code), that line is left to stand on its own and no second row
# is added. Without this, a probe's detailed row and this wrapper's bare exit-code row share a
# name and the last one written wins, which silently discards the detail.
run_capture() {
  local name="$1"
  shift
  local output
  output="$(mktemp)"
  set +e
  "$@" >"$output" 2>&1
  local code=$?
  set -e
  cat "$output" >>"$LOG"
  if grep -q '^RESULT ' "$output"; then
    if [ "$code" -ne 0 ]; then
      echo "RESULT ${name}_exit exit=${code}" | tee -a "$LOG"
    fi
  else
    echo "RESULT ${name} exit=${code}" | tee -a "$LOG"
  fi
  rm -f "$output"
  return 0
}
