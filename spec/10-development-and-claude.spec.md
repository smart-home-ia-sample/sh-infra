# Development Guide
Phase 1 foundation/BFA/registration -> Phase 2 MCP -> Phase 3 agents -> Phase 4 A2A -> Phase 5 LangChain/LangGraph -> Phase 6 AG-UI -> Phase 7 event simulation -> Phase 8 quality/docs.

Claude must read relevant specs before coding, keep services independently deployable, prefer simple solutions, avoid unnecessary DB/queues/Kubernetes, mock external LLMs in tests, update tests/docs with changes, keep Docker Compose runnable, never expose chain-of-thought or secrets.

Repository:
sh-ai/agents/{orchestrator,security,environment,energy}/, bfa/, mcp/home/, front/, infrastructure/docker/, docs/, tests/, docker-compose.yml, README.md.

Initial architecture decisions: monorepo; one container per agent; self-registration; BFA routes but does not reason; MCP is capability boundary; LangGraph handles stateful orchestration; simulated devices only; no chain-of-thought in UI.
