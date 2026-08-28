# Domain and MVP Scenarios
Rooms: living_room, kitchen, bedroom. Devices: lights, TV, AC, curtain, coffee maker, refrigerator, front door, window, motion sensor, alarm. Deterministic seed state. Energy values are simulated.

Scenario 1: turn off living-room light.
Scenario 2: bedtime -> common lights off, bedroom climate configured, relevant security checked.
Scenario 3: leave home -> Security secures, Environment switches off nonessential devices, Energy identifies critical devices, Security may ask Energy via A2A, Orchestrator verifies.
Scenario 4: energy status -> total, top consumers, recommendations.
Scenario 5: home status -> security, active devices, environment, energy, recent events.

Post-MVP simulation events: motion_detected, door_opened, temperature_changed, device_on/off.
