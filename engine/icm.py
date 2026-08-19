"""
ICM (Independent Chip Model) via algoritmo Malmuth-Harville.

Converte uma distribuição de stacks (fichas) numa mesa de torneio em
"equity" de dinheiro real, dado a estrutura de premiação (payouts por
posição). Isso é o que faz o chip EV e o $EV divergirem perto de
bolha/mesa final — fundamental pra qualquer solver de MTT.

Este módulo é isolado do CFR de propósito, igual o motor de equity:
ICM é um cálculo probabilístico bem definido (não faz parte do
algoritmo de equilíbrio em si), então validamos ele separadamente.
"""

from functools import lru_cache


def icm_equity(stacks: list[float], payouts: list[float]) -> list[float]:
    """
    stacks: lista de stacks (fichas) de cada jogador, na mesa atual.
    payouts: lista de premios por posicao (payouts[0] = 1o lugar,
             payouts[1] = 2o lugar, etc). len(payouts) pode ser menor
             que len(stacks) (nem todo mundo premiado).
    Retorna: lista de $EV por jogador, na mesma ordem de `stacks`.
    """
    n = len(stacks)
    stacks_t = tuple(stacks)

    @lru_cache(maxsize=None)
    def first_place_probs(remaining: tuple) -> tuple:
        total = sum(stacks_t[i] for i in remaining)
        return tuple(stacks_t[i] / total for i in remaining)

    equity = [0.0] * n

    def recurse(remaining: tuple, payout_idx: int, prob_reach: float):
        if payout_idx >= len(payouts) or len(remaining) == 0:
            return
        if len(remaining) == 1:
            equity[remaining[0]] += prob_reach * payouts[payout_idx]
            return
        probs = first_place_probs(remaining)
        for idx, p in zip(remaining, probs):
            equity[idx] += prob_reach * p * payouts[payout_idx]
            rest = tuple(x for x in remaining if x != idx)
            recurse(rest, payout_idx + 1, prob_reach * p)

    recurse(tuple(range(n)), 0, 1.0)
    return equity


if __name__ == "__main__":
    print("--- Validacao do calculo de ICM (propriedades matematicas, nao numeros decorados) ---")

    # Propriedade 1: soma das equities = soma dos payouts (dinheiro nao pode sumir nem surgir)
    stacks = [5000, 3000, 2000]
    payouts = [500.0, 300.0, 200.0]
    eq = icm_equity(stacks, payouts)
    total_eq = sum(eq)
    total_payout = sum(payouts)
    print(f"Propriedade 1 (conservacao de dinheiro): soma equity={total_eq:.2f}, "
          f"soma payouts={total_payout:.2f}  [{'OK' if abs(total_eq-total_payout)<0.01 else 'FALHOU'}]")

    # Propriedade 2: stacks iguais -> equity igual (split exato do prize pool)
    stacks_eq = [1000, 1000, 1000]
    eq2 = icm_equity(stacks_eq, payouts)
    expected_each = total_payout / 3
    ok2 = all(abs(v - expected_each) < 0.01 for v in eq2)
    print(f"Propriedade 2 (stacks iguais = equity igual): {eq2} "
          f"esperado {expected_each:.2f} cada  [{'OK' if ok2 else 'FALHOU'}]")

    # Propriedade 3: monotonicidade -- mais fichas nunca pode dar menos $EV
    stacks3a = [4000, 3000, 3000]
    stacks3b = [5000, 2500, 2500]  # jogador 0 ganhou fichas, os outros perderam igualmente
    eq3a = icm_equity(stacks3a, payouts)
    eq3b = icm_equity(stacks3b, payouts)
    ok3 = eq3b[0] > eq3a[0]
    print(f"Propriedade 3 (monotonicidade): jogador0 com mais fichas tem mais $EV? "
          f"{eq3a[0]:.2f} -> {eq3b[0]:.2f}  [{'OK' if ok3 else 'FALHOU'}]")

    # Caso extremo: 2 jogadores, winner-take-all -- ICM = chip EV exatamente
    # (nao ha diferenca entre chip e $ quando so tem 1 premio e 2 jogadores)
    stacks4 = [7000, 3000]
    payouts4 = [1000.0]
    eq4 = icm_equity(stacks4, payouts4)
    expected4 = [1000.0 * 7000/10000, 1000.0 * 3000/10000]
    ok4 = all(abs(a-b) < 0.01 for a, b in zip(eq4, expected4))
    print(f"Caso HU winner-take-all (deve ser exatamente proporcional ao stack): "
          f"{eq4} esperado {expected4}  [{'OK' if ok4 else 'FALHOU'}]")
