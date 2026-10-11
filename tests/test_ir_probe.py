"""tools/ir_probe.py turns one harness call into the single word the containment drill checks."""
import ir_probe
from harness_client import HarnessResult

LOCKDOWN = "Northstar Assist is temporarily unavailable while the security team investigates an issue."
BLOCKED = "Northstar Assist can't help with that request."


def _result(text: str, stop: str, chunks: int = 0, out_tokens: int = 0) -> HarnessResult:
    return HarnessResult(text=text, tool_calls=(), tool_results=(), stop_reasons=(stop,),
                         usage={"outputTokens": out_tokens}, latency_ms=1, errors=(),
                         retrieved_chunk_count=chunks, retrieved_sources=())


def test_a_grounded_answer_is_observed_as_answered():
    answer = _result("Hybrid work is three office days.", "end_turn", chunks=5, out_tokens=80)
    assert ir_probe.observe(answer, None, LOCKDOWN) == "answered"


def test_the_lockdown_message_is_observed_as_lockdown():
    assert ir_probe.observe(_result(LOCKDOWN + " Please try again later.", "guardrail_intervened"), None, LOCKDOWN) == "lockdown"


def test_an_ordinary_guardrail_block_is_not_mistaken_for_lockdown():
    assert ir_probe.observe(_result(BLOCKED, "guardrail_intervened"), None, LOCKDOWN) == "blocked"


def test_an_iam_denial_is_observed_as_access_denied():
    error = "An error occurred (runtimeClientError) ... (AccessDeniedException) when calling the ConverseStream operation"
    assert ir_probe.observe(None, error, LOCKDOWN) == "access_denied"


def test_any_other_failure_is_observed_as_error():
    assert ir_probe.observe(None, "ThrottlingException: slow down", LOCKDOWN) == "error"


def test_an_answer_without_retrieval_is_not_reported_as_answered():
    """During recovery the drill waits for a real grounded answer, not for any text."""
    assert ir_probe.observe(_result("I could not find that.", "end_turn", out_tokens=12), None, LOCKDOWN) == "no_retrieval"
