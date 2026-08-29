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

## cEV/ICM de uma mão jogada (2026-08)

Diferente dos jobs acima (geram tabela de range offline, minutos), este é
resolução SÍNCRONA — recebe uma mão específica que já foi jogada e devolve
o $EV daquele momento, em <1s, sem treinar CFR (cálculo analítico direto:
equity real via Monte Carlo + ICM Malmuth-Harville, ver
`engine/hand_cev.py`).

**Escopo desta primeira versão:** só cobre all-in HEADS-UP com as duas mãos
CONHECIDAS (foram a showdown e mostraram). Sem vilão sabido, ou all-in
multiway, o endpoint não tenta adivinhar — retorna erro em vez de estimar
com um range assumido sem base.

```ts
const res = await fetch(`${SOLVER_API_URL}/hands/compute_cev`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": process.env.SOLVER_API_KEY!,
  },
  body: JSON.stringify({
    hero_combo: "AhAd",
    villain_combo: "KsKc",
    hero_stack_before: 3000,
    villain_stack_before: 3000,
    other_stacks: [8000, 5000], // demais jogadores da mesa, parados nesse momento
    payouts: [500, 300, 200], // tournament_payouts.places do produto
  }),
});
// { hero_equity_pct, hero_expected_chip_delta, hero_expected_icm_dollars,
//   hero_icm_baseline_dollars, hero_expected_icm_delta_dollars, ... }
```

Não grava nada no Supabase — é stateless, o produto decide o que fazer com
o resultado (ex: comparar `hero_expected_icm_delta_dollars` contra o
resultado real da mão pra achar o "luck-adjusted" delta, e somar isso ao
longo do tempo pra virar Net Expected Profit / EV ROI%).

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
  `engine/rfi_jam.py::compute_exploitability`), 4 stacks (15/25/40/60bb)
  já em produção no Supabase. Action da fase `bb_jam` gravado como
  `"allin"` (renomeado de `"jam"` — mesmo significado, nome mais direto).
- ✅ **Múltiplos tamanhos de abertura** (`RfiJamSolver(open_sizes=[2.0,
  2.5, 3.0])`, em vez de `open_size` escalar) — o SB ganha um nó de
  decisão com 1+N ações (fold + uma por tamanho) em vez de só
  fold-ou-abrir; BB responde a CADA tamanho com sua própria subárvore
  fold-ou-jam. Continua sendo o único ponto da árvore onde uma escolha
  de tamanho existe (jam e call-jam continuam all-in por definição, um
  tamanho só). **Não é** o 3-bet "de verdade" do item abaixo — ainda é
  a mesma simplificação de "toda resposta a um raise vira all-in", só
  que agora com várias opções de tamanho pra ABRIR antes disso.
  Validado: com uma lista de 1 tamanho, reproduz bit-a-bit o motor
  anterior (`tests/rfi_jam_multisize.py`, teste de regressão); com
  múltiplos tamanhos, convergência (exploitability + monotonicidade
  por força de mão) fica no mesmo patamar do motor de 1 tamanho na
  mesma verba de iterações. `jobs/solve_rfi_jam_batch.py` e os spots já
  em produção continuam usando `open_size` escalar (nenhuma mudança de
  comportamento) — ainda não geramos nem subimos nenhum spot multi-
  tamanho pro Supabase; falta decidir os tamanhos (ex 2x/2.5x/3x) e
  atualizar o job + o schema de `gto_nodes` + o frontend pra consumir.
- ✅ **Ante** (2026-08, bug real corrigido) — até aqui o motor de RFI/jam
  nunca modelava ante nenhum, resolvia como se o pote fosse só blinds.
  Toda mão real de MTT do produto tem ante (conferido contra 203 mãos
  reais importadas por um usuário: nenhuma sem ante) — os spots gerados
  representavam um jogo diferente do que se joga de verdade. Corrigido
  com o parâmetro `ante_pool` em `RfiJamSolver` (`engine/rfi_jam.py`):
  diferente de `dead_money` (blind de terceiro, só conta se alguém de
  fato "isolar" — por isso fica de fora do nó "abridor desiste de
  cara"), ante já está morto desde antes de qualquer decisão, então
  **entra também** nesse nó (o defensor leva por W.O. mesmo que o
  abridor desista sem brigar). `jobs/solve_rfi_jam_batch.py::
  run_rfi_jam_batch` ganhou `ante_bb`/`table_size` (default 0.0/8 —
  `ante_bb=0` reproduz o comportamento de sempre, spot_id só ganha
  sufixo `_ante{X}` quando `ante_bb>0`, nunca sobrescreve os spots já
  em produção). Validado em `tests/rfi_jam_ante.py`: (1) regressão —
  `ante_pool=0.0` bate bit-a-bit com a fórmula antiga nos 4 terminais;
  (2) sanidade — ante realista (12,5% do bb × 8 assentos, faixa
  observada nas mãos reais) alarga o range de abertura do SB de 69%
  pra 78% dos combos (fato conhecido de teoria de jogo: mais dead money
  = pote melhor pra roubar), com exploitability no mesmo patamar.
  **Falta**: rodar `jobs/solve_rfi_jam_batch.py` de novo com
  `ante_bb`/`table_size` reais pra cada faixa de nível de torneio e
  subir os spots `_ante` pro Supabase — o motor está pronto, os spots
  publicados ainda não foram regerados.
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
  validação de exploitability rigorosa que o motor heads-up** (o
  heads-up faz best response EXATO por enumeração completa de pares de
  classe; aqui é via Monte Carlo — ver item 3 abaixo — porque com 4+
  seats não dá pra enumerar tudo: 169^4 combinações só pra 4
  jogadores). Mãos de fronteira podem
  oscilar bastante entre rodadas (mesmo fenômeno já documentado no
  heads-up, não é bug). É lento por natureza (equity multiway via
  Monte Carlo) — pensado pra rodar OFFLINE, no seu PC, por
  horas/dias/semanas, não no meu sandbox. Ver
  `run_offline_multiway.py` (tem checkpoint automático).
  - ✅ **2 bugs reais corrigidos em `engine/multiway_rfi.py`**
    (2026-08, achados ao conferir ponto a ponto os arquivos
    `resultado_CO_vs_BB_15bb.pkl`/`25bb.pkl` que o usuário rodou o
    fim de semana inteiro — **os dois arquivos ficaram inválidos e
    precisam ser regerados**, não é só questão de ante):
    1. **Blind morto sumindo do pote** — quando um jogador com blind
       (SB/BB) foldava ANTES de alguém dar jam, esse dinheiro nunca
       era creditado a ninguém no showdown final: o branch de
       showdown com 2+ jogadores vivos não considerava jogadores fora
       do `live_set` de jeito nenhum, e o branch de 1 jogador vivo só
       considerava uma parte (uma condição que excluía exatamente os
       blinds foldados antes do jammer). É o mesmo sintoma do bug
       original reportado no parser ("o pote não está indo pra
       nenhum jogador"), só que dentro do solver — e independe de
       ante: mesmo sem ante, o motor já dava resultado errado nesse
       cenário. Corrigido unificando a contabilidade em `_showdown`:
       todo seat fora do `live_set` credita seu custo (post, ou o
       open size se for o abridor) ao vencedor, não importa se
       foldou antes ou depois do jam.
    2. **Ante** — mesmo bug que existia em `rfi_jam.py` antes do fix
       de ante: este motor nunca modelava ante nenhum. Adicionado
       `ante_pool` no `MultiwayRfiSolver` (mesma semântica do motor
       heads-up: morto desde t=0, entra em `_terminal_all_fold` e em
       `_showdown`). `run_offline_all_positions.py` agora passa
       `ante_pool = ANTE_BB * TABLE_SIZE` (default 0,125bb × 8
       assentos) pra todas as combinações, e os arquivos de saída
       ganharam sufixo `_ante0.125` — não porque o valor do ante
       importa pro nome, mas pra garantir que o script não reaproveite
       silenciosamente um `checkpoint_*.pkl`/`resultado_*.pkl` antigo
       (gerado com o motor com bug #1, mesmo sem ante).
    Validado em `tests/multiway_rfi_fixes.py` (não dá pra fazer um
    teste de convergência completo como o do heads-up aqui — motor
    multiway é lento demais nesse sandbox pra caber em teste unitário
    — então a validação é direta nos terminais, sem treinar o CFR
    inteiro). **Recorrida** (usuário apagou os `resultado_`/
    `checkpoint_CO_vs_BB_15bb`/`25bb.pkl` antigos e já está rodando
    `run_offline_all_positions.py` do zero com os fixes, no PC dele).
  - ✅ **Exploitability + upload, adicionados depois (2026-08)** — até
    aqui faltavam 2 peças pra fechar o ciclo desse motor:
    3. **Sem métrica de convergência**: o `resultado_*.pkl` só trazia
       `config`/`strategy`/`iterations`, nada que dissesse "isso
       convergiu bem?". Adicionado `best_response_value`/
       `compute_exploitability` em `MultiwayRfiSolver` — Monte Carlo
       (cada seat, um de cada vez, joga a ação de maior ICM em toda
       decisão própria enquanto os outros seguem a média já
       convergida; a soma das best responses por seat é a métrica,
       mesma convenção do motor heads-up — termômetro comparável entre
       runs, não exploitability literal em $). `run_offline_all_
       positions.py` agora calcula isso uma vez no fim de cada
       combinação e grava `exploitability`/`best_response_by_seat` no
       `resultado_*.pkl`. Validado em `test_exploitability_runs`
       (roda de ponta a ponta, devolve número finito por seat — não dá
       pra validar a DIREÇÃO do valor sem treinar por muito mais tempo
       que cabe em teste unitário).
    4. **Sem script de upload**: diferente do heads-up
       (`run_offline_rfi_jam_ante.py::upload_results`), não existia
       nada que lesse os `resultado_*.pkl` multiway e subisse pro
       Supabase. Adicionado `build_drill_row`/`upload_results` direto
       em `run_offline_all_positions.py` (`python3
       run_offline_all_positions.py --upload`). Schema do `gto_nodes`
       é mais simples que o do heads-up: só frequência por mão/seat/
       fase (`phase1`/`phase2`), sem EV nem gap por mão — isso exigiria
       um equivalente de `compute_action_evs` que este motor não tem
       (EV exato por classe não escala pra N jogadores do jeito que
       escala pra 2). `spot_id` usa prefixo novo (`rfi_multiway_...`,
       `action="rfi_multiway"`) pra não colidir com os spots
       heads-up (`rfi_jam_...`) — **o frontend ainda não consome esse
       formato**, então subir os spots é seguro (não quebra nada em
       produção), mas vai precisar de trabalho de frontend depois pra
       exibir.
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
  - **Exploitability rigorosa via best-response exato, agora pra
    QUALQUER rua** (river, turn ou flop — `PostflopSolver.compute_exploitability()`,
    mesmo padrão de `tests/kuhn_poker.py` e
    `engine/rfi_jam.py::compute_exploitability`, mas cobrindo a árvore
    inteira, não só uma decisão isolada como o teste de MDF): testado
    no mesmo spot polarizado-vs-bluffcatcher, exploitability ficou em
    0,39% do pote no river — ver `tests/postflop_exploitability.py`.
    Detalhe de implementação: a convenção de contabilidade do motor faz
    `br_oop + br_ip` somar sempre `pot0` num equilíbrio perfeito (não
    0 como em Kuhn Poker), então `compute_exploitability()` já
    devolve o valor com essa constante subtraída.
    (2026-08) Generalizado pra board incompleto (turn/flop): a
    recursão espelha exatamente a árvore de treino
    (`_br_bet_or_check`/`_br_facing_bet`/`_br_facing_raise`/`_br_end_of_action`),
    mas nos nós de chance enumera EXATAMENTE todas as cartas que faltam
    (não amostra 1 como o treino) — mais pesado, mas exato. Quando a
    recursão chega num infoset nunca visitado no treino (comum no
    flop), a classe correspondente do oponente é EXCLUÍDA do cálculo
    (peso zero) em vez de assumir um comportamento padrão tipo "sempre
    folda" — evita viesar o resultado numa direção sem justificativa.
    Validado em 3 camadas antes de confiar no resultado: (1) reproduz
    exatamente os 0,39% do pote do river (mesmo código, board de 5
    cartas nunca cria nó de chance); (2) no turn, roda em <1s e a
    exploitability cai de forma monotônica com mais treino (3,77% em
    3k iterações → 1,60% em 10k → 0,82% em 30k), com o número de
    infosets estável (2175) — sinal de que a árvore inteira já é
    descoberta cedo e a queda vem de refinamento de estratégia, não de
    viés por infoset faltante; (3) aplicado ao próprio spot do flop
    (ver item "Flop" abaixo) pra responder de vez a dúvida do AA/KK.
  - Limitações conhecidas (documentadas): (1) decisões são por classe
    de mão, não por combo — sem discriminação de blocker dentro da
    classe (mesmo espírito da aproximação já aceita em
    `hand_classes.py` pro pré-flop); (2) raise limitado a um único
    tamanho (all-in), mesma simplificação do pré-flop pra 3-bet/4-bet;
    (3) a carta sorteada nos nós de chance ignora blockers com as mãos
    específicas dos jogadores (só evita colidir com o board).
- ⏳/✅ **Flop** — performance corrigida e verificada (2026-08); métrica
  principal (MDF) validada, métrica secundária (freq. de aposta de
  AA/KK) explicada via exploitability rigorosa (convergência lenta
  confirmada, não bug) mas o spot em si ainda não converge o
  suficiente pra virar validação formal. Três achados:
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
     que não bateu. Investigação inicial: o regret_sum acumulado de
     "check" e "bet" fica sempre positivo e da mesma ordem de grandeza
     nos dois (nenhum domina o outro claramente), consistente com
     quase-indiferença entre as duas ações nesse spot específico, não
     com erro de cálculo -- mas isso sozinho não provava nada.
     **(2026-08) Resolvido com exploitability rigorosa** (ver item
     acima): rodando `compute_exploitability()` (agora generalizado pra
     board incompleto) nesse mesmo spot do flop, com 5k/20k/50k
     iterações de treino, a exploitability cai de forma monotônica --
     85,16% do pote (5k) -> 33,82% (20k) -> 14,32% (50k) -- com o
     número de infosets praticamente estável entre 20k e 50k (272663 ->
     272700, cresceu <0,03%). Isso confirma a hipótese: **não é bug,
     é convergência genuinamente lenta** nesse spot (o IP só ter UMA
     classe de mão, e o flop sortear 2 cartas por chance node, tornam
     o equilíbrio mais lento de alcançar) -- a queda é suave e
     consistente, não estagnada nem oscilando, só ainda longe de zero
     em 50k. Não dá pra tratar o teste como validado ainda (14% de
     exploitability é alto), mas a ferramenta agora existe pra medir
     isso de verdade em vez de confiar só na métrica proxy de
     frequência de aposta -- próximo passo, se for continuar
     investigando esse spot específico: rodar bem mais iterações (ex:
     200k+) e/ou testar com um range de IP mais realista (não uma
     classe só) pra ver se converge mais rápido.
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
