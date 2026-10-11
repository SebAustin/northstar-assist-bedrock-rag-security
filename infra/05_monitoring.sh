#!/usr/bin/env bash
# S5 (Task 6): model-invocation logging, AI-specific metric filters and CloudWatch alarms.
#
# Usage: infra/05_monitoring.sh logging   turn on Bedrock model-invocation logging (run this first)
#        infra/05_monitoring.sh filters   create metric filters, alarms and saved queries from monitoring/*.json
#        infra/05_monitoring.sh status    save the current configuration and alarm states as evidence
#
# "filters" is a separate step on purpose: the filter patterns in monitoring/metric_filters.json were
# written against real log records, which only exist after "logging" has been on for some traffic.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account
state_load
state_require HARNESS_ROLE_NAME KB_ROLE_NAME

readonly LOG_GROUP="/northstar/bedrock/invocations"
readonly RETENTION_DAYS=7          # long enough for incident triage, short enough to limit how long PII sits in logs
readonly LOGGING_ROLE="NorthstarBedrockInvocationLoggingRole"
readonly NAMESPACE="Northstar/Assist"
readonly MON_DIR="${NORTHSTAR_MONITORING_DIR:-${PROJECT_ROOT}/monitoring}"
readonly EVIDENCE_DIR="${EVIDENCE_ROOT}/task6"
mkdir -p "$EVIDENCE_DIR"

enable_logging() {
  confirm "Create log group ${LOG_GROUP}, role ${LOGGING_ROLE}, and turn on Bedrock model-invocation logging?"
  if [[ "$(aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
             --query "length(logGroups[?logGroupName=='${LOG_GROUP}'])" --output text)" == "0" ]]; then
    aws logs create-log-group --log-group-name "$LOG_GROUP"
  else
    log "log group ${LOG_GROUP} already exists"
  fi
  aws logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days "$RETENTION_DAYS"
  aws logs tag-log-group --log-group-name "$LOG_GROUP" --tags project=northstar-assist 2>/dev/null || true

  local trust policy role_arn
  trust="$(jq -n --arg a "$ACCOUNT_ID" --arg r "$AWS_REGION" '{Version:"2012-10-17",Statement:[{
    Effect:"Allow", Principal:{Service:"bedrock.amazonaws.com"}, Action:"sts:AssumeRole",
    Condition:{StringEquals:{"aws:SourceAccount":$a}, ArnLike:{"aws:SourceArn":("arn:aws:bedrock:"+$r+":"+$a+":*")}}}]}')"
  if ! aws iam get-role --role-name "$LOGGING_ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$LOGGING_ROLE" --assume-role-policy-document "$trust" \
      --description "Lets Bedrock write model-invocation logs to ${LOG_GROUP} only" \
      --tags Key=project,Value=northstar-assist >/dev/null
    log "created role ${LOGGING_ROLE}"
  fi
  policy="$(jq -n --arg a "$ACCOUNT_ID" --arg r "$AWS_REGION" --arg g "$LOG_GROUP" '{Version:"2012-10-17",Statement:[{
    Sid:"WriteInvocationLogsOnly", Effect:"Allow", Action:["logs:CreateLogStream","logs:PutLogEvents"],
    Resource:("arn:aws:logs:"+$r+":"+$a+":log-group:"+$g+":log-stream:aws/bedrock/modelinvocations")}]}')"
  aws iam put-role-policy --role-name "$LOGGING_ROLE" --policy-name WriteInvocationLogs --policy-document "$policy"
  role_arn="$(aws iam get-role --role-name "$LOGGING_ROLE" --query Role.Arn --output text)"
  state_set INVOCATION_LOG_GROUP "$LOG_GROUP"

  sleep 10   # a brand-new role must propagate before Bedrock can assume it
  aws bedrock put-model-invocation-logging-configuration --logging-config \
    "cloudWatchConfig={logGroupName=${LOG_GROUP},roleArn=${role_arn}},textDataDeliveryEnabled=true,imageDataDeliveryEnabled=false,embeddingDataDeliveryEnabled=false,videoDataDeliveryEnabled=false,audioDataDeliveryEnabled=false"
  log "model-invocation logging is on → ${LOG_GROUP} (retention ${RETENTION_DAYS} days)"
  save_status
}

# A loop fed by `< <(jq ...)` runs zero times when jq fails and the script still exits 0. So every definition
# file is checked here, before the first AWS call: a typo must stop the run, not silently skip an alarm
# (or delete the saved queries and recreate none).
validate_definitions() {
  local file rule
  for rule in \
    'metric_filters.json|type == "array" and length > 0 and all(.[]; (.name|type) == "string" and (.metric|type) == "string" and (.value|type) == "string" and (.pattern|type) == "string" and (.pattern|length) > 0)' \
    'alarms.json|type == "array" and length > 0 and all(.[]; (.AlarmName|type) == "string" and has("Threshold") and has("ComparisonOperator"))' \
    'saved_queries.json|type == "array" and length > 0 and all(.[]; (.name|type) == "string" and (.query|type) == "string" and (.query|length) > 0)'
  do
    file="${MON_DIR}/${rule%%|*}"
    [[ -f "$file" ]] || die "${rule%%|*} is missing from ${MON_DIR}"
    jq -e "${rule#*|}" "$file" >/dev/null 2>&1 \
      || die "${rule%%|*} is not valid: it must be a JSON array whose entries all have the required fields. Nothing was changed."
  done
}

create_filters_and_alarms() {
  validate_definitions
  confirm "Create metric filters and alarms from monitoring/*.json?"
  local row
  while read -r row; do
    aws logs put-metric-filter --log-group-name "$LOG_GROUP" \
      --filter-name "$(jq -r .name <<<"$row")" \
      --filter-pattern "$(jq -r .pattern <<<"$row" | sed "s|__HARNESS_ROLE__|${HARNESS_ROLE_NAME}|g; s|__KB_ROLE__|${KB_ROLE_NAME}|g")" \
      --metric-transformations "$(jq -c --arg ns "$NAMESPACE" '[{metricName:.metric, metricNamespace:$ns, metricValue:.value, unit:(.unit // "Count")} + (if .default_zero then {defaultValue:0} else {} end)]' <<<"$row")"
    log "metric filter $(jq -r .name <<<"$row") → ${NAMESPACE}/$(jq -r .metric <<<"$row")"
  done < <(jq -c '.[]' "${MON_DIR}/metric_filters.json")

  while read -r row; do
    aws cloudwatch put-metric-alarm --cli-input-json "$(jq -c 'del(._comment)' <<<"$row")"
    log "alarm $(jq -r .AlarmName <<<"$row")"
  done < <(jq -c '.[]' "${MON_DIR}/alarms.json")

  local stale
  for stale in $(aws logs describe-query-definitions --query-definition-name-prefix "NorthstarAssist" \
                   --query 'queryDefinitions[].queryDefinitionId' --output text); do
    aws logs delete-query-definition --query-definition-id "$stale" >/dev/null   # replace, never duplicate
  done
  while read -r row; do
    aws logs put-query-definition --name "$(jq -r .name <<<"$row")" --log-group-names "$LOG_GROUP" \
      --query-string "$(jq -r .query <<<"$row" | sed "s|__HARNESS_ROLE__|${HARNESS_ROLE_NAME}|g")" >/dev/null
    log "saved query $(jq -r .name <<<"$row")"
  done < <(jq -c '.[]' "${MON_DIR}/saved_queries.json")
  save_status
}

save_status() {
  evidence task6 invocation_logging_config bedrock get-model-invocation-logging-configuration
  evidence task6 log_group logs describe-log-groups --log-group-name-prefix "$LOG_GROUP"
  evidence task6 metric_filters logs describe-metric-filters --log-group-name "$LOG_GROUP"
  evidence task6 alarms cloudwatch describe-alarms --alarm-name-prefix NorthstarAssist
  dump_role "$LOGGING_ROLE" "${EVIDENCE_DIR}/roles" 2>/dev/null || true
}

case "${1:-}" in
  logging) enable_logging ;;
  filters) create_filters_and_alarms ;;
  status)  save_status ;;
  *) die "usage: $0 logging|filters|status" ;;
esac
