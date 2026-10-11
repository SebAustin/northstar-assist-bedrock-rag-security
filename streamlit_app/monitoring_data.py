"""Thin, pure data layer for the Monitoring page (no Streamlit imports, so it is unit-testable).

Two sources feed the same ``DashboardData`` shape:

* ``local``: ``results/*.jsonl`` written by ``tools/run_suite.py`` (offline default);
* ``cloudwatch``: Bedrock model-invocation log records pulled with CloudWatch Logs Insights.

The aggregation itself lives in ``tools/metrics.py`` so the dashboard, the alarm threshold calculation and the
launch report all share one implementation.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:  # `streamlit run` does not use pytest.ini's pythonpath
    sys.path.insert(0, str(ROOT / "tools"))

import metrics  # noqa: E402  (needs the sys.path tweak above)

log = logging.getLogger("monitoring_data")

DEFAULT_LOG_GROUP = "/northstar/bedrock/invocations"
DEFAULT_ROLE_FILTER = "HarnessDefaultServiceRole"
DEFAULT_REGION = "us-east-1"
MAX_QUERY_ROWS = 10_000  # Logs Insights hard limit for `limit`
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_TIMEOUT = 60.0
BLOCKED_ROWS = 10
WINDOWS: dict[str, timedelta | None] = {
    "Last hour": timedelta(hours=1),
    "Last 6 hours": timedelta(hours=6),
    "Last 24 hours": timedelta(hours=24),
    "Last 7 days": timedelta(days=7),
    "All time": None,  # local files only: Logs Insights always needs a bounded range
}
_TERMINAL_FAILURES = frozenset({"Failed", "Cancelled", "Timeout"})
_ROLE_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+=,.@_-/:")


class MonitoringSourceError(RuntimeError):
    """A data source cannot be used (missing boto3, no credentials ...); the message is safe to show a user."""


class InsightsError(RuntimeError):
    """A Logs Insights query ended in a failure status."""


class InsightsTimeoutError(InsightsError):
    """A Logs Insights query did not complete within the polling timeout."""


def _source_errors() -> tuple[type[BaseException], ...]:
    errors: tuple[type[BaseException], ...] = (MonitoringSourceError, InsightsError)
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:  # pragma: no cover - boto3 is a declared dependency
        return errors
    return (*errors, BotoCoreError, ClientError)


SOURCE_ERRORS = _source_errors()


@dataclass(frozen=True)
class Settings:
    log_group: str
    role_name: str
    region: str
    results_dir: Path


def settings_from_env(env: Mapping[str, str]) -> Settings:
    """Read page configuration from an environment mapping (``os.environ`` in the page)."""
    return Settings(
        log_group=env.get("INVOCATION_LOG_GROUP") or DEFAULT_LOG_GROUP,
        role_name=env.get("HARNESS_ROLE_NAME") or DEFAULT_ROLE_FILTER,
        region=env.get("AWS_REGION") or DEFAULT_REGION,
        results_dir=Path(env["RESULTS_DIR"]) if env.get("RESULTS_DIR") else ROOT / "results",
    )


# ------------------------------------------------------------------ Logs Insights
def build_insights_query(role_name: str | None, limit: int = MAX_QUERY_ROWS) -> str:
    """Query returning raw invocation-log messages, optionally filtered to one role ARN substring.

    The role name is interpolated into the query, so it is restricted to IAM-name/ARN characters.
    """
    if not 1 <= limit <= MAX_QUERY_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_QUERY_ROWS}")
    lines = ["fields @timestamp, @message"]
    if role_name:
        if not set(role_name) <= _ROLE_NAME_CHARS:
            raise ValueError("HARNESS_ROLE_NAME may only contain letters, digits and + = , . @ _ - / :")
        lines.append(f'| filter identity.arn like "{role_name}"')
    lines += ["| sort @timestamp desc", f"| limit {limit}"]
    return "\n".join(lines)


def rows_to_records(rows: Sequence[Sequence[Mapping[str, str]]]) -> list[dict]:
    """Convert Insights rows (lists of ``{"field", "value"}``) into invocation-record dicts.

    A ``@message`` field holds the raw log record as JSON and is parsed; rows without it are mapped field by
    field. Rows that are not JSON objects are skipped (and logged), never raised, so one bad line cannot blank
    the dashboard.
    """
    records: list[dict] = []
    for row in rows:
        fields = {cell["field"]: cell["value"] for cell in row if cell.get("field") != "@ptr"}
        if "@message" not in fields:
            if fields:
                records.append(fields)
            continue
        try:
            record = json.loads(fields["@message"])
        except (TypeError, ValueError):
            log.warning("skipping Insights row with non-JSON @message")
            continue
        if not isinstance(record, dict):
            log.warning("skipping Insights row whose @message is not a JSON object")
            continue
        if record.get("timestamp") is None and fields.get("@timestamp"):
            record = {**record, "timestamp": fields["@timestamp"]}
        records.append(record)
    return records


@dataclass(frozen=True)
class InsightsResult:
    rows: tuple[tuple[Mapping[str, str], ...], ...]
    records_matched: float | None
    truncated: bool


def run_insights_query(client: Any, log_group: str, query: str, start: datetime, end: datetime, *,
                       limit: int = MAX_QUERY_ROWS, poll_interval: float = DEFAULT_POLL_INTERVAL,
                       timeout: float = DEFAULT_TIMEOUT, sleep: Callable[[float], None] = time.sleep) -> InsightsResult:
    """Start a Logs Insights query and poll until it completes.

    ``client`` and ``sleep`` are injected so the loop is testable with a fake. Elapsed time is the sum of the
    sleeps, which keeps the timeout deterministic under test.
    """
    if not log_group:
        raise ValueError("log group name is required")
    if end <= start:
        raise ValueError("start must be before end")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")
    query_id = client.start_query(logGroupName=log_group, startTime=int(start.timestamp()),
                                  endTime=int(end.timestamp()), queryString=query, limit=limit)["queryId"]
    waited = 0.0
    while True:
        response = client.get_query_results(queryId=query_id)
        status = response.get("status")
        if status == "Complete":
            rows = tuple(tuple(row) for row in response.get("results", []))
            matched = (response.get("statistics") or {}).get("recordsMatched")
            return InsightsResult(rows=rows, records_matched=matched, truncated=len(rows) >= limit)
        if status in _TERMINAL_FAILURES:
            raise InsightsError(f"Logs Insights query {query_id} ended with status {status}")
        if waited >= timeout:
            _stop_quietly(client, query_id)
            raise InsightsTimeoutError(f"Logs Insights query {query_id} still {status} after {timeout:g}s")
        sleep(poll_interval)
        waited += poll_interval


def _stop_quietly(client: Any, query_id: str) -> None:
    try:
        client.stop_query(queryId=query_id)
    except Exception:  # noqa: BLE001 - best-effort cleanup; the timeout error is what matters
        log.warning("could not stop Logs Insights query %s", query_id, exc_info=True)


def fetch_invocation_records(client: Any, log_group: str, role_name: str | None, window: timedelta, *,
                             now: datetime, limit: int = MAX_QUERY_ROWS,
                             sleep: Callable[[float], None] = time.sleep, **poll: float) -> tuple[list[dict], bool]:
    """Run the invocation-log query for ``[now - window, now]``; returns (records, truncated)."""
    result = run_insights_query(client, log_group, build_insights_query(role_name, limit), now - window, now,
                                limit=limit, sleep=sleep, **poll)
    return rows_to_records(result.rows), result.truncated


def make_logs_client(region: str) -> Any:
    """Create a CloudWatch Logs client, raising ``MonitoringSourceError`` with a friendly message if impossible."""
    try:
        import boto3
    except ImportError as exc:
        raise MonitoringSourceError("boto3 is not installed; run `pip install boto3` to use CloudWatch.") from exc
    session = boto3.Session(region_name=region)
    if session.get_credentials() is None:
        raise MonitoringSourceError("No AWS credentials found. Set AWS_PROFILE (for example `udacity`) or the "
                                    "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY variables.")
    return session.client("logs")


# ---------------------------------------------------------------- local files / windows
def list_result_files(results_dir: Path) -> list[Path]:
    """``*.jsonl`` files in ``results_dir``, newest first (empty if the directory does not exist)."""
    if not Path(results_dir).is_dir():
        return []
    return sorted(Path(results_dir).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def filter_by_window(records: Sequence[dict], since: datetime | None) -> list[dict]:
    """Records at or after ``since``. Records without a parseable timestamp are dropped when filtering."""
    if since is None:
        return list(records)
    kept = []
    for record in records:
        stamp = metrics.parse_timestamp(record.get("timestamp"))
        if stamp is not None and stamp >= since:
            kept.append(record)
    return kept


def load_local_records(files: Sequence[Path], since: datetime | None = None) -> list[dict]:
    """Load suite JSONL files and keep records inside the window. Raises ``ValueError`` naming file:line."""
    return filter_by_window(metrics.load_jsonl(files), since)


# ------------------------------------------------------------------ dashboard shaping
@dataclass(frozen=True)
class DashboardData:
    """Everything the Monitoring page renders, already aggregated (and PII-safe)."""

    source: str
    record_count: int
    intervention_rate: float | None
    retrieval_success_rate: float | None
    p95_output_tokens: float | None
    error_count: int
    group_label: str
    interventions_by_group: dict[str, int]
    token_series: tuple[dict, ...]
    consistency: tuple[dict, ...]
    blocked: tuple[dict, ...]
    notes: tuple[str, ...] = ()


def _series(points: Sequence[tuple[Any, int | None, int | None]]) -> tuple[dict, ...]:
    dated = [(metrics.parse_timestamp(ts), out, inp) for ts, out, inp in points]
    usable = sorted(((ts, out, inp) for ts, out, inp in dated if ts is not None and out is not None),
                    key=lambda p: p[0])
    return tuple({"timestamp": ts, "output_tokens": out, "input_tokens": inp} for ts, out, inp in usable)


def build_suite_dashboard(records: Sequence[dict]) -> DashboardData:
    """Shape run_suite JSONL records for the page."""
    rate = metrics.intervention_rate(records)
    has_tokens = bool(metrics.usage_values(records, "outputTokens"))
    points = [(r.get("timestamp"), r["usage"].get("outputTokens"), r["usage"].get("inputTokens"))
              for r in records if isinstance(r.get("usage"), dict)]
    return DashboardData(
        source="local",
        record_count=len(records),
        intervention_rate=rate["rate"] if records else None,
        retrieval_success_rate=metrics.retrieval_success_rate(records),
        p95_output_tokens=metrics.token_stats(records)["output"]["p95"] if has_tokens else None,
        error_count=rate["by_outcome"][metrics.ERROR],
        group_label="Category",
        interventions_by_group={name: g["intervened"] for name, g in rate["by_category"].items() if g["intervened"]},
        token_series=_series(points),
        consistency=tuple(metrics.consistency_findings(records)),
        blocked=tuple(metrics.blocked_sessions(records, BLOCKED_ROWS)),
    )


def build_invocation_dashboard(records: Sequence[dict]) -> DashboardData:
    """Shape Bedrock invocation-log records for the page. Never exposes prompt text: blocked rows show policies."""
    summaries = [metrics.parse_invocation_record(r) for r in records]
    turns = metrics.turn_metrics(summaries)
    tokens = turns["output_tokens"]
    finals = turns["final_answer_turns"]
    floor = datetime.min.replace(tzinfo=timezone.utc)
    intervened = sorted((s for s in summaries if s.guardrail_intervened),
                        key=lambda s: metrics.parse_timestamp(s.timestamp) or floor, reverse=True)
    blocked = tuple({"case_id": s.request_id or "-", "timestamp": s.timestamp or "",
                     "outcome": metrics.BLOCKED if s.guardrail_blocked else metrics.MASKED,
                     "turn": "policies: " + (", ".join(s.guardrail_policies) or "unknown") + " (prompt text not shown)"}
                    for s in intervened[:BLOCKED_ROWS])
    return DashboardData(
        source="cloudwatch",
        record_count=len(summaries),
        intervention_rate=(turns["interventions"] / finals) if finals else None,
        retrieval_success_rate=turns["retrieval_success_rate"],
        p95_output_tokens=metrics.percentile(tokens, 95) if tokens else None,
        error_count=turns["errors"],
        group_label="Guardrail policy",
        interventions_by_group=turns["interventions_by_policy"],
        token_series=_series([(s.timestamp, s.output_tokens, s.input_tokens) for s in summaries]),
        consistency=(),
        blocked=blocked,
        notes=("Consistency findings need the repeated runs in local suite files.",),
    )
