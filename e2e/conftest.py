import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Build the stack from the sibling checkouts so the suite tests local code, not
# the published images. `./bootstrap.sh` must have cloned the siblings.
COMPOSE_FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.build.yml", "-f", "docker-compose.local.yml"]

# Overridable so this suite can also run from inside a helper container
# (docker-in-docker via the host's socket) against `host.docker.internal`;
# defaults to `localhost` for the normal case (CI runner / host machine).
E2E_HOST = os.environ.get("E2E_HOST", "localhost")

BASE_URLS = {
    "bfa": f"http://{E2E_HOST}:8000",
    "home_mcp": f"http://{E2E_HOST}:8100",
    "security": f"http://{E2E_HOST}:8200",
    "environment": f"http://{E2E_HOST}:8300",
    "energy": f"http://{E2E_HOST}:8400",
    "orchestrator": f"http://{E2E_HOST}:8500",
    "bff": f"http://{E2E_HOST}:8080",
}

# health path per service (default is /health)
HEALTH_PATH = {"bff": "/actuator/health"}


def _compose(*args: str, env: dict | None = None) -> None:
    subprocess.run(["docker", "compose", *COMPOSE_FILES, *args], cwd=REPO_ROOT, check=True, env=env)


def _wait_until_healthy(timeout_seconds: float = 180) -> None:
    deadline = time.time() + timeout_seconds
    pending = dict(BASE_URLS)
    while pending and time.time() < deadline:
        for name, url in list(pending.items()):
            try:
                response = httpx.get(f"{url}{HEALTH_PATH.get(name, '/health')}", timeout=2.0)
                if response.status_code == 200:
                    del pending[name]
            except httpx.HTTPError:
                pass
        if pending:
            time.sleep(2)

    if pending:
        raise RuntimeError(f"services never became healthy: {list(pending)}")


@pytest.fixture(scope="session", autouse=True)
def docker_stack():
    # Force deterministic mock LLM regardless of any local .env (docker compose
    # auto-loads .env, which may set LLM_PROVIDER=google for manual testing).
    env = {
        **os.environ,
        "SIMULATION_ENABLED": "false",
        "LLM_PROVIDER": "mock",
    }
    _compose("up", "--build", "-d", env=env)
    try:
        _wait_until_healthy()
        _warm_up()
        yield BASE_URLS
    finally:
        _compose("down")


def _warm_up(attempts: int = 8) -> None:
    """`/health` being 200 doesn't mean the whole chain (BFF JVM warmup, first
    MCP session, MQTT connect, first device-command echo) is ready. Drive one
    real command through it until it succeeds before the scored tests run."""
    for i in range(attempts):
        try:
            resp = httpx.post(
                f"{BASE_URLS['orchestrator']}/converse",
                json={"message": "Apague as luzes da sala."},
                timeout=30.0,
            )
            if resp.status_code == 200 and resp.json().get("status") == "ok":
                return
        except httpx.HTTPError:
            pass
        time.sleep(3)
    raise RuntimeError("stack never warmed up (a /converse command never succeeded)")
