"""Pure, immutable aggregation shared by the Streamlit dashboard, the alarm thresholds and the launch report.

Two kinds of input are supported:

* **Suite records**: one JSON object per run, as written by ``run_suite.main`` to ``results/suite_*.jsonl``
  (``case_id``, ``outcome``, ``retrieved_chunk_count``, ``usage``, ``passed``, ``turns`` ...).
* **Bedrock model-invocation log records**: one JSON object per model call, as delivered to CloudWatch Logs
  (``timestamp``, ``operation``, ``identity.arn``, ``modelId``, ``input.*``, ``output.*``).

NOTE (PLAN R2): the invocation-log key names used here follow the *documented* schema but have not yet been
validated against real log lines from this account. The parsers are deliberately defensive (every key is
optional, bodies may be dicts, lists of stream events or JSON strings); re-validate against a real record
before wiring metric filters to the same paths.

Usage:
  .venv/bin/python tools/metrics.py results/suite_*.jsonl [--json]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTCOMES = ("GUARDRAIL_BLOCKED", "ANSWERED_WITH_RETRIEVAL", "ANSWERED_NO_RETRIEVAL", "ERROR")
BLOCKED = "GUARDRAIL_BLOCKED"
MASKED = "ANSWER_MASKED"  # delivered with a value hidden; invocation-log view only
ERROR = "ERROR"
BENIGN_RUBRIC = "benign_control"
BENIGN_EXPECTED = "ANSWERED"
PREVIEW_CHARS = 80  # prompts can contain PII: never surface more than this
DEFAULT_SPIKE_MULTIPLIER = 3

GUARDRAIL_STOP_REASON = "guardrail_intervened"
GUARDRAIL_ACTION_KEY = "amazon-bedrock-guardrailAction"
GUARDRAIL_ACTION_INTERVENED = "INTERVENED"
BLOCK_ACTION = "BLOCKED"
POLICY_ACTIONS = frozenset({BLOCK_ACTION, "ANONYMIZED", "INTERVENED"})
FINAL_STOP_REASON = "end_turn"


# --------------------------------------------------------------------------- loading
def load_jsonl(paths: str | Path | Iterable[str | Path]) -> list[dict]:
    """Read JSON-lines files into a list of dicts, skipping blank lines.

    Raises ``ValueError`` naming the file and 1-based line number for malformed JSON or non-object lines.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    records: list[dict] = []
    for path in paths:
        with Path(path).open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{number}: invalid JSON ({exc.msg})") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{number}: expected a JSON object, got {type(value).__name__}")
                records.append(value)
    return records


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (``Z`` or offset, naive = UTC) into an aware datetime, else ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)  # Logs Insights style "2026-10-08 15:01:09.123"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ suite-record metrics
def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _group(records: Sequence[dict], key: str) -> dict[str, dict]:
    totals: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    for record in records:
        label = str(record.get(key) or "unknown")
        totals[label] += 1
        blocked[label] += record.get("outcome") == BLOCKED
    return {label: {"total": totals[label], "intervened": blocked[label], "rate": _rate(blocked[label], totals[label])}
            for label in totals}


def intervention_rate(records: Sequence[dict]) -> dict:
    """Overall guardrail intervention rate plus counts by outcome, ``category`` and ``owasp``."""
    counts = Counter(str(r.get("outcome") or "UNKNOWN") for r in records)
    by_outcome = {outcome: counts.get(outcome, 0) for outcome in OUTCOMES}
    by_outcome.update({k: v for k, v in counts.items() if k not in by_outcome})
    return {
        "total": len(records),
        "intervened": by_outcome[BLOCKED],
        "rate": _rate(by_outcome[BLOCKED], len(records)),
        "by_outcome": by_outcome,
        "by_category": _group(records, "category"),
        "by_owasp": _group(records, "owasp"),
    }


def retrieval_success_rate(records: Sequence[dict]) -> float | None:
    """Share of non-blocked, non-error turns that retrieved at least one KB chunk (``None`` if no such turns)."""
    eligible = [r for r in records if r.get("outcome") not in (BLOCKED, ERROR)]
    if not eligible:
        return None
    return sum(1 for r in eligible if (r.get("retrieved_chunk_count") or 0) > 0) / len(eligible)


def percentile(values: Sequence[float], q: float) -> float:
    """``q`` in [0, 100], linear interpolation between closest ranks (numpy's default); 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = math.ceil(position)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _stats(values: Sequence[float]) -> dict:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0}
    return {"mean": sum(values) / len(values), "p50": percentile(values, 50), "p95": percentile(values, 95),
            "max": max(values)}


def usage_values(records: Iterable[dict], key: str) -> list[int]:
    values = []
    for record in records:
        usage = record.get("usage")
        value = usage.get(key) if isinstance(usage, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            values.append(value)
    return values


def token_stats(records: Sequence[dict]) -> dict:
    """``{"output": {mean, p50, p95, max}, "input": {...}}`` from ``usage.outputTokens`` / ``usage.inputTokens``."""
    return {"output": _stats(usage_values(records, "outputTokens")),
            "input": _stats(usage_values(records, "inputTokens"))}


def is_benign(record: dict) -> bool:
    return record.get("rubric_category") == BENIGN_RUBRIC or record.get("expected") == BENIGN_EXPECTED


def token_spike_threshold(records: Sequence[dict], multiplier: float = DEFAULT_SPIKE_MULTIPLIER) -> int:
    """``multiplier`` x the p95 output tokens of benign records only, rounded up (the TokenSpike alarm value)."""
    values = usage_values([r for r in records if is_benign(r)], "outputTokens")
    if not values:
        raise ValueError("no benign records with output-token usage: cannot derive a TokenSpike threshold")
    return math.ceil(round(multiplier * percentile(values, 95), 6))


def consistency_findings(records: Sequence[dict]) -> list[dict]:
    """Cases whose runs disagree, with the per-run outcomes in run order.

    ``kind`` is ``verdict`` when some runs passed and some failed, and ``mechanism`` when every run reached the
    same verdict through different outcomes (for example one guardrail block and two refusals by the model).
    """
    by_case: dict[str, list[dict]] = {}
    for record in records:
        by_case.setdefault(str(record.get("case_id")), []).append(record)
    findings = []
    for case_id, runs in by_case.items():
        passes = [bool(r.get("passed")) for r in runs]
        ordered = sorted(runs, key=lambda r: r.get("run") or 0)
        outcomes = [str(r.get("outcome")) for r in ordered]
        if any(passes) and not all(passes):
            kind = "verdict"
        elif len(set(outcomes)) > 1:
            kind = "mechanism"
        else:
            continue
        findings.append({"case_id": case_id, "kind": kind, "passed": sum(passes), "runs": len(runs),
                         "outcomes": outcomes})
    return findings


def _last_turn_preview(record: dict) -> str:
    turns = record.get("turns")
    turn = turns[-1] if isinstance(turns, (list, tuple)) and turns else record.get("turn", "")
    return str(turn or "")[:PREVIEW_CHARS].replace("\n", " ")


def blocked_sessions(records: Sequence[dict], limit: int = 10) -> list[dict]:
    """The ``limit`` most recent guardrail-blocked records, with the turn cut to ``PREVIEW_CHARS`` characters."""
    floor = datetime.min.replace(tzinfo=timezone.utc)
    blocked = [r for r in records if r.get("outcome") == BLOCKED]
    blocked.sort(key=lambda r: parse_timestamp(r.get("timestamp")) or floor, reverse=True)
    return [{"case_id": str(r.get("case_id", "")), "timestamp": str(r.get("timestamp") or ""),
             "outcome": BLOCKED, "turn": _last_turn_preview(r)} for r in blocked[:limit]]


# ------------------------------------------------------- Bedrock invocation-log parsing
@dataclass(frozen=True)
class InvocationSummary:
    """The fields of one model-invocation log record that the dashboard and alarms care about."""

    timestamp: str | None
    operation: str | None
    identity_arn: str | None
    model_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    stop_reason: str | None
    guardrail_intervened: bool
    guardrail_policies: tuple[str, ...]
    has_tool_result: bool
    is_final_answer: bool
    request_id: str | None = None
    error_code: str | None = None
    guardrail_blocked: bool = False  # the turn was stopped; False for an answer delivered with masking


def _as_json(value: Any) -> Any:
    """Bodies are normally objects but may arrive as JSON strings; unparsable strings become ``None``."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _walk(node: Any) -> Iterator[tuple[str, Any]]:
    """Yield every (key, value) pair in a nested dict/list structure, depth first."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _walk_dicts(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_dicts(item)


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(float(value))
        except (ValueError, OverflowError):
            return None
    return None


def _last_walk_value(node: Any, keys: tuple[str, ...]) -> Any:
    found = [value for key, value in _walk(node) if key in keys]
    return found[-1] if found else None


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _blocks(messages: Any) -> list[tuple[str, dict]]:
    """Flatten request messages into ordered (role, content-block) pairs (Converse or Anthropic-native)."""
    flat: list[tuple[str, dict]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", ""))
        content = message.get("content")
        if isinstance(content, str):
            flat.append((role, {"text": content}))
        elif isinstance(content, list):
            flat.extend((role, block) for block in content if isinstance(block, dict))
    return flat


def _is_text(block: dict) -> bool:
    return "text" in block or block.get("type") == "text"


def _is_tool_result(block: dict) -> bool:
    return "toolResult" in block or block.get("type") == "tool_result"


def _request_has_tool_result(request_body: Any) -> bool:
    """True if a ``toolResult`` block follows the last user text block in the request messages."""
    messages = request_body.get("messages") if isinstance(request_body, dict) else None
    blocks = _blocks(messages)
    last_text = max((i for i, (role, block) in enumerate(blocks) if role == "user" and _is_text(block)), default=-1)
    return any(_is_tool_result(block) for _, block in blocks[last_text + 1:])


def _guardrail_intervened(output: Any) -> bool:
    return any((key == "stopReason" and value == GUARDRAIL_STOP_REASON)
               or (key == GUARDRAIL_ACTION_KEY and value == GUARDRAIL_ACTION_INTERVENED)
               for key, value in _walk(output))


def _guardrail_blocked(output: Any, output_tokens: int | None) -> bool:
    """True when an intervention stopped the turn rather than masking part of a delivered answer.

    An input-side block produces no output tokens. An output-side block does (the model wrote the answer before
    it was withheld), so the trace decides: any policy with action BLOCKED means the user got the blocked message.
    """
    if not _guardrail_intervened(output):
        return False
    return not output_tokens or any(node.get("action") == BLOCK_ACTION for node in _walk_dicts(output))


def _guardrail_policies(output: Any) -> tuple[str, ...]:
    """Policy labels (PROMPT_ATTACK, topic names, PII types ...) with a BLOCKED/ANONYMIZED/INTERVENED action."""
    labels = set()
    for node in _walk_dicts(output):
        if node.get("action") not in POLICY_ACTIONS:
            continue
        label = node.get("name") or node.get("type") or ("CUSTOM_WORD" if "match" in node else None)
        if isinstance(label, str):
            labels.add(label)
    return tuple(sorted(labels))


def parse_invocation_record(record: dict) -> InvocationSummary:
    """Summarise one Bedrock model-invocation log record. Never raises on missing or oddly shaped keys."""
    if not isinstance(record, dict):
        raise TypeError(f"invocation record must be a dict, got {type(record).__name__}")
    input_part = record.get("input") if isinstance(record.get("input"), dict) else {}
    output_part = record.get("output") if isinstance(record.get("output"), dict) else {}
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    request_body = _as_json(input_part.get("inputBodyJson"))
    response_body = _as_json(output_part.get("outputBodyJson"))

    input_tokens = _to_int(input_part.get("inputTokenCount"))
    if input_tokens is None:
        input_tokens = _to_int(_last_walk_value(response_body, ("inputTokens", "input_tokens")))
    output_tokens = _to_int(output_part.get("outputTokenCount"))
    if output_tokens is None:
        output_tokens = _to_int(_last_walk_value(response_body, ("outputTokens", "output_tokens")))

    stop_reason = _last_walk_value(response_body, ("stopReason", "stop_reason"))
    stop_reason = stop_reason if isinstance(stop_reason, str) else None
    intervened = _guardrail_intervened(response_body)

    return InvocationSummary(
        timestamp=_opt_str(record.get("timestamp")),
        operation=_opt_str(record.get("operation")),
        identity_arn=_opt_str(identity.get("arn")),
        model_id=_opt_str(record.get("modelId")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
        guardrail_intervened=intervened,
        guardrail_policies=_guardrail_policies(response_body),
        has_tool_result=_request_has_tool_result(request_body),
        is_final_answer=stop_reason == FINAL_STOP_REASON or intervened,
        request_id=_opt_str(record.get("requestId")),
        error_code=_opt_str(record.get("errorCode")),
        guardrail_blocked=_guardrail_blocked(response_body, output_tokens),
    )


def turn_metrics(summaries: Sequence[InvocationSummary]) -> dict:
    """Per-turn (not per-model-call) metrics from invocation summaries (PLAN R1).

    A turn is a final-answer record (``end_turn`` or guardrail intervened). It is either *blocked* (the user got
    the guardrail's blocked message) or *answered* (``end_turn``, or an answer delivered with a value masked).
    The zero-retrieval figures count answered turns only, which is what the NorthstarAssist-ZeroRetrievalRatio
    alarm measures: a blocked prompt never reaches retrieval, so counting it would hide a real retrieval failure.
    """
    finals = [s for s in summaries if s.is_final_answer]
    blocked = [s for s in finals if s.guardrail_blocked]
    answered = [s for s in finals if not s.guardrail_blocked]
    zero = [s for s in answered if not s.has_tool_result]
    policies = Counter(p for s in summaries if s.guardrail_intervened for p in s.guardrail_policies)
    return {
        "records": len(summaries),
        "final_answer_turns": len(finals),
        "blocked_turns": len(blocked),
        "answered_turns": len(answered),
        "zero_retrieval_turns": len(zero),
        "zero_retrieval_ratio": _rate(len(zero), len(answered)),
        "retrieval_success_rate": _rate(len(answered) - len(zero), len(answered)) if answered else None,
        "interventions": sum(1 for s in summaries if s.guardrail_intervened),
        "interventions_by_policy": dict(sorted(policies.items())),
        "output_tokens": [s.output_tokens for s in summaries if s.output_tokens is not None],
        "errors": sum(1 for s in summaries if s.error_code),
    }


# ------------------------------------------------------------------------------- CLI
def build_summary(records: Sequence[dict], multiplier: float = DEFAULT_SPIKE_MULTIPLIER) -> dict:
    """Everything the CLI prints, as one JSON-serialisable dict."""
    try:
        threshold: int | None = token_spike_threshold(records, multiplier)
    except ValueError:
        threshold = None
    return {
        "records": len(records),
        "intervention_rate": intervention_rate(records),
        "retrieval_success_rate": retrieval_success_rate(records),
        "token_stats": token_stats(records),
        "token_spike_multiplier": multiplier,
        "token_spike_threshold": threshold,
        "consistency_findings": consistency_findings(records),
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def render_summary(summary: dict) -> str:
    rate = summary["intervention_rate"]
    out, inp = summary["token_stats"]["output"], summary["token_stats"]["input"]
    lines = [
        f"Records: {summary['records']}",
        f"Guardrail intervention rate: {_pct(rate['rate'])} ({rate['intervened']}/{rate['total']})",
        "Outcomes: " + ", ".join(f"{k}={v}" for k, v in rate["by_outcome"].items()),
        f"Retrieval success rate: {_pct(summary['retrieval_success_rate'])}",
        f"Output tokens: mean {out['mean']:.1f}, p50 {out['p50']:.1f}, p95 {out['p95']:.1f}, max {out['max']}",
        f"Input tokens:  mean {inp['mean']:.1f}, p50 {inp['p50']:.1f}, p95 {inp['p95']:.1f}, max {inp['max']}",
    ]
    if rate["by_category"]:
        lines.append("Interventions by category:")
        lines += [f"  {name}: {g['intervened']}/{g['total']}" for name, g in sorted(rate["by_category"].items())]
    threshold = summary["token_spike_threshold"]
    lines.append(f"TokenSpike threshold ({summary['token_spike_multiplier']:g} x benign p95 output tokens): "
                 + (str(threshold) if threshold is not None else "unavailable (no benign records with usage)"))
    findings = summary["consistency_findings"]
    lines.append(f"Inconsistent cases: {len(findings)}")
    lines += [f"  {f['case_id']} ({f['kind']}): {f['passed']}/{f['runs']} passed, outcomes {f['outcomes']}"
              for f in findings]
    return "\n".join(lines)


def _expand(patterns: Sequence[str]) -> list[str]:
    files: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise SystemExit(f"no files match {pattern!r}")
        files.extend(m for m in matches if m not in files)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise red-team suite results (JSONL).")
    parser.add_argument("paths", nargs="+", help="results/suite_*.jsonl files or glob patterns")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--multiplier", type=float, default=DEFAULT_SPIKE_MULTIPLIER,
                        help="TokenSpike multiplier over benign p95 output tokens (default 3)")
    args = parser.parse_args(argv)
    files = _expand(args.paths)
    try:
        records = load_jsonl(files)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    summary = build_summary(records, args.multiplier)
    if args.json:
        print(json.dumps({"files": files, **summary}, indent=2))
    else:
        print(render_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
