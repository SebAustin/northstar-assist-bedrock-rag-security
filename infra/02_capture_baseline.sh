#!/usr/bin/env bash
# S1: verify the console-created KB, gateway and harness, and snapshot their default IAM roles.
# Read-only. Prerequisite: infra/set_state.sh HARNESS_ARN <arn>; infra/set_state.sh GATEWAY_ID <id>;
#                           infra/set_state.sh KB_ID <id>  (KB_ROLE_NAME is optional)
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account
state_load
state_require HARNESS_ARN GATEWAY_ID KB_ID

harness_id="${HARNESS_ARN##*/}"
evidence task1 harness        bedrock-agentcore-control get-harness --harness-id "$harness_id"
evidence task1 gateway        bedrock-agentcore-control get-gateway --gateway-identifier "$GATEWAY_ID"
evidence task1 gateway_targets bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GATEWAY_ID"

harness_json="${PROJECT_ROOT}/evidence/task1/harness.json"
gateway_json="${PROJECT_ROOT}/evidence/task1/gateway.json"
[[ "$(jq -r '.status // .harness.status // empty' "$harness_json")" =~ READY|ACTIVE ]] \
  || log "WARNING: harness status is not READY: $(jq -c '.status // .harness.status' "$harness_json")"

harness_role_arn="$(jq -r '.. | .executionRoleArn? // empty' "$harness_json" | head -1)"
gateway_role_arn="$(jq -r '.roleArn // empty' "$gateway_json")"
[[ -n "$harness_role_arn" && -n "$gateway_role_arn" ]] || die "Could not read role ARNs from get-harness/get-gateway output"
state_set HARNESS_ROLE_NAME "$(role_name_from_arn "$harness_role_arn")"
state_set GATEWAY_ROLE_NAME "$(role_name_from_arn "$gateway_role_arn")"
state_set GATEWAY_ARN "$(jq -r '.gatewayArn' "$gateway_json")"
state_set MODEL_ID "$(jq -r '.. | .bedrockModelConfig?.modelId // empty' "$harness_json" | head -1)"
state_load

for target_id in $(jq -r '.items[].targetId' "${PROJECT_ROOT}/evidence/task1/gateway_targets.json"); do
  evidence task1 "gateway_target_${target_id}" bedrock-agentcore-control get-gateway-target \
    --gateway-identifier "$GATEWAY_ID" --target-id "$target_id"
done

if [[ ! -d "${PROJECT_ROOT}/iam/before/${HARNESS_ROLE_NAME}" ]]; then   # never overwrite the original baseline
  dump_role "$HARNESS_ROLE_NAME" "${PROJECT_ROOT}/iam/before"
  dump_role "$GATEWAY_ROLE_NAME" "${PROJECT_ROOT}/iam/before"
  [[ -n "${KB_ROLE_NAME:-}" ]] && dump_role "$KB_ROLE_NAME" "${PROJECT_ROOT}/iam/before"
else
  log "iam/before already captured; leaving the original baseline untouched"
fi

# A3 conditional: Managed KBs may or may not be visible through the classic bedrock-agent API.
if aws bedrock-agent get-knowledge-base --knowledge-base-id "$KB_ID" --output json \
     > "${PROJECT_ROOT}/evidence/task1/knowledge_base.json" 2>/dev/null; then
  evidence task1 kb_ingestion_jobs bedrock-agent list-ingestion-jobs --knowledge-base-id "$KB_ID" \
    --data-source-id "$(aws bedrock-agent list-data-sources --knowledge-base-id "$KB_ID" --query 'dataSourceSummaries[0].dataSourceId' --output text)"
else
  rm -f "${PROJECT_ROOT}/evidence/task1/knowledge_base.json"
  log "KB not visible to bedrock-agent API (Managed KB). Use the console sync screenshot (checklist §1)."
fi

# Runtime-log probe (PLAN S1 / R1): do tool-call events land in CloudWatch?
evidence task1 runtime_log_groups logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/
log "Baseline captured. Run: .venv/bin/python tools/run_suite.py --smoke"
