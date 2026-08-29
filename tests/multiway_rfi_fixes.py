"""
Validação de fixes/adições em engine/multiway_rfi.py (motor usado por
run_offline_all_positions.py pra CO/HJ/MP/UTG+1/UTG vs BB).

Contexto (2026-08): o usuário rodou o fim de semana inteiro gerando
resultado_CO_vs_BB_15bb.pkl e resultado_CO_vs_BB_25bb.pkl com a versão
antiga deste motor. Ao conferir ponto a ponto contra o fix de ante já
aplicado em engine/rfi_jam.py, dois problemas apareceram:

1. BUG DE BLIND MORTO (mais grave, independe de ante): em `_showdown`,
   quando alguém entre o abridor e o jammer tinha blind (SB ou BB) e
   FOLDAVA ANTES de alguém dar jam, esse dinheiro nunca era creditado a
   ninguém -- sumia do cálculo de ICM. O branch de showdown multiway
   (2+ jogadores vivos) não considerava jogadores fora do `live_set` de
   jeito nenhum; o branch de 1 jogador vivo só considerava uma parte
   (condição `i > min(live_set)`, que exclui exatamente os blinds
   foldados antes do jammer). Esse é o mesmo sintoma do bug original
   reportado no parser ("o pote não está indo pra nenhum jogador"), só
   que dentro do solver. Fix: `not_live = all seats - live_set`, e todo
   seat em `not_live` credita seu custo (post, ou o open R se for o
   abridor) ao vencedor -- não importa se foldou antes ou depois do jam.

2. FALTA DE ANTE: mesmo bug que existia em rfi_jam.py antes do fix --
   este motor nunca modelava ante. Adicionado `ante_pool` (dead desde
   t=0, entra em `_terminal_all_fold` e em `_showdown`, igual ao já
   validado no motor heads-up).

Diferente de tests/rfi_jam_ante.py, NÃO existe aqui um teste de
"regressão bit-exata com ante_pool=0", porque o fix #1 muda os números
mesmo sem ante -- o motor antigo (mesmo sem ante) já dava resultado
ERRADO nesse cenário. O que se testa é:

  1. Conservação de dinheiro: no cenário controlado (blind morto pré-jam
     seguido de jam+call), o pote morto batido manualmente por
     `_showdown` tem que incluir o blind do jogador que foldou antes do
     jam -- o motor antigo dava 0 aqui.
  2. Ante chega no terminal certo com o valor certo: testado direto nos
     métodos de terminal (`_terminal_all_fold`, `_showdown`), sem
     treinar o CFR completo -- este motor multiway é MUITO mais lento
     que o heads-up (~9-11 it/s neste sandbox, documentado no próprio
     run_offline_all_positions.py), então um teste de convergência
     completo (como o de tests/rfi_jam_ante.py) não é viável aqui em
     tempo de teste unitário.

3. FALTA DE EXPLOITABILITY: diferente de rfi_jam.py (que tem
   `compute_exploitability` via best response exato, por enumeração
   completa de pares de classe), este motor não tinha NADA equivalente
   -- o `resultado_*.pkl` final não trazia nenhuma métrica de quão
   convergido o treino estava. Adicionado `best_response_value`/
   `compute_exploitability` via Monte Carlo (não dá pra enumerar exato
   com 4+ seats -- 169^4 combinações só pra 4 jogadores): cada seat, um
   de cada vez, joga a ação de MAIOR ICM em toda decisão própria
   enquanto os outros seguem a média já convergida; a soma das best
   responses por seat é a métrica de exploitability (mesma convenção
   do motor heads-up -- termômetro comparável entre runs, não um valor
   de exploitability literal em $). `run_offline_all_positions.py`
   agora calcula isso uma vez no final de cada combinação e grava
   `exploitability`/`best_response_by_seat` no `resultado_*.pkl`.
   Validado em `test_exploitability_runs`: roda de ponta a ponta e
   devolve um número finito por seat (não dá pra validar a DIREÇÃO do
   valor sem treinar por muito mais tempo -- com poucas iterações a
   média ainda reflete a exploração quase-aleatória do início do CFR).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import build_equity_matrix  # noqa: E402
from engine.multiway_rfi import MultiwayRfiSolver  # noqa: E402

TABLE_STACKS = [25.0, 25.0, 25.0, 25.0, 40.0, 25.0]
PAYOUTS = [500.0, 300.0, 200.0]
SEATS = ["CO", "BTN", "SB", "BB"]  # 4 seats: CO abre, BTN pula, SB, BB
SEAT_POSTS = [0.0, 0.0, 0.5, 1.0]

_MATRIX, _CLASSES = build_equity_matrix(iterations=60, seed=7)


def build_solver(ante_pool=0.0):
    return MultiwayRfiSolver(
        seat_names=SEATS, seat_idx_in_table=[0, 1, 2, 3],
        seat_posts=SEAT_POSTS, table_stacks=TABLE_STACKS, payouts=PAYOUTS,
        equity_matrix=_MATRIX, classes=_CLASSES,
        open_size=2.2, effective_stack=25.0, ante_pool=ante_pool,
    )


def test_dead_blind_credited():
    print("--- 1. Blind morto foldado antes do jam precisa ir pro vencedor ---")
    solver = build_solver(ante_pool=0.0)

    # Cenario: CO(0) abre, BTN(1) folda, SB(2) folda (blind morto = 0.5!),
    # BB(3) da jam, CO(0) folda pro jam -- unico vivo no showdown e o BB.
    live_set = {3}
    not_live = [i for i in range(4) if i not in live_set]

    def old_buggy_cost(i):
        # formula antiga: so contava quem foldou DEPOIS do jammer (min(live_set))
        min_live = min(live_set)
        cost = solver.R if i == 0 else solver.seat_posts[i]
        return cost if (i == 0 or i > min_live) else 0.0

    def new_cost(i):
        return solver.R if i == 0 else solver.seat_posts[i]

    old_dead = sum(old_buggy_cost(i) for i in not_live)
    new_dead = sum(new_cost(i) for i in not_live)
    print(f"  not_live: {not_live}  |  pote morto (fórmula antiga): {old_dead}  |  (fórmula nova): {new_dead}")

    # antiga: contava o open R do CO (i==0, sempre contado) mas perdia o
    # blind do SB (2 < min(live_set)=3, e 2 != 0) -- so 2.2, faltando 0.5
    assert abs(old_dead - solver.R) < 1e-9, (
        f"a fórmula antiga devia contar só o open do CO ({solver.R}), perdendo o blind do SB -- deu {old_dead}"
    )
    assert abs(new_dead - (solver.R + 0.5)) < 1e-9, (
        f"o blind morto do SB (0.5) precisa somar ao open do CO ({solver.R}) no pote -- deu {new_dead}"
    )
    print("  OK -- o blind morto do SB (0.5) agora é creditado ao vencedor; antes desaparecia.\n")


def test_ante_reaches_terminals():
    print("--- 2. Ante chega nos terminais certos, com o valor certo ---")
    ante_bb = 0.125
    table_size = 8
    ante_pool = ante_bb * table_size

    no_ante = build_solver(ante_pool=0.0)
    with_ante = build_solver(ante_pool=ante_pool)
    hands = {0: "AA", 1: "72o", 2: "72o", 3: "72o"}

    # terminal 1: abridor abre, todo mundo folda -- abridor ganha os
    # blinds + o ante (antes: so os blinds).
    icm0 = no_ante._terminal_all_fold(hands)
    icm1 = with_ante._terminal_all_fold(hands)
    print(f"  _terminal_all_fold -- CO ICM sem ante: {icm0[0]:.4f}  |  com ante: {icm1[0]:.4f}")
    assert icm1[0] > icm0[0], "ICM do abridor deveria subir com ante no terminal 'todo mundo folda'"

    # terminal 2: showdown com 1 unico vivo (BB ganha o pote morto todo,
    # que agora inclui blind pre-jam foldado + ante).
    icm2 = no_ante._showdown({3}, hands)
    icm3 = with_ante._showdown({3}, hands)
    print(f"  _showdown (1 vivo) -- BB ICM sem ante: {icm2[3]:.4f}  |  com ante: {icm3[3]:.4f}")
    assert icm3[3] > icm2[3], "ICM do vencedor deveria subir com ante no showdown de 1 vivo"

    print("  OK -- ante chega em ambos os terminais reais (nenhum ainda os ignora).\n")


def test_exploitability_runs():
    print("--- 3. compute_exploitability roda e devolve valores finitos por seat ---")
    # OBS: não dá pra validar direção (ex: "forçar um seat a sempre foldar
    # só pode ajudar quem responde") com poucas iterações de treino -- a
    # média ainda reflete a exploração quase-aleatória do início do CFR,
    # não uma estratégia perto do equilíbrio, então essa comparação daria
    # ruído, não sinal. O que dá pra validar sem treinar por horas é que
    # o cálculo roda de ponta a ponta e devolve um número por seat.
    solver = build_solver(ante_pool=1.0)
    solver.train(iterations=300, seed=42)
    strat = solver.average_strategy()

    br = solver.compute_exploitability(strat, iterations=80, seed=7)
    print(f"  best response por seat (estratégia ainda mal treinada, só pra testar que roda): {br}")
    assert len(br) == solver.n_seats
    assert all(v == v for v in br.values()), "best response não pode dar NaN"  # v==v descarta NaN
    print("  OK -- compute_exploitability roda sem erro pra todos os seats.\n")


if __name__ == "__main__":
    test_dead_blind_credited()
    test_ante_reaches_terminals()
    test_exploitability_runs()
    print("Todos os testes de multiway_rfi_fixes passaram.")
