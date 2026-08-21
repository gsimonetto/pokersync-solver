# Análise de lacunas — PokerSync (produto + motor)

Levantamento de **2026-08-21**, cruzando os três repositórios com o
estado real do banco de produção (Supabase `PokerSync`,
`olgziujndtlvxegcnaoq`):

| Repo | O que é | Estado |
| --- | --- | --- |
| `gsimonetto/pokersync` | produto (Next.js App Router + Supabase) | 7 módulos live, 155 arquivos |
| `gsimonetto/pokersync-solver` | motor CFR próprio (este repo) | 4.6k linhas, núcleo validado |
| `gsimonetto/pokersync-road-map` | roadmap editável (Lovable/TanStack) | seed inicial, desatualizado |

> O documento mestre do projeto (visão, decisões, estado dos módulos e
> backlog vivo) fica em `POKERSYNC.md`, no repositório do produto. Este
> arquivo cobre só a fronteira entre motor e produto.

## Resumo em uma frase

**O motor já resolve mais do que o produto consome, e o produto já tem
telas e RPCs esperando dados que ninguém gerou.** Quase tudo que falta
é *cola de pipeline* — job, ingestão, contrato de JSON — não matemática
nova.

## Mapa do estado real, capacidade por capacidade

| Capacidade | Motor | Job | API | Dados no Supabase | Frontend |
| --- | :-: | :-: | :-: | :-: | :-: |
| RFI/Jam SB e BTN vs BB (1 tamanho) | ✅ | ✅ | ✅ | ✅ 8 linhas (15/25/40/60bb) | ✅ |
| RFI/Jam multi-tamanho (`open_sizes`) | ✅ | ✅ | ✅ | ❌ 0 linhas | ❌ não lê `by_size` |
| RFI multiway (CO/HJ/MP/UTG+1/UTG vs BB) | ✅ offline | ❌ | ❌ | ❌ 0 linhas | ⚠️ UI lista 8 posições, 6 sempre vazias |
| Push/Fold ICM | ✅ | ✅ | ✅ | ❌ 0 linhas | ❌ nenhum componente lê `action='pushfold'` |
| Pós-flop river/turn | ✅ validado | ❌ | ❌ | ❌ 0 linhas | ❌ |
| Pós-flop flop | ⏳ 14% exploit. | ❌ | ❌ | ❌ | ❌ |
| ChipEV (sem ICM) | ❌ motor é ICM-only | — | — | — | ⚠️ chip já existe riscado na UI |
| 3-bet de verdade (não all-in) | ❌ | — | — | — | — |

O banco inteiro de drills tem **8 linhas**, todas `action='rfi_jam'`,
`street='Preflop'`. Nada mais.

---

## 1. Ganho alto, esforço baixo (fazer primeiro)

### 1.1 Job de push/fold nunca rodou — mas está inteiro

`engine/pushfold_icm.py`, `jobs/solve_pushfold_batch.py` e o endpoint
`POST /jobs/pushfold` (`api/main.py:45`) existem e estão conectados.
`solver_jobs` só tem jobs `rfi_jam_icm_batch` — **nenhum job de
push/fold foi disparado**, e a sugestão de leak *"Push/Fold ICM na
bolha"* (a de maior prioridade em `hand_review_drill_suggestions`) não
tem um único drill pra apontar.

Antes de rodar, corrigir dois detalhes em
`jobs/solve_pushfold_batch.py`:

- `spot_id` recebe `uuid4().hex[:8]` no fim
  (`jobs/solve_pushfold_batch.py:105`) — cada execução cria linha nova
  em vez de atualizar a existente; em duas rodadas o mesmo spot aparece
  duplicado no treino.
- `client.table("drills").insert(...)` sem `on_conflict`.

### 1.2 Bug real de idempotência (com evidência em produção)

3 dos 4 jobs de RFI/Jam **falharam** com:

```
duplicate key value violates unique constraint "drills_pkey"
Key (spot_id)=(rfi_jam_btn_vs_bb_60bb) already exists.
```

O job resolve os 2.5M de iterações inteiros (progresso chegou a `2/2`)
e só então perde tudo no `insert`. Trocar por
`upsert(results, on_conflict="spot_id")` em
`jobs/solve_rfi_jam_batch.py:213` e no batch de push/fold: re-rodar um
spot passa a ser barato, que é exatamente o que se quer quando se está
subindo iterações pra melhorar convergência.

### 1.3 O mapa de ruas do produto está invertido em relação ao banco

`lib/services/drill-service.ts:118` (produto) documenta:

> `"preflop"` fica de fora de propósito: não existe nenhum drill de
> preflop na base hoje (confirmado — todos são Flop/Turn/River).

Hoje é o **inverso exato**: a base é 100% Preflop e não tem uma linha
de Flop/Turn/River. Consequência em cadeia:

- `resolveSuggestionStreet()` devolve `null` pra todo leak de preflop;
- `suggestionHasDrills()` → `false` → o botão "treinar isso" do
  `components/revisor/leaks-card.tsx:49` **nunca aparece**;
- `fetchDrillBatchBySuggestion()` retorna `[]` pras 4 sugestões de
  preflop.

Some-se a isso que `isValidGtoNode()`
(`lib/services/drill-service.ts:40`) exige `{actions, strategy}` — o
formato que o job de push/fold grava — enquanto as 8 linhas existentes
usam `{sb_open, bb_jam, sb_call_jam}`. Ou seja: **`fetchDrillBatch()`
filtraria 100% do estoque atual**, e nenhum arquivo do produto chama
essa função hoje (só `fetchDrillFacets`). É um caminho morto esperando
o estoque certo — que o item 1.1 já produz no formato certo.

### 1.4 Stacks que a UI promete e o banco não tem

`components/drill/rfi-jam-drill.tsx` oferece
`[10, 15, 20, 25, 30, 40, 50, 60]`; existem só 15/25/40/60. Os chips de
10/20/30/50 aparecem riscados. É um `POST /jobs/rfi_jam` com
`stacks_bb: [10, 20, 30, 50]` — nenhum código novo, ~4 spots × 2
matchups de máquina.

---

## 2. O maior buraco: pós-flop não tem pipeline nenhum

`engine/postflop.py` (773 linhas) resolve river e turn com
exploitability rigorosa medida (0,39% do pote no river). E não existe:

- `jobs/solve_postflop_batch.py`;
- endpoint na API;
- contrato de `gto_nodes` pra árvore de múltiplas ruas (o formato
  compacto atual só cobre 3 fases pré-flop fixas);
- qualquer UI de drill pós-flop — `components/drill/poker-table.tsx`
  existe e é usado só pelo drill de RFI/Jam.

**Ativo pronto e órfão:** a tabela `flop_subsets` já tem **184 flops
com peso normalizado** (`sum(weight) = 1.0000`), classificados por
`texture`/`pairing`/`high_bucket`/`connectivity`, criada em 2026-08-14 —
e **nenhum dos dois repositórios a referencia**. É exatamente o input de
seleção de board que um job de pós-flop precisa.

**Idem `preflop_ranges`:** 29 ranges nomeadas (`BTN_3BET_NON_JAM`,
`BTN_FLAT_CALL`, `BB_CALL`, `UTG_RFI`…), cobrindo justamente as árvores
de 3-bet não-all-in que o motor ainda não modela. Nenhum arquivo do
produto lê essa tabela. Serve como range de entrada (range vs range) pro
`PostflopSolver` sem precisar inventar ranges do zero.

Impacto de destravar isso: **8 das 12 sugestões de leak** apontam pra
flop/turn/river (`cbet` no flop, `bluffcatch`/`thin_value`/`hero_call`
no river, `pot_control`/`barrel` no turn). Hoje nenhuma delas tem
estoque, e as RPCs `suggest_drills_for_user`, `suggest_drills_for_leak`
e `assign_team_drill` (coach mandando drill pro jogador) estão todas
paradas pelo mesmo motivo.

---

## 3. Multiway: resultado offline não tem caminho de volta

`run_offline_all_positions.py` roda CO/HJ/MP/UTG+1/UTG vs BB e salva
`resultado_<posição>_<stack>bb.pkl`. Falta:

- script de ingestão `.pkl → linha de drills` (hoje o README diz "me
  avisa quais arquivos existem" — é um passo manual sem código);
- `MATCHUPS` em `jobs/solve_rfi_jam_batch.py:34` só aceita `sb_vs_bb` e
  `btn_vs_bb`, e levanta `ValueError` pro resto — proposital, mas
  precisa de um caminho paralelo pro motor multiway;
- decisão registrada sobre **qual métrica de convergência carimbar**: o
  multiway não tem best-response de N jogadores, então ou se implementa,
  ou se sobe com validação estrutural + marca de "beta" visível na UI.

Enquanto isso, `ALL_POSITIONS` no produto
(`lib/services/rfi-jam-service.ts:35`) lista as 8 posições e 6 delas
nunca terão spot — a UI já trata isso riscando o chip, então o custo hoje
é de expectativa, não de bug.

---

## 4. Multi-tamanho: falta a última milha dos dois lados

O motor aceita `open_sizes=[2.0, 2.5, 3.0]` e o job já grava numa linha
separada com sufixo `_msize` e formato `{sizes, by_size}`
(`jobs/solve_rfi_jam_batch.py:87`). Falta:

1. decidir os tamanhos e rodar (nenhuma linha `_msize` no banco);
2. `lib/services/rfi-jam-service.ts` só entende o formato antigo —
   `getRfiJamSpot()` lê `nodes.sb_open` direto e quebraria num spot
   multi-tamanho;
3. UI: escolher/mostrar o tamanho no drill.

---

## 5. Robustez do serviço de jobs (o que dói quando escalar)

- **Jobs longos em `BackgroundTasks` do FastAPI**: 2.5M iterações num
  processo web do Railway. Se o container reinicia, o job fica
  `running` pra sempre — não há heartbeat, timeout nem retomada. O
  motor offline tem checkpoint; o job em produção não.
- **Sem `GET /jobs` (lista) e sem cancelamento** — só dá pra consultar
  um job se você guardou o UUID.
- **Erro gravado cru**: o `str(e)` do PostgREST vira um dict Python
  dentro da coluna `error` (visível nos 3 jobs que falharam).
- **`.env.example` não existe** — o README manda `cp .env.example .env`
  no primeiro passo do setup.
- **Sem CI**: `tests/` são scripts com `print`, não asserts de pytest.
  Nada garante que `tests/kuhn_poker.py` roda antes de um merge — num
  repo cuja premissa é "o motor é confiável porque é validado", isso é
  a lacuna mais barata de fechar (um workflow + `assert` nos 4 testes
  rápidos: Kuhn, river, turn, multisize).

---

## 6. Pontas soltas menores (verificadas)

- `drill_results` (0 linhas) não é referenciada por nenhum arquivo do
  produto — quem registra treino é `training_sessions` (97 linhas) via
  RPC `register_training`. Tabela legada; confirmar e dropar.
- `drills_backup_20260805` continua no schema público.
- O tipo "ChipEV" na UI depende de um motor sem ICM que não existe —
  `RfiJamSolver` é ICM-only por construção. Custo real: mexer no cálculo
  de utilidade terminal, não é só um flag.

---

## 7. Roadmap está desatualizado a ponto de enganar

`src/lib/pokersync-seed.ts` cria **todos** os itens com
`status: "todo"` (o helper `mk()` não recebe status em nenhuma chamada),
incluindo os 7 módulos que já estão live no produto — Banca, Revisor,
Treino, Hub, Time, Performance e Construtor de Ranges. O changelog tem
uma entrada só (2026-07-30).

Além disso, **não existe nenhum módulo "Motor GTO próprio" no
roadmap** — o trabalho de maior risco técnico do projeto (CFR, ICM,
pós-flop, multiway) é invisível no board que deveria representar o
projeto.

---

## Ordem sugerida

| # | Item | Esforço | Destrava |
| --- | --- | --- | --- |
| 1 | `upsert(on_conflict="spot_id")` nos dois jobs + `spot_id` determinístico no push/fold | ~1h | re-rodar spot sem perder job de horas |
| 2 | Corrigir mapa de ruas + validador de `gto_nodes` no `drill-service` | ~1h | loop Revisor → Treino (leaks-card) |
| 3 | Rodar job de push/fold ICM (endpoint já existe) | máquina | 1ª sugestão de leak com estoque real |
| 4 | Rodar RFI/Jam nos stacks 10/20/30/50 | máquina | 8 → 16 spots, UI sem chip riscado |
| 5 | `.env.example` + CI com os 4 testes rápidos | ~2h | proteção do núcleo validado |
| 6 | `jobs/solve_postflop_batch.py` + endpoint + contrato de `gto_nodes` (usando `flop_subsets` e `preflop_ranges`) | grande | 8 das 12 sugestões de leak, coach → drill |
| 7 | UI de drill pós-flop | grande | idem |
| 8 | Ingestão dos `.pkl` multiway + decisão de métrica | médio | 6 posições faltantes |
| 9 | Multi-tamanho ponta a ponta (rodar + ler `by_size` + UI) | médio | profundidade do treino pré-flop |
| 10 | Sincronizar o roadmap (status reais + módulo do Motor) | ~1h | o board voltar a valer como fonte de verdade |

Os itens 1–5 são um dia de trabalho somados e mudam o produto de
"8 spots" pra "loop de leak → treino funcionando". O 6 é o projeto
grande de verdade.
