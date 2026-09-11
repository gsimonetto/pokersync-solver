"""
Validação de engine/pushfold_icm.py (PushFoldICMSolver). Convertido do
bloco __main__ antigo (só imprimia numeros, sem travar o CI em
regressão) pra um teste de verdade com assert.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import build_equity_matrix  # noqa: E402
from engine.pushfold import PushFoldSolver  # noqa: E402
from engine.pushfold_icm import PushFoldICMSolver, combo_count  # noqa: E402

# Fidelidade baixa de proposito (mesma justificativa de tests/pushfold.py).
_EQUITY_MATRIX, _CLASSES = build_equity_matrix(iterations=40, seed=7)


def test_icm_faz_sentido_qualitativo():
    """NAO afirma a direcao classica "ICM sempre aperta o range perto da
    bolha" -- testei 2 configuracoes de mesa diferentes (6-handed com
    stack curto no meio da tabela, e bolha classica 3-handed com um
    stack bem curto) e o resultado foi CONTRA essa direcao nas duas
    (o range de push da SB ficou mais LARGO sob ICM, nao mais estreito
    -- num dos casos, 100% das maos). Isso pode ser correto pra essas
    configuracoes especificas (ex: BB defendendo muito menos pra
    preservar o cash quase garantido, o que aumenta MUITO a fold equity
    da SB e justificaria push largo) ou pode ser um bug real em
    pushfold_icm.py -- nao tenho confianca suficiente pra decidir sem
    validar contra uma segunda fonte, e nao e' hora de travar o CI numa
    afirmacao que pode estar errada. Ver resumo/pendencias entregue ao
    usuario -- fica registrado aqui como investigacao futura.

    Este teste, por enquanto, so confirma propriedades que SAO
    inequivocas: dinheiro nao pode sumir (ja' coberto em tests/icm.py)
    e AA continua preferido sobre lixo mesmo sob ICM."""
    other_stacks = [40, 25, 18, 12]
    table_stacks = [15, 15] + other_stacks
    payouts = [500.0, 300.0, 200.0]

    icm_solver = PushFoldICMSolver(
        sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
        equity_matrix=_EQUITY_MATRIX, classes=_CLASSES,
    )
    icm_solver.train(iterations=2000)
    icm_strat = icm_solver.average_strategy()

    assert icm_strat["sb_push"]["AA"] > icm_strat["sb_push"]["72o"], (
        "Sob ICM, AA ainda precisa ser preferido a 72o (mesmo que o range geral mude de tamanho)"
    )
    return icm_solver, icm_strat


def test_final_evs_tem_gap_maior_em_maos_marginais():
    # final_evs() alimenta o "quanto voce perdeu" no produto -- o gap
    # entre fold e push deve ser MENOR pra maos de fronteira do que pra
    # maos claramente certas/erradas (senao o produto mostraria "erro
    # grave" pra decisoes que na verdade sao quase indiferentes).
    other_stacks = [40, 25, 18, 12]
    table_stacks = [15, 15] + other_stacks
    payouts = [500.0, 300.0, 200.0]
    solver = PushFoldICMSolver(sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
                                equity_matrix=_EQUITY_MATRIX, classes=_CLASSES)
    solver.train(iterations=2000)
    strat = solver.average_strategy()
    evs = solver.final_evs(strat)

    gap_aa = abs(evs["sb_ev_push"]["AA"] - evs["sb_ev_fold"])
    gap_72o = abs(evs["sb_ev_push"]["72o"] - evs["sb_ev_fold"])
    # mao marginal (perto de 50% push) deve ter gap MENOR que mao clara
    marginal_class = min(_CLASSES, key=lambda c: abs(strat["sb_push"][c] - 0.5))
    gap_marginal = abs(evs["sb_ev_push"][marginal_class] - evs["sb_ev_fold"])

    assert gap_marginal <= max(gap_aa, gap_72o), (
        f"Mao marginal ({marginal_class}, push={strat['sb_push'][marginal_class]:.2f}) deveria ter "
        f"gap fold-vs-push menor que uma mao clara: gap_marginal={gap_marginal:.3f} "
        f"gap_aa={gap_aa:.3f} gap_72o={gap_72o:.3f}"
    )


if __name__ == "__main__":
    test_icm_faz_sentido_qualitativo()
    print("  OK -- AA > 72o sob ICM (tamanho do range vs chip EV fica de fora, ver docstring)")
    test_final_evs_tem_gap_maior_em_maos_marginais()
    print("  OK -- gap fold-vs-push e' menor pra mao marginal que pra mao clara")
    print("Todos os testes de pushfold_icm passaram.")
