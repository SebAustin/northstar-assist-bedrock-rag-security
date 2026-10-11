#!/usr/bin/env bash
# Export the Markdown deliverables to Word and PDF for submission (deliverables/export/).
# Needs pandoc and LibreOffice (soffice). The two template-based documents are already .docx.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/deliverables/export"
command -v pandoc >/dev/null || { echo "ERROR: pandoc is not installed" >&2; exit 1; }
command -v soffice >/dev/null || { echo "ERROR: LibreOffice (soffice) is not installed" >&2; exit 1; }
mkdir -p "$OUT"
cd "${ROOT}/deliverables"   # image links in the Markdown are relative to this directory
for source in 0*.md; do
  name="${source%.md}"
  pandoc --from gfm --to docx --output "${OUT}/${name}.docx" "$source"
  echo "wrote deliverables/export/${name}.docx"
done
cp ML-BOM.docx STRIDE-ML.docx "$OUT/"
soffice --headless --convert-to pdf --outdir "$OUT" "$OUT"/*.docx >/dev/null
count="$(find "$OUT" -name '*.pdf' | wc -l | tr -d ' ')"
[[ "$count" == "7" ]] || { echo "ERROR: expected 7 PDFs in ${OUT}, found ${count}" >&2; exit 1; }
echo "wrote ${count} PDFs to deliverables/export/"
