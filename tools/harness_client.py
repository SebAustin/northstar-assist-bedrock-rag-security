"""Invoke the Northstar Assist AgentCore harness and turn its event stream into evidence.

The harness streams every model turn, including the Retrieve tool call and its
result, so one parse yields: the answer, which tools ran, how many KB chunks came
back and from where, token usage, and whether a guardrail stopped the turn.
"""
from __future__ import annotations

import enum
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

# "guardrail_intervened" is what the live harness returns for both a block and a masked answer.
GUARDRAIL_STOP_REASONS = frozenset({"guardrail_intervened", "content_filtered"})
EXPLICIT_BLOCK_STOP_REASONS = frozenset({"content_filtered"})


class Outcome(str, enum.Enum):
    ANSWERED_WITH_RETRIEVAL = "ANSWERED_WITH_RETRIEVAL"
    ANSWERED_NO_RETRIEVAL = "ANSWERED_NO_RETRIEVAL"
    GUARDRAIL_BLOCKED = "GUARDRAIL_BLOCKED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ToolCall:
    tool_use_id: str
    name: str
    input: Any


@dataclass(frozen=True)
class HarnessResult:
    text: str
    tool_calls: tuple[ToolCall, ...]
    tool_results: tuple[Any, ...]
    stop_reasons: tuple[str, ...]
    usage: dict[str, int]
    latency_ms: int | None
    errors: tuple[str, ...]
    retrieved_chunk_count: int
    retrieved_sources: tuple[str, ...]
    hook_events: tuple[dict, ...] = field(default=())

    @property
    def stop_reason(self) -> str | None:
        return self.stop_reasons[-1] if self.stop_reasons else None

    @property
    def guardrail_intervened(self) -> bool:
        """True when a guardrail blocked or altered (masked) any part of the turn."""
        return bool(GUARDRAIL_STOP_REASONS.intersection(self.stop_reasons))

    def to_record(self) -> dict:
        record = asdict(self)
        record["stop_reason"] = self.stop_reason
        record["guardrail_intervened"] = self.guardrail_intervened
        return record


def _parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _find_retrieval_results(payload: Any) -> list[dict]:
    """Search a tool result (any nesting) for KB `retrievalResults` entries."""
    if isinstance(payload, str):
        parsed = _parse_json(payload)
        return [] if isinstance(parsed, str) else _find_retrieval_results(parsed)
    if isinstance(payload, list):
        return [hit for item in payload for hit in _find_retrieval_results(item)]
    if isinstance(payload, dict):
        if isinstance(payload.get("retrievalResults"), list):
            return payload["retrievalResults"]
        return [hit for value in payload.values() for hit in _find_retrieval_results(value)]
    return []


def _source_uri(chunk: dict) -> str | None:
    location = chunk.get("location") or {}
    uri = (location.get("s3Location") or {}).get("uri")
    return uri or (chunk.get("metadata") or {}).get("x-amz-bedrock-kb-source-uri")


def parse_stream(events: Iterable[dict]) -> HarnessResult:
    """Fold InvokeHarness stream events into a single immutable result."""
    text_parts: list[str] = []
    tool_starts: dict[int, dict] = {}
    tool_inputs: dict[int, list[str]] = {}
    # One tool result arrives as several deltas: a JSON document is streamed in text pieces.
    result_text: dict[int, list[str]] = {}
    result_json: dict[int, list[Any]] = {}
    stop_reasons: list[str] = []
    errors: list[str] = []
    hooks: list[dict] = []
    usage: dict[str, int] = {}
    latency_ms: int | None = None

    for event in events:
        if "contentBlockStart" in event:
            block = event["contentBlockStart"]
            if "toolUse" in block["start"]:
                tool_starts[block["contentBlockIndex"]] = block["start"]["toolUse"]
        elif "contentBlockDelta" in event:
            index = event["contentBlockDelta"]["contentBlockIndex"]
            delta = event["contentBlockDelta"]["delta"]
            if "text" in delta:
                text_parts.append(delta["text"])
            if "toolUse" in delta:
                tool_inputs.setdefault(index, []).append(delta["toolUse"]["input"])
            for item in delta.get("toolResult", []):
                if "json" in item:
                    result_json.setdefault(index, []).append(item["json"])
                elif "text" in item:
                    result_text.setdefault(index, []).append(item["text"])
        elif "messageStop" in event:
            stop_reasons.append(event["messageStop"]["stopReason"])
        elif "metadata" in event:
            usage = dict(event["metadata"].get("usage", {}))
            latency_ms = event["metadata"].get("metrics", {}).get("latencyMs", latency_ms)
        elif "hookEvent" in event:
            hooks.append(event["hookEvent"])
        else:
            for error_key in ("runtimeClientError", "internalServerException", "validationException"):
                if error_key in event:
                    errors.append(event[error_key].get("message") or error_key)

    tool_calls = tuple(
        ToolCall(
            tool_use_id=start["toolUseId"],
            name=start["name"],
            input=_parse_json("".join(tool_inputs.get(index, []))),
        )
        for index, start in sorted(tool_starts.items())
    )
    tool_results: list[Any] = []
    for index in sorted(result_json.keys() | result_text.keys()):
        tool_results.extend(result_json.get(index, []))
        if index in result_text:
            tool_results.append(_parse_json("".join(result_text[index])))
    chunks = _find_retrieval_results(tool_results)
    sources = tuple(dict.fromkeys(uri for uri in map(_source_uri, chunks) if uri))

    return HarnessResult(
        text="".join(text_parts),
        tool_calls=tool_calls,
        tool_results=tuple(tool_results),
        stop_reasons=tuple(stop_reasons),
        usage=usage,
        latency_ms=latency_ms,
        errors=tuple(errors),
        retrieved_chunk_count=len(chunks),
        retrieved_sources=sources,
        hook_events=tuple(hooks),
    )


def classify(result: HarnessResult, blocked_messages: Iterable[str] = ()) -> Outcome:
    """Map a result to the outcome categories used in the test matrix and dashboard."""
    if result.errors:
        return Outcome.ERROR
    if any(message and message in result.text for message in blocked_messages):
        return Outcome.GUARDRAIL_BLOCKED
    if EXPLICIT_BLOCK_STOP_REASONS.intersection(result.stop_reasons):
        return Outcome.GUARDRAIL_BLOCKED
    # An intervention with no model output and no retrieval is an input-side block;
    # an intervention on a delivered answer is masking, which is still an answer.
    blocked_before_model = result.retrieved_chunk_count == 0 and not result.usage.get("outputTokens")
    if result.guardrail_intervened and blocked_before_model:
        return Outcome.GUARDRAIL_BLOCKED
    if result.retrieved_chunk_count > 0:
        return Outcome.ANSWERED_WITH_RETRIEVAL
    return Outcome.ANSWERED_NO_RETRIEVAL


def new_session_id() -> str:
    """Harness session IDs must be at least 33 characters; a UUID4 string is 36."""
    return str(uuid.uuid4())


def invoke(client: Any, harness_arn: str, prompt: str, session_id: str | None = None, *,
           model_id: str | None = None, system_prompt: str | None = None) -> HarnessResult:
    """Send one user message to the harness and parse the full streamed response.

    model_id and system_prompt are per-request overrides. They exist to test whether a caller
    can replace the harness's own model settings (and so its guardrail) or its system prompt.
    """
    overrides: dict[str, Any] = {}
    if model_id is not None:
        overrides["model"] = {"bedrockModelConfig": {"modelId": model_id}}
    if system_prompt is not None:
        overrides["systemPrompt"] = [{"text": system_prompt}]
    response = client.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=session_id or new_session_id(),
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        **overrides,
    )
    return parse_stream(response["stream"])
