# pokersync-solver

Motor CFR próprio do PokerSync (Discounted CFR + ICM), separado do
repositório principal (`pokersync-next`) por decisão de arquitetura —
evita que uma mudança no motor quebre o deploy do produto.

## O que tem aqui

- `engine/` — núcleo validado: CFR genérico (`cfr_core.py`), equity
  pré-flop com blockers (`equity.py`, `equity_blockers.py`,
  `equity_final.py`), classes de mão (`hand_classes.py`), ICM
  (`icm.py`), solver de shove/fold com e sem ICM (`pushfold.py`,
  `pushfold_icm.py`), motor pós-flop — river heads-up
  (`postflop.py`, ver status abaixo).
- `jobs/` — scripts de geração em lote, sobem resultado pro Supabase.
- `api/` — API mínima (FastAPI) só pra disparar/monitorar jobs.
- `tests/` — validação do núcleo CFR contra Kuhn Poker (solução
  analítica conhecida, rodar sempre que mexer em `cfr_core.py`) e do
  motor de river contra a fórmula fechada de MDF
  (`tests/postflop_river.py`).

## Setup local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # preencher SUPABASE_SERVICE_ROLE_KEY e SOLVER_API_KEY
```

Validar o núcleo antes de qualquer coisa:
```bash
python3 tests/kuhn_poker.py
```
Deve mostrar exploitability próxima de 0 (na casa de poucos mbb/hand).

Rodar a API local:
```bash
uvicorn api.main:app --reload
```

## ⚠️ Pendente antes do primeiro job real: migration `solver_jobs`

A API grava status de job nessa tabela — ela **não existe ainda** no
Supabase do PokerSync. Rodar manualmente no dashboard (nunca de forma
automática, seguindo o mesmo cuidado do pipeline principal com
alterações de schema):

```sql
create table if not exists public.solver_jobs (
  id uuid primary key,
  job_type text not null,
  status text not null default 'running',
  params jsonb,
  progress text,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
```

Também vale confirmar o schema real de `drills` (via
`information_schema.columns`) antes do primeiro upload — o mapeamento
em `jobs/solve_pushfold_batch.py::build_drill_row()` foi escrito
seguindo a convenção do pipeline anterior (TexasSolver), mas não foi
validado coluna a coluna contra a tabela real ainda.

## Deploy (Railway)

1. Criar novo projeto no Railway, apontando pra este repo.
2. Railway detecta o `Dockerfile` automaticamente (`railway.json` já
   configurado).
3. Setar as env vars (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `SOLVER_API_KEY`) no painel do Railway.
4. Deploy. A URL gerada é o que o Next.js vai chamar.

## Uso pelo Next.js (pokersync-next)

```ts
await fetch(`${SOLVER_API_URL}/jobs/pushfold`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": process.env.SOLVER_API_KEY!,
  },
  body: JSON.stringify({
    stacks_bb: [10, 15, 20],
    other_stacks: [40, 25, 18, 12],
    payouts: [500, 300, 200],
  }),
});
```

## Status do motor (o que já foi validado)

- ✅ Núcleo CFR (Discounted CFR + regret matching) — validado contra
  Kuhn Poker, exploitability ~1 mbb/hand.
- ✅ Motor de equity pré-flop — validado contra números públicos
  conhecidos (AA vs KK, etc), com blockers reais.
- ✅ ICM (Malmuth-Harville) — validado via propriedades matemáticas
  (conservação de dinheiro, monotonicidade, caso degenerado HU).
- ✅ Shove/fold heads-up com ICM — funcionando ponta a ponta.
- ✅ RFI/jam heads-up com ICM — **SB vs BB e BTN vs BB validados**
  (exploitability rigorosa, best-response exato — ver
  `engine/rfi_jam.py::compute_exploitability`), 3 stacks (15/25/40bb)
  já em produção no Supabase, 60bb pendente de upload.
- ⏳ CO vs BTN e UTG vs BB — bloqueados como matchup heads-up (2
  jogadores) — a aproximação de "dead money" só é precisa com no
  máximo 1 jogador pulado (BTN vs BB). **Resolvido via motor
  multiway** (`engine/multiway_rfi.py`), ver abaixo.
- ✅/⏳ **Motor multiway (N jogadores)** — arquitetura pronta.
  Validado estruturalmente: bate com o motor heads-up no caso
  degenerado de 2 seats, mãos claras (AA/AKo/KK/QQ) convergem
  corretamente perto de 100%. Achei e corrigi 1 bug real durante essa
  validação (o abridor estava usando o mecanismo de decisão errado —
  fold-ou-jam em vez de fold-ou-abrir). **Não tem o mesmo nível de
  validação de exploitability rigorosa que o motor heads-up** (best
  response completo pra N jogadores não foi implementado — é mais
  complexo que o caso de 2 jogadores). Mãos de fronteira podem
  oscilar bastante entre rodadas (mesmo fenômeno já documentado no
  heads-up, não é bug). É lento por natureza (equity multiway via
  Monte Carlo) — pensado pra rodar OFFLINE, no seu PC, por
  horas/dias/semanas, não no meu sandbox. Ver
  `run_offline_multiway.py` (tem checkpoint automático).
- ⏳ 3-bet "de verdade" (não all-in) pré-flop — não iniciado. A árvore
  de RFI atual trata qualquer resposta a um raise como shove (correto
  pra stack curto/médio, não serve pra stack profundo).
- ✅/⏳ **Pós-flop — river heads-up** (`engine/postflop.py`) — primeira
  rua pós-flop real: dado um board fixo (5 cartas), range vs range
  (por classe de mão) e tamanhos de aposta configuráveis, resolve a
  árvore check/bet -> fold/call/raise(all-in) -> fold/call via CFR
  exato (full-enumeration, sem amostragem, igual `pushfold.py`). Força
  de mão calculada com o avaliador real (`treys`) direto no board —
  sem Monte Carlo, já que no river o board está 100% definido.
  **Validado contra fórmula fechada de teoria dos jogos**: no caso
  clássico "range polarizada (valor puro + blefe puro) vs
  bluff-catcher puro", a frequência de call do bluff-catcher batida
  pelo CFR reproduz `MDF = pote/(pote+aposta)` com <1% de erro (ver
  `tests/postflop_river.py`). Limitação conhecida (documentada,
  mesmo espírito da aproximação já aceita em `hand_classes.py` pro
  pré-flop): decisões são por classe de mão, não por combo — dois
  combos da mesma classe (ex AhKh vs AsKs) têm a mesma frequência de
  bet/call, sem discriminação de blocker dentro da classe. Raise é
  limitado a um único tamanho (all-in), mesma simplificação do
  pré-flop pra 3-bet/4-bet.
- ⏳ Turn e flop — não iniciado. Diferente do river, essas ruas têm
  carta por vir, então exigem nó de chance (turn/river runouts) sobre
  a árvore de apostas já construída — provavelmente via amostragem
  (MCCFR), no mesmo espírito da amostragem já usada no motor multiway
  pra equity. Próximo passo natural depois do river.
- ⏳ Squeeze (multiway) — arquitetura pronta (mesmo motor multiway
  acima), não validado num spot de squeeze de verdade ainda (só no
  caso degenerado de 2 jogadores).

## Rodando o motor multiway offline (squeeze, CO vs BTN, UTG vs BB)

Pensado pra rodar no SEU computador por horas/dias/semanas, não no
sandbox de desenvolvimento. `run_offline_multiway.py` salva
checkpoint automático — se o PC desligar ou travar, roda de novo e
ele continua de onde parou, sem perder progresso.

```bash
python3 run_offline_multiway.py
```

Ajuste `MATCHUP_CONFIG` no topo do arquivo pro spot desejado (nomes
dos seats, quem tem blind, stacks, payouts). O exemplo padrão já vem
configurado pra um squeeze de 3 jogadores.

**Antes de confiar no resultado:** mãos claramente fortes/fracas (AA,
KK, trash em posição ruim) devem convergir de forma ESTÁVEL entre
rodadas diferentes — se ficarem balançando muito mesmo depois de
milhões de iterações, isso indica bug de verdade, não é
comportamento esperado. Mãos de fronteira (EV quase empatado entre
as opções) PODEM oscilar mesmo bem convergidas — isso é esperado.
