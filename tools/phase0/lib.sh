#!/usr/bin/env bash
# Shared helpers for the Phase 0 tool-evaluation workflow.
#
# Every probe appends its output to one log file and reports a machine-readable "RESULT ..."
# line, so a whole run reads from one place and a failing probe never hides the probes after it.

LOG="${LOG:-${GITHUB_WORKSPACE:-$PWD}/phase0_log.txt}"
mkdir -p "$(dirname "$LOG")"
: >> "$LOG"

# Every probe is bounded. Godot sat waiting for an import that never came and the job burned
# its full 45-minute ceiling before being cancelled; a probe that hangs must cost seconds, not
# a job. Override with PROBE_TIMEOUT when a probe legitimately needs longer.
PROBE_TIMEOUT="${PROBE_TIMEOUT:-300}"

# run_capture <name> <command> [args...]
#
# Runs the command under `timeout`, copies its output into the log, and records a result line.
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
  timeout --signal=KILL "${PROBE_TIMEOUT}" "$@" >"$output" 2>&1
  code=$?
  [ "$had_errexit" -eq 1 ] && set -e

  cat "$output" >>"$LOG"

  if [ "$code" -eq 137 ]; then
    # Killed by timeout: say so, because a silent hang reads like a crash.
    echo "RESULT ${name}_timeout exit=137 timeout=${PROBE_TIMEOUT}s" | tee -a "$LOG"
  elif grep -q '^RESULT ' "$output"; then
    # The probe reported for itself. Only add a row if it failed without saying so.
    #
    # The pattern must tolerate ANY spacing around the colon. It used to be the literal
    # '"ok": false', which is how Python's json.dumps writes it — but the GDScript probes emit
    # JSON.stringify output, which has no space: {"step":"x","ok":false}. So the grep never
    # matched a Godot failure, a redundant `<name>_exit` row was appended to every failing
    # GDScript probe, and once those rows stopped being discarded that row read as a crash.
    if [ "$code" -ne 0 ] && ! grep -qE '"ok"[[:space:]]*:[[:space:]]*false' "$output"; then
      echo "RESULT ${name}_exit exit=${code}" | tee -a "$LOG"
    fi
  else
    echo "RESULT ${name} exit=${code}" | tee -a "$LOG"
  fi

  rm -f "$output"
  return 0
}
