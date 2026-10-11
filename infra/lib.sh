# shellcheck shell=bash
# Shared helpers for Northstar Assist infra scripts. Source, don't execute.
#
# Every script calls require_lab_account first, so nothing can ever touch the
# personal AWS account: commands only run against the Udacity Cloud Lab
# profile in us-east-1.

set -euo pipefail

readonly LAB_PROFILE="udacity"
readonly LAB_REGION="us-east-1"
# Optional second guard: set NORTHSTAR_PERSONAL_ACCOUNT_ID in your shell to an account these scripts must never touch.
readonly PERSONAL_ACCOUNT_ID="${NORTHSTAR_PERSONAL_ACCOUNT_ID:-}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${NORTHSTAR_STATE_FILE:-${PROJECT_ROOT}/infra/state.env}"   # non-secret resource IDs only (override: tests)
EVIDENCE_ROOT="${NORTHSTAR_EVIDENCE_ROOT:-${PROJECT_ROOT}/evidence}"    # tests point this at a temp dir

die()  { echo "ERROR: $*" >&2; exit 1; }
log()  { echo "[$(date +%H:%M:%S)] $*" >&2; }

require_lab_account() {
  [[ "${AWS_PROFILE:-}" == "$LAB_PROFILE" ]] \
    || die "AWS_PROFILE must be '${LAB_PROFILE}' (got '${AWS_PROFILE:-<unset>}'). Run: export AWS_PROFILE=${LAB_PROFILE}"
  [[ "${AWS_REGION:-}" == "$LAB_REGION" ]] \
    || die "AWS_REGION must be ${LAB_REGION} (got '${AWS_REGION:-<unset>}'). Run: export AWS_REGION=${LAB_REGION}"
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)" \
    || die "Could not call sts:GetCallerIdentity. Are the Cloud Lab credentials expired?"
  [[ -z "$PERSONAL_ACCOUNT_ID" || "$ACCOUNT_ID" != "$PERSONAL_ACCOUNT_ID" ]] \
    || die "Profile resolves to the personal account ${PERSONAL_ACCOUNT_ID}; refusing to continue."
  export ACCOUNT_ID
}

# Persist a non-secret KEY=VALUE (resource names/ARNs) for later scripts.
state_set() {
  local key="$1" value="$2"
  touch "$STATE_FILE"
  grep -v "^${key}=" "$STATE_FILE" > "${STATE_FILE}.tmp" || true
  printf '%s=%q\n' "$key" "$value" >> "${STATE_FILE}.tmp"
  mv "${STATE_FILE}.tmp" "$STATE_FILE"
}

state_load() {
  # shellcheck source=/dev/null
  if [[ -f "$STATE_FILE" ]]; then source "$STATE_FILE"; fi
}

state_require() {
  local key
  for key in "$@"; do
    [[ -n "${!key:-}" ]] || die "Missing ${key} in infra/state.env. Run the earlier step or set it with: infra/set_state.sh ${key} <value>"
  done
}

# Save AWS CLI JSON output as evidence: evidence <task-dir> <name> <aws args...>
evidence() {
  local dir="${EVIDENCE_ROOT}/$1" name="$2"; shift 2
  mkdir -p "$dir"
  aws "$@" --output json > "${dir}/${name}.json"
  log "evidence → evidence/$(basename "$dir")/${name}.json"
}

# Ask before any action that creates, changes or deletes cloud resources.
confirm() {
  [[ "${ASSUME_YES:-}" == "1" ]] && return 0
  read -r -p "$* [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || die "Aborted by user."
}

# Snapshot every policy on a role (inline + attached managed) into <dir>/<role>/.
dump_role() {
  local role="$1" dir="$2/$1" name arn version
  mkdir -p "$dir"
  aws iam get-role --role-name "$role" --output json > "${dir}/role.json"
  for name in $(aws iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text); do
    aws iam get-role-policy --role-name "$role" --policy-name "$name" --output json > "${dir}/inline_${name}.json"
  done
  for arn in $(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text); do
    version="$(aws iam get-policy --policy-arn "$arn" --query 'Policy.DefaultVersionId' --output text)"
    aws iam get-policy-version --policy-arn "$arn" --version-id "$version" --output json \
      > "${dir}/managed_${arn##*/}.json"
  done
  log "snapshot of role ${role} → ${dir#"$PROJECT_ROOT"/}"
}

role_name_from_arn() { echo "${1##*/}"; }
