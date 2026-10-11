#!/usr/bin/env bash
# S1: create the private, encrypted, versioned document bucket and upload all 30 Northstar docs.
# Idempotent: re-running reuses the bucket stored in infra/state.env.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
require_lab_account
state_load

readonly DOCS_DIR="${PROJECT_ROOT}/starter/northstar-knowledge-base"
readonly EXPECTED_DOCS=30

local_count="$(find "$DOCS_DIR" -type f ! -name '.*' | wc -l | tr -d ' ')"
[[ "$local_count" == "$EXPECTED_DOCS" ]] || die "Expected ${EXPECTED_DOCS} local docs, found ${local_count}"

if [[ -z "${BUCKET:-}" ]]; then
  BUCKET="northstar-assist-kb-$(openssl rand -hex 4)"   # random suffix: no personal info in names
fi

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  log "bucket ${BUCKET} already exists; reusing it"
else
  confirm "Create S3 bucket ${BUCKET} in ${AWS_REGION} and upload ${EXPECTED_DOCS} docs?"
  aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" >/dev/null
  log "created ${BUCKET}"
fi
state_set BUCKET "$BUCKET"

aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
# Versioning gives IR an audit trail of every document change (poisoning investigations).
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=project,Value=northstar-assist}]'

aws s3 sync "$DOCS_DIR/" "s3://${BUCKET}/" --exclude ".*" --only-show-errors

remote_count="$(aws s3api list-objects-v2 --bucket "$BUCKET" --query 'length(Contents)' --output text)"
[[ "$remote_count" == "$EXPECTED_DOCS" ]] || die "Bucket holds ${remote_count} objects, expected ${EXPECTED_DOCS}"
log "verified ${remote_count}/${EXPECTED_DOCS} documents in s3://${BUCKET}/"

evidence task1 s3_objects        s3api list-objects-v2 --bucket "$BUCKET" --query 'Contents[].{Key:Key,Size:Size}'
evidence task1 s3_versioning     s3api get-bucket-versioning --bucket "$BUCKET"
evidence task1 s3_encryption     s3api get-bucket-encryption --bucket "$BUCKET"
evidence task1 s3_public_access  s3api get-public-access-block --bucket "$BUCKET"
log "Next: follow infra/CONSOLE_CHECKLIST.md §1 using S3 URI s3://${BUCKET}/"
