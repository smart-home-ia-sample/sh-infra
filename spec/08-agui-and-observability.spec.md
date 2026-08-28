# AG-UI and Observability
Frontend views: Home Dashboard, Assistant, Agent Activity. Dashboard shows rooms/devices/security/temperature/energy. Activity shows workflow, agent tasks, A2A calls, MCP tools, status/errors and final result.

Use AG-UI-compatible event/state streaming. Do not expose hidden chain-of-thought; expose concise safe events and summaries.

Every request has correlation_id propagated Frontend -> BFA -> Agent -> A2A -> MCP. Structured logs include service, level, correlation_id, request_id, task_id, operation, duration_ms and status. Never log secrets.
