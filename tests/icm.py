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


def _icm_por_permutacao(stacks, payouts):
    """Referência independente (força bruta): soma, pra TODA ordem de
    chegada possível, a probabilidade Malmuth-Harville dela vezes os
    prêmios. Lento, só pra conferir a implementação real em mesas
    pequenas."""
    import itertools
    n = len(stacks)
    eq = [0.0] * n
    for order in itertools.permutations(range(n)):
        p = 1.0
        remaining = sum(stacks)
        for idx in order:
            if remaining <= 0:
                break
            p *= stacks[idx] / remaining
            remaining -= stacks[idx]
        for place, idx in enumerate(order[: len(payouts)]):
            eq[idx] += p * payouts[place]
    return eq


def test_bate_com_referencia_forca_bruta():
    import random
    rng = random.Random(5)
    for _ in range(300):
        n = rng.randint(2, 6)
        stacks = [rng.uniform(1, 100) for _ in range(n)]
        payouts = sorted((rng.uniform(1, 500) for _ in range(rng.randint(1, n))), reverse=True)
        got = icm_equity(stacks, payouts)
        want = _icm_por_permutacao(stacks, payouts)
        assert max(abs(a - b) for a, b in zip(got, want)) < 1e-9, (stacks, payouts, got, want)


def test_varios_eliminados_na_mesma_mao_nao_quebra():
    # Caso real que travava o run_offline_all_positions.py em HJ/MP/UTG+1/UTG
    # (ZeroDivisionError): 5 jogadores all-in, 1 ganha, 4 quebram, sobra 1
    # jogador de fora -- 3 prêmios, só 2 jogadores com fichas.
    payouts = [500.0, 300.0, 200.0]
    eq = icm_equity([76.0, 0.0, 0.0, 0.0, 0.0, 40.0], payouts)
    assert abs(sum(eq) - sum(payouts)) < 1e-9, f"dinheiro sumiu/surgiu: {eq}"
    # os 4 eliminados empatam (mesmo stack antes da mão): dividem o 3o prêmio
    for v in eq[1:5]:
        assert abs(v - 50.0) < 1e-9, eq
    # os 2 com fichas disputam 1o e 2o normalmente
    assert abs(eq[0] + eq[5] - 800.0) < 1e-9 and eq[0] > eq[5], eq


def test_desempate_de_eliminados_pelo_stack_inicial():
    # Regra de torneio: quem quebra na mesma mão termina na frente se
    # começou a mão com mais fichas; empate divide os prêmios.
    eq = icm_equity([100.0, 0.0, 0.0, 0.0], [500.0, 300.0, 200.0, 100.0], bust_tiebreak=[40, 30, 20, 20])
    assert [round(v, 9) for v in eq] == [500.0, 300.0, 150.0, 150.0], eq


def test_eliminado_fora_do_dinheiro_fica_com_zero():
    eq = icm_equity([50.0, 0.0, 50.0], [1000.0])
    assert eq[1] == 0.0 and abs(eq[0] - 500.0) < 1e-9 and abs(eq[2] - 500.0) < 1e-9, eq


if __name__ == "__main__":
    test_conservacao_de_dinheiro()
    print("  OK -- conservacao de dinheiro")
    test_stacks_iguais_equity_igual()
    print("  OK -- stacks iguais = equity igual")
    test_monotonicidade()
    print("  OK -- monotonicidade")
    test_heads_up_winner_take_all_e_proporcional_ao_stack()
    print("  OK -- heads-up winner-take-all proporcional ao stack")
    test_bate_com_referencia_forca_bruta()
    print("  OK -- bate com referencia de forca bruta (300 mesas aleatorias)")
    test_varios_eliminados_na_mesma_mao_nao_quebra()
    print("  OK -- 4 eliminados na mesma mao: sem ZeroDivisionError, dinheiro conservado")
    test_desempate_de_eliminados_pelo_stack_inicial()
    print("  OK -- desempate de eliminados pelo stack no comeco da mao")
    test_eliminado_fora_do_dinheiro_fica_com_zero()
    print("  OK -- eliminado fora do dinheiro fica com zero")
    print("Todos os testes de icm passaram.")
