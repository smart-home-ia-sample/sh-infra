# Smart Home AI

Projeto de portfólio: uma casa inteligente simulada controlada por agentes de
IA, demonstrando LangChain, LangGraph, BFA, A2A, MCP e AG-UI. Sem hardware
real, sem relação com sistemas legais/contratuais.

Especificação completa em [`spec/`](spec/).

> **Nota (2026-08-29):** o histórico de fases abaixo é registro de época e usa
> os caminhos do monorepo antigo (`shared/python/`, `mcp/home/`, `agents/`).
> Hoje cada serviço é um repo `sh-*` independente e a descoberta é
> **catalog-first** (o BFA puxa os descritores de `CATALOG_SOURCES`, sem
> auto-registro nem heartbeat) — ver [`spec/13`](spec/13-catalog-first-discovery.spec.md)
> e [`docs/architecture.md`](docs/architecture.md) para o estado atual.

## Status

- **Fase 1 (concluída):** monorepo, BFA (registro, descoberta, roteamento por
  capability, health/ready, correlation_id, logs estruturados) e biblioteca
  compartilhada (`shared/python/smart_home_common`) com cliente de
  self-registration reutilizável pelos agentes/MCP. O BFA resolve o host do
  `endpoint` de cada serviço pelo IP de origem da própria chamada de
  registro (com suporte a `X-Forwarded-For` para um eventual proxy futuro);
  o serviço só informa `port`/`path`/`use_ssl`, nunca a URL inteira.
- **Fase 2 (concluída):** Home MCP (`mcp/home/`) usando o SDK oficial do
  protocolo MCP (`mcp`, transporte streamable-http): estado simulado da casa,
  12 tools, 6 resources (`home://*`) e 4 prompts (`leave_home`, `bedtime`,
  `energy_optimization`, `home_status`), auto-registrado no BFA.
- **Fase 3 (concluída):** agentes **Security**, **Environment** e **Energy**
  (`agents/`), cada um autorregistrado no BFA, com lógica de domínio que
  chama o Home MCP via `smart_home_common.HomeMcpClient` (endpoint resolvido
  dinamicamente pelo BFA).
- **Fase 4 (concluída):** protocolo **A2A oficial** (`a2a-sdk`, não um REST
  customizado) — cada agente expõe um **Agent Card** real em
  `/.well-known/agent-card.json` (skills, capabilities) e um endpoint
  JSON-RPC (`smart_home_common.mount_a2a`/`IntentAgentExecutor`); chamadas
  entre agentes usam `smart_home_common.AgentClient` (descobre o alvo via
  BFA, resolve o Agent Card real, envia a mensagem via SDK oficial). Os 4
  fluxos do spec estão implementados de verdade: Orchestrator→Security
  (`secure_home`), Orchestrator→Environment (`switch_off_nonessential`),
  Orchestrator→Energy (`inspect_consumption`) e Security→Energy
  (`identify_critical_devices`) — inclusive com falha parcial explícita
  (se a Energy cair, o Security ainda tranca a porta/arma o alarme e expõe
  `critical_devices_error` em vez de travar). Um **Orchestrator mínimo**
  (`agents/orchestrator/`, sem LLM) expunha `POST /run {"scenario": "leave_home"}`.
- **Fase 5 (concluída):** Orchestrator real com **LangGraph** + **LangChain**
  (`agents/orchestrator/app/graph/`): grafo
  `START → interpret → discover → plan → dispatch → collect → validate →
  (recovery_explain | final)` com branch condicional real em `validate`.
  `POST /converse {"message": "..."}` interpreta os 5 comandos em linguagem
  natural do MVP (`.spec/00-overview.spec.md`) e despacha os agentes certos
  via A2A. `LLM_PROVIDER=mock` (default, determinístico, sem rede — usado em
  testes/CI) ou `LLM_PROVIDER=google` (Gemini real via `langchain-google-genai`,
  precisa de `GEMINI_API_KEY`). `validate` confere o efeito real das mutações
  contra o que o MCP retornou (nunca confia na alegação do LLM); qualquer
  falha (agente indisponível, comando não reconhecido) cai no branch
  `recovery_explain` com mensagem explícita. Environment ganhou a skill
  `check_environment` para o cenário "status da casa".
- **Fase 6 (concluída):** protocolo **AG-UI oficial** (`ag-ui-protocol` no
  backend, `@ag-ui/client` no frontend) e o **frontend** (`front/`, React +
  Vite + TypeScript) com as 3 telas do spec:
  - **Dashboard**: polling em `GET /home-status` (Orchestrator, sem passar
    pelo LLM) — segurança, ambiente, energia, eventos recentes.
  - **Assistant**: chat que envia a mensagem via `POST /agui/run`
    (SSE real) e mostra a resposta final conforme os eventos
    `TEXT_MESSAGE_*` chegam.
  - **Agent Activity**: timeline ao vivo dos mesmos eventos AG-UI —
    `StepStarted/Finished` por nó do LangGraph e `ToolCallStart/Result`
    por chamada A2A — sem expor raciocínio interno do LLM.
  `agents/orchestrator/app/agui.py` traduz a execução real do grafo
  (`graph.astream(..., stream_mode="updates")`) em eventos AG-UI de
  verdade. Validado de ponta a ponta com o Gemini real via Chrome:
  Dashboard, Assistant e Agent Activity todos refletindo a mesma execução
  em tempo real.
- **Fase 7 (concluída):** simulação de eventos de fundo no Home MCP
  (`mcp/home/app/simulation.py`) — a cada `SIMULATION_INTERVAL_SECONDS`
  (default `20`, desligável via `SIMULATION_ENABLED=false`) dispara um
  evento aleatório real (`motion_detected`, `door_opened`,
  `temperature_changed`, `device_on`/`device_off`), muta o estado de
  verdade e grava em `home://events` — visível no Dashboard sem nenhuma
  mudança no frontend. Iniciado via o hook `lifespan` do `MCPServer`
  (nenhum serviço/endpoint novo).
- **Fase 8 (concluída):** suíte de testes **E2E** (`tests/e2e/`) que sobe o
  `docker compose` real, roda os 5 cenários MVP contra o sistema completo e
  3 testes de falha (BFA indisponível, Home MCP indisponível, device
  inválido ponta a ponta), e derruba tudo ao final. Documentação
  consolidada em [`docs/architecture.md`](docs/architecture.md) e
  [`docs/testing.md`](docs/testing.md).

### Redesign em andamento (`.spec/11-persistence-auth-mqtt.spec.md`)

- **Orquestrador dinâmico (concluído — build-order 4):** os tipos `Literal` de
  device/cômodo viraram `str`. O nó `interpret` busca a topologia viva uma vez
  (`home://devices` + `home://rooms`, best effort) e a propaga: o prompt de
  classificação recebe o inventário real de ids por cômodo, o mock resolve
  `(cômodo, tipo)` → slug (fallback para o slug legado `f"{cômodo}_{tipo}"`), e
  um id inventado pelo LLM é rebaixado para `unknown`. `bedtime` e o default de
  `turn_off_light` resolvem os devices por `(tipo + cômodo)` a partir de
  `state["topology"]`. O `discover` usa `/resolve/agents` do BFA com fallback
  para `?capability=` exato. Novo nó `chitchat` logo após o `interpret` (aresta
  condicional) responde saudações direto, sem `discover/plan/dispatch/collect/
  validate` — `"olá"` deixa de ser modelado como falha de interpretação.
- **Fase 4 (concluída):** **religamento do Home MCP + identidade do usuário.**
  O MCP virou **adaptador fino sobre o BFF** (`mcp/home/app/bff_client.py`):
  `SEED_DEVICES`/`simulation.py`/`state.py` deletados; topologia via
  `GET /api/homes/{default}/devices|rooms`, estado e os recursos
  `home://security|environment|energy|events` derivados de
  `GET /api/home-status/snapshot`, mutações via `POST /api/devices/{id}/command`
  (que publica MQTT e bloqueia no eco). **Dashboard e Assistant agora
  compartilham a mesma simulação.** Ponte de `slug`: coluna `devices.slug` no
  BFF (semeada com as 13 chaves legadas), o MCP mapeia `slug ↔ UUID`,
  orchestrator e E2E não mudam. **O JWT do usuário viaja a cadeia inteira** no
  header `Authorization: Bearer` (BFF → orchestrator → A2A → agente → MCP →
  BFF), re-validado a cada operação; plumbing em `smart_home_common.auth`
  (contextvar + `AuthTokenMiddleware`). Entradas sem token (`/converse`,
  startup) fazem self-login como demo (`ServiceLogin`). `/home-status` do
  orchestrator removido.
- **Fase 3 (concluída):** **BFA** — registry por serviço lógico → lista de
  instâncias (por endpoint), cada uma com `last_seen` e status derivado do TTL
  do heartbeat (`REGISTRATION_TTL_SECONDS`, default 45s; despejo após
  `REGISTRATION_GRACE_SECONDS`, default 300s). Shape plano mantido em
  `GET /agents`, `?capability=`, `GET /mcp` (consumidores intactos);
  `GET /agents/{name}` mostra todas as instâncias. Lookup e `/resolve` escolhem
  instância saudável por **round-robin**. **`POST /resolve` / `/resolve/agents`
  / `/resolve/tools`** `(query, top_k=3, threshold=0.3)` — `rank_bm25.BM25Okapi`
  sobre o catálogo registrado (1 doc por agente, 1 por tool), tokenizador tira
  acento + stopwords PT/EN; score = **cobertura da query** (0..1), então
  `threshold` = "cobrir X% da query" e `"olá tudo bem"` → `[]`. Agentes e MCP
  mandam o catálogo (skills / tools com tags + exemplos PT) no payload de
  registro; o Home MCP expõe `GET /tools`. Sem circuit breaker, sem probe
  ativo. O `discover` do orchestrator consome `/resolve/agents` (com fallback
  exato) — ver "Orquestrador dinâmico" acima.
- **Fase 2 (em andamento):** **MQTT** — `mosquitto` (com credencial, não
  anônimo) + **`device-sim/`** (Python/Paho, reator MQTT puro: inventa default
  por tipo na primeira vez que ouve falar de um device, ecoa `.../state`
  retido, LWT `home/simulator/status`). O **BFF** ganhou cliente MQTT (Paho
  Java), a rota **`POST /api/devices/{id}/command`** `{action, value?}` —
  ação semântica validada contra o tipo, publica `.../set`, **bloqueia no eco
  `.../state`** (~3s → 504), devolve o estado confirmado (é a rota que os
  tools do MCP vão chamar), `GET /api/devices/{id}/state`, e
  **`GET /api/home-status` como stream SSE** servido do read-model do BFF:
  **snapshot completo no connect, depois só deltas** — um evento `device`
  pequeno (~320 B) por dispositivo que muda (`{deviceId, state, rollups, ...}`)
  em vez do snapshot inteiro (~5 KB); o front funde os deltas num `HomeStatus`
  completo em memória. Rollups triviais de alarme/portas/consumo/ativos.
  `GET /api/home-status/snapshot` para o one-shot. O **Dashboard** trocou polling
  por esse stream e ganhou **botões** por dispositivo (ligar/desligar, abrir/
  fechar, trancar, armar, ± brilho/temperatura) que chamam
  `POST /api/devices/{id}/command`; o estado atualiza sozinho pelo SSE. O
  `/home-status` do orchestrator continua existindo (testes o usam), só não é
  mais acessível via `/api`. O **religamento do Home MCP foi adiado pro fim**
  (junto com a auth de agentes/tools).
- **Fase 1 (concluída):** **BFF** (`bff/`, Spring Boot + H2 embedded) — passa a
  ser a única coisa que o browser acessa: serve o build do React, autentica via
  **JWT** (um usuário demo, `demo`/`demo`), persiste **casa / cômodos /
  dispositivos** (13 devices e 5 cômodos semeados, byte-a-byte iguais ao
  `SEED_DEVICES` de hoje), expõe CRUD em `/api/homes|rooms|devices`, e faz
  passthrough de SSE pro orchestrator em `/api/agui/run` e `/api/home-status`
  (proxy streaming próprio, `JDK HttpClient` + `StreamingResponseBody`). O
  `front/` deixou de ter Dockerfile e URL fixa do orchestrator (`/api`
  relativo); ganhou tela de login. Serviços internos seguem com portas
  publicadas nesta fase. Testado ponta a ponta no `docker compose`
  (login → CRUD → `/api/home-status` → SSE do `/api/agui/run`).

## Rodando os serviços

```
docker compose up --build
```

**BFA** (`http://localhost:8000`)
- `GET /health`, `GET /ready`
- `POST /agents/register`, `POST /mcp/register`
- `GET /agents?capability=lock_door` — roteamento por capability
- `GET /mcp` — lista servidores MCP registrados

**Home MCP** (`http://localhost:8100`, protocolo MCP via streamable-http em `/mcp`)
- `GET /health`, `GET /ready`
- Conectar com um cliente MCP (ex. `mcp.client.streamable_http.streamable_http_client`)
  para listar/chamar tools, ler resources (`home://rooms`, `home://devices`,
  `home://security`, `home://environment`, `home://energy`, `home://events`)
  e prompts.

**Agentes A2A** — Security (`:8200`), Environment (`:8300`), Energy (`:8400`)
- `GET /health`, `GET /ready`
- `GET /.well-known/agent-card.json` — Agent Card real (skills/capabilities)
- Endpoint A2A (JSON-RPC) na raiz — usar `smart_home_common.a2a_client.call_agent`
  ou qualquer cliente A2A oficial. Skills: Security (`secure_home`,
  `lock_door`, `unlock_door`, `arm_alarm`, `disarm_alarm`, `check_security`),
  Environment (`switch_off_nonessential`, `turn_light_on`, `turn_light_off`,
  `set_light_brightness`, `set_temperature`, `turn_ac_on`, `turn_ac_off`,
  `open_curtain`, `close_curtain`), Energy (`inspect_consumption`,
  `identify_critical_devices`).

**Orchestrator** (`http://localhost:8500`, sem A2A de entrada — REST simples)
- `GET /health`, `GET /ready`
- `POST /converse {"message": "Vou sair de casa.", "correlation_id": "..."}` —
  comandos em PT-BR: apagar luz de um cômodo, ir dormir, sair de casa,
  consumo de energia, status da casa. Resposta:
  `{"status": "ok"|"error", "final_response": "...", "observations": {...}}`.
- `POST /agui/run` — endpoint AG-UI (recebe `RunAgentInput`, retorna SSE
  com eventos reais do protocolo). Usado pelo frontend.
- `GET /home-status` — snapshot rápido (sem LLM) usado pelo Dashboard.

**Frontend** — servido pelo BFF em `http://localhost:8080`. Login: `demo` / `demo`.
Desenvolvimento local sem Docker: `cd front && npm install && npm run dev`
(com o BFF rodando; o Vite faz proxy de `/api` e `/auth`).

## Testes

Serviços Python — unitário/integração por serviço (rápido, sem Docker):

```
cd bfa && pip install -r requirements-dev.txt && pytest
cd mcp/home && pip install -r requirements-dev.txt && pytest
cd agents/security && pip install -r requirements-dev.txt && pytest
cd agents/environment && pip install -r requirements-dev.txt && pytest
cd agents/energy && pip install -r requirements-dev.txt && pytest
cd agents/orchestrator && pip install -r requirements-dev.txt && pytest
cd shared/python && pip install -e . pytest 'uvicorn[standard]' fastapi && pytest
```

BFF (Java) — 40 testes (JUnit 5 + Mockito), H2 em memória:

```
cd bff && ./mvnw test
# ou, sem Java/Maven local:
docker run --rm -v "$PWD/bff:/build" -w /build maven:3.9-eclipse-temurin-21 mvn -B test
```

device-sim (Python) — 6 testes:

```
cd device-sim && pip install -r requirements-dev.txt && pytest
```

E2E (sobe o `docker compose` real, precisa de Docker disponível):

```
cd tests/e2e && pip install -r requirements.txt && pytest
```

Detalhes de cobertura e rastreabilidade em [`docs/testing.md`](docs/testing.md);
visão geral da arquitetura em [`docs/architecture.md`](docs/architecture.md).
