#!/usr/bin/env bash
# S4 (Task 4): replace the broad console-generated policies on the harness, gateway and KB roles with
# the scoped documents in iam/after/, then prove the result with the IAM policy simulator.
#
# Each scoped document becomes a new default VERSION of the existing customer-managed policy. The
# original documents are kept in iam/before/, and --rollback re-applies them as a new version.
#
# Usage: infra/04_iam_harden.sh             apply + simulate
#        infra/04_iam_harden.sh --simulate  simulate the live roles only (labelled with --label, default "after")
#        infra/04_iam_harden.sh --rollback  re-apply the original documents from iam/before/
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account
state_load
state_require HARNESS_ROLE_NAME GATEWAY_ROLE_NAME KB_ROLE_NAME

MODE="apply"
LABEL="after"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --simulate) MODE="simulate"; shift ;;
    --rollback) MODE="rollback"; shift ;;
    --label)    LABEL="${2:?usage: --label <name>}"; shift 2 ;;
    *) die "unknown option: $1" ;;
  esac
done

readonly AFTER_DIR="${PROJECT_ROOT}/iam/after"
readonly EVIDENCE_DIR="${PROJECT_ROOT}/evidence/task4"
readonly ORIGINAL_VERSION="v1"
mkdir -p "$EVIDENCE_DIR"

# role-name | managed-policy-name-prefix | scoped document
readonly TARGETS=(
  "${HARNESS_ROLE_NAME}|AmazonBedrockAgentCoreHarnessExecutionPolicy|harness_execution_policy.json"
  "${GATEWAY_ROLE_NAME}|AmazonBedrockAgentCoreGatewayKBAccess|gateway_kb_access_policy.json"
  "${GATEWAY_ROLE_NAME}|AmazonBedrockAgentCoreGatewayBasePolicy|gateway_base_policy.json"
  "${KB_ROLE_NAME}|AmazonBedrockFoundationModelPolicyForKnowledgeBase|kb_foundation_model_policy.json"
)

policy_arn_for() {  # policy_arn_for <role> <policy-name-prefix>
  aws iam list-attached-role-policies --role-name "$1" \
    --query "AttachedPolicies[?starts_with(PolicyName, '$2')].PolicyArn | [0]" --output text
}

# Make <document> the default version of the managed policy <arn>.
# The lab denies iam:SetDefaultPolicyVersion, so every change (rollback included) is a new version.
# IAM keeps at most five versions: when full, the oldest non-default version other than v1 is pruned.
set_policy_document() {  # set_policy_document <policy-arn> <json-document-file>
  local arn="$1" document="$2" current version oldest
  current="$(aws iam get-policy --policy-arn "$arn" --query Policy.DefaultVersionId --output text)"
  if diff -q <(aws iam get-policy-version --policy-arn "$arn" --version-id "$current" \
                 --query PolicyVersion.Document --output json | jq -S .) <(jq -S . "$document") >/dev/null; then
    log "unchanged: ${arn##*/} already matches ${document#"$PROJECT_ROOT"/}"
    return 0
  fi
  if [[ "$(aws iam list-policy-versions --policy-arn "$arn" --query 'length(Versions)' --output text)" -ge 5 ]]; then
    oldest="$(aws iam list-policy-versions --policy-arn "$arn" --output json \
      | jq -r --arg keep "$ORIGINAL_VERSION" '[.Versions[] | select(.IsDefaultVersion | not) | select(.VersionId != $keep)] | sort_by(.CreateDate) | .[0].VersionId')"
    aws iam delete-policy-version --policy-arn "$arn" --version-id "$oldest"
    log "pruned ${arn##*/} ${oldest} to stay under the five-version limit"
  fi
  version="$(aws iam create-policy-version --policy-arn "$arn" --set-as-default \
               --policy-document "file://${document}" --query PolicyVersion.VersionId --output text)"
  log "set ${arn##*/} to ${document#"$PROJECT_ROOT"/} as ${version}"
}

apply_scoped_policies() {
  local target role prefix document arn
  for target in "${TARGETS[@]}"; do
    IFS='|' read -r role prefix document <<<"$target"
    arn="$(policy_arn_for "$role" "$prefix")"
    [[ "$arn" != "None" && -n "$arn" ]] || die "No policy starting with ${prefix} is attached to ${role}"
    set_policy_document "$arn" "${AFTER_DIR}/${document}"
  done
}

rollback_policies() {
  local target role prefix document arn original
  original="$(mktemp)"
  for target in "${TARGETS[@]}"; do
    IFS='|' read -r role prefix document <<<"$target"
    arn="$(policy_arn_for "$role" "$prefix")"
    jq .PolicyVersion.Document "${PROJECT_ROOT}/iam/before/${role}/managed_${arn##*/}.json" > "$original"
    set_policy_document "$arn" "$original"
  done
  rm -f "$original"
}

simulate_matrix() {
  local final="${EVIDENCE_DIR}/simulation_${LABEL}.jsonl" table="${EVIDENCE_DIR}/simulation_${LABEL}.md"
  local out="${final}.tmp"   # only replace the previous result once every row has been evaluated
  local row role_key role_var role_arn action resource context decision
  : > "$out"
  while read -r row; do
    role_key="$(jq -r .role <<<"$row")"
    role_var="${role_key}_ROLE_NAME"
    role_arn="$(aws iam get-role --role-name "${!role_var}" --query Role.Arn --output text)"
    action="$(jq -r .action <<<"$row")"
    resource="$(jq -r .resource <<<"$row")"
    context=()
    if jq -e '.context_profile' <<<"$row" >/dev/null; then
      context+=("ContextKeyName=bedrock:InferenceProfileArn,ContextKeyValues=$(jq -r .context_profile <<<"$row"),ContextKeyType=string")
    fi
    if jq -e '.context_guardrail' <<<"$row" >/dev/null; then
      context+=("ContextKeyName=bedrock:GuardrailIdentifier,ContextKeyValues=$(jq -r .context_guardrail <<<"$row"),ContextKeyType=string")
    fi
    if jq -e '.context_account' <<<"$row" >/dev/null; then
      context+=("ContextKeyName=aws:ResourceAccount,ContextKeyValues=$(jq -r .context_account <<<"$row"),ContextKeyType=string")
    fi
    decision="$(aws iam simulate-principal-policy --policy-source-arn "$role_arn" --action-names "$action" \
                  --resource-arns "$resource" ${context[@]+--context-entries "${context[@]}"} \
                  --query 'EvaluationResults[0].EvalDecision' --output text)"
    jq -nc --argjson r "$row" --arg d "$decision" '$r + {decision: $d, as_expected: (($d == "allowed") == ($r.expect == "allowed"))}' >> "$out"
  done < <(jq -c '.[]' "${PROJECT_ROOT}/iam/simulation_matrix.json")
  mv "$out" "$final"
  out="$final"
  {
    echo "| Role | Action | Resource | Why it matters | Decision |"
    echo "|---|---|---|---|---|"
    jq -r '"| \(.role) | `\(.action)` | `\(.resource | sub("arn:aws:"; ""))` | \(.why) | \(.decision) |"' "$out"
  } > "$table"
  log "simulation (${LABEL}): $(jq -s '[.[] | select(.decision == "allowed")] | length' "$out") allowed, $(jq -s '[.[] | select(.decision != "allowed")] | length' "$out") denied, $(jq -s '[.[] | select(.as_expected | not)] | length' "$out") differ from the hardened target → ${table#"$PROJECT_ROOT"/}"
}

case "$MODE" in
  simulate) simulate_matrix ;;
  rollback)
    confirm "Re-apply the original console-generated documents from iam/before/ to the four managed policies?"
    rollback_policies ;;
  apply)
    confirm "Apply the scoped policies in iam/after/ to ${HARNESS_ROLE_NAME}, ${GATEWAY_ROLE_NAME} and ${KB_ROLE_NAME}?"
    apply_scoped_policies
    log "waiting 15 s for IAM to propagate"
    sleep 15
    for role in "$HARNESS_ROLE_NAME" "$GATEWAY_ROLE_NAME" "$KB_ROLE_NAME"; do
      rm -rf "${EVIDENCE_DIR}/roles_after/${role}"
      dump_role "$role" "${EVIDENCE_DIR}/roles_after"
    done
    simulate_matrix
    log "Next: .venv/bin/python tools/run_suite.py --smoke --label after_iam && .venv/bin/python tools/override_probe.py --label after_hardening" ;;
esac
