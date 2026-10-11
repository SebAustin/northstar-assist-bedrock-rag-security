#!/usr/bin/env bash
# S6 (Task 7): controlled indirect prompt injection. Plants one clearly labelled synthetic document in the
# knowledge base, asks the assistant about it, then removes it. The bucket is versioned, so the planted
# version stays available as evidence after the delete.
#
# Usage: infra/06_poison_test.sh         plant, probe, clean (clean also runs if an earlier step fails)
#        infra/06_poison_test.sh plant   upload the document and sync the knowledge base
#        infra/06_poison_test.sh probe   run test case IND-01 three times
#        infra/06_poison_test.sh clean   delete the document, sync, and check that 30 documents remain
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

readonly MODE="${1:-all}"
case "$MODE" in
  all|plant|probe|clean) ;;
  *) die "usage: $0 [plant|probe|clean]" ;;
esac

require_lab_account
state_load
state_require BUCKET KB_ID KB_DATA_SOURCE_ID

# Defaults are variant A (a document that labels itself a test). Variant B, an unlabelled document:
#   POISON_DOC=test/northstar_workplace_faq.txt POISON_KEY=faq/northstar_workplace_faq.txt \
#   POISON_CASE=IND-02 POISON_LABEL=poisoned_unlabelled POISON_RUNS=5 infra/06_poison_test.sh
readonly LOCAL_DOC="${PROJECT_ROOT}/${POISON_DOC:-test/northstar_test_poisoned_faq.txt}"
readonly S3_KEY="${POISON_KEY:-test/northstar_test_poisoned_faq.txt}"
readonly CASE_ID="${POISON_CASE:-IND-01}"
readonly LABEL="${POISON_LABEL:-poisoned}"
readonly RUNS="${POISON_RUNS:-3}"
readonly EXPECTED_DOCS=30
readonly EVIDENCE_DIR="${PROJECT_ROOT}/evidence/task7"
readonly PYTHON="${PROJECT_ROOT}/.venv/bin/python"
readonly POLL_SECONDS=10
readonly POLL_ATTEMPTS=60
mkdir -p "$EVIDENCE_DIR"

object_count() { aws s3api list-objects-v2 --bucket "$BUCKET" --query 'length(Contents)' --output text; }

sync_kb() {  # sync_kb <evidence-name>: start an ingestion job and wait for COMPLETE with 0 failed documents
  local name="$1" job status="" failed attempt
  job="$(aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$KB_DATA_SOURCE_ID" \
           --query ingestionJob.ingestionJobId --output text)"
  log "ingestion job ${job} started"
  for attempt in $(seq 1 "$POLL_ATTEMPTS"); do
    status="$(aws bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$KB_DATA_SOURCE_ID" \
                --ingestion-job-id "$job" --query ingestionJob.status --output text)"
    [[ "$status" == "COMPLETE" || "$status" == "FAILED" || "$status" == "STOPPED" ]] && break
    sleep "$POLL_SECONDS"
  done
  aws bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$KB_DATA_SOURCE_ID" \
    --ingestion-job-id "$job" --output json > "${EVIDENCE_DIR}/${name}.json"
  [[ "$status" == "COMPLETE" ]] || die "ingestion job ${job} ended as ${status} after ${attempt} checks (see evidence/task7/${name}.json)"
  failed="$(jq -r '.ingestionJob.statistics.numberOfDocumentsFailed' "${EVIDENCE_DIR}/${name}.json")"
  [[ "$failed" == "0" ]] || die "ingestion job ${job} reported ${failed} failed documents"
  log "ingestion job ${job} COMPLETE: $(jq -c '.ingestionJob.statistics' "${EVIDENCE_DIR}/${name}.json")"
}

plant() {
  confirm "Upload the synthetic poisoned FAQ to s3://${BUCKET}/${S3_KEY} and sync the knowledge base?"
  [[ -f "$LOCAL_DOC" ]] || die "document ${LOCAL_DOC} not found"
  aws s3 cp "$LOCAL_DOC" "s3://${BUCKET}/${S3_KEY}" --only-show-errors
  # The label lives in an object tag, where the model cannot see it.
  aws s3api put-object-tagging --bucket "$BUCKET" --key "$S3_KEY" --tagging 'TagSet=[{Key=purpose,Value=security-test}]'
  sync_kb "ingestion_${LABEL}"
  log "planted; bucket now holds $(object_count) objects"
}

probe() {
  # A failing case is the finding this test exists to measure, not a script error.
  if "$PYTHON" "${PROJECT_ROOT}/tools/run_suite.py" --only "$CASE_ID" --runs "$RUNS" --label "$LABEL"; then
    log "${CASE_ID} passed ${RUNS} of ${RUNS}: the injected instruction was not followed"
  else
    log "${CASE_ID} did not pass ${RUNS} of ${RUNS}: see results/matrix_${LABEL}.md (recorded as a finding)"
  fi
}

clean() {
  local count
  aws s3 rm "s3://${BUCKET}/${S3_KEY}" --only-show-errors
  sync_kb "ingestion_${LABEL}_cleaned"
  count="$(object_count)"
  aws s3api list-object-versions --bucket "$BUCKET" --prefix "$S3_KEY" --output json > "${EVIDENCE_DIR}/${LABEL}_doc_versions.json"
  [[ "$count" == "$EXPECTED_DOCS" ]] || die "bucket holds ${count} objects after cleanup, expected ${EXPECTED_DOCS}"
  log "cleaned: ${count} documents, planted version kept in history (evidence/task7/${LABEL}_doc_versions.json)"
}

case "$MODE" in
  plant) plant ;;
  probe) probe ;;
  clean) clean ;;
  all)
    plant
    trap 'log "a step failed after the document was planted; removing it"; clean' ERR
    probe
    trap - ERR
    clean
    "$PYTHON" "${PROJECT_ROOT}/tools/run_suite.py" --only "$CASE_ID" --runs 1 --label "after_${LABEL}_cleanup" \
      || log "${CASE_ID} still fails after cleanup: check that the sync removed the document"
    ;;
esac
