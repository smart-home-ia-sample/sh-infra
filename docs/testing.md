# Testes

Dois níveis: unitário/integração por serviço (rápido, sem Docker — Python via
`pytest`, BFF via `mvn test`), e E2E (lento, sobe o `docker compose` real).
Ver [`architecture.md`](architecture.md) para o desenho do sistema sendo testado.

## Unitário / integração (por serviço)

```
cd bfa && pip install -r requirements-dev.txt && pytest   # registry TTL/round-robin + BM25 /resolve
cd mcp/home && pip install -r requirements-dev.txt && pytest
cd agents/security && pip install -r requirements-dev.txt && pytest
cd agents/environment && pip install -r requirements-dev.txt && pytest
cd agents/energy && pip install -r requirements-dev.txt && pytest
cd agents/orchestrator && pip install -r requirements-dev.txt && pytest
cd shared/python && pip install -e . pytest 'uvicorn[standard]' fastapi && pytest
```

Cada serviço testa sua própria lógica de domínio isoladamente (mocks para
BFA/MCP/agentes remotos). `shared/python` testa a biblioteca comum,
incluindo o roundtrip A2A real (cliente + servidor no mesmo processo,
sem containers). O Home MCP (`mcp/home`) hoje é um adaptador sobre o BFF —
os testes de tools/resources usam um `bff_client` falso com uma casa em
memória.

### BFF (`bff/`, Java)

```
cd bff && ./mvnw test
# sem Java/Maven local:
docker run --rm -v "$PWD/bff:/build" -w /build maven:3.9-eclipse-temurin-21 mvn -B test
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
cd device-sim && python -m pytest    # ou via container python:3.11-slim
```

8 testes da lógica pura (`DeviceWorld` + `capability_descriptor`): default por
tipo, invenção na primeira vez, merge de `changes`, evento aleatório de fundo,
descriptor de traits por tipo (anunciado retido em `.../capabilities`).

## E2E (`tests/e2e/`)

Sobe o stack via `docker compose up --build -d`, espera todos ficarem
saudáveis (`GET /health`, e `GET /actuator/health` no BFF), faz um
**warm-up** (dispara um `/converse` até dar `ok` — a cadeia
A2A→MCP→BFF→MQTT→eco é lenta no primeiro request a frio), roda os testes
contra o sistema real, e derruba tudo ao final (mesmo se algum teste
falhar).

Sem Python no host, dá pra rodar a suíte de dentro de um container com o
socket do Docker montado:

```
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/repo -w /repo/tests/e2e \
  -e E2E_HOST=host.docker.internal -e COMPOSE_PROJECT_NAME=sh-ia \
  --add-host host.docker.internal:host-gateway \
  python:3.11 bash -c 'pip install -q -r requirements.txt && pytest'
# (o container também precisa do binário `docker` + plugin `compose`)
```

```
cd tests/e2e
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

Duplicate registration e timeout/retry de transporte já têm cobertura
unitária/de integração e não são reimplementados no nível E2E:

| Caso de falha exigido pelo spec       | Onde está testado                                              |
|----------------------------------------|-----------------------------------------------------------------|
| Registro duplicado                     | `bfa/tests/test_routes.py`                                      |
| Timeout / retry de transporte A2A       | `shared/python/tests/test_a2a_roundtrip.py`                     |
| Device inválido (nível de domínio)      | `mcp/home/tests/test_tools.py`                                  |
| Agente indisponível (nível do grafo)    | `agents/orchestrator/tests/test_graph.py`                       |
| BFA indisponível (sistema real)          | `tests/e2e/test_failures.py::test_bfa_unavailable_degrades_explicitly` |
| MCP indisponível (sistema real)          | `tests/e2e/test_failures.py::test_mcp_unavailable_degrades_explicitly` |
| Device inválido (sistema real, via A2A)  | `tests/e2e/test_failures.py::test_invalid_device_returns_explicit_error` |

### Nota sobre timing no `test_failures.py`

O BFA mantém o registro apenas em memória; `test_bfa_unavailable_degrades_explicitly`
para e sobe o container `bfa` de propósito. Os demais serviços se
recuperam sozinhos via o heartbeat de re-registro (ver
[`architecture.md`](architecture.md#robustez-do-registro-bfa)), mas para
não deixar o teste seguinte dependente de um sleep fixo, ele faz polling
em `GET /agents?capability=...` até a capability voltar a aparecer
(`_wait_for_capability`), em vez de assumir um tempo fixo de propagação.
