"""Content schema for the template filler: errors, scoring, YAML loading and validation.

Kept separate from ``fill_templates`` so the docx plumbing and the content rules can be read (and tested)
independently.  ``fill_templates`` re-exports everything here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

STRIDE_CATEGORIES = {
    "spoofing": "Spoofing",
    "tampering": "Tampering",
    "repudiation": "Repudiation",
    "information_disclosure": "Information Disclosure",
    "denial_of_service": "Denial of Service",
    "elevation_of_privilege": "Elevation of Privilege",
}
ID_PREFIX = {"spoofing": "S", "tampering": "T", "repudiation": "R", "information_disclosure": "I",
             "denial_of_service": "D", "elevation_of_privilege": "E"}
STATUSES = ("Planned", "Partially mitigated", "Mitigated", "Accepted")
CRITICAL_MIN, HIGH_MIN, MEDIUM_MIN = 15, 10, 5
MODEL_LABELS = ("A", "B")

ASSET_HEADER = ["Asset", "Classification", "Where it lives", "Why an attacker wants it", "Related threats"]
COMPONENT_HEADER = ["Component", "Type", "Provider", "Intended use", "Security failure mode",
                    "Limitations / transparency gaps"]


class ContentError(ValueError):
    """Raised when a content file or a template does not have the expected shape."""



def _check_rating(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ContentError(f"{name} must be an integer from 1 to 5, got {value!r}")
    return value


def risk_score(likelihood: Any, impact: Any) -> int:
    """Likelihood (1-5) x impact (1-5)."""
    return _check_rating(likelihood, "likelihood") * _check_rating(impact, "impact")


def priority_for(score: int) -> str:
    """Critical >= 15, High 10-14, Medium 5-9, otherwise Low."""
    if score >= CRITICAL_MIN:
        return "Critical"
    if score >= HIGH_MIN:
        return "High"
    return "Medium" if score >= MEDIUM_MIN else "Low"



# --------------------------------------------------------------------------- content loading and validation


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from ``path``."""
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ContentError(f"{path}: top level must be a mapping")
    return data


def _require(mapping: Any, keys: tuple[str, ...], where: str) -> None:
    if not isinstance(mapping, dict):
        raise ContentError(f"{where}: expected a mapping")
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ContentError(f"{where}: missing key(s) {missing}")


def _require_rows(rows: Any, width: int, where: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise ContentError(f"{where}: expected a non-empty list of rows")
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise ContentError(f"{where}: every row needs exactly {width} cells, got {row!r}")


MODEL_KEYS = ("key", "title", "summary", "model_info", "bom_generation", "references", "tags", "datasets",
              "architecture", "lineage", "io", "hardware_software", "software_required", "usage")
USAGE_KEYS = ("intended", "out_of_scope", "misuse")
MODEL_INFO_KEYS = ("Name", "Version", "Type", "Author", "Licenses", "Libraries", "Source URL")


def validate_mlbom(content: dict[str, Any]) -> None:
    """Check the ML-BOM content file has everything the builder needs."""
    _require(content, ("system_overview", "models", "supporting_components", "findings_intro", "findings",
                       "attestation"), "mlbom")
    _require(content["system_overview"], ("intro", "dataflow", "flow", "request_path", "ingestion_path"),
             "system_overview")
    models = content["models"]
    if not isinstance(models, list) or len(models) != len(MODEL_LABELS):
        raise ContentError("mlbom: expected exactly two models (foundation model and embedding model)")
    for index, model in enumerate(models):
        where = f"models[{index}]"
        _require(model, MODEL_KEYS, where)
        _require(model["model_info"], MODEL_INFO_KEYS, f"{where}.model_info")
        _require(model["usage"], USAGE_KEYS, f"{where}.usage")
        _require_rows(model["datasets"], 4, f"{where}.datasets")
        _require_rows(model["lineage"], 4, f"{where}.lineage")
        _require_rows(model["references"], 2, f"{where}.references")
        _require_rows(model["hardware_software"], 2, f"{where}.hardware_software")
    _require(content["supporting_components"], ("intro", "rows"), "supporting_components")
    _require_rows(content["supporting_components"]["rows"], len(COMPONENT_HEADER), "supporting_components.rows")
    for finding in content["findings"]:
        _require(finding, ("id", "title", "severity", "text", "action"), "findings")
    _require_rows(content["attestation"], 3, "attestation")


def validate_stride(content: dict[str, Any]) -> None:
    """Check the STRIDE-ML content file; threat IDs, categories, ratings and boundaries are cross-checked."""
    _require(content, ("system", "assets", "register_intro", "category_intros", "threats", "residual_intro",
                       "residual_risks", "recommendations_intro", "recommendations", "signoff"), "stride")
    _require(content["system"], ("name", "purpose", "architecture", "key_components", "trust_boundaries"),
             "system")
    boundaries = set()
    for boundary in content["system"]["trust_boundaries"]:
        _require(boundary, ("id", "name", "text"), "trust_boundaries")
        boundaries.add(boundary["id"])
    _require(content["assets"], ("intro", "rows"), "assets")
    _require_rows(content["assets"]["rows"], len(ASSET_HEADER), "assets.rows")
    _require(content["category_intros"], tuple(STRIDE_CATEGORIES), "category_intros")
    seen: set[str] = set()
    for threat in content["threats"]:
        _validate_threat(threat, boundaries, seen)
    for risk in content["residual_risks"]:
        _require(risk, ("name", "text"), "residual_risks")
    _require_rows(content["signoff"], 3, "signoff")


def _validate_threat(threat: dict[str, Any], boundaries: set[str], seen: set[str]) -> None:
    _require(threat, ("id", "name", "category", "boundary", "scenario", "likelihood", "impact", "mitigation",
                      "mitigation_summary", "residual", "status"), "threat")
    tid = threat["id"]
    if tid in seen:
        raise ContentError(f"duplicate threat id {tid}")
    seen.add(tid)
    category = threat["category"]
    if category not in STRIDE_CATEGORIES:
        raise ContentError(f"{tid}: unknown STRIDE category {category!r}")
    if not tid.startswith(f"{ID_PREFIX[category]}-"):
        raise ContentError(f"{tid}: id prefix must be {ID_PREFIX[category]}- for {category}")
    if threat["boundary"] not in boundaries:
        raise ContentError(f"{tid}: unknown trust boundary {threat['boundary']}")
    if threat["status"] not in STATUSES:
        raise ContentError(f"{tid}: status must be one of {STATUSES}, got {threat['status']!r}")
    risk_score(threat["likelihood"], threat["impact"])
