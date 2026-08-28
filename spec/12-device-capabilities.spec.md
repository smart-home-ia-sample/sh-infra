# Device Capabilities (self-announced)

Follows `11-persistence-auth-mqtt.spec.md`. Turns "what a device can do" from
knowledge hardcoded in four places (BFF `DeviceActions`, Home MCP tools, each
agent's `SKILLS`, orchestrator `Capability`) into **one descriptor the simulated
device announces about itself**, persisted with the device and served upward.

Model chosen: **B — the `device-sim` is the authority** (the Matter / HomeKit
commissioning model: the physical device advertises its clusters/traits, the
controller stores and drives them). The BFF becomes a pure gateway for this:
persist what was announced, validate commands against it, serve it.

## Why

- Adding `coffee_maker` / `tv` / `window` to the seed made them visible to the
  interpreter (topology injection) but uncontrollable — no capability, no tool.
  The fix must not be "add four more hardcoded entries in four files".
- Real controllers don't hardcode device abilities by type. The type is a
  template; the instance carries the truth.
- Single source → adding a device kind = teaching the `device-sim` its traits +
  default state + state evolution. BFF, MCP, agents, orchestrator unchanged.

## The capability descriptor

Per **device instance**. A list of *traits*; each trait names the commands it
accepts, the state keys it owns, and (optionally) a param schema per command and
human text + PT example phrasings for retrieval.

```json
{
  "traits": [
    { "trait": "on_off",
      "commands": ["turn_on", "turn_off"],
      "state": ["on"],
      "description": "liga e desliga o aparelho",
      "examples": ["liga a TV", "desliga a cafeteira", "acende a luz"] },
    { "trait": "brightness",
      "commands": ["set_brightness"],
      "params": { "set_brightness": { "type": "integer", "min": 0, "max": 100, "unit": "%" } },
      "state": ["brightness"],
      "description": "ajusta o brilho",
      "examples": ["diminui o brilho", "coloca a luz em 30%"] },
    { "trait": "thermostat",
      "commands": ["set_temperature"],
      "params": { "set_temperature": { "type": "number", "min": 16, "max": 30, "unit": "C" } },
      "state": ["temperature"],
      "description": "define a temperatura alvo",
      "examples": ["ajusta para 22 graus", "esfria o quarto"] }
  ]
}
```

Trait vocabulary (initial): `on_off`, `brightness`, `thermostat`, `open_close`,
`lock`, `arm_disarm`, `occupancy` (read-only, no commands).

Default trait set per current type (what the `device-sim` announces):

| type            | traits                    |
|-----------------|---------------------------|
| light           | on_off                    |
| dimmable_light  | on_off, brightness        |
| ac              | on_off, thermostat        |
| tv              | on_off                    |
| coffee_maker    | on_off                    |
| refrigerator    | on_off                    |
| curtain         | open_close                |
| window          | open_close                |
| door            | lock                      |
| alarm           | arm_disarm                |
| motion_sensor   | occupancy                 |

Because it's per instance, a future device typed `light` may announce
`[on_off, brightness, color]` with no enum change; a smart plug typed
`coffee_maker` still announces just `[on_off]`.

## Announce flow

```
1. BFF create/update/delete device (H2 CRUD)
     → publishes  home/{homeId}/{roomSlug}/{deviceKey}/set|get  as today
     → publishes  home/{homeId}/topology/changed
2. device-sim (owns the "hardware"): on topology/changed, or first sight of a
   device on any of its topics, publishes RETAINED:
     home/{homeId}/{roomSlug}/{deviceKey}/state          (as today)
     home/{homeId}/{roomSlug}/{deviceKey}/capabilities   (NEW) -> {"traits":[...]}
3. BFF subscribes to  home/+/+/+/capabilities  (alongside .../state, .../availability),
   writes the descriptor to devices.capabilities (JSON column)
4. BFF serves it:
     GET /api/homes/{id}/devices          -> each device carries "capabilities"
     GET /api/home-status/snapshot        -> same
5. BFF command validation (POST /api/devices/{id}/command) is now generic:
     - action must appear in some trait.commands of THIS device's descriptor
     - value must satisfy that command's params schema (type / min / max)
   DeviceActions loses SWITCHABLE / OPENABLE / the per-type switch.
```

### Bootstrap / sim-offline handshake

- Between the device row being created and its `capabilities` arriving, the
  device is **not provisioned**. A command in that window returns
  `409 device not provisioned` (Problem Detail), never a guessed action.
- If the `device-sim` is down at create time, the descriptor arrives late — when
  the sim reconnects and republishes the retained `capabilities`. The device
  simply isn't controllable until then; the Dashboard shows it as pending.
- **Seed pre-fill.** `DataSeeder` fills the 13 seeded devices' `capabilities`
  from a `DeviceTraitTemplates` table (type → trait list) so a fresh stack — and
  every MQTT-off integration test — has a working descriptor immediately, before
  the sim's first announce. This template is used **only** at seed time and on a
  user-supplied create/update with no override; it is **never consulted at
  command time** (that path reads the stored descriptor only). The `device-sim`
  keeps its own copy of the same table (different service, different language);
  when it announces, it overwrites the pre-fill with identical content. This is a
  small, deliberate duplication that buys offline testability and a
  no-"device-not-ready"-flash bootstrap for the seeded home.
- A **user-created device with MQTT on** gets its descriptor purely from the
  announce (the seeder template is the fallback when the sim is unreachable).
- `devices.capabilities` is nullable; `capabilities: null` in a DTO means "not
  provisioned yet" — a command then returns `409`. Provisioning is checked with
  the rest of the input validation, *before* the `mqtt.ready()` `503` check (same
  ordering as the existing "reject bad input before the device link" rule), so a
  null-descriptor device reads as `409` even with the link down. In practice the
  seed pre-fill / create fallback means this only bites rows that predate the
  column (an existing H2 file after `ddl-auto: update`), until the sim announces.

## Persistence

- `devices.capabilities` — JSON column (`jsonb` on Postgres, character LOB on
  H2) via Hibernate `@JdbcTypeCode(SqlTypes.JSON)`, mapped to a small record
  tree (`CapabilityDescriptor(List<Trait> traits)`).
- No child table now. Add `device_trait` later only if capability filtering has
  to happen in SQL — the AI layer does the matching, not the DB.
- `POST` / `PUT /api/devices/**` accept an **optional** `capabilities` override
  in the body (a real controller can force-set a descriptor); normally omitted
  and filled by the announce.

## Home MCP

- Drop the 12 type-scoped tools (`turn_light_on`, `turn_ac_on`, `open_curtain`,
  …). Register **~10 generic verb tools**, one per command in the trait
  vocabulary:
  `turn_on(device_id)`, `turn_off(device_id)`, `open(device_id)`,
  `close(device_id)`, `lock(device_id)`, `unlock(device_id)`, `arm(device_id)`,
  `disarm(device_id)`, `set_brightness(device_id, value)`,
  `set_temperature(device_id, value)`. Each just forwards to
  `POST /api/devices/{id}/command {action, value?}`; the BFF re-validates against
  the device descriptor. `turn_light_on` vs `turn_ac_on` collapses — the
  `device_id` disambiguates.
- `home://devices` resource: each device gains `capabilities` (the trait list)
  and a flattened `actions` (the union of `trait.commands`) for cheap checks.
- `GET /tools` and the BFA catalog are built from the **trait catalog ∩ traits
  actually installed in this home** — `/resolve` only advertises verbs that have
  a target. Descriptions + examples come from the trait definitions, not
  restated per tool.

## Agents

- `environment` / `security` stop enumerating fine-grained skills. They expose
  the verb capabilities they own and forward `{device_id, action, value}`
  straight through to the MCP:
  - `environment`: `turn_on`, `turn_off`, `open`, `close`, `set_brightness`,
    `set_temperature`
  - `security`: `lock`, `unlock`, `arm`, `disarm`
- Agent-level capabilities that are *not* a single device verb stay as they are:
  `check_environment`, `check_security`, `inspect_consumption`,
  `switch_off_nonessential`, `secure_home`, and the scenario capabilities.

## Orchestrator

- `interpret` emits `{device_id, action, value?}` for the device-control path
  instead of a closed `Capability` Literal. `action` is a plain string.
- Runtime validation: `action` must be in `home://devices[device_id].actions`;
  otherwise the command degrades to `unknown` (same as a hallucinated
  `device_id` today).
- The interpret prompt's device inventory (`_topology_text`) now lists, per
  device, its allowed actions — so the model picks from a real per-device menu.
- `EXPECTED_EFFECTS` becomes a small generic map keyed by verb
  (`turn_on → on:true`, `turn_off → on:false`, `open → open:true`,
  `close → open:false`, `lock → locked:true`, …) rather than per-capability.
- `plan` / scenario resolution (`bedtime`, `leave_home`) already resolve devices
  by `(type, room)` from the live topology — unchanged, they just emit verbs.

## Tool retrieval — BM25 now, embeddings optional later

The `/resolve` corpus is tiny (~10 verb tools, a handful of agents, ~13
devices). Ranking quality is dominated by **description quality**, which model B
fixes at the source (trait `description` + `examples`, single-sourced).

Stay on **BM25** (`rank_bm25.BM25Okapi`, already in place), with two cheap recall
improvements:

- **PT stemming** in the tokenizer (`snowballstemmer` "portuguese") so
  `acende / acenda / acendendo` collapse to one stem — kills most morphology
  misses in Portuguese.
- **A small hand-kept synonym expansion map** for domain jargon
  (`café → cafeteira`, `gelado|frio → temperatura`, `escuro → luz`, …), applied
  to the query before scoring.

Tool docs are assembled automatically from the trait catalog's `examples`, so
the curated phrasings live in one place.

**Embeddings (dense retrieval)** are deferred (call it Phase B): worthwhile only
if BM25 + stemming + synonyms still misses free-form phrasing in practice
("faz um cafézinho" → `coffee_maker` `turn_on`). When added, it slots in behind
the same `/resolve` interface as an optional second ranker (RRF or
`max(bm25_norm, cosine)`), gated by `RESOLVE_RANKER=bm25|hybrid` with a lazy
model load, so the default stack stays free of a `torch`/`sentence-transformers`
(or embedding-API) dependency. See `README` note on why the trait descriptor is
written to be embeddable (human text + examples per trait).

Also note: for device *targeting* the orchestrator has a stronger structured
signal than any ranker — the device's declared traits ARE the allowed command
set, so once the device is resolved (fuzzy match on nickname + room over a
per-home list of ~13) the action menu is a membership set, not a search.

## Build order

1. **BFF** — `devices.capabilities` JSON column; `DeviceTraitTemplates` (type →
   traits) used by `DataSeeder` + as the create/update fallback only; subscribe
   `.../capabilities` and persist the announced descriptor; generic
   `DeviceActions` (verb → state-change, validated against the stored
   descriptor; `409` when absent, after the `503` link check); `capabilities` in
   device + snapshot DTOs; optional override on create/update; drop
   `SWITCHABLE`/`OPENABLE`/the per-type switch.
2. **device-sim** — its own trait-templates table; publish retained
   `.../capabilities` on first sight of a device; keep the existing per-type
   default-state logic (now a sibling of the trait templates).
3. **Home MCP** — generic verb tools; `home://devices` carries
   `capabilities` + `actions`; `/tools` + catalog from trait-catalog ∩ installed.
4. **Agents** — `environment` / `security` forward `{device_id, action, value}`;
   verb capabilities; drop the fine `SKILLS` enumeration.
5. **Orchestrator** — `{device_id, action, value}` from `interpret`; validate
   against `home://devices[*].actions`; generic `EXPECTED_EFFECTS`; prompt lists
   per-device actions.
6. **`/resolve`** — PT stemming + synonym expansion; docs from trait examples.
   (Embeddings/hybrid ranker: Phase B, not this pass.)

Each layer green in Docker before the next; full E2E at the end plus a new
scenario ("desliga a cafeteira").

## Supersedes

- `11-*` "Orchestrator changes": the `Capability` Literal and per-capability
  `EXPECTED_EFFECTS` described there are replaced by `{device_id, action, value}`
  + a per-verb effect map.
- `06-mcp.spec.md` tool list: the type-scoped tools are replaced by generic
  verbs driven by the announced descriptor.
