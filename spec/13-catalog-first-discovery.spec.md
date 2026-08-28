# 13 — Catalog-first discovery, thin BFA

Status: **agreed, not yet implemented.** Supersedes the registry parts of
`03-bfa-and-registration`.

## Why

The BFA today keeps a per-instance registry (heartbeat TTL, round-robin
`_pick_instance`, eviction). On any orchestrator — Kubernetes, Nomad, ECS, even
`docker compose` with replicas — that is the platform's job: a Service/DNS name
already fronts N healthy instances and load-balances. The app-level registry
re-implements infrastructure and is a second source of truth that can drift from
the platform's.

What the platform does **not** do: tell an agent *which* service handles
"estou indo dormir". That — a searchable capability catalog + semantic ranking —
is the part of the BFA worth keeping.

## Decisions

### 1. BFA = stateless capability catalog + semantic resolver

Drop from the BFA:
- the per-instance registry, `last_seen`/heartbeat TTL, eviction
- `_pick_instance` round-robin
- `POST /register` (the write path)

Keep: `search.py` (BM25 + PT stemming + synonym map) — unchanged. The BFA is now
derived state only; the catalog can be rebuilt from scratch at any time.

### 2. The catalog is built by **pull**, from a static source list

New env **`CATALOG_SOURCES`**: comma-separated list of logical base URLs, e.g.
`http://security:8200,http://environment:8300,http://energy:8400,http://home-mcp:8100`.

On boot (and on `POST /refresh`, and optionally on an interval) the BFA fetches
each source's descriptor and (re)builds the BM25 index:
- A2A agents: `GET {url}/.well-known/agent-card` (or the a2a-sdk's card path)
- MCP: `GET {url}/tools`

The descriptor is authored by the service and lives next to the code that
implements it (no drift). A source that is down at boot is retried, not fatal;
`/resolve` just won't return it until fetched.

Not chosen: k8s label discovery via the API — removes the static list but
couples the BFA to the platform and needs RBAC. For a fixed, small fleet the
env list is the right trade.

### 3. `/resolve*` returns **logical service names**, not `IP:port`

`POST /resolve { query, kind?: agents|tools, top_k }` →
`[{ id (capability/verb), service (logical name), description, tags, examples, score }, …]`.

The caller invokes `http://{service}` and the platform picks the instance. No
`IP:port`, no instance health in the BFA (readiness probes + endpoint pruning
cover "currently up").

### 4. Catalog-first orchestration

The `interpret` node stops treating the hardcoded `DEVICE_VERBS` tuple as the
source of truth:

1. `POST BFA /resolve { query: <user utterance + short context>, top_k: N }` →
   the ranked capability menu.
2. The LLM prompt = system + that menu rendered as the available actions + live
   home topology + history → structured intent `{ capability, service, args }`
   (or `chitchat` / `unknown`).
3. `plan` resolves `device_id` from topology and builds the payload.
4. `dispatch` calls `service` by logical name.
5. `validate` checks `EXPECTED_EFFECTS` via MCP — unchanged.

`discover` collapses (the resolve already named the service). The **mock**
interpreter keeps a static verb map — it is a deterministic CI stand-in and does
not call the BFA.

### 5. No self-registration anywhere

Each agent / MCP / the orchestrator: delete `registration.py`, the lifespan
`register_with_bfa` hook, and the heartbeat. Descriptors are *served* at the
well-known endpoint, not *pushed*. The orchestrator's `converse` capability was
catalog decoration for a target nobody resolves (the BFF reaches it at a fixed
URL) — it simply isn't in the catalog.

`sh-common`: `registration_client.py` (`ServiceInfo`, `register_with_retry`,
`run_registration_heartbeat`) is removed → **`sh-common` v0.2.0** → bump
`SH_COMMON_REF` in every Python service's Dockerfile + `requirements-dev.txt`.

### 6. LLM access — deferred, but the shape is decided

Whether an agent reasons is a per-domain choice (security = deterministic;
energy-summary = needs an LLM). When an agent needs one it calls the LLM
**through `sh-common`'s wrapper** — the single place that owns provider / key /
model / fallback (gemini→ollama) / (later) cost + tracing. A dedicated
`llm-gateway` service only if that grows. Not built now (no agent reasons yet).

## Kept as-is

- `search.py` BM25 + stemming + synonyms
- A2A protocol between orchestrator ↔ workers
- the MCP tool contract (synchronous, `{ok,state}` echo)
- the JWT-forwarding chain (BFF → orchestrator → A2A → agent → MCP → BFF)

## Migration order

1. `sh-common` v0.2.0 (drop `registration_client`); tag; bump refs everywhere.
2. `sh-bfa`: `CATALOG_SOURCES` pull + index; strip the registry; `/resolve`
   returns logical names. Rewrite `test_registry.py`.
3. Agents / MCP: delete self-registration; ensure the descriptor endpoint carries
   `tags` + `examples`.
4. `sh-orchestrator`: catalog-first `interpret`; collapse `discover`.
5. `sh-infra`: `CATALOG_SOURCES` in `compose/core.yml`; re-run e2e.
