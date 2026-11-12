#!/usr/bin/env bash
# Shared helpers for the Phase 0 tool-evaluation workflow.
#
# Every probe appends its output to one log file and reports a machine-readable "RESULT ..."
# line, so a whole run reads from one place and a failing probe never hides the probes after it.

LOG="${LOG:-${GITHUB_WORKSPACE:-$PWD}/phase0_log.txt}"
mkdir -p "$(dirname "$LOG")"
: >> "$LOG"

# run_capture <name> <command> [args...]
#
# Runs the command, copies its output into the log, and records a result line.
#
# If the command already printed its own RESULT line — the Python and GDScript probes do, with
# far more detail than an exit code — that line stands on its own and no second row is added.
# Without this the probe's detailed row and this wrapper's bare exit-code row share a name and
# the last one written wins, silently discarding the detail.
#
# Shell options are saved and restored rather than set to a fixed value: a function that calls
# `set -e` changes the caller's shell too, which is how a probe step aborted before its next
# probe ran.
run_capture() {
  local name="$1"
  shift
  local output
  local code
  output="$(mktemp)"

  local had_errexit=0
  case "$-" in
    *e*) had_errexit=1 ;;
  esac
  set +e
  "$@" >"$output" 2>&1
  code=$?
  [ "$had_errexit" -eq 1 ] && set -e

  cat "$output" >>"$LOG"

  if grep -q '^RESULT ' "$output"; then
    # The probe reported for itself. Only add a row if it failed without saying so.
    if [ "$code" -ne 0 ] && ! grep -q '"ok": false' "$output"; then
      echo "RESULT ${name}_exit exit=${code}" | tee -a "$LOG"
    fi
  else
    echo "RESULT ${name} exit=${code}" | tee -a "$LOG"
  fi

  rm -f "$output"
  return 0
}
