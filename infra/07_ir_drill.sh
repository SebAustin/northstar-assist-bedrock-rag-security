#!/usr/bin/env bash
# Task 6 drill: prove both containment levels of infra/ir_contain.sh against the live harness, then recover.
#
# Sequence: baseline → lockdown → restore → stop → resume. After each change the benign smoke question is
# sent until the expected behaviour is observed, and the time that took is recorded. One session is opened
# before the lockdown and reused after it, to prove containment also covers sessions that already exist.
# If a step fails, the EXIT trap removes the incident deny and re-attaches the Northstar guardrail.
#
# Usage: infra/07_ir_drill.sh        (asks once; the assistant is unavailable for a few minutes)
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account
state_load
state_require HARNESS_ARN HARNESS_ROLE_NAME

readonly CONTAIN="${PROJECT_ROOT}/infra/ir_contain.sh"
readonly PROBE=("${PROJECT_ROOT}/.venv/bin/python" "${PROJECT_ROOT}/tools/ir_probe.py")
readonly OUT="${EVIDENCE_ROOT}/task6/ir_drill.jsonl"
readonly PROBE_ATTEMPTS=12
readonly PROBE_PAUSE=10
DRILL_DONE=0
mkdir -p "$(dirname "$OUT")"

recover() {
  [[ "$DRILL_DONE" == "1" ]] && return 0
  log "drill did not finish: removing the incident deny and re-attaching the Northstar guardrail"
  ASSUME_YES=1 "$CONTAIN" resume  || log "WARNING: resume failed; run it by hand"
  ASSUME_YES=1 "$CONTAIN" restore || log "WARNING: restore failed; run it by hand"
}
trap recover EXIT

# expect <step> <observation> [session]: probe until the assistant shows <observation>; record how long it took.
expect() {
  local step="$1" want="$2" session="${3:-}" started got="{}" seen="" attempt
  started="$(date +%s)"
  for attempt in $(seq 1 "$PROBE_ATTEMPTS"); do
    got="$("${PROBE[@]}" ${session:+--session "$session"})" || got='{"observed":"error","text":"probe failed to run"}'
    seen="$(jq -r .observed <<<"$got")"
    [[ "$seen" == "$want" ]] && break
    sleep "$PROBE_PAUSE"
  done
  jq -nc --arg step "$step" --arg want "$want" --argjson probe "$got" --argjson attempts "$attempt" \
    --argjson seconds "$(( $(date +%s) - started ))" \
    '{step:$step, expected:$want, observed:$probe.observed, as_expected:($probe.observed == $want), attempts:$attempts,
      seconds_until_observed:$seconds, at:$probe.at, session:$probe.session, user_sees:$probe.text}' >> "$OUT"
  [[ "$seen" == "$want" ]] || die "step ${step}: expected ${want}, observed ${seen} after ${attempt} probes"
  log "step ${step}: ${seen} (probe ${attempt})"
}

confirm "Run the containment drill on the live harness? The assistant is unavailable for a few minutes."
: > "$OUT"
export ASSUME_YES=1
open_session="$("${PROJECT_ROOT}/.venv/bin/python" -c 'import uuid; print(uuid.uuid4())')"

expect "0 baseline (session opened before the incident)" answered "$open_session"
"$CONTAIN" lockdown
expect "1 lockdown, new session" lockdown
expect "1 lockdown, session opened before it" lockdown "$open_session"
"$CONTAIN" restore
expect "2 restore" answered
"$CONTAIN" stop
expect "3 stop (IAM deny)" access_denied
"$CONTAIN" resume
expect "4 resume" answered
DRILL_DONE=1
"$CONTAIN" status | tee "${EVIDENCE_ROOT}/task6/ir_drill_final_status.txt"
grep -q '^state: *NORMAL' "${EVIDENCE_ROOT}/task6/ir_drill_final_status.txt" || die "final state is not NORMAL"
log "drill complete → evidence/task6/ir_drill.jsonl"
