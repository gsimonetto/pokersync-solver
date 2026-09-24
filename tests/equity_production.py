"""
Confere a matriz de equity de PRODUCAO (engine/data/equity_matrix_169.json,
usada pelos jobs heads-up da API): carrega sem erro, e' coerente
(equity(a,b) + equity(b,a) = 1) e bate com numeros de equity conhecidos
e com um recalculo independente (outra semente, mais simulacoes).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_blockers import class_vs_class_equity  # noqa: E402
from engine.equity_final import get_production_equity_matrix, load_equity_matrix  # noqa: E402


def test_arquivo_carrega_e_e_coerente():
    matrix, classes = load_equity_matrix()
    assert len(classes) == 169
    for a in classes:
        for b in classes:
            assert abs(matrix[(a, b)] + matrix[(b, a)] - 1.0) < 1e-6, (a, b)
    assert get_production_equity_matrix()[1] == classes


def test_bate_com_valores_conhecidos():
    matrix, _ = load_equity_matrix()
    conhecidos = [("AA", "KK", 0.82), ("AKo", "QQ", 0.43), ("22", "AKo", 0.525),
                  ("AKs", "AKo", 0.525), ("72o", "AKo", 0.325), ("AA", "72o", 0.88)]
    for a, b, esperado in conhecidos:
        # 4000 simulacoes por par -> erro-padrao ~0.008; 0.025 = 3 erros-padrao
        assert abs(matrix[(a, b)] - esperado) < 0.025, (a, b, matrix[(a, b)], esperado)


def test_bate_com_recalculo_independente():
    matrix, _ = load_equity_matrix()
    for a, b in [("KQs", "AJo"), ("99", "AKs"), ("T9s", "88"), ("A5s", "KQo")]:
        ref = class_vs_class_equity(a, b, iterations=30_000, seed=12345)
        assert abs(matrix[(a, b)] - ref) < 0.03, (a, b, matrix[(a, b)], ref)


if __name__ == "__main__":
    test_arquivo_carrega_e_e_coerente()
    print("  OK -- matriz de producao carrega e e' coerente")
    test_bate_com_valores_conhecidos()
    print("  OK -- bate com equities conhecidas")
    test_bate_com_recalculo_independente()
    print("  OK -- bate com recalculo independente")
    print("Todos os testes de equity_production passaram.")
