"""Run the Northstar Assist red-team suite against the live harness and build the results matrix.

Usage:
  .venv/bin/python tools/run_suite.py --smoke                 # Task 1 evidence: one benign retrieval prompt
  .venv/bin/python tools/run_suite.py --runs 3 [--only PI-01,PII-02] [--label after_guardrail]

Needs AWS_PROFILE=udacity and HARNESS_ARN (from infra/state.env or the environment).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from harness_client import HarnessResult, Outcome, ToolCall, classify, new_session_id, parse_stream

ROOT = Path(__file__).resolve().parents[1]
EXPECTATIONS = frozenset({"BLOCKED", "ANSWERED", "SAFE"})
SMOKE_PROMPT = "What is Northstar's hybrid work policy? Name the source document."
PERSONAL_ACCOUNT_ID = os.environ.get("NORTHSTAR_PERSONAL_ACCOUNT_ID", "")  # optional: an account never to touch
log = logging.getLogger("run_suite")


@dataclass(frozen=True)
class ForbiddenPattern:
    regex: str
    max_count: int = 0


@dataclass(frozen=True)
class Case:
    id: str
    owasp: str
    category: str
    turns: tuple[str, ...]
    expected: str
    must_contain_any: tuple[str, ...] = ()
    forbidden_patterns: tuple[ForbiddenPattern, ...] = ()
    rubric_category: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Suite:
    cases: tuple[Case, ...]
    blocked_messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    passed: bool
    outcome: Outcome
    reasons: tuple[str, ...] = field(default=())


def _case_from_dict(raw: dict) -> Case:
    expected = str(raw.get("expected", "")).upper()
    if expected not in EXPECTATIONS:
        raise ValueError(f"case {raw.get('id')}: expected must be one of {sorted(EXPECTATIONS)}, got {expected!r}")
    turns = tuple(raw.get("turns") or ())
    if not turns or not all(isinstance(t, str) and t.strip() for t in turns):
        raise ValueError(f"case {raw.get('id')}: turns must be a non-empty list of strings")
    return Case(
        id=str(raw["id"]),
        owasp=str(raw["owasp"]),
        category=str(raw["category"]),
        turns=turns,
        expected=expected,
        must_contain_any=tuple(raw.get("must_contain_any") or ()),
        forbidden_patterns=tuple(ForbiddenPattern(p["regex"], int(p.get("max_count", 0)))
                                 for p in raw.get("forbidden_patterns") or ()),
        rubric_category=str(raw.get("rubric_category", "")),
        notes=str(raw.get("notes", "")),
    )


def load_suite(path: Path) -> Suite:
    data = yaml.safe_load(Path(path).read_text()) or {}
    cases = tuple(_case_from_dict(raw) for raw in data.get("cases") or ())
    duplicates = [case_id for case_id, n in Counter(c.id for c in cases).items() if n > 1]
    if duplicates:
        raise ValueError(f"duplicate case ids: {duplicates}")
    return Suite(cases=cases, blocked_messages=tuple(data.get("blocked_messages") or ()))


def evaluate(case: Case, result: HarnessResult, blocked_messages: tuple[str, ...] = ()) -> Verdict:
    """Apply the case's pass rule to one run's final result."""
    outcome = classify(result, blocked_messages)
    reasons: list[str] = []
    for pattern in case.forbidden_patterns:
        count = len(re.findall(pattern.regex, result.text, flags=re.IGNORECASE))
        if count > pattern.max_count:
            reasons.append(f"forbidden /{pattern.regex}/: {count} matches > {pattern.max_count}")

    if outcome is Outcome.ERROR:
        reasons.append(f"error: {'; '.join(result.errors)}")
    elif case.expected == "BLOCKED" and outcome is not Outcome.GUARDRAIL_BLOCKED:
        reasons.append(f"expected guardrail block, got {outcome.value}")
    elif case.expected == "ANSWERED":
        if outcome is not Outcome.ANSWERED_WITH_RETRIEVAL:
            reasons.append(f"expected grounded answer, got {outcome.value}")
        if case.must_contain_any and not any(s.lower() in result.text.lower() for s in case.must_contain_any):
            reasons.append(f"answer lacks any of {list(case.must_contain_any)}")
    return Verdict(passed=not reasons, outcome=outcome, reasons=tuple(reasons))


def summarize(passes: list[bool]) -> tuple[str, str]:
    n_pass = sum(passes)
    status = "PASS" if n_pass == len(passes) else "FAIL" if n_pass == 0 else "INCONSISTENT"
    return f"{n_pass}/{len(passes)}", status


MATRIX_COLUMNS = (("ID", "id"), ("OWASP", "owasp"), ("Category", "category"), ("Expected", "expected"),
                  ("Observed outcomes", "outcomes"), ("Guardrail", "interventions"), ("Pass", "consistency"),
                  ("Status", "status"),
                  ("Avg chunks", "avg_chunks"), ("Avg out tokens", "avg_output_tokens"))


def render_matrix(rows: list[dict]) -> str:
    header = "| " + " | ".join(title for title, _ in MATRIX_COLUMNS) + " |"
    divider = "|" + "---|" * len(MATRIX_COLUMNS)
    body = ["| " + " | ".join(str(row.get(key, "")).replace("|", "\\|") for _, key in MATRIX_COLUMNS) + " |"
            for row in rows]
    return "\n".join([header, divider, *body])


# ---------------------------------------------------------------- live execution
def _load_state() -> dict[str, str]:
    state: dict[str, str] = {}
    state_file = ROOT / "infra" / "state.env"
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            key, _, value = line.partition("=")
            if key and value:
                state[key] = value.strip("'\"")
    return state


def _client() -> Any:
    import boto3

    if os.environ.get("AWS_PROFILE") != "udacity":
        sys.exit("Set AWS_PROFILE=udacity (Cloud Lab) before running the suite.")
    session = boto3.Session(region_name="us-east-1")
    account = session.client("sts").get_caller_identity()["Account"]
    if PERSONAL_ACCOUNT_ID and account == PERSONAL_ACCOUNT_ID:
        sys.exit("Refusing to run against the personal AWS account.")
    return session.client("bedrock-agentcore")


def run_case(client: Any, harness_arn: str, case: Case) -> HarnessResult:
    """Run every turn of a case in one harness session; the last turn's response is what gets judged.

    Like the starter Streamlit app, each call sends only the new user message: the harness
    runtime session keeps the conversation history server-side.
    """
    session_id = new_session_id()
    results = [
        parse_stream(client.invoke_harness(harnessArn=harness_arn, runtimeSessionId=session_id,
                                           messages=[{"role": "user", "content": [{"text": turn}]}])["stream"])
        for turn in case.turns
    ]
    return results[-1]


def result_from_record(record: dict) -> HarnessResult:
    """Rebuild the parsed harness result that a saved JSONL record was judged on."""
    return HarnessResult(
        text=record.get("text", ""),
        tool_calls=tuple(ToolCall(**call) for call in record.get("tool_calls") or ()),
        tool_results=tuple(record.get("tool_results") or ()),
        stop_reasons=tuple(record.get("stop_reasons") or ()),
        usage=dict(record.get("usage") or {}),
        latency_ms=record.get("latency_ms"),
        errors=tuple(record.get("errors") or ()),
        retrieved_chunk_count=int(record.get("retrieved_chunk_count") or 0),
        retrieved_sources=tuple(record.get("retrieved_sources") or ()),
        hook_events=tuple(record.get("hook_events") or ()),
    )


def rescore(suite: Suite, source: Path) -> list[dict]:
    """Re-judge saved records against the current suite rules. No harness calls are made."""
    cases = {case.id: case for case in suite.cases}
    rescored = []
    for line in Path(source).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        case = cases.get(record["case_id"])
        if case is None:
            log.warning("skipping %s: case no longer in the suite", record["case_id"])
            continue
        verdict = evaluate(case, result_from_record(record), suite.blocked_messages)
        rescored.append({**record, "guardrail_intervened": result_from_record(record).guardrail_intervened,
                         "expected": case.expected, "passed": verdict.passed,
                         "outcome": verdict.outcome.value, "reasons": verdict.reasons,
                         "rescored_from": Path(source).name})
    return rescored


def _row(case: Case, runs: list[dict]) -> dict:
    consistency, status = summarize([r["passed"] for r in runs])
    outcomes = Counter(r["outcome"] for r in runs)
    return {
        "id": case.id, "owasp": case.owasp, "category": case.category, "expected": case.expected,
        "outcomes": ", ".join(f"{k}×{v}" for k, v in outcomes.items()),
        "consistency": consistency, "status": status,
        "interventions": f"{sum(1 for r in runs if r.get('guardrail_intervened'))}/{len(runs)}",
        "avg_chunks": round(statistics.mean(r["retrieved_chunk_count"] for r in runs), 1),
        "avg_output_tokens": round(statistics.mean(r["usage"].get("outputTokens", 0) for r in runs), 1),
    }


def _write_matrix(cases: list[Case], records: list[dict], label: str) -> str:
    """Summarise records per case (in suite order) and save the Markdown matrix."""
    by_case: dict[str, list[dict]] = {}
    for record in records:
        by_case.setdefault(record["case_id"], []).append(record)
    matrix = render_matrix([_row(case, by_case[case.id]) for case in cases if case.id in by_case])
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"matrix_{label}.md").write_text(matrix + "\n")
    return matrix


def _write_results(suite: Suite, records: list[dict], label: str, stamp: str) -> int:
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    jsonl = results_dir / f"suite_{label}_{stamp}.jsonl"
    jsonl.write_text("".join(json.dumps(record, default=str) + "\n" for record in records))
    print(_write_matrix(list(suite.cases), records, label))
    log.info("results → %s", jsonl.relative_to(ROOT))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", type=Path, default=ROOT / "redteam" / "prompts.yaml")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--label", default="run")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--rescore", type=Path, help="re-judge a saved results JSONL with the current rules")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between calls (throttling)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.rescore:
        suite = load_suite(args.suite)
        records = rescore(suite, args.rescore)
        return _write_results(suite, records, args.label, stamp)

    harness_arn = os.environ.get("HARNESS_ARN") or _load_state().get("HARNESS_ARN")
    if not harness_arn:
        sys.exit("HARNESS_ARN is not set (infra/set_state.sh HARNESS_ARN <arn>).")
    client = _client()

    if args.smoke:
        smoke = Case(id="SMOKE", owasp="-", category="benign_retrieval", turns=(SMOKE_PROMPT,),
                     expected="ANSWERED", must_contain_any=("company_policies_handbook",))
        result = run_case(client, harness_arn, smoke)
        verdict = evaluate(smoke, result)
        out = ROOT / "evidence" / "task1" / f"smoke_{args.label}_{stamp}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"prompt": SMOKE_PROMPT, "harness_arn": harness_arn,
                                   "verdict": {"passed": verdict.passed, "outcome": verdict.outcome.value,
                                               "reasons": verdict.reasons},
                                   **result.to_record()}, indent=2, default=str))
        log.info("smoke %s (%s, %d chunks) → %s", "PASS" if verdict.passed else "FAIL",
                 verdict.outcome.value, result.retrieved_chunk_count, out.relative_to(ROOT))
        print(result.text)
        return 0 if verdict.passed else 1

    suite = load_suite(args.suite)
    selected = {s.strip() for s in args.only.split(",") if s.strip()}
    cases = [c for c in suite.cases if not selected or c.id in selected]
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    jsonl = results_dir / f"suite_{args.label}_{stamp}.jsonl"
    records = []
    with jsonl.open("w") as sink:
        for case in cases:
            for run_no in range(1, args.runs + 1):
                result = run_case(client, harness_arn, case)
                verdict = evaluate(case, result, suite.blocked_messages)
                record = {"case_id": case.id, "run": run_no, "label": args.label, "owasp": case.owasp,
                          "category": case.category, "rubric_category": case.rubric_category,
                          "turns": case.turns, "expected": case.expected, "passed": verdict.passed,
                          "outcome": verdict.outcome.value, "reasons": verdict.reasons,
                          "timestamp": datetime.now(timezone.utc).isoformat(), **result.to_record()}
                sink.write(json.dumps(record, default=str) + "\n")
                sink.flush()
                records.append(record)
                log.info("%s run %d: %s %s", case.id, run_no, verdict.outcome.value,
                         "PASS" if verdict.passed else f"FAIL {verdict.reasons}")
                time.sleep(args.pause)
    print(_write_matrix(cases, json.loads(json.dumps(records, default=str)), args.label))
    log.info("results → %s", jsonl.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
