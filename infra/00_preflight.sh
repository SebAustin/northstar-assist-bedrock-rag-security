#!/usr/bin/env bash
# S0 preflight: what can these Cloud Lab credentials actually do?
# Read-only, apart from one ~5-token Haiku call to confirm model access.
# Writes evidence/preflight.json. Never fails part-way: each probe records ALLOW or DENY.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account

readonly HAIKU_PROFILE="us.anthropic.claude-haiku-4-5-20251001-v1:0"
readonly OUT="${PROJECT_ROOT}/evidence/preflight.json"
RESULTS="$(mktemp)"; readonly RESULTS
trap 'rm -f "$RESULTS"' EXIT
mkdir -p "$(dirname "$OUT")"

record() {  # record <probe> <ALLOW|DENY> [error]
  jq -nc --arg p "$1" --arg r "$2" --arg e "${3:-}" \
    '{probe:$p, result:$r} + (if $e == "" then {} else {error:($e[0:240])} end)' >> "$RESULTS"
  log "$(printf '%-5s %s %s' "$2" "$1" "${3:0:120}")"
}

probe() {  # probe <label> <aws args...>
  local label="$1" err; shift
  if err="$(aws "$@" --output json 2>&1 >/dev/null)"; then
    record "$label" ALLOW
  else
    record "$label" DENY "$err"
  fi
}

readonly TINY_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::example/*"}]}'
readonly HELLO_MSG='[{"role":"user","content":[{"text":"Reply OK"}]}]'
readonly MAX5='{"maxTokens":5}'

probe "bedrock:ListGuardrails"                        bedrock list-guardrails --max-results 1
probe "bedrock:GetModelInvocationLoggingConfiguration" bedrock get-model-invocation-logging-configuration
probe "bedrock:GetInferenceProfile"                   bedrock get-inference-profile --inference-profile-identifier "$HAIKU_PROFILE"
probe "agentcore:ListHarnesses"                       bedrock-agentcore-control list-harnesses
probe "agentcore:ListGateways"                        bedrock-agentcore-control list-gateways
probe "logs:DescribeLogGroups"                        logs describe-log-groups --limit 1
probe "cloudwatch:DescribeAlarms"                     cloudwatch describe-alarms --max-records 1
probe "access-analyzer:ValidatePolicy"                accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document "$TINY_POLICY"
probe "bedrock-runtime:Converse(Haiku 4.5)"           bedrock-runtime converse --model-id "$HAIKU_PROFILE" --messages "$HELLO_MSG" --inference-config "$MAX5"

# Write permissions can't be probed without writing, so we ask the IAM policy simulator (which may itself be denied).
caller_arn="$(aws sts get-caller-identity --query Arn --output text)"
sim_arn="$caller_arn"
if [[ "$caller_arn" == *":assumed-role/"* ]]; then
  sim_arn="arn:aws:iam::${ACCOUNT_ID}:role/$(cut -d/ -f2 <<<"$caller_arn")"
fi
readonly WRITE_ACTIONS=(
  iam:CreateRole iam:PassRole iam:PutRolePolicy iam:DeleteRolePolicy iam:DetachRolePolicy
  bedrock:CreateGuardrail bedrock:PutModelInvocationLoggingConfiguration
  logs:CreateLogGroup logs:PutMetricFilter cloudwatch:PutMetricAlarm
  bedrock-agentcore:UpdateHarness s3:CreateBucket s3:PutBucketVersioning
)
sim_file="${PROJECT_ROOT}/evidence/preflight_simulation.json"
if sim_err="$(aws iam simulate-principal-policy --policy-source-arn "$sim_arn" \
      --action-names "${WRITE_ACTIONS[@]}" --output json 2>&1 >"$sim_file")"; then
  record "iam:SimulatePrincipalPolicy" ALLOW
  jq -r '.EvaluationResults[] | "  \(.EvalDecision)\t\(.EvalActionName)"' "$sim_file" >&2
else
  rm -f "$sim_file"
  record "iam:SimulatePrincipalPolicy" DENY "$sim_err"
  log "Write access will be discovered by the gated scripts themselves."
fi

jq -s --arg acct "...${ACCOUNT_ID: -4}" --arg region "$AWS_REGION" \
  '{account_suffix:$acct, region:$region, probes:.}' "$RESULTS" > "$OUT"
log "wrote evidence/preflight.json"
if jq -e '.probes | any(.result == "DENY")' "$OUT" >/dev/null; then
  log "Some probes were denied. See the PLAN.md S0 fallback rule."
else
  log "All probes allowed."
fi
