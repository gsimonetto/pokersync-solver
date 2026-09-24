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

def icm_equity(stacks: list[float], payouts: list[float], bust_tiebreak: list[float] | None = None) -> list[float]:
    """
    stacks: lista de stacks (fichas) de cada jogador, na mesa atual.
    payouts: lista de premios por posicao (payouts[0] = 1o lugar,
             payouts[1] = 2o lugar, etc). len(payouts) pode ser menor
             que len(stacks) (nem todo mundo premiado).
    bust_tiebreak: opcional, mesma ordem de `stacks` -- criterio de
             desempate entre jogadores ELIMINADOS na mesma mao (stack
             final 0). Regra padrao de torneio: quem comecou a mao com
             MAIS fichas termina na frente; valores iguais empatam e
             dividem igualmente os premios das posicoes que ocupam. Sem
             esse parametro, todos os eliminados empatam entre si.
    Retorna: lista de $EV por jogador, na mesma ordem de `stacks`.

    Correcao (2026-09): a versao anterior quebrava com ZeroDivisionError
    quando 2+ jogadores terminavam com 0 fichas e ainda sobrava premio
    pra distribuir entre eles (a recursao chegava num grupo so' de
    stacks zerados e dividia por soma 0). Isso acontece de verdade no
    treino multiway (ex: HJ vs BB -- 5 jogadores all-in, 1 ganha, 4
    quebram) e travava o run_offline_all_positions.py logo na primeira
    iteracao de HJ, MP, UTG+1 e UTG. Agora:
      - jogadores com fichas disputam as primeiras posicoes pelo
        Malmuth-Harville normal (mesmos numeros de antes, ate' a ultima
        casa decimal -- ver tests/icm.py);
      - jogadores eliminados ficam com as posicoes seguintes, na ordem
        de `bust_tiebreak` (empate = divide os premios).

    Implementacao por programacao dinamica sobre SUBCONJUNTOS de quem ja
    foi colocado (em vez de percorrer cada ordem de chegada possivel):
    mesma formula, mas o custo cai de n!/(n-k)! pra ~2^n no pior caso
    (ex: mesa final de 9 com 9 premios: 362.880 caminhos -> ~2.300
    estados). Com poucos premios (o caso comum, 3 pagos) os dois sao
    rapidos; com muitos premios a versao antiga podia levar minutos por
    chamada.
    """
    n = len(stacks)
    equity = [0.0] * n
    if n == 0 or not payouts:
        return equity

    alive = [i for i in range(n) if stacks[i] > 0]
    busted = [i for i in range(n) if not stacks[i] > 0]

    # --- quem tem fichas: Malmuth-Harville por DP de subconjuntos ---
    # frontier[mascara] = probabilidade de EXATAMENTE os jogadores da
    # mascara terem ocupado (em qualquer ordem) as primeiras posicoes.
    m = len(alive)
    places_alive = min(len(payouts), m)
    if places_alive > 0:
        s = [float(stacks[i]) for i in alive]
        frontier = {0: 1.0}
        for place in range(places_alive):
            prize = payouts[place]
            is_last = place + 1 == places_alive
            next_frontier: dict[int, float] = {}
            for mask, p_mask in frontier.items():
                remaining = [j for j in range(m) if not (mask >> j) & 1]
                total = sum(s[j] for j in remaining)
                for j in remaining:
                    p_j = p_mask * s[j] / total
                    equity[alive[j]] += p_j * prize
                    if not is_last:
                        key = mask | (1 << j)
                        next_frontier[key] = next_frontier.get(key, 0.0) + p_j
            frontier = next_frontier

    # --- eliminados: posicoes depois de todos os que tem fichas ---
    if busted and len(payouts) > m:
        if bust_tiebreak is None:
            groups = [busted]
        else:
            by_value: dict[float, list[int]] = {}
            for i in busted:
                by_value.setdefault(bust_tiebreak[i], []).append(i)
            groups = [by_value[v] for v in sorted(by_value, reverse=True)]
        place = m
        for group in groups:
            prizes = sum(payouts[k] for k in range(place, min(place + len(group), len(payouts))))
            for i in group:
                equity[i] += prizes / len(group)
            place += len(group)

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
