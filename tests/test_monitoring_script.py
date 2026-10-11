"""infra/05_monitoring.sh must refuse to touch AWS when a definition file is broken (stubbed `aws`)."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "05_monitoring.sh"
MUTATIONS = ("put-metric-filter", "put-metric-alarm", "put-query-definition", "delete-query-definition")


def _run(tmp_path: Path, mutate) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Copy monitoring/ to a temp dir, let `mutate(dir)` break it, then run `filters` against a stub aws."""
    definitions = tmp_path / "monitoring"
    shutil.copytree(ROOT / "monitoring", definitions)
    mutate(definitions)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    stub = bin_dir / "aws"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\n\' "$*" >> "{calls}"\n'
        'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo "111122223333"; exit 0; fi\n'
        'if [[ "$*" == *"describe-query-definitions"* ]]; then echo "old-query-id"; exit 0; fi\n'
        'echo "{}"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    state_file = tmp_path / "state.env"
    state_file.write_text("HARNESS_ROLE_NAME=DemoHarnessRole\nKB_ROLE_NAME=DemoKbRole\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AWS_PROFILE": "udacity",
           "AWS_REGION": "us-east-1", "ASSUME_YES": "1", "NORTHSTAR_STATE_FILE": str(state_file),
           "NORTHSTAR_MONITORING_DIR": str(definitions), "NORTHSTAR_EVIDENCE_ROOT": str(tmp_path / "evidence")}
    result = subprocess.run(["bash", str(SCRIPT), "filters"], env=env, capture_output=True, text=True)
    return result, calls.read_text().splitlines() if calls.exists() else []


def _mutations(calls: list[str]) -> list[str]:
    return [c for c in calls if any(verb in c for verb in MUTATIONS)]


def test_valid_definitions_create_every_filter_alarm_and_query(tmp_path):
    result, calls = _run(tmp_path, lambda d: None)

    assert result.returncode == 0, result.stderr
    assert sum("put-metric-filter" in c for c in calls) == len(json.loads((ROOT / "monitoring/metric_filters.json").read_text()))
    assert sum("put-metric-alarm" in c for c in calls) == len(json.loads((ROOT / "monitoring/alarms.json").read_text()))
    assert sum("put-query-definition" in c for c in calls) == len(json.loads((ROOT / "monitoring/saved_queries.json").read_text()))


@pytest.mark.parametrize("name", ["metric_filters.json", "alarms.json", "saved_queries.json"])
def test_a_file_that_is_not_valid_json_stops_the_run_before_any_change(tmp_path, name):
    def add_trailing_comma(definitions: Path) -> None:
        path = definitions / name
        path.write_text(path.read_text().rstrip().rstrip("]") + ",]")

    result, calls = _run(tmp_path, add_trailing_comma)

    assert result.returncode != 0
    assert name in result.stderr
    assert _mutations(calls) == []


def test_a_filter_without_a_pattern_stops_the_run_before_any_change(tmp_path):
    def drop_pattern(definitions: Path) -> None:
        path = definitions / "metric_filters.json"
        filters = json.loads(path.read_text())
        del filters[0]["pattern"]
        path.write_text(json.dumps(filters))

    result, calls = _run(tmp_path, drop_pattern)

    assert result.returncode != 0
    assert "metric_filters.json" in result.stderr
    assert _mutations(calls) == []
