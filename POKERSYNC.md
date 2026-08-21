# PokerSync — Documento Mestre

> **Organize. Estude. Evolua.**

Este arquivo substitui e unifica os cinco documentos anteriores —
`AI_CONTEXT.md`, `PRODUCT.md`, `DECISIONS.md`, `BACKLOG.md` e
`CHANGELOG.md` (todos de 2026-07-30). Nada foi descartado: a visão, os
princípios e as 8 decisões originais estão preservados na íntegra abaixo.
O que mudou é que **cada item de backlog agora carrega o estado real**,
conferido em 2026-08-21 contra o código dos repositórios e contra o banco
de produção — os documentos originais listavam 60+ itens como pendentes,
e a maioria já está no ar.

Repositório do produto: <https://github.com/gsimonetto/pokersync>

**Índice**
1. [O produto](#1-o-produto)
2. [Princípios](#2-princípios)
3. [O que o PokerSync não é](#3-o-que-o-pokersync-não-é)
4. [Arquitetura real](#4-arquitetura-real)
5. [Decisões de produto](#5-decisões-de-produto)
6. [Estado real dos módulos](#6-estado-real-dos-módulos)
7. [Backlog vivo — só o que falta](#7-backlog-vivo--só-o-que-falta)
8. [Lacunas entre motor e produto](#8-lacunas-entre-motor-e-produto)
9. [Changelog](#9-changelog)
10. [Regras de evolução e orientação para IA](#10-regras-de-evolução-e-orientação-para-ia)

---

## 1. O produto

PokerSync é uma plataforma que centraliza as ferramentas de estudo,
gestão e evolução do jogador de poker.

A visão inicial era **manter tudo em um só lugar**. A visão atual é
maior: **ajudar o jogador a evoluir continuamente**, conectando dados,
estudo, revisão, comportamento e performance numa experiência única. A
mesma base atende o jogador individual e, no modo Time, coaches e
gestores.

**Slogan:** PokerSync — Organize. Estude. Evolua.

**Módulos:** Modo Treino · Gestor de Banca · Construtor de Ranges e
Árvores (era "Construtor de Hands") · Review de Mãos · Player Evolution
· Plataforma para Times · Hub de Evolução.

> O Hub de Evolução (XP, missões, ranking, temporadas) não existia nos
> documentos originais — nasceu durante a construção e hoje é um dos sete
> módulos no ar.

## 2. Princípios

1. **Jogador em primeiro lugar.**
2. **Ensinar > apenas informar.**
3. **Simplicidade antes de complexidade** — menos funcionalidades, melhor
   resolvidas.
4. **Módulos conversam entre si** — integração é prioridade, não enfeite.
5. **A experiência diária importa** — o produto é usado antes, durante e
   depois da sessão.
6. **Dados devem gerar ação e aprendizado**, não só relatório.
7. **Acompanhar a evolução, não apenas registrar o histórico.**
8. **Nada isolado** — nenhuma funcionalidade sem propósito claro dentro
   de um módulo ou de uma integração.

## 3. O que o PokerSync não é

O produto deve ser percebido como um **sistema de evolução do jogador**,
e não como:

- um tracker;
- um gestor de banca;
- um repositório de mãos;
- um substituto de solver.

## 4. Arquitetura real

Três repositórios e um banco. Isso não estava documentado em lugar
nenhum e é o contexto que mais falta a quem (ou o que) chega no projeto.

| Onde | O que é | Stack |
| --- | --- | --- |
| [`gsimonetto/pokersync`](https://github.com/gsimonetto/pokersync) | **O produto.** Todas as telas e serviços. | Next.js (App Router) + Supabase |
| [`gsimonetto/pokersync-solver`](https://github.com/gsimonetto/pokersync-solver) | **Motor GTO próprio.** CFR + ICM, jobs em lote, API de disparo. | Python, FastAPI, Railway |
| [`gsimonetto/pokersync-road-map`](https://github.com/gsimonetto/pokersync-road-map) | Roadmap editável (board visual). | TanStack Start / Lovable |
| Supabase `PokerSync` | Banco, RLS, ~65 tabelas e ~90 RPCs. Fonte de verdade de tudo. | Postgres 17 |

**Convenções do produto** (seguir ao implementar):

- Toda leitura/escrita passa por um serviço em `lib/services/*.ts` — as
  telas não falam com o Supabase direto.
- Lógica de poker fica em `lib/poker/*.ts`; lógica de banca em
  `lib/bankroll/*.ts`.
- Regra de negócio pesada e agregação moram em **RPC no Postgres**
  (`team_dashboard`, `get_player_insights`, `register_training`,
  `detect_user_leaks`…), não no cliente.
- O motor é assíncrono por natureza: o produto **nunca resolve um spot em
  tempo real**. Jobs gravam spots na tabela `drills`; as telas consomem
  esse estoque.

**Separação motor ↔ produto** (decisão registrada no repo do solver): o
motor vive fora do repositório do produto para que uma mudança no CFR
nunca quebre o deploy da plataforma.

## 5. Decisões de produto

As oito decisões originais valem integralmente. As quatro seguintes
(009–012) documentam decisões que já foram tomadas na prática — estão
implementadas no código — mas nunca tinham sido escritas.

### 001 — O produto não é apenas um organizador de dados
**Decisão:** o PokerSync deve usar dados para ajudar o jogador a evoluir.
**Motivo:** a visão evoluiu de centralização para evolução contínua.

### 002 — Integração entre módulos é prioridade
**Decisão:** os módulos compartilham contexto quando isso gera valor.
**Exemplo:** mãos revisadas geram sugestões de treino.

### 003 — Review não depende de solver na V1
**Decisão:** o Review de Mãos funciona sem GTO Wizard, PIO ou qualquer
solver externo.
**Motivo:** reduzir a barreira de entrada e entregar valor desde o início.
**Estado:** mantida. O veredito objetivo do Revisor vem da aderência às
ranges do próprio jogador; o motor próprio é reforço opcional, não
requisito.

### 004 — Entrada manual deve existir
**Decisão:** o usuário nunca será obrigado a instalar agente desktop.

### 005 — Agente desktop é caminho futuro
**Decisão:** o agente é alternativa de automação, não dependência.

### 006 — Gestor de Banca deve evoluir para performance
**Decisão:** o módulo vai além de saldo e resultado — hábitos, metas,
sessões, evolução.

### 007 — Times são uma extensão natural
**Decisão:** a arquitetura permite jogadores, coaches, métricas e
performance de times sobre a mesma base.

### 008 — Slogan
**Decisão:** PokerSync — Organize. Estude. Evolua.

### 009 — Motor GTO próprio, em repositório separado *(registrada agora)*
**Decisão:** o PokerSync tem motor próprio (CFR com desconto + ICM), num
repositório à parte, com deploy independente.
**Motivo:** a decisão 003 fala sobre *dependência de solver externo* —
não impede capacidade interna. Ter o motor em casa dá controle sobre
formato, custo e convergência; mantê-lo fora do repo do produto impede
que uma mudança no motor derrube a plataforma.

### 010 — Nada de solve em tempo real *(registrada agora)*
**Decisão:** spots são resolvidos em lote, offline, e gravados na tabela
`drills`. A API do motor só dispara e monitora jobs.
**Motivo:** um spot de RFI/Jam leva milhões de iterações; resolver sob
demanda tornaria a tela refém do motor. Resolução sob demanda só será
reconsiderada quando o Hand Replayer precisar.

### 011 — Convergência sempre carimbada no dado *(registrada agora)*
**Decisão:** toda linha gravada pelo motor leva `engine_version` e
`exploitability`.
**Motivo:** foi a ausência desse log que tornou o diagnóstico do
pipeline antigo (TexasSolver) tão lento. Não se repete.

### 012 — Estrutura mínima aceita: ICM primeiro *(registrada agora)*
**Decisão:** os spots pré-flop são resolvidos com ICM (torneio), não em
ChipEV puro.
**Motivo:** é o contexto real do público-alvo. ChipEV entra depois, se
houver demanda de cash — e exige mudar o cálculo de utilidade terminal
do motor, não é um flag.

## 6. Estado real dos módulos

Legenda: **✅ no ar** · **🟡 parcial** · **⬜ não iniciado** ·
**🔒 pronto no código, bloqueado por falta de dados**

### 6.1 Gestor de Banca — `/banca`

| Item (backlog original) | Estado | Evidência |
| --- | :-: | --- |
| Registro manual de sessão | ✅ | `bankroll_sessions`, 73 sessões reais |
| Fechamento de sessão com resumo | ✅ | `mood`, `tilt`, `diary_note` |
| Diário pós-sessão | ✅ | `updateSessionDiary()` |
| Metas de volume | ✅ | `bankroll_goals` |
| Metas de estudo | ✅ | `bankroll_goals` + `bankroll_study_logs` |
| Resumo automático da sessão | ✅ | KPIs + `bankroll_session_net()` |
| Dashboard de evolução | ✅ | página de 1.918 linhas, heatmap de volume |
| Fluxo de caixa (depósitos/saques) | ✅ | `bankroll_transactions`: depósito, saque, caixinha |
| Métrica de tempo / winrate horário | ✅ | KPIs R$/hora **e** bb/hora com intervalo de confiança |
| Histórico expandido com filtros | 🟡 | "Ver todas" existe, com busca livre que casa data, formato e local; faltam filtros dedicados (seletor de período/formato) |
| **Edição de sessão (lápis)** | ⬜ | só existem `addSession`, `deleteSession` e `updateSessionDiary` — editar ainda exige excluir e refazer |
| Formulário dinâmico por formato | 🟡 | campos já se adaptam (big blind só em cash), mas "Reentradas" não vira "Rebuy/Add-on" em cash |

**Além do backlog** (não estava previsto e está no ar): rake e rakeback,
multi-moeda, staking/backing com markup, BRM com limites por formato,
alertas de banca, anotações no gráfico.

### 6.2 Review de Mãos — `/revisor`

| Item | Estado | Evidência |
| --- | :-: | --- |
| Captura rápida (<30s) | ✅ | `revisor-nova-mao.tsx` |
| Colar hand history | ✅ | `hand_reviews.hand_history` + parser próprio |
| Upload de print | ✅ | `hand_review_images` (com limite por trigger) |
| Etiquetas (3-bet, ICM, PKO, hero call) | ✅ | `hand_review_tags` + `hand_tags` (38 colunas de stats) |
| Fila de revisão | ✅ | `hand_reviews.status` + `revisor-fila.tsx` |
| Histórico de revisões | ✅ | `user_review_summary()` |
| Perguntas guiadas | ✅ | `hand_review_answers` |
| Registro de aprendizado | ✅ | `hand_reviews.learning_note` |
| Sugestão de drills | 🔒 | 12 sugestões cadastradas e 3 RPCs prontas — **sem estoque de drills pra apontar** (ver §8) |

**Além do backlog:** replay de mão com atalhos de teclado, avaliação por
rua (`hand_review_street_evals`), aderência à range com histórico,
compartilhar mão com o time e thread de coach, sessões de mãos.

### 6.3 Modo Treino — `/treino`

| Item | Estado | Evidência |
| --- | :-: | --- |
| Drills personalizados | 🟡 | filtros de posição/stack/tipo funcionam, mas só há 8 spots (RFI/Jam pré-flop) |
| Sugestões baseadas em reviews | 🔒 | `suggest_drills_for_user()` pronta, bloqueada por estoque e por um bug de mapeamento de rua (§8) |
| Sugestões baseadas em performance | ✅ | o leak de formato da Banca vira sugestão de stack curto no treino |

**Além do backlog:** XP, combo de acertos, missões e veredito na mesa;
drill de ranges próprias (`range-drill.tsx`).

### 6.4 Construtor — `/ranges`

O "Construtor de Hands" do documento original virou **Construtor de
Ranges e Árvores**, mais amplo do que o previsto.

| Item | Estado | Evidência |
| --- | :-: | --- |
| Construção de spots | ✅ | editor de ranges, editor de árvores (`strategy_trees`), versionamento |
| Integração com Review | ✅ | importar mão do Revisor, aderência de range |
| Integração com Treino | ✅ | range salva vira drill; biblioteca do motor no construtor |

**Além do backlog:** comparador de ranges, calculadora de equity,
analisador de board (single e multi, com filtro de textura),
biblioteca de time, journal de decisões.

### 6.5 Player Evolution — `/performance`

| Item | Estado |
| --- | :-: |
| ROI · ABI · Volume · Lucro | ✅ |
| Evolução temporal | ✅ (`get_player_timeline`) |
| Tendências | ✅ (`get_period_comparison`) |
| Insights acionáveis | ✅ (`get_player_insights`, `get_skill_breakdown`) |
| Banco de dados unificado de performance | ✅ (`player_stats`, `player_preflop_stats`, `player_postflop_stats`) |

### 6.6 Plataforma para Times — `/time`

| Item | Estado | Evidência |
| --- | :-: | --- |
| Cadastro de time | ✅ | `create_team()` |
| Cadastro/convite de jogadores | ✅ | `team_invites`, `accept_team_invite()` |
| Papéis e permissões | ✅ | RLS + `is_team_admin/manager`, aprovação de membro |
| Dashboard do coach | ✅ | `team_dashboard()`, funil estilo Trello, calendário |
| Metas e acompanhamento | ✅ | `team_player_goals` + progresso |
| Métricas consolidadas | ✅ | financeiro, atividade, leaks por jogador |
| Alertas | ✅ | `team_alerts` + `run_team_alerts()` |
| Score de evolução | 🟡 | existe XP/nível e leaks por jogador; não existe um "score" único consolidado |
| JSON padronizado / sincronização | 🟡 | o schema existe (`hand_sync_devices`, `hand_sync_batches`, `agent_version`, `raw_payload`) |
| **Agente desktop** | ⬜ | nenhum código o consome; zero dispositivos registrados — o schema espera um agente que ainda não existe |

### 6.7 Hub de Evolução — `/hub`

XP com fontes múltiplas, níveis, missões diárias (32 cadastradas),
combo de acertos, ranking com pódio e temporadas com prêmio,
notificações. ✅ no ar — não estava em nenhum documento.

## 7. Backlog vivo — só o que falta

Ordenado por relação valor/esforço. Os itens 1–4 fecham o loop central
do produto ("dados geram ação"), que hoje está aberto.

| # | Item | Módulo | Nota |
| :-: | --- | --- | --- |
| 1 | Corrigir o mapa de ruas e o validador de `gto_nodes` do drill-service | Treino ↔ Review | ~1h; destrava o botão "treinar isso" nos leaks |
| 2 | Gerar estoque de drills: push/fold ICM e stacks 10/20/30/50bb | Treino | motor, job e endpoint já existem — falta disparar |
| 3 | Edição de sessão sem excluir e refazer | Banca | único item do backlog original de Banca ainda intocado |
| 4 | "Ver todo o histórico" com filtro por data | Banca | |
| 5 | Formulário dinâmico completo (Rebuy/Add-on em cash) | Banca | |
| 6 | Pipeline de pós-flop ponta a ponta (job → contrato → UI) | Treino ↔ Review | projeto grande; destrava 8 das 12 sugestões de leak |
| 7 | Score de evolução consolidado do jogador | Times / Hub | há matéria-prima (XP, leaks, aderência, ROI) |
| 8 | Agente desktop | Times | schema pronto, agente inexistente; decisão 005 mantém como futuro |
| 9 | Ações rápidas nos leaks: "criar fila de revisão" além de "treinar spot" | Cross-module | metade já existe |
| 10 | Sincronizar o board do roadmap com a realidade | Roadmap | todos os itens estão marcados "Planejado", inclusive os 7 módulos no ar |

**Ideias futuras** (mantidas dos documentos originais): integrações
externas de dados; integrações opcionais com solvers de terceiros —
hoje parcialmente superada pelo motor próprio; mais automações de
performance.

## 8. Lacunas entre motor e produto

Análise completa em `ANALISE_GAPS.md` (repo do solver, branch
`claude/pokersync-repo-analysis-ev6hnb`). Resumo:

O motor já resolve mais do que o produto consome, e o produto já tem
telas e RPCs esperando dados que nenhum job gerou. A tabela `drills`
inteira tem **8 linhas**, todas RFI/Jam de pré-flop.

- **Push/Fold ICM**: motor, job e endpoint prontos e conectados; nunca
  disparado. A sugestão de leak de maior prioridade não tem drill.
- **Pós-flop river/turn**: motor validado (0,39% de exploitability no
  river), sem job, sem endpoint, sem UI. Dois ativos prontos e órfãos no
  banco: `flop_subsets` (184 flops ponderados) e `preflop_ranges` (29
  ranges nomeadas), que nenhum dos repositórios lê.
- **Bug de idempotência**: 3 de 4 jobs perderam 2,5 milhões de iterações
  no `insert` final por `spot_id` duplicado — falta `upsert`.
- **Bug de mapeamento**: o drill-service documenta que a base é toda
  Flop/Turn/River e exclui "preflop"; hoje é o inverso exato, e o botão
  "treinar isso" do card de leaks nunca aparece.
- **Multiway e multi-tamanho**: motores prontos, sem caminho de ingestão
  e sem leitura do formato novo no frontend.

## 9. Changelog

### 2026-08-21 — Consolidação da documentação
- Cinco documentos (`AI_CONTEXT`, `PRODUCT`, `DECISIONS`, `BACKLOG`,
  `CHANGELOG`) unificados neste arquivo, com o estado real de cada item
  conferido contra código e banco.
- Registradas as decisões 009 a 012, que já vigoravam na prática.
- Publicada a análise de lacunas entre motor e produto.

### 2026-08-19 a 2026-08-21 — Onda de UX e integração
Modo Treino RFI/Jam consumindo o motor próprio; XP real ligado ao treino;
ranking e temporadas no Hub; modo Time completo (funil, calendário,
assistente do coach, alertas); construtor de ranges com árvores, equity e
análise de board; header, modais e margens padronizados em todo o app;
staking, rake/rakeback, multi-moeda e bb/hora na Banca.

### 2026-08-07 a 2026-08-18 — Migração e construção
Produto migrado para Next.js (App Router) e Supabase; módulos de Banca,
Revisor, Hub, Performance e Ranges construídos sobre RLS e RPCs.
*(405 commits no repositório do produto até 2026-08-21.)*

### 2026-07-30 — Documentação inicial
Criada a visão oficial do produto; definido o slogan; registrados os
princípios; roadmap organizado por módulos; decisões 001–008
registradas; backlog inicial criado; definidas a captura manual como
alternativa ao agente desktop e a independência de solver na V1.

## 10. Regras de evolução e orientação para IA

### Regra do roadmap
Toda funcionalidade nova deve:
1. fortalecer um módulo existente; **ou**
2. criar uma integração útil entre módulos; **ou**
3. contribuir claramente para a evolução do jogador ou do time.

O PokerSync não deve virar um conjunto de ferramentas isoladas.

### Antes de implementar
1. A funcionalidade fortalece a visão do produto?
2. Existe módulo relacionado — e o item já não está feito? **Conferir a
   §6 antes de abrir tarefa:** os documentos antigos listavam como
   pendente muita coisa que já está no ar.
3. Há integração com outro módulo que deveria vir junto?
4. Está duplicando algo sem benefício claro?
5. A UX é simples o bastante para um jogador em sessão?

### Ao escrever código
- Serviço em `lib/services`, nunca Supabase direto na tela.
- Agregação pesada vira RPC no Postgres.
- Nada de resolver spot em tempo real (decisão 010).
- Dado gerado pelo motor carrega `engine_version` e `exploitability`
  (decisão 011).
- Antes de mexer no `cfr_core.py`, rodar `tests/kuhn_poker.py`.

### Ao atualizar este documento
Manter os quatro pilares na mesma ordem — visão, decisões, estado real,
backlog — e registrar toda decisão nova numerada, mesmo (e principalmente)
quando ela já tiver sido tomada na prática pelo código.
