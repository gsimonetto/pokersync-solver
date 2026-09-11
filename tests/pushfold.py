"""
Validação de engine/pushfold.py (PushFoldSolver, chip EV puro sem ICM).
Convertido do bloco __main__ antigo (só imprimia numeros, sem travar
o CI em regressão) pra um teste de verdade com assert.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import build_equity_matrix  # noqa: E402
from engine.pushfold import PushFoldSolver  # noqa: E402

# Fidelidade baixa de proposito (o padrao antigo do __main__ usava 250,
# mas isso sozinho leva minutos pras 169x169 combinacoes -- aqui so'
# precisamos de direcao qualitativa certa, nao precisao numerica).
_EQUITY_MATRIX, _CLASSES = build_equity_matrix(iterations=40, seed=7)


def test_push_range_faz_sentido_por_stack():
    for stack in (10, 15, 20):
        solver = PushFoldSolver(stack_bb=stack, equity_matrix=_EQUITY_MATRIX, classes=_CLASSES)
        solver.train(iterations=2000)
        strat = solver.average_strategy()

        aa_push = strat["sb_push"]["AA"]
        ako_push = strat["sb_push"]["AKo"]
        trash_push = strat["sb_push"]["72o"]

        assert aa_push > 0.9, f"stack={stack}: AA deveria empurrar quase sempre, deu {aa_push:.3f}"
        assert ako_push > 0.9, f"stack={stack}: AKo deveria empurrar quase sempre, deu {ako_push:.3f}"
        assert trash_push < aa_push, f"stack={stack}: 72o nao pode empurrar mais que AA"


def test_range_de_push_encolhe_com_stack_maior():
    # Quanto mais fundo o stack, mais estreito o range de push (menos
    # vale arriscar tudo com mao marginal) -- propriedade qualitativa
    # basica de qualquer solver de push/fold correto.
    counts = {}
    for stack in (10, 20, 30):
        solver = PushFoldSolver(stack_bb=stack, equity_matrix=_EQUITY_MATRIX, classes=_CLASSES)
        solver.train(iterations=2000)
        strat = solver.average_strategy()
        counts[stack] = sum(1 for c in _CLASSES if strat["sb_push"][c] > 0.5)

    assert counts[10] >= counts[20] >= counts[30], (
        f"Range de push deveria encolher (ou manter) conforme o stack aumenta: {counts}"
    )


if __name__ == "__main__":
    test_push_range_faz_sentido_por_stack()
    print("  OK -- push range faz sentido por stack (AA/AKo sempre, 72o menos que AA)")
    test_range_de_push_encolhe_com_stack_maior()
    print("  OK -- range de push encolhe com stack maior")
    print("Todos os testes de pushfold passaram.")
