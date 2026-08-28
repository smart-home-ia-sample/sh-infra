# Architecture

Frontend (AG-UI) -> BFA -> Orchestrator/Security/Environment/Energy Agents -> Home MCP -> simulated home state.

BFA = registry, discovery, health and routing. It does not reason with an LLM.
Agents = domain reasoning and decisions.
LangGraph = stateful workflows.
A2A = agent collaboration.
MCP = capability/context boundary: tools, resources, prompts.
AG-UI = user interaction and execution visualization.

Critical boundary: BFA decides WHERE a task goes; agents decide HOW to solve it; MCP performs/returns WHAT is needed.

Note: the real flow is Front -> Orchestrator -> BFA (discovery, not traffic) -> agents -> MCP; the BFA is a control plane consulted per hop, never in the data path. See `11-persistence-auth-mqtt.spec.md` for the persisted home model, JWT auth, MQTT physical layer, BFA `/resolve` (BM25) and heartbeat/TTL liveness that supersede the "static home state" assumptions here.
