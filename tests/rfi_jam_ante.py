"""
Validação do suporte a ante em engine/rfi_jam.py (RfiJamSolver.ante_pool).

Contexto do bug (2026-08): o motor de RFI/Jam (o que de fato gera os
spots gravados em produção via jobs/solve_rfi_jam_batch.py) nunca
modelava ante -- resolvia como se o pote fosse só blinds. Toda mão real
de MTT do produto tem ante (conferido contra 203 mãos reais importadas
por um usuário: nenhuma sem ante), então os spots gerados representavam
um jogo diferente do que o usuário realmente joga -- daí "os números do
drill não batem com a mão real".

Duas checagens:

1. REGRESSÃO -- com ante_pool=0.0 (default, igual sempre foi), os 4
   terminais pré-computados por _precompute_icm_terminals() precisam
   bater EXATAMENTE com a fórmula antiga (sem nenhum termo de ante_pool
   -- reconstruída aqui manualmente a partir do docstring original).
   Não existe uma cópia "legada" separada deste arquivo (diferente do
   multi-size) porque a mudança foi feita direto em rfi_jam.py -- essa
   checagem substitui esse papel: prova que ante_pool=0.0 é matematicamente
   um no-op em cada termo tocado.

2. SANIDADE COM ANTE -- com ante_pool > 0 (ante realista, ~12.5% do bb
   * 8 assentos, faixa observada nas mãos reais analisadas):
   - Fato conhecido de teoria de jogo: ante infla o pote relativo ao
     stack -- o range de abertura ótimo do SB deve ficar MAIS LARGO (em
     combos) com ante do que sem, no mesmo stack efetivo.
   - Exploitability precisa ficar no mesmo patamar do motor sem ante
     (confirma que a árvore convergiu direito, não é só "rodou sem
     crashar").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import build_final_equity_matrix  # noqa: E402
from engine.hand_classes import combo_count  # noqa: E402
from engine.icm import icm_equity  # noqa: E402
from engine.rfi_jam import RfiJamSolver  # noqa: E402

TABLE_STACKS = [25, 25, 40, 30, 20, 15]
PAYOUTS = [500.0, 300.0, 200.0]
ITERATIONS = 60_000
SEED = 42

_EQUITY_MATRIX, _CLASSES, _ = build_final_equity_matrix(fast_iterations=60, blocker_iterations=60, seed=7)


def build_solver(**kwargs):
    solver = RfiJamSolver(
        sb_idx=0, bb_idx=1, table_stacks=TABLE_STACKS, payouts=PAYOUTS,
        equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, effective_stack=25,
        open_size=2.2,
        **kwargs,
    )
    solver.train(iterations=ITERATIONS, seed=SEED)
    return solver


def test_regression_ante_zero():
    print("--- 1. Regressão: ante_pool=0.0 reproduz a fórmula antiga (sem termo de ante) ---")
    solver = build_solver(opener_post=0.5, defender_post=1.0, dead_money=0.0, ante_pool=0.0)

    def icm_pair(sb_delta, bb_delta):
        stacks = list(TABLE_STACKS)
        stacks[0] = max(0.0, stacks[0] + sb_delta)
        stacks[1] = max(0.0, stacks[1] + bb_delta)
        eq = icm_equity(stacks, PAYOUTS)
        return eq[0], eq[1]

    op, dp, T = 0.5, 1.0, solver.T
    expected_fold_root = icm_pair(-op, +op)
    expected_bb_fold_vs_raise = icm_pair(+dp, -dp)
    expected_sb_fold_vs_jam = {s: icm_pair(-s, +s) for s in solver.sizes}
    expected_showdown_sbwins = icm_pair(+T, -T)
    expected_showdown_bbwins = icm_pair(-T, +T)

    checks = [
        ("icm_fold_root", solver.icm_fold_root, expected_fold_root),
        ("icm_bb_fold_vs_raise", solver.icm_bb_fold_vs_raise, expected_bb_fold_vs_raise),
        ("icm_showdown_sbwins", solver.icm_showdown_sbwins, expected_showdown_sbwins),
        ("icm_showdown_bbwins", solver.icm_showdown_bbwins, expected_showdown_bbwins),
    ]
    for size in solver.sizes:
        checks.append((f"icm_sb_fold_vs_jam[{size}]", solver.icm_sb_fold_vs_jam[size], expected_sb_fold_vs_jam[size]))

    max_diff = 0.0
    for name, actual, expected in checks:
        diff = max(abs(actual[0] - expected[0]), abs(actual[1] - expected[1]))
        max_diff = max(max_diff, diff)
        print(f"  {name}: atual={actual}  esperado(fórmula antiga)={expected}  diff={diff:.2e}")
        assert diff < 1e-12, f"{name} diverge da fórmula antiga com ante_pool=0.0 (diff={diff})"

    print(f"  OK -- todos os terminais idênticos à fórmula antiga (maior diff: {max_diff:.2e}).\n")


def test_ante_widens_range():
    print("--- 2. Sanidade: ante real deve alargar o range de abertura do SB ---")
    # Ante ~12.5% do bb * 8 assentos -- faixa observada em mãos reais
    # (30/250=12%, 35/300=11.7%, 20/160=12.5%, 25/200=12.5%, 36/250=14.4%).
    ante_bb = 0.125
    table_size = 8
    ante_pool = ante_bb * table_size

    no_ante = build_solver(opener_post=0.5, defender_post=1.0, dead_money=0.0, ante_pool=0.0)
    with_ante = build_solver(opener_post=0.5, defender_post=1.0, dead_money=0.0, ante_pool=ante_pool)

    def total_open_combos(solver):
        strat = solver.average_strategy()
        return sum(strat["sb_open"][c] * combo_count(c) for c in solver.classes)

    combos_no_ante = total_open_combos(no_ante)
    combos_with_ante = total_open_combos(with_ante)
    print(f"  Combos de abertura do SB -- sem ante: {combos_no_ante:.1f}/1326  |  com ante ({ante_pool:.2f}bb morto): {combos_with_ante:.1f}/1326")

    assert combos_with_ante > combos_no_ante, (
        f"Ante deveria alargar o range de abertura (mais dead money = pote melhor pra roubar), "
        f"mas {combos_with_ante:.1f} <= {combos_no_ante:.1f}"
    )
    print("  OK -- range mais largo com ante, como esperado pela teoria.\n")

    print("--- Exploitability com ante no mesmo patamar de sem ante ---")
    br_sb0, br_bb0 = no_ante.compute_exploitability(no_ante.average_strategy())
    br_sb1, br_bb1 = with_ante.compute_exploitability(with_ante.average_strategy())
    exploit0, exploit1 = br_sb0 + br_bb0, br_sb1 + br_bb1
    print(f"  Exploitability sem ante: {exploit0:.4f}  |  com ante: {exploit1:.4f}")
    assert exploit1 < exploit0 * 3, (
        f"Exploitability com ante ({exploit1:.2f}) desproporcional à baseline sem ante ({exploit0:.2f})"
    )
    print("  OK -- convergência no mesmo patamar.\n")


if __name__ == "__main__":
    test_regression_ante_zero()
    test_ante_widens_range()
    print("Todos os testes de rfi_jam_ante passaram.")
