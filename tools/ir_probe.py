"""Send one benign question to the harness and say, in one word, what a user would see.

Used by infra/07_ir_drill.sh to prove each containment level:
  answered       a grounded answer (the normal state)
  no_retrieval   an answer that did not use the knowledge base
  lockdown       the lockdown guardrail's "temporarily unavailable" message
  blocked        any other guardrail block
  access_denied  the model call was refused by IAM (containment level 2)
  error          anything else

Usage: tools/ir_probe.py [--session <runtimeSessionId>]   prints one JSON line
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness_client import HarnessResult, Outcome, classify, invoke, new_session_id
from run_suite import ROOT, SMOKE_PROMPT, _client, _load_state

LOCKDOWN_CONFIG = ROOT / "guardrail" / "lockdown.json"


def lockdown_message(config: Path = LOCKDOWN_CONFIG) -> str:
    return json.loads(config.read_text())["blockedInputMessaging"]


def observe(result: HarnessResult | None, error: str | None, lockdown_text: str) -> str:
    """Map one probe (a parsed result, or the error text of a failed call) to an observation."""
    if result is None:
        return "access_denied" if error and "AccessDenied" in error else "error"
    if lockdown_text in result.text:
        return "lockdown"
    outcome = classify(result)
    if outcome is Outcome.GUARDRAIL_BLOCKED:
        return "blocked"
    if outcome is Outcome.ANSWERED_WITH_RETRIEVAL:
        return "answered"
    return "error" if outcome is Outcome.ERROR else "no_retrieval"


def main(argv: list[str] | None = None) -> int:
    from botocore.exceptions import ClientError

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", default=None, help="reuse a harness session instead of starting a new one")
    args = parser.parse_args(argv)
    harness_arn = os.environ.get("HARNESS_ARN") or _load_state().get("HARNESS_ARN")
    if not harness_arn:
        sys.exit("HARNESS_ARN is not set (infra/set_state.sh HARNESS_ARN <arn>).")
    session = args.session or new_session_id()
    result, error = None, None
    try:
        result = invoke(_client(), harness_arn, SMOKE_PROMPT, session)
    except ClientError as exc:
        error = str(exc)
    sys.stdout.write(json.dumps({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": session,
        "observed": observe(result, error, lockdown_message()),
        "text": (result.text if result else error or "")[:160],
    }) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
