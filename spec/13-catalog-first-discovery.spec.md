# 13 — Catalog-first discovery, thin BFA

Status: **implemented** (2026-08-29). Supersedes the registry parts of
`03-bfa-and-registration` and `11-persistence-auth-mqtt` (heartbeat TTL,
round-robin instance pick, `POST /register`). Shipped: thin BFA (pull catalog,
`/resolve` logical names), no self-registration anywhere, `sh-common` v0.2.0
tagged + refs bumped, e2e green.

Decision 4 landed as a **narrower change** than first written (see that section):
the `interpret` node now derives its device constants from the live topology
instead of a full BFA-menu-driven rewrite. The `discover` node was **kept**
(it consults `/resolve/agents` per hop); the "collapse discover" idea is
deferred. Decision 6 (LLM-through-`sh-common`) remains deferred — no agent
reasons yet.

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

### 4. Topology-derived `interpret` (shipped scope)

The original plan here was a BFA-menu-driven rewrite: `interpret` would `POST
/resolve` for a ranked capability menu, render it into the LLM prompt, and emit
`{ capability, service, args }`, collapsing `discover`. That is **deferred** —
for a fixed ~10-verb vocabulary the ranking round-trip added latency and a
failure mode for little gain.

What shipped instead: `interpret` stops **hardcoding the device inventory**.
Everything the prompt says about what this house can do is now derived from the
live topology (`home://devices`), with the hardcoded values kept only as the
MCP-unreachable fallback:

- **`available_verbs(topology)`** = the interpreter's known verbs ∩ the union of
  every installed device's announced `actions`. Remove all ACs and
  `set_temperature` drops out of the verb menu the prompt offers.
- the system prompt is a **template** (`_SYSTEM_PROMPT_TEMPLATE`) with
  `<<VERBS>>`, `<<LIGHT_IDS>>`, `<<ALARM_ID>>`, `<<AC_MIN>>`, `<<AC_MAX>>`
  sentinels filled by `build_system_prompt(topology)` per request.
- `turn_off_light`'s id list = `type=light` / `dimmable_light` from topology;
  the alarm id = `type=alarm`; the AC clamp range = the AC's announced
  `params.set_temperature.{min,max}`.

This needed **`home://devices` to carry two new per-device keys**, both flattened
from the announced capability descriptor (spec/12): `actions` (the verbs the
device accepts) and `params` (numeric bounds, e.g.
`{"set_temperature": {"min": 16, "max": 30}}`).

`discover`, `plan`, `dispatch`, `validate` are unchanged: `discover` still
consults `POST /resolve/agents` to confirm a provider exists before planning.
The **mock** interpreter keeps a static verb map — it is a deterministic CI
stand-in and does not call the BFA — but it too now reads device ids from the
passed-in topology.

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

## Migration order (as shipped)

1. `sh-common` v0.2.0 — drop `registration_client`; `build_agent_card` takes
   5-tuple skills `(id, name, description, tags, examples)`; `call_agent` gains
   `agent_url=`; `mcp_client` resolves via `POST /resolve/tools`. Tagged
   `v0.2.0`, GitHub Release publishes the wheel. ✅
2. `sh-bfa` — `catalog.py` pulls each `CATALOG_SOURCES` base URL
   (`/.well-known/agent-card.json` for A2A, `/tools` for MCP) and rebuilds the
   BM25 index on boot / `POST /refresh`. Registry, `_pick_instance`,
   `POST /register`, `registry.py`, `client_host.py` deleted. `/resolve*` returns
   `{kind, service, url, id, name, description, tags, examples, score}`. ✅
3. Agents / MCP — `registration.py` → `skills.py` / `tools_catalog.py` (static
   descriptor lists); no lifespan, no heartbeat. Agent card + `/tools` carry
   `tags` + `examples` (a2a-sdk serializes them natively). ✅
4. `sh-mcp` — `home://devices` flattens `actions` + `params` from the announced
   descriptor. `sh-orchestrator` — `interpret` templatized + topology-derived
   (decision 4, narrowed). ✅
5. `sh-infra` — `CATALOG_SOURCES` in `compose/core.yml`; `bfa` `depends_on` the
   agents + `home-mcp` (it pulls their cards), and those services **lost** their
   `depends_on bfa` (the old registration edge) to break the cycle. `e2e/`
   updated for catalog-first (`test_failures.py` polls `/resolve/agents`). ✅

## Deferred

- BFA-menu-driven `interpret` + `discover` collapse (decision 4, original form).
- LLM access through `sh-common` (decision 6) — no agent reasons yet.
- Periodic catalog refresh on a timer (only boot + `POST /refresh` today).
