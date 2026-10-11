"""Tests for tools/metrics.py: suite-record aggregation and Bedrock invocation-log parsing.

NOTE (PLAN R2): the invocation_*.json fixtures follow the *documented* Bedrock model-invocation-log
schema but are synthetic. Re-validate the field names against real CloudWatch log lines once the
harness has produced some, and update the fixtures if they differ.
"""
import copy
import json
from pathlib import Path

import metrics
import pytest
from metrics import (
    InvocationSummary,
    blocked_sessions,
    consistency_findings,
    intervention_rate,
    load_jsonl,
    parse_invocation_record,
    retrieval_success_rate,
    token_spike_threshold,
    token_stats,
    turn_metrics,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def rec(case_id="T-1", run=1, outcome="ANSWERED_WITH_RETRIEVAL", chunks=2, out_tokens=100, in_tokens=1000,
        passed=True, expected="ANSWERED", category="benign", owasp="-", rubric="", ts="2026-10-08T10:00:00+00:00",
        turns=("hello",)):
    return {"case_id": case_id, "run": run, "outcome": outcome, "retrieved_chunk_count": chunks,
            "usage": {"outputTokens": out_tokens, "inputTokens": in_tokens}, "passed": passed,
            "expected": expected, "category": category, "owasp": owasp, "rubric_category": rubric,
            "timestamp": ts, "turns": list(turns)}


# ------------------------------------------------------------------ load_jsonl
def test_load_jsonl_skips_blank_lines_and_reads_many_files(tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text('{"x": 1}\n\n   \n{"x": 2}\n')
    b.write_text('{"x": 3}\n')

    assert load_jsonl([a, str(b)]) == [{"x": 1}, {"x": 2}, {"x": 3}]


def test_load_jsonl_names_file_and_line_on_bad_json(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"x": 1}\n\n{not json}\n')

    with pytest.raises(ValueError) as exc:
        load_jsonl([bad])

    assert "bad.jsonl" in str(exc.value)
    assert ":3" in str(exc.value)


def test_load_jsonl_rejects_non_object_lines(tmp_path):
    bad = tmp_path / "list.jsonl"
    bad.write_text("[1, 2]\n")

    with pytest.raises(ValueError, match=r"list\.jsonl:1"):
        load_jsonl([bad])


def test_load_jsonl_accepts_a_single_path(tmp_path):
    one = tmp_path / "one.jsonl"
    one.write_text('{"a": 1}\n')

    assert load_jsonl(one) == [{"a": 1}]


# ------------------------------------------------------------- intervention_rate
def test_intervention_rate_counts_outcomes_and_groups():
    records = [
        rec(outcome="GUARDRAIL_BLOCKED", category="direct_injection", owasp="LLM01"),
        rec(outcome="GUARDRAIL_BLOCKED", category="direct_injection", owasp="LLM01"),
        rec(outcome="ANSWERED_WITH_RETRIEVAL", category="benign", owasp="-"),
        rec(outcome="ANSWERED_NO_RETRIEVAL", category="off_scope", owasp="LLM06"),
        rec(outcome="ERROR", category="benign", owasp="-"),
    ]

    result = intervention_rate(records)

    assert result["total"] == 5
    assert result["intervened"] == 2
    assert result["rate"] == pytest.approx(0.4)
    assert result["by_outcome"] == {"GUARDRAIL_BLOCKED": 2, "ANSWERED_WITH_RETRIEVAL": 1,
                                    "ANSWERED_NO_RETRIEVAL": 1, "ERROR": 1}
    assert result["by_category"]["direct_injection"] == {"total": 2, "intervened": 2, "rate": 1.0}
    assert result["by_owasp"]["LLM01"]["intervened"] == 2
    assert result["by_category"]["benign"] == {"total": 2, "intervened": 0, "rate": 0.0}


def test_intervention_rate_on_empty_input_has_all_outcome_keys_at_zero():
    result = intervention_rate([])

    assert result["rate"] == 0.0
    assert result["by_outcome"] == {"GUARDRAIL_BLOCKED": 0, "ANSWERED_WITH_RETRIEVAL": 0,
                                    "ANSWERED_NO_RETRIEVAL": 0, "ERROR": 0}
    assert result["by_category"] == {}


def test_intervention_rate_keeps_unknown_outcomes_and_missing_group_keys():
    result = intervention_rate([{"outcome": "WEIRD"}])

    assert result["by_outcome"]["WEIRD"] == 1
    assert result["by_category"]["unknown"]["total"] == 1


def test_intervention_rate_does_not_mutate_input():
    records = [rec(outcome="GUARDRAIL_BLOCKED")]
    snapshot = copy.deepcopy(records)

    intervention_rate(records)

    assert records == snapshot


# ------------------------------------------------------- retrieval_success_rate
def test_retrieval_success_rate_ignores_blocked_and_error_turns():
    records = [
        rec(chunks=3),
        rec(chunks=0, outcome="ANSWERED_NO_RETRIEVAL"),
        rec(chunks=0, outcome="GUARDRAIL_BLOCKED"),
        rec(chunks=0, outcome="ERROR"),
    ]

    assert retrieval_success_rate(records) == pytest.approx(0.5)


def test_retrieval_success_rate_is_none_without_eligible_turns():
    assert retrieval_success_rate([]) is None
    assert retrieval_success_rate([rec(outcome="GUARDRAIL_BLOCKED", chunks=0)]) is None


# ------------------------------------------------------------------- token_stats
def test_token_stats_covers_output_and_input():
    records = [rec(out_tokens=n, in_tokens=n * 10) for n in (10, 20, 30, 40, 100)]

    stats = token_stats(records)

    assert stats["output"]["mean"] == pytest.approx(40)
    assert stats["output"]["p50"] == pytest.approx(30)
    assert stats["output"]["max"] == 100
    assert stats["output"]["p95"] == pytest.approx(88)  # linear interpolation: 40 + 0.8 * 60
    assert stats["input"]["max"] == 1000


def test_token_stats_handles_empty_input_and_missing_usage():
    zero = {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0}

    assert token_stats([]) == {"output": zero, "input": zero}
    assert token_stats([{"outcome": "ERROR", "usage": {}}, {"outcome": "ERROR"}])["output"] == zero


# ---------------------------------------------------------- token_spike_threshold
def test_token_spike_threshold_is_three_times_benign_p95_rounded_up():
    records = [rec(out_tokens=n, rubric="benign_control") for n in (100, 100, 100, 101)]
    records.append(rec(out_tokens=9999, expected="BLOCKED", rubric="direct_injection"))

    # p95 of [100, 100, 100, 101] = 100.85 -> 3 * 100.85 = 302.55 -> 303
    assert token_spike_threshold(records) == 303
    assert token_spike_threshold(records, multiplier=2) == 202


def test_token_spike_threshold_treats_expected_answered_as_benign():
    records = [rec(out_tokens=50, expected="ANSWERED", rubric=""), rec(out_tokens=500, expected="BLOCKED")]

    assert token_spike_threshold(records) == 150


def test_token_spike_threshold_raises_without_benign_records():
    with pytest.raises(ValueError, match="benign"):
        token_spike_threshold([rec(expected="BLOCKED", rubric="direct_injection")])
    with pytest.raises(ValueError, match="benign"):
        token_spike_threshold([])


# ---------------------------------------------------------- consistency_findings
def test_consistency_findings_reports_only_disagreeing_cases():
    records = [
        rec("A", 1, passed=True), rec("A", 2, passed=True), rec("A", 3, passed=True),
        rec("B", 1, passed=True, outcome="GUARDRAIL_BLOCKED"),
        rec("B", 3, passed=False, outcome="ANSWERED_NO_RETRIEVAL"),
        rec("B", 2, passed=True, outcome="GUARDRAIL_BLOCKED"),
        rec("C", 1, passed=False), rec("C", 2, passed=False),
    ]

    findings = consistency_findings(records)

    assert findings == [{"case_id": "B", "kind": "verdict", "passed": 2, "runs": 3,
                         "outcomes": ["GUARDRAIL_BLOCKED", "GUARDRAIL_BLOCKED", "ANSWERED_NO_RETRIEVAL"]}]


def test_consistency_findings_reports_runs_that_all_pass_through_different_controls():
    """Same verdict, different mechanism: one run stopped by the guardrail, two refused by the model itself.

    The case is safe every time, but which control did the work is down to chance, so it is worth showing.
    """
    records = [
        rec("PI-03", 1, passed=True, outcome="GUARDRAIL_BLOCKED"),
        rec("PI-03", 2, passed=True, outcome="ANSWERED_NO_RETRIEVAL"),
        rec("PI-03", 3, passed=True, outcome="ANSWERED_NO_RETRIEVAL"),
        rec("OK", 1, passed=True, outcome="GUARDRAIL_BLOCKED"), rec("OK", 2, passed=True, outcome="GUARDRAIL_BLOCKED"),
    ]

    assert consistency_findings(records) == [{
        "case_id": "PI-03", "kind": "mechanism", "passed": 3, "runs": 3,
        "outcomes": ["GUARDRAIL_BLOCKED", "ANSWERED_NO_RETRIEVAL", "ANSWERED_NO_RETRIEVAL"]}]


# -------------------------------------------------------------- blocked_sessions
def test_blocked_sessions_returns_most_recent_first_with_truncated_turn():
    long_turn = "x" * 200
    records = [
        rec("OLD", outcome="GUARDRAIL_BLOCKED", ts="2026-10-08T09:00:00+00:00"),
        rec("NEW", outcome="GUARDRAIL_BLOCKED", ts="2026-10-08T11:00:00+00:00", turns=("first", long_turn)),
        rec("OK", outcome="ANSWERED_WITH_RETRIEVAL", ts="2026-10-08T12:00:00+00:00"),
        rec("MID", outcome="GUARDRAIL_BLOCKED", ts="2026-10-08T10:00:00+00:00", turns=("line1\nline2",)),
    ]

    rows = blocked_sessions(records, limit=2)

    assert [r["case_id"] for r in rows] == ["NEW", "MID"]
    assert rows[0] == {"case_id": "NEW", "timestamp": "2026-10-08T11:00:00+00:00",
                       "outcome": "GUARDRAIL_BLOCKED", "turn": "x" * 80}
    assert "\n" not in rows[1]["turn"]


def test_blocked_sessions_tolerates_missing_turns_and_timestamps():
    rows = blocked_sessions([{"case_id": "Z", "outcome": "GUARDRAIL_BLOCKED"}], limit=5)

    assert rows == [{"case_id": "Z", "timestamp": "", "outcome": "GUARDRAIL_BLOCKED", "turn": ""}]


# --------------------------------------------------------- parse_invocation_record
def test_parse_final_answer_after_tool_result():
    s = parse_invocation_record(fixture("invocation_final_after_tool.json"))

    assert isinstance(s, InvocationSummary)
    assert s.timestamp == "2026-10-08T15:01:09Z"
    assert s.operation == "ConverseStream"
    assert s.identity_arn.endswith("session-1")
    assert s.model_id.endswith("claude-haiku-4-5-20251001-v1:0")
    assert (s.input_tokens, s.output_tokens) == (1342, 88)
    assert s.stop_reason == "end_turn"
    assert s.guardrail_intervened is False
    assert s.guardrail_policies == ()
    assert s.has_tool_result is True
    assert s.is_final_answer is True
    assert s.request_id == "req-final"


def test_parse_intermediate_tool_use_call_is_not_final():
    s = parse_invocation_record(fixture("invocation_tool_use.json"))

    assert s.stop_reason == "tool_use"
    assert s.has_tool_result is False
    assert s.is_final_answer is False
    assert s.guardrail_intervened is False


def test_parse_guardrail_block_extracts_policies():
    s = parse_invocation_record(fixture("invocation_guardrail_block.json"))

    assert s.stop_reason == "guardrail_intervened"
    assert s.guardrail_intervened is True
    assert s.guardrail_policies == ("CredentialDisclosure", "PROMPT_ATTACK")  # NONE-action INSULTS excluded
    assert s.is_final_answer is True
    assert s.has_tool_result is False
    assert s.output_tokens == 0


def test_parse_record_with_missing_keys_does_not_raise():
    s = parse_invocation_record(fixture("invocation_missing_keys.json"))

    assert s.operation == "Converse"
    assert s.timestamp is None and s.identity_arn is None and s.model_id is None
    assert s.input_tokens is None and s.output_tokens is None and s.stop_reason is None
    assert s.guardrail_policies == ()
    assert (s.guardrail_intervened, s.has_tool_result, s.is_final_answer) == (False, False, False)


def test_parse_empty_record_and_non_dict():
    assert parse_invocation_record({}).is_final_answer is False
    with pytest.raises(TypeError):
        parse_invocation_record("not a dict")


def test_parse_invoke_model_guardrail_action_and_trace_policies():
    record = {"operation": "InvokeModelWithResponseStream", "input": {"inputBodyJson": {"messages": []}},
              "output": {"outputBodyJson": {
                  "amazon-bedrock-guardrailAction": "INTERVENED",
                  "amazon-bedrock-trace": {"guardrail": {"outputAssessments": {"gr-1": [{
                      "sensitiveInformationPolicy": {"piiEntities": [
                          {"type": "EMAIL", "match": "a@b.c", "action": "ANONYMIZED"},
                          {"type": "SSN", "match": "123", "action": "BLOCKED"}]},
                      "wordPolicy": {"managedWordLists": [{"match": "badword", "type": "PROFANITY", "action": "BLOCKED"}]},
                  }]}}}}}}

    s = parse_invocation_record(record)

    assert s.guardrail_intervened is True
    assert s.stop_reason is None
    assert s.guardrail_policies == ("EMAIL", "PROFANITY", "SSN")
    assert s.is_final_answer is True


def test_parse_streamed_guardrail_intervention_in_event_list():
    record = {"operation": "ConverseStream", "output": {"outputBodyJson": [
        {"messageStart": {"role": "assistant"}},
        {"messageStop": {"stopReason": "guardrail_intervened"}}]}}

    s = parse_invocation_record(record)

    assert s.stop_reason == "guardrail_intervened"
    assert s.guardrail_intervened is True


def test_parse_anthropic_native_body_and_token_fallbacks():
    record = {"operation": "InvokeModel",
              "input": {"inputBodyJson": {"messages": [
                  {"role": "user", "content": "plain string prompt"},
                  {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "n", "input": {}}]},
                  {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}]}},
              "output": {"outputBodyJson": {"stop_reason": "end_turn", "usage": {"input_tokens": 7, "output_tokens": 3}}}}

    s = parse_invocation_record(record)

    assert s.stop_reason == "end_turn"
    assert s.has_tool_result is True
    assert (s.input_tokens, s.output_tokens) == (7, 3)


def test_parse_token_fallback_from_converse_usage_block():
    record = {"output": {"outputBodyJson": {"stopReason": "end_turn", "usage": {"inputTokens": 11, "outputTokens": 5}}}}

    s = parse_invocation_record(record)

    assert (s.input_tokens, s.output_tokens) == (11, 5)


def test_has_tool_result_ignores_results_from_earlier_turns_of_the_session():
    record = {"input": {"inputBodyJson": {"messages": [
        {"role": "user", "content": [{"text": "turn one"}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1"}}]},
        {"role": "assistant", "content": [{"text": "answer one"}]},
        {"role": "user", "content": [{"text": "turn two"}]}]}},
        "output": {"outputBodyJson": {"stopReason": "end_turn"}}}

    s = parse_invocation_record(record)

    assert s.has_tool_result is False
    assert s.is_final_answer is True


def test_has_tool_result_true_when_no_user_text_exists():
    record = {"input": {"inputBodyJson": {"messages": [
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1"}}]}]}}}

    assert parse_invocation_record(record).has_tool_result is True


def test_parse_tolerates_stringified_bodies_and_junk_shapes():
    record = {"input": {"inputBodyJson": json.dumps({"messages": [{"role": "user", "content": [{"text": "hi"}]}]}),
                        "inputTokenCount": "12"},
              "output": {"outputBodyJson": "{not json", "outputTokenCount": "bad"},
              "identity": "oops", "timestamp": 123, "errorCode": "ThrottlingException"}

    s = parse_invocation_record(record)

    assert s.input_tokens == 12
    assert s.output_tokens is None
    assert s.identity_arn is None
    assert s.timestamp == "123"
    assert s.error_code == "ThrottlingException"


# -------------------------------------------------------------------- turn_metrics
def test_turn_metrics_counts_final_turns_zero_retrieval_and_policies():
    summaries = [parse_invocation_record(fixture(n)) for n in (
        "invocation_final_after_tool.json", "invocation_tool_use.json", "invocation_guardrail_block.json")]
    no_retrieval = parse_invocation_record({"output": {"outputBodyJson": {"stopReason": "end_turn"},
                                                       "outputTokenCount": 40}})

    result = turn_metrics([*summaries, no_retrieval])

    assert result["records"] == 4
    assert result["final_answer_turns"] == 3
    assert result["blocked_turns"] == 1 and result["answered_turns"] == 2
    assert result["zero_retrieval_turns"] == 1  # the no-retrieval answer; the guardrail block is not an answer
    assert result["zero_retrieval_ratio"] == pytest.approx(1 / 2)
    assert result["interventions"] == 1
    assert result["interventions_by_policy"] == {"CredentialDisclosure": 1, "PROMPT_ATTACK": 1}
    assert result["output_tokens"] == [88, 61, 0, 40]
    assert result["retrieval_success_rate"] == pytest.approx(0.5)  # 1 of 2 non-blocked final turns


def test_turn_metrics_on_empty_input():
    result = turn_metrics([])

    assert result["final_answer_turns"] == 0
    assert result["zero_retrieval_ratio"] == 0.0
    assert result["retrieval_success_rate"] is None
    assert result["output_tokens"] == []


def test_turn_metrics_counts_errors():
    errored = parse_invocation_record({"errorCode": "ValidationException"})

    assert turn_metrics([errored])["errors"] == 1


# ----------------------------------------------------------------------------- CLI
def test_cli_prints_summary_and_threshold(tmp_path, capsys):
    path = tmp_path / "suite_x.jsonl"
    rows = [rec("A", 1, rubric="benign_control", out_tokens=100), rec("A", 2, rubric="benign_control", out_tokens=100),
            rec("B", 1, outcome="GUARDRAIL_BLOCKED", expected="BLOCKED", chunks=0, passed=True, category="inj"),
            rec("B", 2, outcome="ANSWERED_NO_RETRIEVAL", expected="BLOCKED", chunks=0, passed=False, category="inj")]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    code = metrics.main([str(path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "Guardrail intervention rate" in out
    assert "TokenSpike threshold" in out and "300" in out
    assert "B" in out  # consistency finding


def test_cli_json_output_is_machine_readable(tmp_path, capsys):
    path = tmp_path / "suite_x.jsonl"
    path.write_text(json.dumps(rec("A", 1, rubric="benign_control", out_tokens=100)) + "\n")

    code = metrics.main([str(path), "--json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["token_spike_threshold"] == 300
    assert data["intervention_rate"]["total"] == 1
    assert data["files"] == [str(path)]


def test_cli_without_benign_records_reports_threshold_unavailable(tmp_path, capsys):
    path = tmp_path / "suite_x.jsonl"
    path.write_text(json.dumps(rec("A", 1, expected="BLOCKED", outcome="GUARDRAIL_BLOCKED")) + "\n")

    assert metrics.main([str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["token_spike_threshold"] is None
    assert metrics.main([str(path)]) == 0
    assert "unavailable" in capsys.readouterr().out


def test_cli_expands_globs_and_fails_when_nothing_matches(tmp_path, capsys):
    (tmp_path / "suite_1.jsonl").write_text(json.dumps(rec()) + "\n")
    (tmp_path / "suite_2.jsonl").write_text(json.dumps(rec()) + "\n")

    assert metrics.main([str(tmp_path / "suite_*.jsonl"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["intervention_rate"]["total"] == 2
    with pytest.raises(SystemExit):
        metrics.main([str(tmp_path / "nothing_*.jsonl")])


def test_cli_reports_bad_json_cleanly(tmp_path):
    path = tmp_path / "suite_bad.jsonl"
    path.write_text("{oops\n")

    with pytest.raises(SystemExit) as exc:
        metrics.main([str(path)])

    assert "suite_bad.jsonl:1" in str(exc.value)


# ------------------------------------------------------------------ real records (captured 2026-10-10)
def _real_harness_summaries():
    """Six live conversations: 3 input blocks, 1 refusal without retrieval, 1 grounded answer, 1 masked answer."""
    records = json.loads((Path(__file__).parent / "fixtures" / "invocation_real_sample.json").read_text())
    return [metrics.parse_invocation_record(r) for r in records if "Harness" in r["identity"]["arn"]]


def test_real_records_parse_policies_tool_results_and_stop_reasons():
    summaries = _real_harness_summaries()
    assert [s.stop_reason for s in summaries] == [
        "guardrail_intervened", "guardrail_intervened", "end_turn", "guardrail_intervened",
        "tool_use", "end_turn", "tool_use", "guardrail_intervened"]
    assert set(summaries[0].guardrail_policies) == {"PROMPT_ATTACK", "OtherEmployeesPersonalData"}
    assert list(summaries[7].guardrail_policies) == ["NorthstarApiKey"]
    assert [s.has_tool_result for s in summaries] == [False, False, False, False, False, True, False, True]


def test_real_records_turn_metrics_match_the_cloudwatch_alarm_definition():
    """Input blocks are not answers; a masked answer is an answer. 3 answers, 1 without retrieval."""
    result = metrics.turn_metrics(_real_harness_summaries())
    assert result["blocked_turns"] == 3
    assert result["answered_turns"] == 3
    assert result["zero_retrieval_turns"] == 1
    assert result["zero_retrieval_ratio"] == pytest.approx(1 / 3)
    assert result["retrieval_success_rate"] == pytest.approx(2 / 3)
    assert result["interventions"] == 4
    assert result["interventions_by_policy"]["PROMPT_ATTACK"] == 1


def test_an_output_side_block_is_a_block_even_though_the_model_wrote_tokens():
    """Derived record: the real masked answer with its trace action changed from ANONYMIZED to BLOCKED.

    On an output-side block the model has already produced tokens, so a token count cannot tell it from a
    masked answer. The guardrail trace can.
    """
    records = json.loads((Path(__file__).parent / "fixtures" / "invocation_real_sample.json").read_text())
    masked = records[9]
    output_blocked = json.loads(json.dumps(masked).replace('"ANONYMIZED"', '"BLOCKED"'))

    masked_summary, blocked_summary = (metrics.parse_invocation_record(r) for r in (masked, output_blocked))

    assert masked_summary.guardrail_intervened and not masked_summary.guardrail_blocked
    assert blocked_summary.guardrail_blocked and blocked_summary.output_tokens == 87
    result = metrics.turn_metrics([masked_summary, blocked_summary])
    assert result["answered_turns"] == 1 and result["blocked_turns"] == 1


def test_real_output_side_block_counts_as_blocked_not_answered():
    """Real record (hardened suite, case PI-03): 122 output tokens were written, then the answer was withheld."""
    record = json.loads((Path(__file__).parent / "fixtures" / "invocation_real_output_block.json").read_text())

    summary = metrics.parse_invocation_record(record)

    assert summary.output_tokens == 122 and summary.guardrail_blocked
    assert summary.guardrail_policies == ("OtherEmployeesPersonalData",)
    result = metrics.turn_metrics([summary])
    assert result["blocked_turns"] == 1 and result["answered_turns"] == 0
