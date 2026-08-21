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
  motor pós-flop contra a fórmula fechada de MDF, no river
  (`tests/postflop_river.py`), no turn (`tests/postflop_turn.py`) e
  via exploitability/best-response exato no river
  (`tests/postflop_exploitability.py`).

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

## ✅ Migration `solver_jobs` — feita

A tabela `public.solver_jobs` já existe no Supabase do PokerSync
(criada manualmente no dashboard, conferida via
`information_schema.columns`: `id`, `job_type`, `status`, `params`,
`progress`, `error`, `created_at`, `updated_at` — bate com o que
`api/main.py` e `jobs/solve_pushfold_batch.py` usam).

✅ Schema real de `drills` também já foi conferido (via `list_tables`)
contra o mapeamento em
`jobs/solve_pushfold_batch.py::build_drill_row()` — bate coluna a
coluna, nenhum ajuste necessário.

Ambas as pendências que bloqueavam o primeiro job real em produção
estão resolvidas.

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
- ✅ **Pós-flop — river e turn heads-up** (`engine/postflop.py`,
  classe `PostflopSolver`) — dado um board (3, 4 ou 5 cartas), range
  vs range (por classe de mão) e tamanhos de aposta configuráveis,
  resolve a árvore check/bet -> fold/call/raise(all-in) -> fold/call
  via CFR exato entre classes (full-enumeration, sem amostragem,
  igual `pushfold.py`). Força de mão via avaliador real (`treys`)
  direto no board.
  - **River** (board de 5 cartas, sem carta por vir): 100% exato, sem
    nenhuma amostragem em lugar nenhum.
  - **Turn** (board de 4 cartas, falta o river): quando a rua termina
    sem ninguém all-in, o motor sorteia a carta do river (nó de
    chance via MCCFR, mesmo espírito da amostragem já usada em
    `rfi_jam.py`) e segue a árvore pro river; quando alguém fica
    all-in, calcula a equity EXATA fazendo a média sobre as 46 cartas
    possíveis do river (sem amostragem — rápido o suficiente pra não
    precisar).
  - `RiverSolver` continua existindo como alias de `PostflopSolver`
    (compatibilidade — um board de 5 cartas nunca dispara nó de
    chance, então o comportamento é idêntico ao da v1).
  - **Validado contra fórmula fechada de teoria dos jogos** (MDF =
    pote/(pote+aposta)) tanto no river quanto no turn all-in, com
    <1% e ~2-3% de erro respectivamente (o turn tem mais ruído por
    causa da amostragem de chance — ver `tests/postflop_river.py` e
    `tests/postflop_turn.py`). O cálculo de equity all-in no turn
    (`runout_equity`) também foi cross-validado byte-a-byte contra
    uma reimplementação independente (diff exato = 0).
  - **Exploitability rigorosa via best-response exato** (só pro river
    por enquanto — `PostflopSolver.compute_exploitability()`, mesmo
    padrão de `tests/kuhn_poker.py` e
    `engine/rfi_jam.py::compute_exploitability`, mas cobrindo a árvore
    inteira, não só uma decisão isolada como o teste de MDF): testado
    no mesmo spot polarizado-vs-bluffcatcher, exploitability ficou em
    0,39% do pote — ver `tests/postflop_exploitability.py`. Detalhe de
    implementação: a convenção de contabilidade do motor faz
    `br_oop + br_ip` somar sempre `pot0` num equilíbrio perfeito (não
    0 como em Kuhn Poker), então `compute_exploitability()` já
    devolve o valor com essa constante subtraída.
  - Limitações conhecidas (documentadas): (1) decisões são por classe
    de mão, não por combo — sem discriminação de blocker dentro da
    classe (mesmo espírito da aproximação já aceita em
    `hand_classes.py` pro pré-flop); (2) raise limitado a um único
    tamanho (all-in), mesma simplificação do pré-flop pra 3-bet/4-bet;
    (3) a carta sorteada nos nós de chance ignora blockers com as mãos
    específicas dos jogadores (só evita colidir com o board).
- ⏳/✅ **Flop** — performance corrigida e verificada (2026-08); a
  validação em si segue parcial (métrica principal ok, uma métrica
  secundária ainda em aberto). Três achados:
  1. **Bug de performance corrigido em `engine/cfr_core.py`**
     (`DiscountedCFRTrainer.discount`): a cada iteração, o código
     varria TODOS os infosets já criados pra aplicar o desconto —
     inofensivo quando o conjunto de infosets é estável (river/turn),
     mas no flop cada iteração sorteia turn+river e pode criar
     infosets novos, então a varredura ficava maior a cada passada.
     Medido: 0.017s/iteração com 250 iterações rodadas, 0.183s/iteração
     com 3000 — quase 11x mais lento só por causa da varredura,
     crescendo sem parar. Era por isso que rodar a noite inteira (200k
     iterações) não terminava. Corrigido: desconto agora é aplicado
     sob demanda (cada infoset recalcula seu próprio desconto
     acumulado -- via produtos em log, O(1) -- só quando é tocado de
     novo, ou de uma vez em `trainer.finalize()` no fim do treino),
     matematicamente idêntico ao método antigo (mesma sequência de
     multiplicações, só agrupada) -- **verificado**: Kuhn Poker, river,
     turn e o teste de exploitability do river deram os MESMOS
     números, até a última casa decimal, antes e depois da mudança.
     `postflop_flop_check.py` (1500 iterações) ficou ~17x mais rápido
     (106s -> 6.1s); turn ficou ~2x mais rápido de brinde.
  2. **Métrica principal do teste (MDF do bluff-catcher QQ) converge
     bem e é estável**: rodando 5k/10k/20k/35k/50k/75k/100k iterações
     nesse spot, o erro caiu de 0.133 (5k) pra ~0.011-0.016 a partir de
     35k, e ficou parado nessa faixa até 100k -- sinal claro de
     convergência real, não coincidência de uma rodada só.
  3. **Métrica secundária (frequência de aposta de AA/KK na raiz) NÃO
     estabilizou** mesmo em 150k iterações -- ficou subindo de forma
     ruidosa (AA: 19% em 5k -> 62% em 100k -> ainda subindo em 150k).
     O comentário do teste espera "quase sempre" pras mãos de valor, o
     que não bateu. Investigação: o regret_sum acumulado de "check" e
     "bet" fica sempre positivo e da mesma ordem de grandeza nos dois
     (nenhum domina o outro claramente), e o regret médio por iteração
     é pequeno (< 0.1% do pote) -- consistente com quase-indiferença
     entre as duas ações nesse spot específico, não com erro de
     cálculo. Hipótese mais provável: o IP desse teste só tem UMA
     classe de mão (QQ), não um range real -- contra um range travado
     assim, apostar vs. dar check com o nut pode genuinamente valer
     quase o mesmo, e a variância de sortear 2 cartas por chance node
     (turn+river) torna esse empate técnico ainda mais lento pra
     "decidir" que qualquer decisão bem definida por uma fórmula fechada
     (como a MDF acima). **Não é uma confirmação de bug, mas também não
     é uma confirmação de que está certo** -- falta uma ferramenta de
     exploitability rigorosa pra board incompleto (hoje só existe pro
     river, `compute_exploitability()`) pra fechar essa dúvida de vez.
     Próximo passo, se for continuar: (a) rodar um range de IP mais
     realista (não uma classe só) e ver se a frequência de AA/KK
     estabiliza mais rápido, ou (b) estender `compute_exploitability()`
     pra cobrir board de 3/4 cartas (exigiria enumerar os nós de
     chance exatamente, não por amostragem).
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
