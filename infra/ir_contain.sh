#!/usr/bin/env bash
# Task 6 incident containment for Northstar Assist: two reversible levels, least disruptive first.
#
# Usage: infra/ir_contain.sh status     show which guardrail is attached and whether an incident deny is active
#        infra/ir_contain.sh lockdown   level 1: swap the harness to the block-everything guardrail
#        infra/ir_contain.sh restore    undo level 1: re-attach the Northstar guardrail
#        infra/ir_contain.sh stop       level 2: deny the harness role every model invocation
#        infra/ir_contain.sh resume     undo level 2
#
# Level 1 keeps the assistant reachable: every user gets the "temporarily unavailable" message.
# Level 2 is the fallback when the harness cannot be updated or the guardrail itself is in doubt:
# model calls fail with AccessDenied. Neither level deletes anything, so evidence is preserved.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

readonly MODE="${1:-}"
case "$MODE" in
  status|lockdown|restore|stop|resume) ;;
  *) die "usage: $0 status|lockdown|restore|stop|resume" ;;
esac

require_lab_account
state_load
# Level 2 must work even when the guardrail entries in the state file are missing or wrong.
state_require HARNESS_ROLE_NAME
if [[ "$MODE" != "stop" && "$MODE" != "resume" ]]; then
  state_require HARNESS_ARN MODEL_ID GUARDRAIL_ARN GUARDRAIL_VERSION LOCKDOWN_ARN LOCKDOWN_VERSION
fi

readonly HARNESS_ID="${HARNESS_ARN:+${HARNESS_ARN##*/}}"
readonly DENY_POLICY="NorthstarIncidentDenyModelInvocation"
readonly PROMPT_FILE="${PROJECT_ROOT}/guardrail/system_prompt_v2.txt"
readonly EVIDENCE_DIR="${EVIDENCE_ROOT}/task6"
readonly POLL_SECONDS="${IR_POLL_SECONDS:-10}"
readonly POLL_ATTEMPTS=30
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAMP
readonly FALLBACK="fall back to level 2: $0 stop"
mkdir -p "$EVIDENCE_DIR"

harness_json() { aws bedrock-agentcore-control get-harness --harness-id "$HARNESS_ID" --output json; }

guardrail_of() {  # guardrail_of <harness-json> → "<guardrail ARN> <version>"
  jq -r '.harness.model.bedrockModelConfig.additionalParams.guardrailConfig
         | "\(.guardrailIdentifier // "none") \(.guardrailVersion // "-")"' <<<"$1"
}

# Prints "active" or "absent". An IAM read failure is an error, never "absent".
incident_deny() {
  local names
  names="$(aws iam list-role-policies --role-name "$HARNESS_ROLE_NAME" --query PolicyNames --output json)" \
    || die "cannot read the inline policies of ${HARNESS_ROLE_NAME}; the incident deny state is unknown"
  jq -r --arg p "$DENY_POLICY" 'if index($p) != null then "active" else "absent" end' <<<"$names"
}

# UpdateHarness is a partial update: only the model block is sent, so the system prompt and tools stay as they are.
attach_guardrail() {  # attach_guardrail <guardrail-arn> <version> <evidence-name>
  local arn="$1" version="$2" name="$3" before after model_config status="" attempt
  before="$(harness_json)" || die "cannot read harness ${HARNESS_ID}; ${FALLBACK}"
  model_config="$(jq -c --arg id "$arn" --arg v "$version" --arg m "$MODEL_ID" '
      (.harness.model.bedrockModelConfig // {modelId:$m})
      | .additionalParams = ((.additionalParams // {}) + {guardrailConfig:{guardrailIdentifier:$id, guardrailVersion:$v, trace:"enabled"}})
      | {bedrockModelConfig: .}' <<<"$before")"
  aws bedrock-agentcore-control update-harness --harness-id "$HARNESS_ID" --model "$model_config" --output json \
    > "${EVIDENCE_DIR}/${name}_update_${STAMP}.json" || die "update-harness failed; ${FALLBACK}"
  for attempt in $(seq 1 "$POLL_ATTEMPTS"); do
    status="$(aws bedrock-agentcore-control get-harness --harness-id "$HARNESS_ID" --query harness.status --output text)" \
      || status="UNREADABLE"
    [[ "$status" == "READY" || "$status" == *FAILED* ]] && break
    sleep "$POLL_SECONDS"
  done
  [[ "$status" == "READY" ]] || die "harness status ${status} after ${attempt} checks; ${FALLBACK}"
  after="$(harness_json)" || die "cannot read harness ${HARNESS_ID} after the update; ${FALLBACK}"
  printf '%s\n' "$after" > "${EVIDENCE_DIR}/${name}_harness_${STAMP}.json"
  [[ "$(guardrail_of "$after")" == "${arn} ${version}" ]] \
    || die "harness is READY but uses guardrail $(guardrail_of "$after"), not ${arn##*/} version ${version}; ${FALLBACK}"
  log "harness ${HARNESS_ID} now uses guardrail ${arn##*/} version ${version} (evidence: ${name}_harness_${STAMP}.json)"
}

print_status() {
  local harness attached deny prompt alarms state="NORMAL"
  harness="$(harness_json)" || die "cannot read harness ${HARNESS_ID}; its state is unknown"
  deny="$(incident_deny)"
  alarms="$(aws cloudwatch describe-alarms --alarm-name-prefix NorthstarAssist --state-value ALARM \
              --query 'MetricAlarms[].AlarmName' --output json)" || die "cannot read the alarm states"
  attached="$(guardrail_of "$harness")"
  prompt="matches guardrail/system_prompt_v2.txt"
  [[ "$(jq -r '.harness.systemPrompt[0].text // ""' <<<"$harness")" == "$(cat "$PROMPT_FILE")" ]] || prompt="DIFFERS from guardrail/system_prompt_v2.txt"
  [[ "$attached" == "${GUARDRAIL_ARN} ${GUARDRAIL_VERSION}" && "$prompt" == matches* ]] || state="DRIFT (guardrail or prompt is not the approved one)"
  [[ "$attached" == "${LOCKDOWN_ARN} "* ]] && state="LOCKDOWN"
  [[ "$deny" == "active" ]] && state="STOPPED"
  echo "state:              ${state}"
  echo "attached guardrail: ${attached}"
  echo "system prompt:      ${prompt}"
  echo "tools:              $(jq -r '.harness.tools | length' <<<"$harness")"
  echo "incident IAM deny:  ${deny} (${DENY_POLICY} on ${HARNESS_ROLE_NAME})"
  echo "alarms in ALARM:    $(jq -r 'join(", ") | if . == "" then "none" else . end' <<<"$alarms")"
}

case "$MODE" in
  status) print_status ;;
  lockdown)
    confirm "Swap harness ${HARNESS_ID} to the lockdown guardrail? Every user will get the 'temporarily unavailable' message."
    attach_guardrail "$LOCKDOWN_ARN" "$LOCKDOWN_VERSION" ir_lockdown ;;
  restore)
    confirm "Re-attach the Northstar guardrail version ${GUARDRAIL_VERSION} to harness ${HARNESS_ID}?"
    attach_guardrail "$GUARDRAIL_ARN" "$GUARDRAIL_VERSION" ir_restore ;;
  stop)
    confirm "Deny role ${HARNESS_ROLE_NAME} every model invocation? The assistant will return errors until '$0 resume'."
    aws iam put-role-policy --role-name "$HARNESS_ROLE_NAME" --policy-name "$DENY_POLICY" --policy-document \
      '{"Version":"2012-10-17","Statement":[{"Sid":"IncidentStop","Effect":"Deny","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],"Resource":"*"}]}'
    log "inline policy ${DENY_POLICY} is on ${HARNESS_ROLE_NAME}; IAM can take up to a minute to apply it everywhere" ;;
  resume)
    if [[ "$(incident_deny)" == "absent" ]]; then
      log "no incident deny on ${HARNESS_ROLE_NAME}; nothing to remove"
    else
      confirm "Remove the incident deny from ${HARNESS_ROLE_NAME}?"
      aws iam delete-role-policy --role-name "$HARNESS_ROLE_NAME" --policy-name "$DENY_POLICY"
      log "removed ${DENY_POLICY} from ${HARNESS_ROLE_NAME}"
    fi ;;
esac
