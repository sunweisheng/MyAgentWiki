from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_debug(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "debug_llm_routing.py"), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_debug_contract_reports_function_schema() -> None:
    completed = run_debug("contract", "--task", "claim_role")

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["function_name"] == "submit_claim_role_decisions"
    assert payload["parameters_schema"]["additionalProperties"] is False


def test_debug_simulation_covers_primary_fallback_and_failure() -> None:
    completed = run_debug("simulate", "--scenario", "all")

    assert completed.returncode == 0
    records = {record["scenario"]: record for record in json.loads(completed.stdout)}
    assert records["online_first_success"]["diagnostic"]["route_attempt_counts"] == {"cli": 0, "online": 1}
    assert records["http_403_to_cli"]["diagnostic"]["route_attempt_counts"] == {"cli": 1, "online": 1}
    assert records["http_429_exhausted"]["diagnostic"]["route_attempt_counts"] == {"cli": 1, "online": 3}
    assert records["repairable_json"]["diagnostic"]["attempts"][0]["repaired"] is True
    assert records["both_routes_failed"]["status"] == "failed"
    assert "api_key" not in completed.stdout
