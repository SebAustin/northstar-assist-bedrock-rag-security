"""Tests for streamlit_app/monitoring_data.py: Logs Insights access (with a fake client) and dashboard shaping."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import monitoring_data as md
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, 16, 0, 0, tzinfo=timezone.utc)


class FakeLogs:
    """Stands in for a boto3 CloudWatch Logs client; replays queued get_query_results responses."""

    def __init__(self, responses, query_id="q-1"):
        self.responses = list(responses)
        self.query_id = query_id
        self.started = []
        self.polls = 0
        self.stopped = []

    def start_query(self, **kwargs):
        self.started.append(kwargs)
        return {"queryId": self.query_id}

    def get_query_results(self, queryId):
        assert queryId == self.query_id
        self.polls += 1
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def stop_query(self, queryId):
        self.stopped.append(queryId)


def row(**fields):
    return [{"field": k, "value": v} for k, v in fields.items()] + [{"field": "@ptr", "value": "abc"}]


def fixture_message(name):
    return json.dumps(json.loads((FIXTURES / name).read_text()))


# ---------------------------------------------------------------------- query building
def test_build_query_filters_on_role_substring_and_limits():
    query = md.build_insights_query("HarnessDefaultServiceRole", limit=500)

    assert 'filter identity.arn like "HarnessDefaultServiceRole"' in query
    assert "fields @timestamp, @message" in query
    assert query.rstrip().endswith("limit 500")
    assert "sort @timestamp desc" in query


def test_build_query_without_role_has_no_filter():
    assert "filter" not in md.build_insights_query("")
    assert "filter" not in md.build_insights_query(None)


@pytest.mark.parametrize("bad", ['x" | stats count()', "a b", "x\ny", "role'", "a\\b", "r|s"])
def test_build_query_rejects_injection_in_role_name(bad):
    with pytest.raises(ValueError, match="HARNESS_ROLE_NAME"):
        md.build_insights_query(bad)


def test_build_query_rejects_out_of_range_limit():
    with pytest.raises(ValueError, match="limit"):
        md.build_insights_query("x", limit=0)
    with pytest.raises(ValueError, match="limit"):
        md.build_insights_query("x", limit=md.MAX_QUERY_ROWS + 1)


# -------------------------------------------------------------------- row conversion
def test_rows_to_records_parses_message_json_and_fills_timestamp():
    rows = [row(**{"@timestamp": "2026-10-08 15:01:09.123", "@message": fixture_message("invocation_tool_use.json")})]

    records = md.rows_to_records(rows)

    assert len(records) == 1
    assert records[0]["operation"] == "ConverseStream"
    assert records[0]["timestamp"] == "2026-10-08T15:01:06Z"  # the record's own timestamp wins


def test_rows_to_records_uses_insights_timestamp_when_record_has_none():
    rows = [row(**{"@timestamp": "2026-10-08 15:01:09.123", "@message": '{"operation": "Converse"}'})]

    assert md.rows_to_records(rows)[0]["timestamp"] == "2026-10-08 15:01:09.123"


def test_rows_to_records_skips_unparseable_rows_and_ptr():
    rows = [row(**{"@message": "not json"}), row(**{"@message": "[1]"}), row(**{"@message": '{"ok": 1}'}),
            [{"field": "@ptr", "value": "x"}], row(**{"operation": "Converse", "identity.arn": "arn:x"})]

    records = md.rows_to_records(rows)

    assert records == [{"ok": 1}, {"operation": "Converse", "identity.arn": "arn:x"}]


# ------------------------------------------------------------------------ polling loop
def test_run_query_polls_until_complete_with_injected_sleep():
    complete = {"status": "Complete", "results": [row(**{"@message": "{}"})],
                "statistics": {"recordsMatched": 1.0}}
    client = FakeLogs([{"status": "Scheduled"}, {"status": "Running"}, complete])
    sleeps = []

    result = md.run_insights_query(client, "/g", "q", NOW - timedelta(hours=1), NOW, sleep=sleeps.append,
                                   poll_interval=2.0, timeout=30.0)

    assert client.polls == 3
    assert sleeps == [2.0, 2.0]
    assert len(result.rows) == 1
    assert result.truncated is False
    started = client.started[0]
    assert started["logGroupName"] == "/g"
    assert started["startTime"] == int((NOW - timedelta(hours=1)).timestamp())
    assert started["endTime"] == int(NOW.timestamp())
    assert started["queryString"] == "q"
    assert started["limit"] == md.MAX_QUERY_ROWS


def test_run_query_marks_truncated_when_limit_reached():
    rows = [row(**{"@message": "{}"})] * 3
    client = FakeLogs([{"status": "Complete", "results": rows, "statistics": {"recordsMatched": 50}}])

    result = md.run_insights_query(client, "/g", "q", NOW - timedelta(hours=1), NOW, limit=3, sleep=lambda s: None)

    assert result.truncated is True
    assert result.records_matched == 50


def test_run_query_times_out_and_stops_the_query():
    client = FakeLogs([{"status": "Running"}])
    sleeps = []

    with pytest.raises(md.InsightsTimeoutError):
        md.run_insights_query(client, "/g", "q", NOW - timedelta(hours=1), NOW, sleep=sleeps.append,
                              poll_interval=1.0, timeout=3.0)

    assert sum(sleeps) == 3.0
    assert client.stopped == ["q-1"]


@pytest.mark.parametrize("status", ["Failed", "Cancelled", "Timeout"])
def test_run_query_raises_on_terminal_failure_status(status):
    client = FakeLogs([{"status": status}])

    with pytest.raises(md.InsightsError, match=status):
        md.run_insights_query(client, "/g", "q", NOW - timedelta(hours=1), NOW, sleep=lambda s: None)


def test_run_query_validates_arguments():
    client = FakeLogs([{"status": "Complete", "results": []}])
    with pytest.raises(ValueError, match="start"):
        md.run_insights_query(client, "/g", "q", NOW, NOW - timedelta(hours=1), sleep=lambda s: None)
    with pytest.raises(ValueError, match="log group"):
        md.run_insights_query(client, "", "q", NOW - timedelta(hours=1), NOW, sleep=lambda s: None)
    with pytest.raises(ValueError, match="poll_interval"):
        md.run_insights_query(client, "/g", "q", NOW - timedelta(hours=1), NOW, poll_interval=0, sleep=lambda s: None)


def test_run_query_survives_stop_query_failure():
    class Boom(FakeLogs):
        def stop_query(self, queryId):
            raise RuntimeError("nope")

    with pytest.raises(md.InsightsTimeoutError):
        md.run_insights_query(Boom([{"status": "Running"}]), "/g", "q", NOW - timedelta(hours=1), NOW,
                              sleep=lambda s: None, timeout=1.0)


def test_fetch_invocation_records_end_to_end_with_fake_client():
    message = fixture_message("invocation_final_after_tool.json")
    client = FakeLogs([{"status": "Complete", "results": [row(**{"@message": message})], "statistics": {}}])

    records, truncated = md.fetch_invocation_records(client, "/northstar/bedrock/invocations", "HarnessRole",
                                                     timedelta(hours=6), now=NOW, sleep=lambda s: None)

    assert truncated is False
    assert records[0]["requestId"] == "req-final"
    started = client.started[0]
    assert started["startTime"] == int((NOW - timedelta(hours=6)).timestamp())
    assert 'like "HarnessRole"' in started["queryString"]


# ------------------------------------------------------------------ client construction
def test_make_logs_client_reports_missing_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)

    with pytest.raises(md.MonitoringSourceError, match="boto3"):
        md.make_logs_client("us-east-1")


def test_make_logs_client_reports_missing_credentials(monkeypatch):
    class Session:
        def __init__(self, **kwargs):
            pass

        def get_credentials(self):
            return None

    monkeypatch.setitem(sys.modules, "boto3", type("B", (), {"Session": Session}))

    with pytest.raises(md.MonitoringSourceError, match="credentials"):
        md.make_logs_client("us-east-1")


def test_make_logs_client_returns_logs_client(monkeypatch):
    seen = {}

    class Session:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def get_credentials(self):
            return object()

        def client(self, name):
            seen["client"] = name
            return "CLIENT"

    monkeypatch.setitem(sys.modules, "boto3", type("B", (), {"Session": Session}))

    assert md.make_logs_client("eu-west-1") == "CLIENT"
    assert seen == {"kwargs": {"region_name": "eu-west-1"}, "client": "logs"}


def test_source_errors_include_boto_and_insights_errors():
    assert md.InsightsError in md.SOURCE_ERRORS
    assert md.MonitoringSourceError in md.SOURCE_ERRORS
    from botocore.exceptions import ClientError
    assert ClientError in md.SOURCE_ERRORS


def test_settings_from_env_applies_defaults_and_overrides():
    defaults = md.settings_from_env({})
    assert defaults.log_group == "/northstar/bedrock/invocations"
    assert defaults.role_name == md.DEFAULT_ROLE_FILTER
    assert defaults.region == "us-east-1"
    assert defaults.results_dir.name == "results"

    custom = md.settings_from_env({"INVOCATION_LOG_GROUP": "/g", "HARNESS_ROLE_NAME": "R", "AWS_REGION": "eu-west-1",
                                   "RESULTS_DIR": "/tmp/x"})
    assert (custom.log_group, custom.role_name, custom.region, custom.results_dir) == ("/g", "R", "eu-west-1",
                                                                                      Path("/tmp/x"))


# ----------------------------------------------------------------- local files / windows
def test_list_result_files_newest_first(tmp_path):
    old = tmp_path / "suite_old.jsonl"
    new = tmp_path / "suite_new.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    (tmp_path / "matrix.md").write_text("x")
    os.utime(old, (time.time() - 100, time.time() - 100))

    assert md.list_result_files(tmp_path) == [new, old]
    assert md.list_result_files(tmp_path / "missing") == []


def test_filter_by_window_keeps_records_since_cutoff_and_drops_undated_ones():
    records = [{"timestamp": "2026-10-08T15:30:00+00:00"}, {"timestamp": "2026-10-08T10:00:00Z"}, {"x": 1}]

    kept = md.filter_by_window(records, NOW - timedelta(hours=1))

    assert kept == [records[0]]
    assert md.filter_by_window(records, None) == records


def test_load_local_records_combines_files_and_applies_window(tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text('{"timestamp": "2026-10-08T15:30:00+00:00", "n": 1}\n')
    b.write_text('{"timestamp": "2026-10-01T15:30:00+00:00", "n": 2}\n')

    assert [r["n"] for r in md.load_local_records([a, b])] == [1, 2]
    assert [r["n"] for r in md.load_local_records([a, b], NOW - timedelta(hours=1))] == [1]


def test_window_options_cover_all_time_for_local_only():
    assert md.WINDOWS["Last hour"] == timedelta(hours=1)
    assert md.WINDOWS["All time"] is None


# ------------------------------------------------------------------ dashboard shaping
def suite_rec(case_id, outcome, category, out_tokens, ts, chunks=0, turn="a prompt", passed=True, run=1):
    return {"case_id": case_id, "run": run, "outcome": outcome, "category": category, "owasp": "LLM01",
            "retrieved_chunk_count": chunks, "usage": {"outputTokens": out_tokens, "inputTokens": 10},
            "timestamp": ts, "turns": [turn], "passed": passed, "expected": "BLOCKED"}


def test_suite_dashboard_computes_kpis_and_tables():
    records = [
        suite_rec("PI-01", "GUARDRAIL_BLOCKED", "direct_injection", 0, "2026-10-08T10:00:00+00:00", turn="p" * 300),
        suite_rec("PI-01", "ANSWERED_NO_RETRIEVAL", "direct_injection", 120, "2026-10-08T10:01:00+00:00",
                  passed=False, run=2),
        suite_rec("B-01", "ANSWERED_WITH_RETRIEVAL", "benign", 80, "2026-10-08T10:02:00+00:00", chunks=3),
        suite_rec("E-01", "ERROR", "benign", 0, "2026-10-08T10:03:00+00:00"),
    ]

    d = md.build_suite_dashboard(records)

    assert d.source == "local" and d.record_count == 4
    assert d.intervention_rate == pytest.approx(0.25)
    assert d.retrieval_success_rate == pytest.approx(0.5)
    assert d.p95_output_tokens == pytest.approx(114, abs=1)
    assert d.error_count == 1
    assert d.interventions_by_group == {"direct_injection": 1}
    assert d.group_label == "Category"
    assert [p["output_tokens"] for p in d.token_series] == [0, 120, 80, 0]
    assert d.consistency[0]["case_id"] == "PI-01"
    assert len(d.blocked[0]["turn"]) == 80


def test_suite_dashboard_on_empty_records():
    d = md.build_suite_dashboard([])

    assert d.record_count == 0
    assert d.intervention_rate is None
    assert d.retrieval_success_rate is None
    assert d.p95_output_tokens is None
    assert d.interventions_by_group == {} and d.token_series == () and d.blocked == ()


def invocation_records():
    names = ("invocation_final_after_tool.json", "invocation_tool_use.json", "invocation_guardrail_block.json",
             "invocation_missing_keys.json")
    return [json.loads((FIXTURES / n).read_text()) for n in names]


def test_invocation_dashboard_computes_kpis_without_raw_text():
    d = md.build_invocation_dashboard(invocation_records())

    assert d.source == "cloudwatch" and d.record_count == 4
    assert d.intervention_rate == pytest.approx(0.5)  # 1 of 2 final-answer turns
    assert d.retrieval_success_rate == pytest.approx(1.0)
    assert d.p95_output_tokens == pytest.approx(85.3, abs=0.1)
    assert d.interventions_by_group == {"CredentialDisclosure": 1, "PROMPT_ATTACK": 1}
    assert d.group_label == "Guardrail policy"
    assert d.consistency == ()
    assert d.blocked[0]["case_id"] == "req-blocked"
    assert "PROMPT_ATTACK" in d.blocked[0]["turn"]
    assert "Ignore all previous" not in json.dumps(d.blocked)
    assert [p["output_tokens"] for p in d.token_series] == [61, 88, 0]  # sorted by time, undated dropped


def test_invocation_dashboard_on_empty_records():
    d = md.build_invocation_dashboard([])

    assert d.intervention_rate is None and d.p95_output_tokens is None and d.error_count == 0


def test_invocation_dashboard_labels_a_masked_answer_differently_from_a_block():
    """Real records: three input blocks and one answer delivered with the API key masked."""
    records = json.loads((FIXTURES / "invocation_real_sample.json").read_text())

    rows = md.build_invocation_dashboard(records).blocked

    outcomes = {row["turn"]: row["outcome"] for row in rows}
    assert outcomes["policies: NorthstarApiKey (prompt text not shown)"] == "ANSWER_MASKED"
    assert sum(row["outcome"] == "GUARDRAIL_BLOCKED" for row in rows) == 3
