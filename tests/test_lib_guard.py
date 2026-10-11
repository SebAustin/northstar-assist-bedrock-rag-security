"""Behavioural tests for infra/lib.sh's account guard, run against a stubbed `aws` CLI."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "infra" / "lib.sh"
PERSONAL_ACCOUNT = "999988887777"  # stands in for an account the scripts must never touch
LAB_ACCOUNT = "111122223333"


def _stub_aws(tmp_path: Path, account: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "aws"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo "' + account + '"; exit 0; fi\n'
        "exit 0\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run_guard(tmp_path, account, profile="udacity", region="us-east-1"):
    env = {**os.environ, "PATH": f"{_stub_aws(tmp_path, account)}:{os.environ['PATH']}",
           "NORTHSTAR_PERSONAL_ACCOUNT_ID": PERSONAL_ACCOUNT}
    env.pop("AWS_PROFILE", None)
    env.pop("AWS_REGION", None)
    if profile is not None:
        env["AWS_PROFILE"] = profile
    if region is not None:
        env["AWS_REGION"] = region
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}" && require_lab_account && echo "OK $ACCOUNT_ID"'],
        env=env, capture_output=True, text=True,
    )


def test_passes_for_lab_profile_and_lab_account(tmp_path):
    result = _run_guard(tmp_path, LAB_ACCOUNT)
    assert result.returncode == 0, result.stderr
    assert f"OK {LAB_ACCOUNT}" in result.stdout


def test_refuses_personal_account_even_with_udacity_profile(tmp_path):
    result = _run_guard(tmp_path, PERSONAL_ACCOUNT)
    assert result.returncode != 0
    assert "personal account" in result.stderr


@pytest.mark.parametrize("profile", [None, "default", "personal"])
def test_refuses_wrong_or_missing_profile(tmp_path, profile):
    result = _run_guard(tmp_path, LAB_ACCOUNT, profile=profile)
    assert result.returncode != 0
    assert "AWS_PROFILE" in result.stderr


def test_refuses_wrong_region(tmp_path):
    result = _run_guard(tmp_path, LAB_ACCOUNT, region="eu-west-1")
    assert result.returncode != 0
    assert "us-east-1" in result.stderr
