#!/usr/bin/env bash
# S8: remove every AWS resource this project created in the Cloud Lab account, then verify nothing is left.
#
# Usage: infra/99_teardown.sh --plan   list what exists; changes nothing
#        infra/99_teardown.sh          delete everything (asks first), then list what is left
#
# Order matters: things that use a resource go before the resource (harness before gateway, gateway before
# knowledge base, roles last). Every step skips what is already gone, so the script can be re-run. A step that
# fails is recorded and the run continues; the final inventory is the result, and the exit code is non-zero
# if anything is left. The lab's own roles and policies (voclabs, Pvoclabs*, voc-cancel-cred) and the AWS
# service-linked role are never touched.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

MODE="delete"
case "${1:-}" in
  "") ;;
  --plan) MODE="plan" ;;
  *) die "usage: $0 [--plan]" ;;
esac

require_lab_account
state_load
state_require BUCKET KB_ID KB_DATA_SOURCE_ID GATEWAY_ID HARNESS_ARN HARNESS_ROLE_NAME GATEWAY_ROLE_NAME KB_ROLE_NAME \
  GUARDRAIL_ID LOCKDOWN_ID

readonly HARNESS_ID="${HARNESS_ARN##*/}"
readonly LOGGING_ROLE="NorthstarBedrockInvocationLoggingRole"
readonly ROLES=("$HARNESS_ROLE_NAME" "$GATEWAY_ROLE_NAME" "$KB_ROLE_NAME" "$LOGGING_ROLE")
readonly LOG_GROUPS=("/northstar/bedrock/invocations" "/aws/vendedlogs/bedrock/knowledge-base/APPLICATION_LOGS/${KB_ID}")
readonly RUNTIME_LOG_PREFIX="/aws/bedrock-agentcore/runtimes/harness_NorthstarAssist"
readonly WAIT_SECONDS="${TEARDOWN_WAIT_SECONDS:-10}"
readonly WAIT_ATTEMPTS=30
FAILED=()

# attempt <description> <command...>: run a step; on failure record it and carry on.
attempt() {
  local what="$1"; shift
  if "$@" >/dev/null 2>"${TMPDIR:-/tmp}/northstar_teardown.err"; then
    log "done: ${what}"
  else
    FAILED+=("${what}: $(tr '\n' ' ' < "${TMPDIR:-/tmp}/northstar_teardown.err" | cut -c1-200)")
    log "FAILED: ${what}"
  fi
}

# wait_gone <description> <command that prints something while the resource still exists>
wait_gone() {
  local what="$1" attempt_no; shift
  for attempt_no in $(seq 1 "$WAIT_ATTEMPTS"); do
    [[ -z "$("$@" 2>/dev/null || true)" ]] && return 0
    sleep "$WAIT_SECONDS"
  done
  FAILED+=("${what} still exists after ${attempt_no} checks")
}

# ------------------------------------------------------------------ inventory (read-only)
harness_present()   { aws bedrock-agentcore-control list-harnesses --output json | jq -r --arg id "$HARNESS_ID" '.. | objects | select(.harnessId? == $id) | .harnessId'; }
runtimes_present()  { aws bedrock-agentcore-control list-agent-runtimes --query "agentRuntimes[?starts_with(agentRuntimeName, 'harness_NorthstarAssist')].agentRuntimeId" --output text; }
gateway_present()   { aws bedrock-agentcore-control list-gateways --query "items[?gatewayId=='${GATEWAY_ID}'].gatewayId" --output text; }
targets_present()   { if [[ -n "$(gateway_present)" ]]; then aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID" --query 'items[].targetId' --output text; fi; }
identities_present(){ aws bedrock-agentcore-control list-workload-identities --query "workloadIdentities[?starts_with(name, 'harness_NorthstarAssist') || name=='${GATEWAY_ID}'].name" --output text; }
kb_present()        { aws bedrock-agent list-knowledge-bases --query "knowledgeBaseSummaries[?knowledgeBaseId=='${KB_ID}'].knowledgeBaseId" --output text; }
guardrails_present(){ aws bedrock list-guardrails --query "guardrails[?id=='${GUARDRAIL_ID}' || id=='${LOCKDOWN_ID}'].id" --output text; }
logging_present()   { aws bedrock get-model-invocation-logging-configuration --query 'loggingConfig.cloudWatchConfig.logGroupName' --output text | grep -v '^None$' || true; }
alarms_present()    { aws cloudwatch describe-alarms --alarm-name-prefix NorthstarAssist --query 'MetricAlarms[].AlarmName' --output text; }
queries_present()   { aws logs describe-query-definitions --query-definition-name-prefix NorthstarAssist --query 'queryDefinitions[].queryDefinitionId' --output text; }
log_groups_present(){
  local group
  for group in "${LOG_GROUPS[@]}" "$RUNTIME_LOG_PREFIX"; do
    aws logs describe-log-groups --log-group-name-prefix "$group" --query 'logGroups[].logGroupName' --output text
  done | tr '\t' '\n' | sed '/^$/d'
}
kb_deliveries()     { aws logs describe-delivery-sources --output json | jq -r --arg kb "$KB_ID" '.deliverySources[]? | select((.resourceArns // []) | any(contains($kb))) | .name'; }
kb_delivery_dests() { aws logs describe-delivery-destinations --output json | jq -r --arg kb "$KB_ID" '.deliveryDestinations[]? | select((.deliveryDestinationConfiguration.destinationResourceArn // "") | contains($kb)) | .name'; }
bucket_present()    { aws s3api list-buckets --query "Buckets[?Name=='${BUCKET}'].Name" --output text; }
roles_present()     { local role; for role in "${ROLES[@]}"; do aws iam get-role --role-name "$role" --query Role.RoleName --output text 2>/dev/null || true; done; }
policies_present()  { aws iam list-policies --scope Local --query "Policies[?starts_with(PolicyName, 'AmazonBedrock')].PolicyName" --output text; }

inventory() {  # prints "<kind>: <names>" for everything that still exists; prints nothing when the account is clean
  local kind found
  for kind in harness runtimes gateway targets identities kb guardrails logging alarms queries log_groups bucket roles policies; do
    found="$("${kind}_present" | tr '\t\n' '  ' | sed 's/ *$//')"
    [[ -n "$found" ]] && echo "${kind}: ${found}"
  done
  found="$( { kb_deliveries; kb_delivery_dests; } | tr '\n' ' ' | sed 's/ *$//')"
  [[ -n "$found" ]] && echo "log deliveries: ${found}"
  return 0
}

# ------------------------------------------------------------------ deletion steps
delete_monitoring() {
  local names id
  names="$(alarms_present)"
  # shellcheck disable=SC2086  # alarm names contain no spaces; one argument per name is intended
  [[ -n "$names" ]] && attempt "delete alarms" aws cloudwatch delete-alarms --alarm-names $names
  for id in $(queries_present); do attempt "delete saved query ${id}" aws logs delete-query-definition --query-definition-id "$id"; done
  [[ -n "$(logging_present)" ]] && attempt "turn off model-invocation logging" aws bedrock delete-model-invocation-logging-configuration
  return 0
}

delete_agent() {
  local id
  if [[ -n "$(harness_present)" ]]; then
    attempt "delete harness ${HARNESS_ID}" aws bedrock-agentcore-control delete-harness --harness-id "$HARNESS_ID"
    wait_gone "harness ${HARNESS_ID}" harness_present
  fi
  for id in $(runtimes_present); do   # normally removed with the harness
    attempt "delete runtime ${id}" aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id "$id"
  done
  wait_gone "harness runtime" runtimes_present
  for id in $(targets_present); do
    attempt "delete gateway target ${id}" aws bedrock-agentcore-control delete-gateway-target --gateway-identifier "$GATEWAY_ID" --target-id "$id"
  done
  wait_gone "gateway targets" targets_present
  if [[ -n "$(gateway_present)" ]]; then
    attempt "delete gateway ${GATEWAY_ID}" aws bedrock-agentcore-control delete-gateway --gateway-identifier "$GATEWAY_ID"
    wait_gone "gateway ${GATEWAY_ID}" gateway_present
  fi
  for id in $(identities_present); do   # normally removed with the harness and the gateway
    attempt "delete workload identity ${id}" aws bedrock-agentcore-control delete-workload-identity --name "$id"
  done
}

delete_knowledge_base() {
  if [[ -n "$(kb_present)" ]]; then
    attempt "delete data source ${KB_DATA_SOURCE_ID}" aws bedrock-agent delete-data-source --knowledge-base-id "$KB_ID" --data-source-id "$KB_DATA_SOURCE_ID"
    wait_gone "data source ${KB_DATA_SOURCE_ID}" aws bedrock-agent list-data-sources --knowledge-base-id "$KB_ID" --query 'dataSourceSummaries[].dataSourceId' --output text
    attempt "delete knowledge base ${KB_ID}" aws bedrock-agent delete-knowledge-base --knowledge-base-id "$KB_ID"
    wait_gone "knowledge base ${KB_ID}" kb_present
  fi
}

delete_guardrails() {
  local id
  for id in $(guardrails_present); do attempt "delete guardrail ${id}" aws bedrock delete-guardrail --guardrail-identifier "$id"; done
}

delete_logs() {
  local source id group
  for source in $(kb_deliveries); do
    for id in $(aws logs describe-deliveries --query "deliveries[?deliverySourceName=='${source}'].id" --output text); do
      attempt "delete log delivery ${id}" aws logs delete-delivery --id "$id"
    done
    attempt "delete log delivery source ${source}" aws logs delete-delivery-source --name "$source"
  done
  for id in $(kb_delivery_dests); do
    attempt "delete log delivery destination ${id}" aws logs delete-delivery-destination --name "$id"
  done
  while read -r group; do
    [[ -n "$group" ]] && attempt "delete log group ${group}" aws logs delete-log-group --log-group-name "$group"
  done < <(log_groups_present)
  return 0
}

delete_bucket() {
  [[ -n "$(bucket_present)" ]] || return 0
  local batch
  while :; do   # a versioned bucket is only empty when every version and delete marker is gone
    batch="$(aws s3api list-object-versions --bucket "$BUCKET" --max-items 500 --output json \
      | jq -c '{Objects: ([.Versions[]?, .DeleteMarkers[]?] | map({Key, VersionId})), Quiet: true}')"
    [[ "$(jq '.Objects | length' <<<"$batch")" == "0" ]] && break
    aws s3api delete-objects --bucket "$BUCKET" --delete "$batch" >/dev/null || { FAILED+=("empty bucket ${BUCKET}"); return 0; }
  done
  attempt "delete bucket ${BUCKET}" aws s3api delete-bucket --bucket "$BUCKET"
}

delete_roles() {
  local role name arn version
  for role in $(roles_present); do
    for name in $(aws iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text); do
      attempt "delete inline policy ${name} on ${role}" aws iam delete-role-policy --role-name "$role" --policy-name "$name"
    done
    for arn in $(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text); do
      attempt "detach ${arn##*/} from ${role}" aws iam detach-role-policy --role-name "$role" --policy-arn "$arn"
      [[ "$arn" == *":policy/service-role/AmazonBedrock"* ]] || continue   # only the policies the console created for these roles
      for version in $(aws iam list-policy-versions --policy-arn "$arn" --query 'Versions[?!IsDefaultVersion].VersionId' --output text); do
        attempt "delete ${arn##*/} ${version}" aws iam delete-policy-version --policy-arn "$arn" --version-id "$version"
      done
      attempt "delete policy ${arn##*/}" aws iam delete-policy --policy-arn "$arn"
    done
    attempt "delete role ${role}" aws iam delete-role --role-name "$role"
  done
}

# ------------------------------------------------------------------ main
if [[ "$MODE" == "plan" ]]; then
  echo "Resources that exist now and would be deleted:"
  inventory
  exit 0
fi

mkdir -p "${EVIDENCE_ROOT}/teardown"
echo "This deletes every Northstar Assist resource in account ${ACCOUNT_ID}:"
inventory | tee "${EVIDENCE_ROOT}/teardown/before.txt"   # also the resource-name list reviewed for personal data
confirm "Delete all of the above? Evidence in this repository is not affected."
delete_monitoring
delete_agent
delete_knowledge_base
delete_guardrails
delete_logs
delete_bucket
delete_roles

mkdir -p "${EVIDENCE_ROOT}/teardown"
left="$(inventory)"
{ echo "Teardown run at $(date -u +%Y-%m-%dT%H:%M:%SZ) in account ${ACCOUNT_ID}"
  echo "Remaining resources: ${left:-none}"
  echo "Steps that failed: ${#FAILED[@]}"
  if [[ "${#FAILED[@]}" -gt 0 ]]; then printf '  - %s\n' "${FAILED[@]}"; fi
} | tee "${EVIDENCE_ROOT}/teardown/result.txt"
[[ -z "$left" ]] || die "resources remain; fix the cause or delete them in the console, then re-run $0"
log "teardown complete: nothing left"
