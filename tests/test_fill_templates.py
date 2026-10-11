"""Tests for tools/fill_templates.py: pure docx helpers, content validation and end-to-end builds."""
import copy
import hashlib
import textwrap
from pathlib import Path

import fill_templates as ft
import pytest
from docx import Document

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "starter"
MLBOM_TEMPLATE = STARTER / "ML-BOM Template.docx"
STRIDE_TEMPLATE = STARTER / "STRIDE-ML Template.docx"
ALL_TOKENS = {t: f"value-of-{t.lower()}" for t in ft.KNOWN_TOKENS}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def all_text(doc):
    """Every paragraph and table-cell text in the document, in body order."""
    chunks = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            chunks.extend(cell.text for cell in row.cells)
    return chunks


def headings(doc):
    return [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]


@pytest.fixture
def mlbom_doc():
    return Document(str(MLBOM_TEMPLATE))


@pytest.fixture
def stride_doc():
    return Document(str(STRIDE_TEMPLATE))


# --------------------------------------------------------------------------- state and tokens


def test_load_state_parses_shell_quoted_values_and_skips_comments(tmp_path):
    path = tmp_path / "state.env"
    path.write_text(textwrap.dedent("""
        # comment
        KB_ID=ABCDEFGHIJ
        BUCKET='northstar-assist-kb-1a2b3c4d'
        HARNESS_ROLE_NAME=Role\\ With\\ Space

        BROKEN LINE
    """))
    state = ft.load_state(path)
    assert state == {"KB_ID": "ABCDEFGHIJ", "BUCKET": "northstar-assist-kb-1a2b3c4d",
                     "HARNESS_ROLE_NAME": "Role With Space"}


def test_load_state_returns_empty_dict_when_file_missing(tmp_path):
    assert ft.load_state(tmp_path / "nope.env") == {}


def test_resolve_tokens_replaces_nested_values_without_mutating_input():
    data = {"a": "bucket {{BUCKET}}", "b": ["{{KB_ID}} and {{BUCKET}}", 3], "c": {"d": "plain"}}
    original = copy.deepcopy(data)
    resolved, unresolved = ft.resolve_tokens(data, {"BUCKET": "bkt", "KB_ID": "KB1"})
    assert resolved == {"a": "bucket bkt", "b": ["KB1 and bkt", 3], "c": {"d": "plain"}}
    assert unresolved == set()
    assert data == original


def test_resolve_tokens_leaves_missing_tokens_and_reports_them():
    resolved, unresolved = ft.resolve_tokens(["x {{GATEWAY_ARN}} y", "{{KB_ID}}"], {"KB_ID": "K"})
    assert resolved == ["x {{GATEWAY_ARN}} y", "K"]
    assert unresolved == {"GATEWAY_ARN"}


# --------------------------------------------------------------------------- scoring


@pytest.mark.parametrize("likelihood,impact,score,priority", [
    (5, 5, 25, "Critical"), (3, 5, 15, "Critical"), (5, 3, 15, "Critical"),
    (2, 5, 10, "High"), (4, 3, 12, "High"), (3, 3, 9, "Medium"),
    (1, 5, 5, "Medium"), (2, 2, 4, "Low"), (1, 1, 1, "Low"),
])
def test_risk_score_and_priority_follow_thresholds(likelihood, impact, score, priority):
    assert ft.risk_score(likelihood, impact) == score
    assert ft.priority_for(score) == priority


@pytest.mark.parametrize("likelihood,impact", [(0, 3), (6, 3), (3, 0), (3, 6), ("3", 3), (2.5, 3)])
def test_risk_score_rejects_out_of_range_inputs(likelihood, impact):
    with pytest.raises(ft.ContentError):
        ft.risk_score(likelihood, impact)


# --------------------------------------------------------------------------- table helpers


def test_fill_kv_table_replaces_values_and_drops_placeholder_formatting(mlbom_doc):
    table = mlbom_doc.tables[0]
    ft.fill_kv_table(table, {"Name": "Claude Haiku 4.5", "Version": "20251001-v1:0"})
    assert table.rows[1].cells[1].text == "Claude Haiku 4.5"
    assert table.rows[2].cells[1].text == "20251001-v1:0"
    run = table.rows[1].cells[1].paragraphs[0].runs[0]
    assert not run.italic
    assert table.rows[1].cells[0].text == "Name"
    assert table.rows[3].cells[1].text.startswith("[Required")  # untouched row


def test_fill_kv_table_supports_multiline_values(mlbom_doc):
    table = mlbom_doc.tables[0]
    ft.fill_kv_table(table, {"Name": "line one\nline two"})
    cell = table.rows[1].cells[1]
    assert [p.text for p in cell.paragraphs] == ["line one", "line two"]


def test_fill_kv_table_unknown_field_raises_unless_add_missing(mlbom_doc):
    table = mlbom_doc.tables[0]
    with pytest.raises(ft.ContentError, match="Inference profile"):
        ft.fill_kv_table(table, {"Inference profile": "x"})
    before = len(table.rows)
    ft.fill_kv_table(table, {"Inference profile": "us.anthropic"}, add_missing=True)
    assert len(table.rows) == before + 1
    assert [c.text for c in table.rows[-1].cells] == ["Inference profile", "us.anthropic"]


def test_fill_grid_table_fills_existing_rows_and_removes_unused_empty_ones(mlbom_doc):
    table = mlbom_doc.tables[2]  # Other References: header + 3 prefilled label rows
    ft.fill_grid_table(table, [["Website", "https://example.com"]])
    assert [[c.text for c in r.cells] for r in table.rows] == [
        ["Reference Type", "URL/Link"], ["Website", "https://example.com"]]


def test_fill_grid_table_appends_rows_copying_last_row_style(mlbom_doc):
    table = mlbom_doc.tables[3]  # Training Datasets: header + 2 rows, 4 columns
    rows = [[f"ds{i}", "url", "lic", "notes"] for i in range(4)]
    ft.fill_grid_table(table, rows)
    assert [r.cells[0].text for r in table.rows[1:]] == ["ds0", "ds1", "ds2", "ds3"]
    assert all(r.cells[0].paragraphs[0].style.name == "Compact" for r in table.rows)


def test_fill_grid_table_pads_short_rows_and_rejects_long_rows(mlbom_doc):
    table = mlbom_doc.tables[3]
    ft.fill_grid_table(table, [["only-name"]])
    assert [c.text for c in table.rows[1].cells] == ["only-name", "", "", ""]
    with pytest.raises(ft.ContentError):
        ft.fill_grid_table(table, [["1", "2", "3", "4", "5"]])


# --------------------------------------------------------------------------- paragraph helpers


def test_replace_placeholder_paragraph_swaps_in_several_paragraphs_with_same_style(mlbom_doc):
    original = ft.find_paragraph(mlbom_doc, "[Required: Description of how the model")
    style = original.style.name
    new = ft.replace_placeholder_paragraph(mlbom_doc, "[Required: Description of how", ["one", "two", "three"])
    assert [p.text for p in new] == ["one", "two", "three"]
    assert all(p.style.name == style for p in new)
    texts = [p.text for p in mlbom_doc.paragraphs]
    idx = texts.index("one")
    assert texts[idx:idx + 3] == ["one", "two", "three"]
    assert not any(t.startswith("[Required: Description of how") for t in texts)


def test_replace_placeholder_paragraph_requires_a_match(mlbom_doc):
    with pytest.raises(ft.ContentError):
        ft.replace_placeholder_paragraph(mlbom_doc, "[No such placeholder", ["x"])


def test_insert_paragraph_after_places_paragraph_directly_after_anchor(mlbom_doc):
    anchor = ft.find_paragraph(mlbom_doc, "Overview", exact=True)
    created = ft.insert_paragraph_after(anchor, "hello", style="Body Text", bold_prefix="Label:")
    assert anchor._p.getnext() is created._p
    assert created.text == "Label: hello"
    assert created.runs[0].bold is True


def test_insert_table_after_builds_styled_table_with_header_and_rows(mlbom_doc):
    anchor = ft.find_paragraph(mlbom_doc, "Overview", exact=True)
    table = ft.insert_table_after(mlbom_doc, anchor, ["A", "B"], [["1", "2"], ["3", "4"]], widths=[1, 3])
    assert anchor._p.getnext() is table._tbl
    assert [[c.text for c in r.cells] for r in table.rows] == [["A", "B"], ["1", "2"], ["3", "4"]]
    assert table.style.name == "Table"
    assert table.rows[0].cells[0].paragraphs[0].runs[0].bold is True


def test_insert_table_after_rejects_ragged_rows(mlbom_doc):
    anchor = ft.find_paragraph(mlbom_doc, "Overview", exact=True)
    with pytest.raises(ft.ContentError):
        ft.insert_table_after(mlbom_doc, anchor, ["A", "B"], [["only one"]])


def test_find_placeholders_and_unresolved_tokens(mlbom_doc):
    assert any("[Required" in t for t in ft.find_placeholders(mlbom_doc))
    ft.replace_placeholder_paragraph(mlbom_doc, "[Tags or labels", ["{{BUCKET}}"])
    assert ft.find_unresolved_tokens(mlbom_doc) == {"BUCKET"}


# --------------------------------------------------------------------------- content validation


def test_real_content_files_validate():
    ft.validate_mlbom(ft.load_yaml(ROOT / "content" / "mlbom.yaml"))
    ft.validate_stride(ft.load_yaml(ROOT / "content" / "stride.yaml"))


def minimal_threat(**overrides):
    base = dict(id="S-01", name="n", category="spoofing", boundary="TB1", scenario="s", likelihood=3,
                impact=3, mitigation="m", mitigation_summary="ms", residual="r", status="Planned")
    return {**base, **overrides}


def stride_with(*threats):
    content = copy.deepcopy(ft.load_yaml(ROOT / "content" / "stride.yaml"))
    content["threats"] = list(threats)
    return content


def test_validate_stride_rejects_duplicate_ids():
    with pytest.raises(ft.ContentError, match="duplicate"):
        ft.validate_stride(stride_with(minimal_threat(), minimal_threat()))


def test_validate_stride_rejects_id_prefix_not_matching_category():
    with pytest.raises(ft.ContentError, match="prefix"):
        ft.validate_stride(stride_with(minimal_threat(id="T-01")))


def test_validate_stride_rejects_unknown_category_status_and_missing_keys():
    with pytest.raises(ft.ContentError):
        ft.validate_stride(stride_with(minimal_threat(category="phishing")))
    with pytest.raises(ft.ContentError):
        ft.validate_stride(stride_with(minimal_threat(status="Done-ish")))
    broken = minimal_threat()
    del broken["residual"]
    with pytest.raises(ft.ContentError, match="residual"):
        ft.validate_stride(stride_with(broken))


def test_validate_stride_rejects_unknown_trust_boundary():
    with pytest.raises(ft.ContentError, match="TB9"):
        ft.validate_stride(stride_with(minimal_threat(boundary="TB9")))


def test_validate_mlbom_requires_two_models_and_supporting_components():
    content = copy.deepcopy(ft.load_yaml(ROOT / "content" / "mlbom.yaml"))
    content["models"] = content["models"][:1]
    with pytest.raises(ft.ContentError, match="two models"):
        ft.validate_mlbom(content)


def test_real_stride_content_meets_coverage_requirements():
    content = ft.load_yaml(ROOT / "content" / "stride.yaml")
    threats = content["threats"]
    assert len(threats) >= 14
    assert {t["category"] for t in threats} == set(ft.STRIDE_CATEGORIES)
    for needed in ("TB1", "TB2", "TB3", "TB4", "TB5"):
        assert any(t["boundary"] == needed for t in threats), needed
    roles = " ".join(r[0] for r in content["signoff"])
    assert "AI Security Engineer (author)" in roles


# --------------------------------------------------------------------------- end-to-end: ML-BOM


@pytest.fixture(scope="module")
def mlbom_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("mlbom") / "ML-BOM.docx"
    content = ft.load_yaml(ROOT / "content" / "mlbom.yaml")
    ft.build_mlbom(content, MLBOM_TEMPLATE, out, state=ALL_TOKENS)
    return Document(str(out))


def test_mlbom_has_no_placeholders_or_tokens(mlbom_out):
    assert ft.find_placeholders(mlbom_out) == []
    assert not any("[" in t for t in all_text(mlbom_out))
    assert ft.find_unresolved_tokens(mlbom_out) == set()


def test_mlbom_structure_system_overview_two_models_components_findings(mlbom_out):
    h = headings(mlbom_out)
    first_model_a = next(i for i, x in enumerate(h) if x.startswith("Model A"))
    assert h.index("Overview") < h.index("System Overview") < first_model_a
    assert any(x.startswith("Model B: Amazon Titan Text Embeddings V2") for x in h)
    assert sum(x.endswith("1. Model Information") for x in h) == 2
    assert sum(x.endswith("3.3 Misuse or Malicious Use") for x in h) == 2
    order = [h.index(x) for x in h if x.startswith("4. Supporting Components and IAM Roles")]
    assert len(order) == 1
    assert h.index("5. Findings") > order[0]
    assert h.index("Attestation") > h.index("5. Findings")
    assert h[-1] == "References"
    text = "\n".join(all_text(mlbom_out))
    assert "Employee → " in text and "AgentCore Gateway" in text and "Managed" in text


def test_mlbom_model_tables_filled_for_both_models(mlbom_out):
    text = "\n".join(all_text(mlbom_out))
    assert "us.anthropic.claude-haiku-4-5-20251001-v1:0" in text
    assert "amazon.titan-embed-text-v2:0" in text
    assert "1024" in text
    kv = [t for t in mlbom_out.tables if t.rows[0].cells[0].text == "Field" and t.rows[1].cells[0].text == "Name"]
    assert len(kv) == 2
    assert kv[0].rows[1].cells[1].text != kv[1].rows[1].cells[1].text


def test_mlbom_supporting_components_table_columns_and_roles(mlbom_out):
    tables = [t for t in mlbom_out.tables if t.rows[0].cells[0].text == "Component"]
    assert len(tables) == 1
    table = tables[0]
    assert [c.text for c in table.rows[0].cells] == [
        "Component", "Type", "Provider", "Intended use", "Security failure mode",
        "Limitations / transparency gaps"]
    names = " ".join(r.cells[0].text for r in table.rows[1:])
    for expected in ("knowledge corpus", "S3", "vector store", "Gateway", "Harness", "Guardrail", "CloudWatch"):
        assert expected.lower() in names.lower(), expected
    roles = "\n".join(c.text for r in table.rows[1:] for c in r.cells)
    assert "NorthstarBedrockInvocationLoggingRole" in roles
    assert ALL_TOKENS["HARNESS_ROLE_NAME"] in roles
    assert ALL_TOKENS["GATEWAY_ROLE_NAME"] in roles
    assert ALL_TOKENS["KB_ROLE_NAME"] in roles


def test_mlbom_attestation_filled_and_unique_bookmark_ids(mlbom_out):
    att = next(t for t in mlbom_out.tables if [c.text for c in t.rows[0].cells] == ["Role", "Name", "Date"])
    assert att.rows[1].cells[0].text == "Author"
    assert att.rows[1].cells[1].text
    ids = mlbom_out.element.body.xpath(".//w:bookmarkStart/@w:id")
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------- end-to-end: STRIDE-ML


@pytest.fixture(scope="module")
def stride_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("stride") / "STRIDE-ML.docx"
    content = ft.load_yaml(ROOT / "content" / "stride.yaml")
    ft.build_stride(content, STRIDE_TEMPLATE, out, state=ALL_TOKENS)
    return Document(str(out)), content


def test_stride_has_no_placeholders_and_keeps_appendix_and_references(stride_out):
    doc, _ = stride_out
    assert ft.find_placeholders(doc) == []
    assert not any("[" in t for t in all_text(doc))
    h = headings(doc)
    assert "Appendix: Common ML Threat Categories" in h and h[-1] == "References"
    text = "\n".join(all_text(doc))
    assert "Model Extraction: Stealing model functionality" in text


def test_stride_renders_each_threat_with_table_mitigation_and_residual(stride_out):
    doc, content = stride_out
    texts = [p.text for p in doc.paragraphs]
    for threat in content["threats"]:
        assert f"{threat['id']}: {threat['name']}" in texts
    assert sum(t.startswith("Mitigation:") for t in texts) == len(content["threats"])
    assert sum(t.startswith("Residual:") for t in texts) == len(content["threats"])
    detail = [t for t in doc.tables if [c.text for c in t.rows[0].cells] ==
              ["Trust boundary", "Likelihood (1-5)", "Impact (1-5)", "Risk score", "Priority"]]
    assert len(detail) == len(content["threats"])
    ordered = [t for cat in ft.STRIDE_CATEGORIES for t in content["threats"] if t["category"] == cat]
    for table, threat in zip(detail, ordered, strict=True):
        score = threat["likelihood"] * threat["impact"]
        cells = [c.text for c in table.rows[1].cells]
        assert cells[3] == str(score) and cells[4] == ft.priority_for(score)
        assert cells[0].startswith(threat["boundary"])


def test_stride_section_order_and_register_after_section_2(stride_out):
    doc, content = stride_out
    h = headings(doc)
    assert h.index("2. Data Assets") < h.index("Prioritized Risk Register") < h.index("3. STRIDE-ML Threat Analysis")
    register = next(t for t in doc.tables if t.rows[0].cells[0].text == "ID" and len(t.columns) == 9)
    assert [c.text for c in register.rows[0].cells] == [
        "ID", "Threat", "STRIDE", "L", "I", "Score", "Priority", "Mitigation", "Status"]
    assert len(register.rows) - 1 == len(content["threats"])
    scores = [int(r.cells[5].text) for r in register.rows[1:]]
    assert scores == sorted(scores, reverse=True)
    prev = register._tbl.getprevious()
    assert prev is not None  # a paragraph (explanation) precedes the register


def test_stride_threats_are_grouped_under_their_category_heading(stride_out):
    doc, content = stride_out
    body = [p.text for p in doc.paragraphs]
    for number, category in enumerate(ft.STRIDE_CATEGORIES.values(), start=1):
        start = body.index(f"3.{number} {category}")
        end = body.index(f"3.{number + 1} {list(ft.STRIDE_CATEGORIES.values())[number]}") if number < 6 \
            else body.index("4. Residual Risks")
        span = body[start:end]
        wanted = [t for t in content["threats"] if ft.STRIDE_CATEGORIES[t["category"]] == category]
        assert wanted, category
        for t in wanted:
            assert f"{t['id']}: {t['name']}" in span


def test_stride_signoff_residual_and_recommendations_filled(stride_out):
    doc, content = stride_out
    signoff = next(t for t in doc.tables if [c.text for c in t.rows[0].cells] == ["Role", "Name", "Date"])
    assert signoff.rows[1].cells[0].text == "AI Security Engineer (author)"
    texts = [p.text for p in doc.paragraphs]
    for risk in content["residual_risks"]:
        assert any(t.startswith(f"{risk['name']}:") for t in texts)
    assert any(t.startswith("R1") or t.startswith("1.") for t in texts)


def test_stride_overview_paragraphs_filled(stride_out):
    doc, content = stride_out
    texts = [p.text for p in doc.paragraphs]
    assert any(t.startswith("System Name: ") and "Northstar" in t for t in texts)
    assert any(t.startswith("Purpose: ") for t in texts)
    assert any(t.startswith("Trust Boundaries:") for t in texts)
    assert any(t.startswith("TB5") for t in texts)


# --------------------------------------------------------------------------- CLI


def run_main(tmp_path, *extra, state_text=None):
    state = tmp_path / "state.env"
    if state_text is not None:
        state.write_text(state_text)
    out = tmp_path / "out"
    argv = ["--state", str(state), "--out-dir", str(out), *extra]
    return ft.main(argv), out


def test_main_default_mode_warns_but_succeeds_when_tokens_unresolved(tmp_path, capsys):
    code, out = run_main(tmp_path)
    captured = capsys.readouterr()
    assert code == 0
    assert (out / "ML-BOM.docx").exists() and (out / "STRIDE-ML.docx").exists()
    assert "unresolved" in captured.err.lower() and "BUCKET" in captured.err


def test_main_check_fails_when_tokens_unresolved(tmp_path):
    code, _ = run_main(tmp_path, "--check")
    assert code == 1


def test_main_check_passes_when_state_complete(tmp_path):
    state_text = "".join(f"{k}={v}\n" for k, v in ALL_TOKENS.items())
    code, out = run_main(tmp_path, "--check", state_text=state_text)
    assert code == 0
    assert ft.find_unresolved_tokens(Document(str(out / "ML-BOM.docx"))) == set()


def test_main_never_modifies_starter_templates(tmp_path):
    before = (sha256(MLBOM_TEMPLATE), sha256(STRIDE_TEMPLATE))
    run_main(tmp_path)
    assert (sha256(MLBOM_TEMPLATE), sha256(STRIDE_TEMPLATE)) == before


def test_main_refuses_to_write_into_starter_directory(tmp_path):
    with pytest.raises(SystemExit):
        ft.main(["--state", str(tmp_path / "s.env"), "--out-dir", str(STARTER)])
