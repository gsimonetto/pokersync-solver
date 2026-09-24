"""
Validação do modo chipEV puro (`use_icm=False`) em MultiwayRfiSolver
(3+ jogadores) -- mesma ideia de tests/rfi_jam_chipev.py, mas pro motor
multiway. Ver engine/multiway_rfi.py::_icm (único ponto de acesso a
ICM no motor -- quando use_icm=False, devolve o delta de fichas cru em
vez de rodar Malmuth-Harville).

Duas checagens:

1. Não quebra e devolve probabilidades válidas (roda a árvore inteira
   sem erro, sem NaN, direção qualitativa básica preservada: mão
   premium >> lixo).
2. O modo realmente MUDA o resultado -- comparando lado a lado com o
   mesmo spot em modo ICM (payouts reais, cenário com pressão real de
   bolha: 2 seats curtos de 10bb competindo por 2 vagas pagas de 4
   jogadores), pelo menos uma classe de mão tem que divergir de forma
   clara entre os dois modos. Isso pega uma regressão onde `use_icm`
   silenciosamente não faz nada (ex: se alguém reintroduzir uma
   chamada a icm_equity que não passa por `_icm()`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import build_final_equity_matrix  # noqa: E402
from engine.multiway_rfi import MultiwayRfiSolver  # noqa: E402

_EQUITY_MATRIX, _CLASSES, _ = build_final_equity_matrix(fast_iterations=40, blocker_iterations=40, seed=7)

# 2 seats curtos (10bb) modelados, mais 2 stacks fundos de fora (60bb) --
# só 2 dos 4 jogadores da mesa são pagos: pressão de bolha real pros
# dois seats de 10bb (podem terminar fora do dinheiro).
_CONFIG = dict(
    seat_names=["opener", "BB"], seat_idx_in_table=[0, 1],
    seat_posts=[0.0, 1.0], table_stacks=[10, 10, 60, 60],
    open_size=2.2, effective_stack=10, equity_matrix=_EQUITY_MATRIX, classes=_CLASSES,
)


def test_multiway_chipev_nao_quebra_e_sanidade():
    print("--- MultiwayRfiSolver chipEV: roda sem quebrar, AA >> 72o ---")
    solver = MultiwayRfiSolver(payouts=None, use_icm=False, **_CONFIG)
    solver.train(iterations=5_000, seed=1)
    strat = solver.average_strategy()

    aa_open = strat["phase1"][0]["AA"]
    trash_open = strat["phase1"][0]["72o"]
    print(f"  AA abre {aa_open:.3f}  72o abre {trash_open:.3f}")
    assert 0.0 <= aa_open <= 1.0 and 0.0 <= trash_open <= 1.0, "frequencia fora de [0,1]"
    assert aa_open == aa_open and trash_open == trash_open, "NaN na estrategia"  # NaN != NaN
    assert aa_open > trash_open, f"AA deveria abrir mais que 72o: AA={aa_open} 72o={trash_open}"
    print("  OK.\n")


def test_multiway_chipev_diverge_de_icm_com_pressao_de_bolha():
    print("--- MultiwayRfiSolver: chipEV diverge de ICM sob pressao real de bolha ---")
    chip_solver = MultiwayRfiSolver(payouts=None, use_icm=False, **_CONFIG)
    chip_solver.train(iterations=3_000, seed=1)
    chip_strat = chip_solver.average_strategy()

    icm_solver = MultiwayRfiSolver(payouts=[500.0, 300.0], use_icm=True, **_CONFIG)
    icm_solver.train(iterations=3_000, seed=1)
    icm_strat = icm_solver.average_strategy()

    max_diff = 0.0
    for c in _CLASSES:
        max_diff = max(max_diff, abs(chip_strat["phase1"][0][c] - icm_strat["phase1"][0][c]))
    print(f"  Maior diferenca entre chipEV e ICM (abridor, todas as classes): {max_diff:.4f}")
    # Generoso de proposito (17k iteracoes pra 2 seats e' pouco pra
    # convergencia fina) -- so precisa provar que o modo realmente
    # muda o resultado, nao medir a magnitude exata do efeito de ICM.
    assert max_diff > 0.02, (
        f"chipEV e ICM deveriam divergir sob pressao real de bolha -- "
        f"maior diferenca encontrada foi so {max_diff:.4f}, sinal de que use_icm pode nao estar "
        f"tendo efeito de verdade"
    )
    print("  OK -- o modo realmente muda a estrategia (use_icm nao e' um no-op).\n")


def test_showdown_chipev_mantem_perda_de_quem_foldou():
    """Regressão (2026-09-24): em chipEV, o showdown com 2+ jogadores
    vivos deixava de fora do resultado quem tinha foldado com dinheiro no
    pote (valor negativo: SB perde 0.5, abridor perde o open) -- quem lia
    com .get(seat, 0.0) via 0 em vez da perda real, e o fold desses seats
    parecia mais barato do que é (viés pra foldar)."""
    print("--- chipEV: showdown multiway mantém a perda de quem foldou ---")
    solver = MultiwayRfiSolver(
        seat_names=["CO", "SB", "BB"], seat_idx_in_table=[0, 1, 2], seat_posts=[0.0, 0.5, 1.0],
        table_stacks=[20, 20, 20], payouts=None, use_icm=False, open_size=2.2, effective_stack=20,
        equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, ante_pool=0.375,
    )
    hands = {0: "AA", 1: "72o", 2: "KK"}
    # SB foldou (tinha 0.5 no pote); CO e BB foram pro showdown
    result = solver._showdown({0, 2}, hands)
    assert abs(result.get(1, 0.0) - (-0.5)) < 1e-9, f"SB foldou com 0.5 no pote, deveria ficar -0.5: {result}"
    # abridor foldou pro jam (tinha aberto 2.2); SB e BB no showdown
    result = solver._showdown({1, 2}, hands)
    assert abs(result.get(0, 0.0) - (-2.2)) < 1e-9, f"abridor foldou depois de abrir 2.2: {result}"
    # conservação: tudo que um perde o outro ganha (+ o ante morto, que
    # não sai do bolso de nenhum seat modelado)
    for live in ({0, 2}, {1, 2}, {0, 1, 2}, {0, 1}):
        result = solver._showdown(live, hands)
        assert abs(sum(result.values()) - 0.375) < 1e-9, (live, result)
    print("  OK -- SB fica com -0.5 e o abridor com -2.2 quando foldam; fichas conservadas\n")


if __name__ == "__main__":
    test_multiway_chipev_nao_quebra_e_sanidade()
    test_multiway_chipev_diverge_de_icm_com_pressao_de_bolha()
    test_showdown_chipev_mantem_perda_de_quem_foldou()
    print("Todos os testes de multiway_rfi_chipev passaram.")
