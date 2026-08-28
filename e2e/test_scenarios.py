"""End-to-end tests for the 5 MVP scenarios from `.spec/00-overview.spec.md`,
run against the real `docker compose` stack (LLM_PROVIDER=mock, set by
docker-compose.yml's default).
"""

import httpx


def _converse(base_urls: dict, message: str) -> dict:
    response = httpx.post(f"{base_urls['orchestrator']}/converse", json={"message": message}, timeout=30.0)
    assert response.status_code == 200
    return response.json()


def test_scenario_1_turn_off_living_room_light(docker_stack):
    result = _converse(docker_stack, "Apague as luzes da sala.")

    assert result["status"] == "ok"
    assert result["observations"]["turn_off"]["state"]["id"] == "living_room_light"
    assert result["observations"]["turn_off"]["state"]["on"] is False


def test_scenario_6_turn_off_appliance(docker_stack):
    # The redesign: the coffee maker is a real device with an on_off trait, so the
    # assistant can turn it off through the generic `turn_off` verb.
    result = _converse(docker_stack, "Desliga a cafeteira.")

    assert result["status"] == "ok"
    assert result["observations"]["turn_off"]["state"]["id"] == "kitchen_coffee_maker"
    assert result["observations"]["turn_off"]["state"]["on"] is False


def test_scenario_2_bedtime(docker_stack):
    result = _converse(docker_stack, "Estou indo dormir.")

    assert result["status"] == "ok"
    assert "check_security" in result["observations"]


def test_scenario_3_leave_home(docker_stack):
    result = _converse(docker_stack, "Vou sair de casa.")

    assert result["status"] == "ok"
    security = result["observations"]["secure_home"]
    assert security["doors"]["front_door"]["locked"] is True
    assert security["alarm_armed"] is True
    assert "critical_devices" in security  # proves the real Security->Energy A2A call ran


def test_scenario_4_energy_status(docker_stack):
    result = _converse(docker_stack, "Como está o consumo de energia?")

    assert result["status"] == "ok"
    energy = result["observations"]["inspect_consumption"]
    assert "total_watts" in energy
    assert "top_consumers" in energy


def test_scenario_5_home_status(docker_stack):
    result = _converse(docker_stack, "O que está acontecendo na casa?")

    assert result["status"] == "ok"
    observations = result["observations"]
    assert "check_security" in observations
    assert "check_environment" in observations
    assert "inspect_consumption" in observations
    assert "events" in observations
