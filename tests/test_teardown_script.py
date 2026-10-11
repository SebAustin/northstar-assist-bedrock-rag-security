"""infra/99_teardown.sh --plan must only read, and the script must refuse to run outside the lab profile."""
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "99_teardown.sh"
STATE = ("BUCKET=demo-bucket\nKB_ID=KB123\nKB_DATA_SOURCE_ID=DS123\nGATEWAY_ID=gw-1\n"
         "HARNESS_ARN=arn:aws:bedrock-agentcore:us-east-1:111122223333:harness/Demo-abc\n"
         "HARNESS_ROLE_NAME=DemoHarnessRole\nGATEWAY_ROLE_NAME=DemoGatewayRole\nKB_ROLE_NAME=DemoKbRole\n"
         "GUARDRAIL_ID=g1\nLOCKDOWN_ID=g2\n")
MUTATING = ("delete-", "detach-", "put-", "update-", "create-", " rm ", "remove-")


def _run(tmp_path: Path, *args: str, profile: str = "udacity") -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    stub = bin_dir / "aws"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\n\' "$*" >> "{calls}"\n'
        'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo "111122223333"; exit 0; fi\n'
        'if [[ "$*" == *"--output json"* ]]; then echo "{}"; else echo "demo-resource"; fi\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    state_file = tmp_path / "state.env"
    state_file.write_text(STATE)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AWS_PROFILE": profile, "AWS_REGION": "us-east-1",
           "NORTHSTAR_STATE_FILE": str(state_file), "NORTHSTAR_EVIDENCE_ROOT": str(tmp_path / "evidence")}
    env.pop("ASSUME_YES", None)
    result = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_plan_lists_resources_and_changes_nothing(tmp_path):
    result, calls = _run(tmp_path, "--plan")

    assert result.returncode == 0, result.stderr
    assert "would be deleted" in result.stdout and "demo-resource" in result.stdout
    assert [c for c in calls if any(verb in c for verb in MUTATING)] == []


def test_delete_without_confirmation_changes_nothing(tmp_path):
    """No ASSUME_YES and no terminal: the confirmation prompt reads nothing and the run aborts."""
    result, calls = _run(tmp_path)

    assert result.returncode != 0
    assert [c for c in calls if any(verb in c for verb in MUTATING)] == []


def test_refuses_to_run_outside_the_lab_profile(tmp_path):
    result, calls = _run(tmp_path, profile="default")

    assert result.returncode != 0
    assert "AWS_PROFILE" in result.stderr
    assert [c for c in calls if any(verb in c for verb in MUTATING)] == []
