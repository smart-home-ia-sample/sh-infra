# Persistence, Auth and MQTT

Redesign that turns the static simulated home into a user-owned, persisted,
message-driven model. Supersedes the "static home state" assumptions in
`02-architecture.spec.md`, `03-bfa-and-registration.spec.md` and
`06-mcp.spec.md` where they conflict.

> **Follow-on:** `12-device-capabilities.spec.md` replaces the hardcoded
> per-type action knowledge (BFF `DeviceActions`, MCP type-scoped tools,
> orchestrator `Capability` Literal) with a capability descriptor the
> `device-sim` announces per device over MQTT and the BFF persists.

## Goals

- The home (homes, rooms, devices) is **persisted** and **CRUD-editable** by
  the end user, not hardcoded.
- One demo user ships with a seeded model home identical to today's simulated
  state — no visible behavior change on first run.
- A simulated physical layer speaks **MQTT**, so the Home MCP is a semantic
  boundary over messaging instead of an in-process dict.
- Simple JWT auth in front of everything.

## Polyglot boundaries

| Layer | Stack | Owns |
|-------|-------|------|
| Front | React + Vite + AG-UI, static build served by the BFF | UI only, static |
| BFF | **Java / Spring Boot** (servlet MVC + JPA), **H2 embedded** | edge gateway, auth, home/room/device CRUD, single DB writer, live device read-model (MQTT) for the Dashboard |
| device-sim | **Java / Spring Boot**, **Eclipse Paho** (no Spring Integration) | simulated device runtime state (in memory), MQTT |
| AI layer | Python — Orchestrator, Security, Environment, Energy, Home MCP, BFA | reasoning, A2A, MCP, discovery |
| Broker | Mosquitto | MQTT transport |

- `smart_home_common` (Python) is **not** reused by the Java services. Each Java
  service carries a minimal filter for `correlation_id` propagation + structured
  logging (service, level, correlation_id, request_id, operation, duration_ms,
  status).
- BFF and device-sim **do not register with the BFA** — they are not
  capability-discoverable. Only A2A agents and MCP servers register.
- A2A between agents is untouched by this redesign.

## Auth

- JWT, **HS256**, single symmetric secret `JWT_SECRET` (env).
- **One demo user**, `DEMO_USER` + `DEMO_PASS_HASH` (env). No user table beyond
  what `homes.user_id` references; no signup.
- Access token only, TTL 60 min, **no refresh**. Expiry → front returns to login.
- Claims: `sub`, `iat`, `exp`.
- Validated **only at the edge**, in-process by a servlet filter on `/api/**`
  (rejects with 401 before any handler or proxy runs). `POST /auth/login` is the
  only public route. Downstream services trust the internal network.
- Front stores the token in `localStorage` (demo tradeoff: XSS-exposed),
  sends `Authorization: Bearer <jwt>` on every call, including the AG-UI
  `HttpAgent({ headers })`. On `401`: clear token, go to login.

## Edge wiring — the BFF is the only thing the browser talks to

No nginx. The BFF (Spring Boot, servlet MVC) serves the static React build *and*
is the API gateway. One process faces the browser.

```
browser → BFF  (single origin, no CORS)
  /                            → static SPA build (index.html fallback for client routes)
  POST /auth/login             → local, public
  /api/homes|rooms|devices/*   → local (H2)
  GET  /api/home-status        → local (SSE from the BFF's MQTT read-model)
  POST /api/agui/run           → proxied to orchestrator  (SSE)
```

- The Vite build output is baked into the BFF image — multi-stage Docker (node
  build → copy `dist/` into the Java image), served from the classpath;
  unknown non-`/api` paths fall back to `index.html`.
- Auth = a servlet filter on `/api/**`, validating the JWT in-process and
  rejecting with 401 before any proxy.
- `/api/agui/run` is proxied to the orchestrator by a small hand-rolled
  streaming controller (JDK `HttpClient` + `StreamingResponseBody`, response
  body copied through unbuffered) rather than a gateway library — the
  orchestrator's uvicorn parser is strict about the forwarded request.
  `/api/home-status` is an SSE emitted locally by the BFF (phase 2; phase 1
  proxies it the same way as `/api/agui/run`).
- No CORS anywhere: browser ↔ BFF, BFF ↔ internal services server-to-server.
- Internal services (`bfa`, `home-mcp`, `orchestrator`, agents, `device-sim`,
  `mosquitto`) are **not** published in `docker-compose`; only the BFF is.
- Front config: API base is a relative `/api` (same origin as the page).
- Local dev: `npm run dev` (Vite) with a dev proxy to the BFF for `/api` `/auth`.

## Real-time home status

`GET /api/home-status` is an **SSE stream served directly by the BFF** — it never
touches the orchestrator or the agents. Pure device state needs no reasoning.

- The BFF subscribes to `home/+/+/+/state` and `.../availability`, keeps a
  read-model keyed by `device_uuid` enriched from H2 (room, nickname, type), and
  records the last N observed state changes as the events feed.
- `GET /api/home-status` (SSE): first event = full snapshot, then one event per
  device change. `GET /api/home-status/snapshot` = same shape, one-shot (tests,
  cheap callers).
- Snapshot shape = every device with its current state, grouped by room, plus
  trivially-derived rollups (alarm armed, doors locked, naive total watts,
  recent events). Deep energy analysis (top consumers, recommendations) stays
  with the Energy agent on the assistant path — not the live dashboard.
- The orchestrator's `GET /home-status` route is **removed**. The Dashboard no
  longer talks to the AI layer at all; only Assistant / Agent Activity use
  `/api/agui/run`.
- The Home MCP keeps its **own** MQTT read-model for agent-time reads
  (`home://environment` etc. during command execution) — a second lightweight
  subscriber to the same retained topics; MQTT fan-out handles that. No MCP
  change feed or resource subscription is needed.
- Front: the Dashboard drops polling, opens the stream, repaints cards per
  event. `fetchHomeStatus()` → `subscribeHomeStatus(onSnapshot)`.

## Data model (H2, owned by BFF)

```
homes
  uuid        PK
  user_id     FK → demo user
  name        e.g. "Casa Modelo"
  is_default  bool

rooms
  uuid        PK
  home_uuid   FK
  name        e.g. "Sala" / "Cozinha" / "Quarto"
  slug        stable key e.g. "living_room" -- MQTT topic segment; orchestrator room match

devices
  uuid        PK        -- generated by BFF on insert; stable key everywhere
  home_uuid   FK        -- denormalized; used in the MQTT topic and in queries
  room_uuid   FK        -- "localização"
  type        enum      -- "tipo"
  nickname    text      -- "apelido", e.g. "Luz da sala"; NOT NULL, unique per home
  created_at
```

- `type` is a **closed vocabulary**: `light` (on/off), `dimmable_light`
  (on/off + brightness), `ac, curtain, door, window, tv, coffee_maker,
  refrigerator, motion_sensor, alarm`. A device's capabilities derive from its
  `type` — `set_brightness` is only valid on `dimmable_light`. Seed: bedroom
  light is `dimmable_light`; kitchen/living-room lights are plain `light`.
- **No `default_state` column.** Initial runtime state is decided by the
  device-sim per `type` (`light` → off / brightness 0, `ac` → off / 24 °C,
  `curtain`/`window` → closed, `door` → unlocked+closed, `alarm` → disarmed,
  etc.). BFF owns topology only, never runtime state.
- **Multi-home**: schema supports N homes per user; the app uses the user's
  `is_default` home. A `home_id` context threaded through the whole call chain
  is deferred.
- **Datasource is env-configurable.** Unset → embedded H2 file (single
  instance). Set `DB_URL` (`jdbc:postgresql://…`) + `DB_USERNAME` +
  `DB_PASSWORD` → external Postgres, and the BFF runs stateless/replicated
  behind a load balancer (JWT is stateless; no `HttpSession`). Driver and
  Hibernate dialect auto-detect from the URL; the Postgres driver ships on the
  classpath. The seeder is race-safe: `homes(user_id, name)` is unique and a
  losing replica catches the integrity violation.
- **Seed**: demo user + one `is_default` home "Casa Modelo" + **5 rooms** (Sala,
  Cozinha, Quarto, Entrada, Casa toda — the last two host `front_door` and
  `alarm`) + the 13 devices currently in `mcp/home/app/state.py::SEED_DEVICES`,
  same rooms and types, so the seeded system is byte-for-byte today's behavior.
  Implemented as an idempotent seeder (runs when the device table is empty), not
  a Flyway script.

## MQTT

- Broker: Mosquitto.
- Topic shape: `home/{home_uuid}/{room_slug}/{device_uuid}/{set|state|availability}`.
  - `{device_uuid}` — the stable DB key, not a slug (survives a nickname change).
  - `{room_slug}` — readable segment derived from the room name.
- `state` messages are **retained** — a fresh subscriber gets current state.
- `set` — command in. `state` — device's echo of its new state.
- `availability`:
  - device-sim's MQTT connection **LWT** publishes all its devices offline if
    the simulator process dies.
  - an individually "unplugged" device is an explicit `availability=offline`
    publish.
- Control topic `home/{home_uuid}/topology/changed` — BFF publishes it after any
  device/room CRUD; device-sim and Home MCP re-hydrate the topology from the BFF
  HTTP API on receipt.

## device-sim (Java / Spring Boot / Paho)

- On startup: `GET {bff}/homes/{id}/devices`, build in-memory state map, apply
  per-`type` defaults, publish a retained `state` per device.
- Subscribes to `.../+/+/set`; on a command: mutate its in-memory state,
  optionally inject bounded latency/failure (within the MCP's echo timeout, to
  exercise recovery), publish the resulting `.../state`.
- Holds **all** runtime state; nothing persisted; resets on restart.
- Re-hydrates on `topology/changed`.

## Home MCP changes

- `SEED_DEVICES` and `ROOMS` are removed from `state.py`.
- The MCP becomes an **MQTT subscriber + materialized view**:
  - device list / rooms: from the BFF HTTP API.
  - current device state: from retained `.../state` messages.
- `home://rooms`, `home://devices` and the derived snapshots
  (`home://security|environment|energy|events`) are computed from the view.
- Tool contract stays **synchronous**: a mutating tool publishes `.../set` and
  **blocks until it observes the matching `.../state` echo**, timeout ≈ 3 s,
  then returns the resulting state (or an explicit error / timeout). This keeps
  the orchestrator's `dispatch` / `validate` / `EXPECTED_EFFECTS` unchanged.
- Fallback: if the broker or BFF is unavailable at startup, the MCP degrades
  explicitly (empty/last-known view) rather than crashing.
- Every MCP tool is documented for BFA ranking with
  `annotations={"tags": [...], "examples": [...]}` alongside its `description`.
- New MCP route `GET /tools` returns a schema map of all tools
  (`name`, `description`, `input_schema`, `annotations`).

## BFA changes

- **Registry** keyed `logical service → list of instances`. Each instance:
  resolved `endpoint`, `last_seen`, derived `status`.
  - `status = healthy` while `last_seen` is within the TTL (≈ `3 × 15 s`
    heartbeat = 45 s); `unhealthy` beyond; instance **evicted** after a longer
    grace (≈ 5 min).
  - Liveness comes from the existing re-registration heartbeat
    (`run_registration_heartbeat`). No active probing, no circuit breaker.
- **Resolution endpoints**:
  - `POST /resolve` — `resolve(query, top_k=3, threshold=0.3)` over agents +
    tools.
  - `POST /resolve/agents` — agents only.
  - `POST /resolve/tools` — tools only.
- Index built **at registration**: tokenize `name` + `description` +
  capabilities + `tags` + `examples` (accents stripped, PT/EN stopwords
  dropped). Agents and MCP send their catalog in the registration payload
  (agents from their skills, MCP from its tool list; the MCP also serves it at
  `GET /tools`).
- Ranking: **Okapi BM25** (`rank_bm25.BM25Okapi`). The score returned and
  filtered on is **query coverage** = raw BM25 / the best score this query could
  attain (`Σ idf(term) · (k1+1)`), so it lands in 0..1 and `threshold` means
  "the doc covers at least this fraction of the query". Stopwords + coverage
  together give `"olá tudo bem" → []`.
- **Two-stage routing**: BM25 ranks logical services; a healthy instance of the
  chosen service is picked by **round-robin**. BM25 never sees an instance;
  round-robin never sees relevance.
- The BFA **only ranks and returns**; the caller (supervisor/agent) decides.
  No LLM in the BFA.
- No CORS on the BFA — the browser never touches it. Front→orchestrator
  discovery does **not** go through the BFA (nginx routes that hop).

## Orchestrator changes

- `discover` node resolves each capability via the BFA `/resolve/agents`
  (capability text ranked against the A2A catalog, `threshold=0.0`), falling back
  to the exact `GET /agents?capability=` lookup when `/resolve` errors or returns
  no hit — a BM25 miss on a valid capability must never block a real command.
  `call_agent` (dispatch) still does its own exact `?capability=` lookup.
- `interpret`:
  - `ControllableDevice` / room `Literal` types are now plain `str`.
  - the `interpret` node fetches the live topology once (`home://devices` +
    `home://rooms`, best effort — empty on an unreachable MCP) and threads it
    through `interpret_command`. It is stashed in graph state as `topology` and
    reused by `plan`.
  - the classification system prompt keeps its tuned prose (the worked
    temperature-delta examples) but gets `_topology_text(topology)` appended: the
    per-room inventory of the **actual** registered device ids + types, with an
    instruction to use only those ids and answer `unknown` for a room/type that
    isn't listed.
  - the interpreter still emits a `device_id` string directly; the node then
    re-checks it against the live id set and downgrades the whole command to
    `unknown` if the id was hallucinated (not registered).
  - the mock interpreter (CI, no LLM) resolves `(room, type)` against the live
    topology via `resolve_device_id`, with the legacy `f"{room}_{type}"` slug as
    the offline fallback.
- `plan`: `bedtime` and the `turn_off_light` default resolve their devices by
  `(type + room)` from `state["topology"]` (`resolve_device_id`), not by
  hardcoded ids. `leave_home` dispatches capability-level agents only, so it has
  no device ids to resolve.
- New intent `chitchat` (greeting / casual talk): a dedicated `chitchat` node
  (warm reply, `validation_ok=True`) sits right after `interpret` via a
  conditional edge, skipping `discover / plan / dispatch / collect / validate`.
  `"olá"` stops being modeled as an interpretation failure.

## `"olá"` end-to-end (target)

```
browser → BFF  /api/agui/run  (Bearer jwt)
  BFF JWT filter validates jwt → ok
  BFF proxies → orchestrator /agui/run
    interpret → intent = chitchat
    → final (warm greeting)
    → AG-UI TextMessage* + RunFinished  (SSE, streamed back through the BFF)
```

BFA: not called. Agents: not called. MQTT / device-sim / MCP: not touched.
Only backend work is the BFF's in-process JWT check.

## Build order

Each phase ends with the full test suite green before the next starts.

1. **BFF** (done) — Spring Boot (servlet MVC + JPA) + H2 + schema + idempotent
   seed + `POST /auth/login` + JWT servlet filter on `/api/**` + CRUD API + a
   hand-rolled streaming proxy to the orchestrator for `/api/agui/run` and
   `/api/home-status` + serving the Vite build (multi-stage Docker, `index.html`
   SPA fallback); front login screen. Seed = the 13 current devices; AI layer
   unchanged; behavior identical. Internal service ports stay published and the
   E2E suite keeps hitting them directly; unpublishing them and routing E2E
   through the BFF is a later step.
2. **MQTT** — Mosquitto (not anonymous: one credential, per-topic ACLs come
   with the service-auth phase) + `device-sim` (Python, pure MQTT reactor: no
   HTTP, invents a per-type default the first time it hears of a device, echoes
   retained `.../state` on `set`/`get`, LWT `home/simulator/status`). BFF gains
   an MQTT client (Paho Java) — pulled forward from the read-model work:
   - `POST /api/devices/{id}/command` `{action, value?}` — semantic action
     (`turn_on`/`set_temperature`/…) validated against the device type,
     published as `home/{homeId}/{roomSlug}/{deviceId}/set`, **blocks on the
     `.../state` echo** (~3s → 504), returns the confirmed state. This is the
     route the Home MCP tools will call.
   - `GET /api/devices/{id}/state` — latest state from the read-model (publishes
     a `get` first if unseen).
   - MQTT down / `bff.mqtt.enabled=false` → command 503; auth + CRUD unaffected.
   - `GET /api/home-status` — **live SSE from the BFF read-model**: one full
     `snapshot` event on connect, then a small `device` event per change
     (`{deviceId, nickname, type, roomSlug, state, at, rollups}`, ~320 B vs the
     ~5 KB snapshot) and a `simulator` event when the sim goes on/offline. The
     front merges deltas into a full HomeStatus in memory. `GET
     /api/home-status/snapshot` — full shape, one-shot. Snapshot = devices
     grouped by room + trivial rollups (`alarmArmed`, `allDoorsLocked`,
     `openDoors`, naive `totalWatts`, `activeDevices`) + last ~10 events. Served
     entirely locally — the BFF no longer proxies `/api/home-status`. The
     orchestrator's own `/home-status` **stays** (its unit tests and the E2E
     `test_mcp_unavailable` probe use it); it's just unreachable via `/api`. Its
     removal moves to the MCP-rewire phase.
   - `topology/changed` — the BFF publishes `home/{homeId}/topology/changed`
     after any room/device CRUD (nothing consumes it yet).
   - Dashboard switched from polling to the SSE stream (fetch + stream reader,
     not `EventSource`, so it can send the bearer token).
   **Home MCP rewire is deferred to the very end** (after BFA + orchestrator),
   when the whole system is clearer. Until then the MCP keeps its in-memory
   `SEED_DEVICES` and the Assistant path is unchanged — so the MCP's state and
   the device-sim's state are two independent simulations in the interim.
3. **BFA** (done) — registry keyed logical-service → list of instances (by
   resolved endpoint), each with `last_seen` and a status derived from the
   heartbeat TTL (`REGISTRATION_TTL_SECONDS`, default 45s; evicted after
   `REGISTRATION_GRACE_SECONDS`, default 300s). Flat response shape kept for
   `GET /agents`, `GET /agents?capability=`, `GET /mcp` so every existing
   consumer is unchanged; `GET /agents/{name}` / `GET /mcp/{name}` now return a
   richer view with every instance. Capability lookup and `/resolve` pick a
   healthy instance by **round-robin**. `POST /resolve`, `/resolve/agents`,
   `/resolve/tools` `(query, top_k=3, threshold=0.3)` — Okapi BM25 (`rank_bm25.BM25Okapi`)
   over the registered catalog (one doc per agent, one per MCP tool), tokenizer
   strips accents + PT/EN stopwords; the score is **query coverage** (raw BM25 /
   best attainable score for the query, 0..1) so `threshold` means "cover at
   least this fraction of the query" and `"olá tudo bem"` → `[]`. Results carry
   the round-robin-picked endpoint; a service with no healthy instance is
   dropped. Agents/MCP send their catalog (skills / tools with tags + PT
   example phrasings) in the registration payload; the Home MCP also exposes
   `GET /tools` (schema map + annotations). No circuit breaker, no active
   probing. The orchestrator's `discover` node consumes `/resolve/agents`
   (phase 4), with an exact `?capability=` fallback.
4. **Orchestrator** (done) — `Literal → str` for device/room; the `interpret`
   node fetches the live topology once and threads it through: prompt gets the
   real per-room device-id inventory appended, mock resolves `(room, type)` →
   slug, and a hallucinated id is downgraded to `unknown`. `bedtime` /
   `turn_off_light` resolve devices by `(type + room)` from `state["topology"]`.
   `discover` resolves each capability via `/resolve/agents` with an exact
   `?capability=` fallback. New `chitchat` node after `interpret` (conditional
   edge) short-circuits greetings to a warm reply.
5. **Front** — CRUD screens for rooms/devices; optional multi-home UI.
6. **Home MCP rewire + user identity** (done — pulled ahead of phases 4/5)
   - **MCP is a thin adapter over the BFF** (`mcp/home/app/bff_client.py`).
     `SEED_DEVICES`/`ROOMS`/`simulation.py`/`state.py` deleted. Topology from
     `GET /api/homes/{default}/devices|rooms`; live state and the derived
     `home://security|environment|energy|events` resources from
     `GET /api/home-status/snapshot`; mutating tools call
     `POST /api/devices/{id}/command` (which publishes MQTT and blocks on the
     echo). `validate`/`EXPECTED_EFFECTS` unchanged: the tool return keeps the
     legacy `{"ok", "state"}` shape and `state["id"]` is the device **slug**.
     Dashboard and Assistant now share one simulation (both → BFF → device-sim).
   - **Device slug bridge**: `devices.slug` column on the BFF (unique per home,
     auto-derived from the nickname if omitted), seeded with the 13 legacy keys
     (`living_room_light`, `front_door`, `alarm`, …). The MCP maps slug ↔ BFF
     UUID; the orchestrator and E2E keep using slugs unchanged.
   - **Identity — the user's JWT rides the whole chain** on `Authorization:
     Bearer` at every hop (BFF proxy forwards it → orchestrator → A2A →
     agent → MCP → BFF), and the BFF re-validates on each operation. Nothing in
     the middle verifies — a forged token dies at the BFF. Plumbing:
     `smart_home_common.auth` — a contextvar + `AuthTokenMiddleware` (raw ASGI,
     mounted on the orchestrator and every agent via `mount_a2a`) that lifts the
     incoming token so `call_agent` / `HomeMcpClient` forward it automatically.
   - **Token-less entry points** (`POST /converse`, service startup): the
     orchestrator/MCP self-login as the demo user (`ServiceLogin` →
     `POST /auth/login` with `DEMO_USER`/`DEMO_PASS`, cached, refreshed before
     expiry). Best-effort — if the BFF login is unreachable the request still
     degrades via `recovery_explain` rather than 500. Expiry mid-conversation is
     a known gap (refresh tokens later).
   - The orchestrator's own `/home-status` route is **removed** (only two tests
     used it; reworked to `/converse`).

## Testing implications

- BFF: JUnit 5 + Mockito + Spring Test, H2 in-memory — **29 tests, green in
  Docker** (`JwtServiceTest` HS256 edge cases; `HomeServiceTest` mocked-repo
  branch logic; `BffIntegrationTest` `@SpringBootTest`+MockMvc, `@Transactional`
  rollback per test: login, `/api/**` JWT guard, seed, home/room/device CRUD,
  slug/nickname/room-with-devices conflicts, bad enum → 400, per-user scoping,
  seed idempotency, SPA fallback, `/actuator/health`, proxy routes 401 before
  forwarding). Later: `topology/changed` publish, MQTT read-model, `/api/home-status`
  SSE (first event = full snapshot, one per change) + `/snapshot` one-shot.
- device-sim: JUnit — per-type default state, `set → state` round trip,
  latency/failure injection, LWT.
- MQTT-dependent tests need a broker: an in-process/embedded broker for unit
  scope, real Mosquitto for E2E.
- Home MCP: existing tests adapt to the materialized view (broker fixture /
  fake); the synchronous tool contract must still hold.
- E2E (`tests/e2e/`): compose now includes `mosquitto`, `bff` (also serves the
  front), `device-sim`;
  add login → protected route, device CRUD → command against the new device,
  simulator-down (`availability` LWT) degrades explicitly, Dashboard
  `/api/home-status` SSE emits the new state after a device change.
- Deterministic mock mode (`LLM_PROVIDER=mock`) still required for CI.
