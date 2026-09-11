"""
Validação de engine/icm.py (Malmuth-Harville) por propriedades
matemáticas, não números decorados. Convertido do bloco __main__
antigo do próprio engine/icm.py (que só imprimia "OK"/"FALHOU" sem
travar o CI) pra um teste de verdade com assert.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.icm import icm_equity  # noqa: E402


def test_conservacao_de_dinheiro():
    stacks = [5000, 3000, 2000]
    payouts = [500.0, 300.0, 200.0]
    eq = icm_equity(stacks, payouts)
    assert abs(sum(eq) - sum(payouts)) < 0.01, (
        f"Dinheiro nao pode sumir nem surgir: soma equity={sum(eq):.2f}, soma payouts={sum(payouts):.2f}"
    )


def test_stacks_iguais_equity_igual():
    payouts = [500.0, 300.0, 200.0]
    eq = icm_equity([1000, 1000, 1000], payouts)
    expected_each = sum(payouts) / 3
    for v in eq:
        assert abs(v - expected_each) < 0.01, f"Stacks iguais deveriam splitar o prize pool: {eq}"


def test_monotonicidade():
    payouts = [500.0, 300.0, 200.0]
    eq_a = icm_equity([4000, 3000, 3000], payouts)
    eq_b = icm_equity([5000, 2500, 2500], payouts)  # jogador 0 ganhou fichas dos outros
    assert eq_b[0] > eq_a[0], f"Mais fichas nunca pode dar menos $EV: {eq_a[0]:.2f} -> {eq_b[0]:.2f}"


def test_heads_up_winner_take_all_e_proporcional_ao_stack():
    # Caso degenerado: 2 jogadores, 1 premio -- ICM = chip EV exatamente
    # (nao ha diferenca entre chip e $ quando so tem 1 premio e 2 jogadores)
    stacks = [7000, 3000]
    payouts = [1000.0]
    eq = icm_equity(stacks, payouts)
    expected = [1000.0 * 7000 / 10000, 1000.0 * 3000 / 10000]
    for got, want in zip(eq, expected):
        assert abs(got - want) < 0.01, f"HU winner-take-all deve ser proporcional ao stack: {eq} esperado {expected}"


if __name__ == "__main__":
    test_conservacao_de_dinheiro()
    print("  OK -- conservacao de dinheiro")
    test_stacks_iguais_equity_igual()
    print("  OK -- stacks iguais = equity igual")
    test_monotonicidade()
    print("  OK -- monotonicidade")
    test_heads_up_winner_take_all_e_proporcional_ao_stack()
    print("  OK -- heads-up winner-take-all proporcional ao stack")
    print("Todos os testes de icm passaram.")
