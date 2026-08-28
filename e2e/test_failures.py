"""E2E failure-mode tests against the real docker compose stack.

Duplicate registration and transport-level timeout/retry are already
covered at the unit/integration level (`bfa/tests/test_routes.py`,
`shared/python/tests/test_a2a_roundtrip.py`) and are not repeated here.
This file covers failures that only make sense with real containers:
BFA down, MCP down, and an invalid device id against a live agent.
"""

import subprocess
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _wait_for_capability(bfa_url: str, capability: str, timeout_seconds: float = 15.0) -> None:
    """Polls the BFA until a healthy agent for `capability` is registered.

    Makes this test independent of the exact timing/ordering of the other
    failure tests in this file (which stop/start services), rather than
    relying on a fixed sleep after restart.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = httpx.get(f"{bfa_url}/agents", params={"capability": capability}, timeout=5.0)
        if response.status_code == 200 and response.json():
            return
        time.sleep(1)
    raise AssertionError(f"no agent for capability '{capability}' registered within {timeout_seconds}s")


def _stop(service: str) -> None:
    subprocess.run(["docker", "compose", "stop", service], cwd=REPO_ROOT, check=True)


def _start(service: str) -> None:
    subprocess.run(["docker", "compose", "start", service], cwd=REPO_ROOT, check=True)
    # Give dependent services time to re-register via their heartbeat
    # (REGISTRATION_HEARTBEAT_SECONDS=3 in this test run — see conftest.py)
    # before the next test relies on them being registered again.
    time.sleep(6)


def test_bfa_unavailable_degrades_explicitly(docker_stack):
    _stop("bfa")
    try:
        # With the BFA down the orchestrator can't discover any agent; the
        # request must degrade via recovery_explain, never 500. Each capability
        # lookup carries a ~5s connect timeout — give headroom.
        response = httpx.post(
            f"{docker_stack['orchestrator']}/converse",
            json={"message": "O que está acontecendo na casa?"},
            timeout=45.0,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert body["final_response"]  # an explicit message, not a stack trace
    finally:
        _start("bfa")


def test_mcp_unavailable_degrades_explicitly(docker_stack):
    _stop("home-mcp")
    try:
        response = httpx.post(
            f"{docker_stack['orchestrator']}/converse",
            json={"message": "Como está o consumo de energia?"},
            timeout=20.0,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
    finally:
        _start("home-mcp")


def test_invalid_device_returns_explicit_error(docker_stack):
    import asyncio

    from smart_home_common.a2a_client import call_agent

    _wait_for_capability(docker_stack["bfa"], "turn_off")

    result = asyncio.run(
        call_agent(
            docker_stack["bfa"],
            "turn_off",
            "turn_off",
            {"device_id": "does_not_exist"},
            sender="e2e-test",
        )
    )

    assert result["status"] == "ok"  # the agent task itself completed
    assert result["result"]["ok"] is False
    assert "does_not_exist" in result["result"]["error"]
