# sh-infra

The full **Smart Home AI** stack: `docker compose`, the MQTT broker config, the
end-to-end suite, and the architecture specs. Each service is its own repo.

## Repos

| repo | stack | port | role |
|------|-------|------|------|
| `sh-frontend` | React + Vite | — | Dashboard + AG-UI assistant SPA (built, served by the BFF) |
| `sh-bff` | Java / Spring Boot | 8080 | edge gateway: SPA + JWT auth + home/device persistence (H2/Postgres) + MQTT + proxy to the orchestrator |
| `sh-bfa` | Python / FastAPI | 8000 | service registry (heartbeat TTL, round-robin) + BM25 `/resolve` |
| `sh-orchestrator` | Python / LangGraph | 8500 | interpret → discover → dispatch (A2A) → validate → AG-UI |
| `sh-agent-security` | Python / A2A | 8200 | `secure_home`, `check_security`, `lock`/`unlock`/`arm`/`disarm` |
| `sh-agent-environment` | Python / A2A | 8300 | `check_environment`, `switch_off_nonessential`, `turn_on`/`turn_off`/`set_*`/`open`/`close` |
| `sh-agent-energy` | Python / A2A | 8400 | `inspect_consumption`, `identify_critical_devices` |
| `sh-mcp` | Python / MCP | 8100 | thin adapter over the BFF: generic verb tools + `home://*` resources |
| `sh-device-sim` | Python / paho-mqtt | — | simulated devices; announces each device's capability descriptor over MQTT |
| `sh-common` | Python lib | — | shared logging / auth / A2A / MCP-client / registration — installed from its repo at a version tag (`v0.1.0`), NOT cloned |

Container images publish to **GitHub Packages** (`ghcr.io/<owner>/sh-*`) from each
repo's CI on `main`. `sh-common` publishes its wheel as a GitHub Release asset on
a `vX.Y.Z` tag (GitHub Packages has no PyPI registry).

## Branches

| branch | `docker-compose.yml` | needs |
|--------|----------------------|-------|
| **main** | pulls `ghcr.io/$GHCR_OWNER/sh-*:$SH_TAG` | just this repo + `GHCR_OWNER` in `.env` |
| **dev**  | builds every service from `../sh-<name>` | all service repos cloned as siblings (`./bootstrap.sh`) |

`docker-compose.build.yml` (the build variant) is kept on both branches for
ad-hoc use: `docker compose -f docker-compose.build.yml up --build`.

## Run it — main (published images)

```sh
cp .env.example .env          # set GHCR_OWNER; LLM_PROVIDER; FRONT_DIST_URL
docker compose up -d
# http://localhost:8080   (demo / demo)
```

## Run it — dev (build from source)

```sh
git checkout dev
ORG=<your-org> ./bootstrap.sh   # clones the service repos as siblings
cp .env.example .env
docker compose up --build -d
```

Sibling layout after `bootstrap.sh`:

```
smart-home/
  sh-infra/   <- here
  sh-bff/  sh-bfa/  sh-orchestrator/
  sh-agent-{security,environment,energy}/
  sh-mcp/  sh-device-sim/
```

## End-to-end tests

```sh
cd e2e
pip install -r requirements.txt
pytest            # forces LLM_PROVIDER=mock, brings the stack up/down itself
```

Needs Docker. `e2e/conftest.py` runs `docker compose` from this repo root.

## Docs

- `ARCHITECTURE.md` — system overview
- `spec/` — numbered design specs (`11-persistence-auth-mqtt`, `12-device-capabilities` are the latest)
- `docs/` — architecture + testing notes
