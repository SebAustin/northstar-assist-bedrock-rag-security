#!/usr/bin/env bash
# Build the reviewer-facing submission archives from the committed project.
#   northstar-assist-submission.zip         the seven deliverables at the top level, screenshots, and the project
#   northstar-assist-deliverables-only.zip  the same without the project folder (small; documents and screenshots)
# Run tools/export_docs.sh first if a deliverable changed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT="${ROOT}/deliverables/export"
STAGE="$(mktemp -d)"
TOP="${STAGE}/Northstar-Assist-Submission"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "${TOP}/screenshots"

# source name in deliverables/export  →  name the reviewer sees
while IFS='|' read -r source target; do
  for ext in pdf docx; do
    [[ -f "${EXPORT}/${source}.${ext}" ]] || { echo "ERROR: missing ${source}.${ext}; run tools/export_docs.sh" >&2; exit 1; }
    cp "${EXPORT}/${source}.${ext}" "${TOP}/${target}.${ext}"
  done
done <<'MAP'
01_harness_evidence|Task1_Working_Harness_Evidence
ML-BOM|Task2_ML-BOM
STRIDE-ML|Task3_STRIDE-ML_Threat_Model
04_iam_hardening|Task4_IAM_Hardening_Summary
05_safety_controls|Task5_Safety_Controls
06_monitoring_and_ir|Task6_Monitoring_Plan_and_IR_Playbook
07_launch_readiness|Task7_Launch_Readiness_Report
MAP

for shot in "${ROOT}"/evidence/task*/*.jpg; do
  task="$(basename "$(dirname "$shot")")"
  cp "$shot" "${TOP}/screenshots/Task${task#task}_$(basename "$shot")"
done
cp "${ROOT}/SUBMISSION_INDEX.md" "${TOP}/README.md"

cd "$STAGE"
rm -f "${ROOT}/northstar-assist-deliverables-only.zip" "${ROOT}/northstar-assist-submission.zip"
zip -qr "${ROOT}/northstar-assist-deliverables-only.zip" Northstar-Assist-Submission
git -C "$ROOT" archive --format=tar --prefix=Northstar-Assist-Submission/project/ HEAD | tar -xf - -C "$STAGE"
zip -qr "${ROOT}/northstar-assist-submission.zip" Northstar-Assist-Submission
for archive in northstar-assist-deliverables-only.zip northstar-assist-submission.zip; do
  unzip -tq "${ROOT}/${archive}" >/dev/null
  echo "${archive}: $(unzip -l "${ROOT}/${archive}" | tail -1 | awk '{print $2}') files, $(du -h "${ROOT}/${archive}" | cut -f1 | tr -d ' ')"
done
