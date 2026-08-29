# Testes

Dois níveis: unitário/integração por serviço (rápido, sem Docker — Python via
`pytest`, BFF via `mvn test`), e E2E (lento, sobe o `docker compose` real).
Ver [`architecture.md`](architecture.md) para o desenho do sistema sendo testado.

## Unitário / integração (por serviço)

Cada serviço é seu próprio repo (`sh-*`), lado a lado no workspace:

```
cd ../sh-bfa && pip install -r requirements-dev.txt && pytest   # catálogo (pull) + BM25 /resolve
cd ../sh-mcp && pip install -r requirements-dev.txt && pytest
cd ../sh-agent-security && pip install -r requirements-dev.txt && pytest
cd ../sh-agent-environment && pip install -r requirements-dev.txt && pytest
cd ../sh-agent-energy && pip install -r requirements-dev.txt && pytest
cd ../sh-orchestrator && pip install -r requirements-dev.txt && pytest
cd ../sh-common && pip install -e . pytest 'uvicorn[standard]' fastapi && pytest
```

Cada serviço testa sua própria lógica de domínio isoladamente (mocks para
BFA/MCP/agentes remotos). `sh-common` testa a biblioteca comum,
incluindo o roundtrip A2A real (cliente + servidor no mesmo processo,
sem containers). O Home MCP (`sh-mcp`) hoje é um adaptador sobre o BFF —
os testes de tools/resources usam um `bff_client` falso com uma casa em
memória.

### BFF (`sh-bff`, Java)

```
cd ../sh-bff && ./mvnw test
# sem Java/Maven local:
docker run --rm -v "$PWD/../sh-bff:/build" -w /build maven:3.9-eclipse-temurin-21 mvn -B test
```

46 testes (JUnit 5 + Mockito + Spring Test), H2 em memória, MQTT desligado
(`bff.mqtt.enabled=false` no profile de teste):

- **`JwtServiceTest`** — emissão/verificação HS256: roundtrip, token expirado,
  adulterado, assinado com outro segredo, lixo, segredo curto demais.
- **`HomeServiceTest`** (Mockito puro) — ramos do serviço difíceis de exercitar
  por HTTP: acesso a casa de outro usuário → 404; primeira casa forçada a
  `default`; trocar a casa default limpa a anterior; slug/apelido duplicado →
  409; apagar cômodo com dispositivos → 409; cômodo de outra casa no
  create/update de dispositivo → 400; renomear dispositivo para o próprio
  apelido é permitido.
- **`DeviceActionsTest`** (puro) — tradução do verbo semântico (`turn_on`,
  `set_temperature`, `open`, `lock`, …) para o `changes` do MQTT, validado
  contra o **descriptor de capacidades anunciado** do dispositivo (o verbo está
  em algum `trait.commands`? o valor está no range de `trait.params`?);
  descriptor nulo → `NotProvisionedException` (409).
- **`BffIntegrationTest`** (`@SpringBootTest` + MockMvc, `@Transactional` com
  rollback por teste) — login (senha/usuário errado, campo faltando), guarda
  JWT em `/api/**`, seed (Casa Modelo / 5 cômodos / 13 devices), CRUD de
  casa/cômodo/dispositivo, conflitos (slug/apelido duplicado, apagar cômodo
  com devices), tipo de device inválido → 400, escopo por usuário, seed
  idempotente, `POST /api/devices/{id}/command` (503 com MQTT off, 404 device
  desconhecido, 400 verbo fora do descriptor, 409 device sem `capabilities`
  ainda), descriptor anunciado é servido em `capabilities` no device/snapshot,
  override de `capabilities` no create, `GET /api/home-status/snapshot`
  (topologia completa com `state: null` quando MQTT off, rollups zerados),
  `GET /api/home-status` abre conexão SSE, guarda de auth nos dois, SPA servida
  com fallback de `index.html`, `/actuator/health` público, `/api/agui/run`
  responde 401 antes de qualquer chamada ao orchestrator.

### device-sim (`device-sim/`, Python)

```
cd ../sh-device-sim && python -m pytest    # ou via container python:3.11-slim
```

8 testes da lógica pura (`DeviceWorld` + `capability_descriptor`): default por
tipo, invenção na primeira vez, merge de `changes`, evento aleatório de fundo,
descriptor de traits por tipo (anunciado retido em `.../capabilities`).

## E2E (`e2e/`)

Sobe o stack a partir dos checkouts irmãos
(`-f docker-compose.yml -f docker-compose.build.yml -f docker-compose.local.yml
up --build -d`), espera todos ficarem saudáveis (`GET /health`, e
`GET /actuator/health` no BFF), faz um **warm-up** (dispara um `/converse`
até dar `ok` — a cadeia A2A→MCP→BFF→MQTT→eco é lenta no primeiro request a
frio), roda os testes contra o sistema real, e derruba tudo ao final
(mesmo se algum teste falhar).

Sem Python no host, dá pra rodar a suíte de dentro de um container com o
socket do Docker montado. Como o BFA devolve URLs internas do compose
(`http://environment:8300`), o container helper precisa entrar na rede do
stack (`--network sh-infra_default`) para os testes que chamam agentes via
A2A:

```
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /caminho/para/o/workspace:/work -w /work/sh-infra \
  --network sh-infra_default \
  -e E2E_HOST=host.docker.internal \
  --add-host host.docker.internal:host-gateway \
  python:3.11 bash -c 'pip install -q -r e2e/requirements.txt && pytest e2e/'
# (o container também precisa do binário `docker` + plugin `compose`)
```

```
cd e2e
pip install -r requirements.txt
pytest
```

Requer Docker disponível e rodando. Força `LLM_PROVIDER=mock` e
`SIMULATION_ENABLED=false` no ambiente do compose (independente de
qualquer `.env` local) para manter os testes determinísticos.

### O que a suíte E2E cobre

- **`test_scenarios.py`** — os 5 comandos do MVP (`.spec/00-overview.spec.md`)
  via `POST /converse` contra o sistema real: apagar luz, ir dormir, sair
  de casa, consumo de energia, status da casa; + "desliga a cafeteira"
  (eletrodoméstico controlado pelo verbo genérico `turn_off`).
- **`test_failures.py`** — falhas que só fazem sentido com containers de
  verdade: BFA indisponível, Home MCP indisponível, device inválido
  ponta a ponta.

### O que a suíte E2E **não** repete

Timeout/retry de transporte e checagens de nível de domínio já têm
cobertura unitária/de integração e não são reimplementados no nível E2E:

| Caso de falha exigido pelo spec       | Onde está testado                                              |
|----------------------------------------|-----------------------------------------------------------------|
| Ranking BM25 / catálogo vazio          | `sh-bfa/tests/test_routes.py`, `test_catalog.py`               |
| Timeout / retry de transporte A2A       | `sh-common/tests/test_a2a_roundtrip.py`                        |
| Device inválido (nível de domínio)      | `sh-mcp/tests/test_tools.py`                                   |
| Agente indisponível (nível do grafo)    | `sh-orchestrator/tests/test_graph.py`                          |
| BFA indisponível (sistema real)          | `e2e/test_failures.py::test_bfa_unavailable_degrades_explicitly` |
| MCP indisponível (sistema real)          | `e2e/test_failures.py::test_mcp_unavailable_degrades_explicitly` |
| Device inválido (sistema real, via A2A)  | `e2e/test_failures.py::test_invalid_device_returns_explicit_error` |

### Nota sobre timing no `test_failures.py`

`test_bfa_unavailable_degrades_explicitly` para e sobe o container `bfa` de
propósito. Não há mais heartbeat de re-registro: ao voltar, o BFA re-puxa o
catálogo de `CATALOG_SOURCES` sozinho (ver
[`architecture.md`](architecture.md#catálogo-do-bfa-catalog-first-spec13)).
Para não deixar o teste seguinte dependente de um sleep fixo, ele faz
polling em `POST /resolve/agents` até a capability voltar a ser resolvida
(`_wait_for_capability`), em vez de assumir um tempo fixo de propagação.
