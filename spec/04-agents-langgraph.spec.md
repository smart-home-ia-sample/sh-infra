# Agents and LangGraph
Agents: Orchestrator, Security, Environment, Energy. Each runs in its own container and exposes health/readiness and A2A endpoint.

Orchestrator LangGraph state: request_id, user_message, intent, capabilities, selected_agents, pending/completed/failed_tasks, observations, final_response.
Graph: START -> Interpret -> Discover -> Plan -> Dispatch -> Collect -> Validate -> (Recovery/Explain | Final). At least one real conditional branch.

Security: doors/windows/alarm/presence. Environment: lights/brightness/temperature/AC/curtains. Energy: consumption/top consumers/recommendations. Agents never import each other directly; use A2A.

LangChain handles LLM integration, structured output, prompts and client/tool integration. Do not use LangGraph as a wrapper around one LLM call.
