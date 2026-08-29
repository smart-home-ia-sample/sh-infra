# BFA and Registration

> **Superseded by `13-catalog-first-discovery.spec.md` (2026-08-29).** There is
> no registration path anymore: no `POST /agents/register` / `POST /mcp/register`,
> no heartbeat TTL, no round-robin instance pick. The BFA now *pulls* each
> service's descriptor from `CATALOG_SOURCES` and `/resolve*` returns logical
> service names. Only the BM25 ranking (`search.py`) survives. Kept here as the
> original design record.

Agents and MCP servers register when ready and retry with exponential backoff.

POST /agents/register: name, endpoint, capabilities, protocol, version.
POST /mcp/register: name, endpoint, capabilities, protocol, version.
GET /agents, GET /agents/{name}, GET /mcp, GET /mcp/{name}, GET /health, GET /ready.

Routing selects healthy agents by exact/best capability match. Duplicate registration updates the logical service. Unavailable services produce explicit errors. Propagate correlation_id/request_id/task_id.

Agent startup: start server -> wait BFA -> register -> READY.

Extended in `11-persistence-auth-mqtt.spec.md`: registry keyed logical-service -> list of instances with last_seen + derived status (heartbeat TTL, no active probing, no circuit breaker); `/resolve`, `/resolve/agents`, `/resolve/tools` (BM25 + regex over the registered A2A skills / MCP tool schemas, ranking only); two-stage routing (BM25 picks the service, round-robin picks the instance).

