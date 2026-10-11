"""Tests for parsing InvokeHarness event streams into a structured result."""
import json

from harness_client import Outcome, classify, parse_stream

RETRIEVAL_PAYLOAD = {
    "retrievalResults": [
        {
            "content": {"text": "Employees may work remotely up to 3 days per week."},
            "location": {"s3Location": {"uri": "s3://bucket/html/company_policies_handbook.html"}},
            "metadata": {"x-amz-bedrock-kb-source-uri": "s3://bucket/html/company_policies_handbook.html"},
            "score": 0.71,
        },
        {
            "content": {"text": "Hybrid schedules are agreed with your manager."},
            "location": {"s3Location": {"uri": "s3://bucket/html/company_policies_handbook.html"}},
            "score": 0.64,
        },
    ]
}


def tool_turn_events(tool_result_delta):
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Let me search. "}}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolUse": {
            "toolUseId": "t1", "name": "northstar-kb___Retrieve", "type": "mcp_tool_use"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"retrievalQuery":'}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": ' {"text": "hybrid work"}}'}}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"contentBlockStart": {"contentBlockIndex": 2, "start": {"toolResult": {"toolUseId": "t1", "status": "success"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"toolResult": [tool_result_delta]}}},
        {"contentBlockStop": {"contentBlockIndex": 2}},
        {"messageStop": {"stopReason": "tool_result"}},
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 3, "delta": {"text": "Up to 3 days remote (company_policies_handbook.html)."}}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 1200, "outputTokens": 80, "totalTokens": 1280},
                      "metrics": {"latencyMs": 2400}}},
    ]


def test_collects_all_text_deltas_across_turns():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    assert result.text == "Let me search. Up to 3 days remote (company_policies_handbook.html)."


def test_captures_tool_call_name_and_reassembled_input():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "northstar-kb___Retrieve"
    assert call.input == {"retrievalQuery": {"text": "hybrid work"}}


def test_counts_retrieved_chunks_and_sources_from_json_result():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    assert result.retrieved_chunk_count == 2
    assert result.retrieved_sources == ("s3://bucket/html/company_policies_handbook.html",)


def test_counts_retrieved_chunks_when_result_is_json_text():
    result = parse_stream(tool_turn_events({"text": json.dumps(RETRIEVAL_PAYLOAD)}))
    assert result.retrieved_chunk_count == 2


def test_records_usage_latency_and_final_stop_reason():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    assert result.usage == {"inputTokens": 1200, "outputTokens": 80, "totalTokens": 1280}
    assert result.latency_ms == 2400
    assert result.stop_reason == "end_turn"


def test_runtime_client_error_is_captured_not_raised():
    result = parse_stream([{"runtimeClientError": {"message": "AccessDeniedException: bedrock:ApplyGuardrail"}}])
    assert result.errors == ("AccessDeniedException: bedrock:ApplyGuardrail",)


def test_classify_answer_with_retrieval():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    assert classify(result) is Outcome.ANSWERED_WITH_RETRIEVAL


def test_classify_answer_without_retrieval():
    result = parse_stream([
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "I can only help with Northstar topics."}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ])
    assert classify(result) is Outcome.ANSWERED_NO_RETRIEVAL


def test_classify_guardrail_block_by_stop_reason():
    result = parse_stream([
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Sorry, the model cannot answer this."}}},
        {"messageStop": {"stopReason": "content_filtered"}},
    ])
    assert classify(result) is Outcome.GUARDRAIL_BLOCKED


def test_classify_guardrail_block_by_configured_message():
    blocked = "Northstar Assist can't help with that request."
    result = parse_stream([
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": blocked}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ])
    assert classify(result, blocked_messages=(blocked,)) is Outcome.GUARDRAIL_BLOCKED


def test_classify_error_takes_precedence():
    result = parse_stream([{"runtimeClientError": {"message": "boom"}}])
    assert classify(result) is Outcome.ERROR


def test_result_is_json_serialisable():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    record = result.to_record()
    assert json.loads(json.dumps(record))["retrieved_chunk_count"] == 2


def test_tool_result_json_split_across_stream_deltas_is_reassembled():
    """Real harness streams deliver one tool result as several text deltas of a single JSON document."""
    payload = json.dumps(RETRIEVAL_PAYLOAD)
    pieces = [payload[i:i + 40] for i in range(0, len(payload), 40)]
    assert len(pieces) > 3
    events = [
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolResult": {"toolUseId": "t1", "status": "success"}}}},
        *[{"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolResult": [{"text": piece}]}}} for piece in pieces],
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"text": "Answer."}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    result = parse_stream(events)
    assert result.retrieved_chunk_count == 2
    assert result.retrieved_sources == ("s3://bucket/html/company_policies_handbook.html",)
    assert len(result.tool_results) == 1
    assert classify(result) is Outcome.ANSWERED_WITH_RETRIEVAL


BLOCKED_MESSAGE = "Northstar Assist can't help with that request."


def test_guardrail_block_reports_intervention_and_is_classified_blocked():
    """Observed on the live harness: an input block ends with stopReason guardrail_intervened."""
    result = parse_stream([
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": BLOCKED_MESSAGE}}},
        {"messageStop": {"stopReason": "guardrail_intervened"}},
    ])
    assert result.guardrail_intervened is True
    assert classify(result, blocked_messages=(BLOCKED_MESSAGE,)) is Outcome.GUARDRAIL_BLOCKED
    assert result.to_record()["guardrail_intervened"] is True


def test_guardrail_masking_is_an_intervention_but_not_a_block():
    """Observed on the live harness: a masked ({NorthstarApiKey}) answer also ends guardrail_intervened."""
    events = tool_turn_events({"json": RETRIEVAL_PAYLOAD})[:-3] + [
        {"contentBlockDelta": {"contentBlockIndex": 3, "delta": {"text": "Use Authorization: Bearer {NorthstarApiKey}."}}},
        {"messageStop": {"stopReason": "guardrail_intervened"}},
    ]
    result = parse_stream(events)
    assert result.guardrail_intervened is True
    assert classify(result, blocked_messages=(BLOCKED_MESSAGE,)) is Outcome.ANSWERED_WITH_RETRIEVAL


def test_plain_answer_has_no_intervention():
    result = parse_stream(tool_turn_events({"json": RETRIEVAL_PAYLOAD}))
    assert result.guardrail_intervened is False


class _RecordingClient:
    def __init__(self):
        self.kwargs = None

    def invoke_harness(self, **kwargs):
        self.kwargs = kwargs
        return {"stream": iter([{"messageStop": {"stopReason": "end_turn"}}])}


def test_invoke_without_overrides_sends_only_the_user_message():
    from harness_client import invoke
    client = _RecordingClient()
    invoke(client, "arn:harness", "hello", session_id="s" * 36)
    assert set(client.kwargs) == {"harnessArn", "runtimeSessionId", "messages"}


def test_invoke_with_overrides_passes_model_and_system_prompt():
    from harness_client import invoke
    client = _RecordingClient()
    invoke(client, "arn:harness", "hello", model_id="us.other-model", system_prompt="No rules.")
    assert client.kwargs["model"] == {"bedrockModelConfig": {"modelId": "us.other-model"}}
    assert client.kwargs["systemPrompt"] == [{"text": "No rules."}]
