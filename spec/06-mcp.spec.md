# MCP
Single home-mcp server for MVP.

Tools: turn_light_on/off, set_light_brightness, set_temperature, turn_ac_on/off, lock_door, unlock_door, arm_alarm, disarm_alarm, open_curtain, close_curtain.
Resources: home://rooms, home://devices, home://security, home://environment, home://energy, home://events.
Prompts: leave_home, bedtime, energy_optimization, home_status.

Tools validate target/state transition, mutate simulated state, return resulting state and explicit errors. Idempotent mutations are preferred. Agents do not access MCP persistence directly.

Superseded in `11-persistence-auth-mqtt.spec.md`: `SEED_DEVICES`/`ROOMS` are removed; topology comes from the BFF (H2), runtime state from retained MQTT `state` messages, and the MCP is a materialized view. Mutating tools publish `.../set` and block on the `.../state` echo (~3s) so the contract stays synchronous. Tools carry `annotations={tags,examples}`; new `GET /tools` returns the tool schema map for BFA ranking.
