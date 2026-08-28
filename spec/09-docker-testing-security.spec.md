# Docker, Testing and Security
Docker Compose services: bfa, orchestrator-agent, security-agent, environment-agent, energy-agent, home-mcp, frontend. Use service names, not localhost. Readiness and registration retry handle startup order. Env vars include BFA_URL, MCP_URL, LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LOG_LEVEL.

Tests: unit validation/domain/state/registration; integration registration/routing/A2A/MCP; E2E all five scenarios; failure tests for unavailable BFA/MCP, timeout, invalid device, conflicts, duplicate registration. CI supports fake/mock LLM.

Security: no secrets in Git; validate boundaries; agent capability allow-list; user input is untrusted; never trust LLM mutation claims; verify through MCP.

