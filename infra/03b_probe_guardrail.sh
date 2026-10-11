#!/usr/bin/env bash
# S3 (Task 5): exercise every guardrail control directly with ApplyGuardrail, input and output side,
# independent of the model. Writes evidence/task5/guardrail_probes.jsonl and a Markdown table.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account
state_load
state_require GUARDRAIL_ID GUARDRAIL_VERSION

readonly PROBES="${PROJECT_ROOT}/guardrail/probes.json"
readonly OUT="${PROJECT_ROOT}/evidence/task5/guardrail_probes.jsonl"
readonly TABLE="${PROJECT_ROOT}/evidence/task5/guardrail_probes.md"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

while read -r probe; do
  text="$(jq -r .text <<<"$probe")"
  source_side="$(jq -r .source <<<"$probe")"
  response="$(aws bedrock-runtime apply-guardrail --guardrail-identifier "$GUARDRAIL_ID" \
    --guardrail-version "$GUARDRAIL_VERSION" --source "$source_side" --output-scope FULL \
    --content "$(jq -nc --arg t "$text" '[{text:{text:$t}}]')" --output json)"
  jq -nc --argjson p "$probe" --argjson r "$response" '
    $p + {
      action: $r.action,
      output: ([$r.outputs[]?.text] | join(" ")),
      triggered: ([
        ($r.assessments[].topicPolicy.topics[]? | select(.detected) | "topic:" + .name),
        ($r.assessments[].contentPolicy.filters[]? | select(.detected) | "content:" + .type),
        ($r.assessments[].sensitiveInformationPolicy.piiEntities[]? | select(.detected) | "pii:" + .type + "=" + .action),
        ($r.assessments[].sensitiveInformationPolicy.regexes[]? | select(.detected) | "regex:" + .name + "=" + .action),
        ($r.assessments[].wordPolicy.managedWordLists[]? | select(.detected) | "word:" + .type)
      ] | unique),
      passed: ($r.action == $p.expect)
    }' >> "$OUT"
done < <(jq -c '.[]' "$PROBES")

{
  echo "| ID | Control | Side | Expected | Observed | Triggered by | Result |"
  echo "|---|---|---|---|---|---|---|"
  jq -r '"| \(.id) | \(.control) | \(.source) | \(.expect) | \(.action) | \(.triggered | join(", ")) | \(if .passed then "PASS" else "FAIL" end) |"' "$OUT"
} > "$TABLE"
cat "$TABLE"
failed="$(jq -s '[.[] | select(.passed | not)] | length' "$OUT")"
log "$(jq -s length "$OUT") probes, ${failed} not as expected → evidence/task5/guardrail_probes.{jsonl,md}"
