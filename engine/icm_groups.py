"""
ICM exato (Malmuth-Harville) pra torneio INTEIRO -- mesa + jogadores das
outras mesas -- e os cenários de ICM do pré-flop v5 (2026-09-30).

Por que existe: `engine/icm.py` faz a conta por subconjuntos de
jogadores (~2^n estados) -- ótimo pra uma mesa de 9, impossível pra uma
bolha com 20+ jogadores vivos. Mas numa mão de pré-flop quase todo mundo
fica com o MESMO stack (quem está em outras mesas, quem foldou sem pôr
fichas): agrupando jogadores de stack igual, o estado da conta passa a
ser "quantos de cada grupo ainda não foram colocados" -- poucos milhares
de estados, conta exata e rápida. Mesmo número que o icm.py (conferido
em tests/preflop_v5.py).

Eliminados (stack 0) ficam com as posições depois de todos os vivos,
dividindo igualmente (no pré-flop v5 todo mundo da mesa começa com o
mesmo stack -- o desempate "quem começou com mais" dá empate).
"""

from functools import lru_cache


def icm_grouped(stacks, payouts):
    """$EV de cada jogador (mesma ordem de `stacks`)."""
    n = len(stacks)
    alive_vals = sorted({float(s) for s in stacks if s > 0})
    counts = tuple(sum(1 for s in stacks if s > 0 and float(s) == v) for v in alive_vals)
    m = sum(counts)
    per_group = _group_equity(tuple(alive_vals), counts, tuple(payouts))
    busted = [i for i in range(n) if not stacks[i] > 0]
    bust_share = 0.0
    if busted:
        prizes = sum(payouts[k] for k in range(m, min(m + len(busted), len(payouts))))
        bust_share = prizes / len(busted)
    out = []
    for s in stacks:
        if s > 0:
            g = alive_vals.index(float(s))
            out.append(per_group[g] / counts[g])
        else:
            out.append(bust_share)
    return out


@lru_cache(maxsize=200_000)
def _group_equity(vals, counts, payouts):
    """Soma do $ esperado de cada GRUPO (dividir pelo tamanho do grupo dá
    o de cada jogador). DP pela ordem de chegada: a cada posição, quem a
    ocupa sai de um grupo com chance (restantes do grupo x stack) / total."""
    k_max = min(len(payouts), sum(counts))
    eq = [0.0] * len(vals)
    frontier = {counts: 1.0}
    for place in range(k_max):
        prize = payouts[place]
        nxt = {}
        for state, p in frontier.items():
            total = sum(c * v for c, v in zip(state, vals))
            for g, (c, v) in enumerate(zip(state, vals)):
                if c == 0:
                    continue
                q = p * c * v / total
                eq[g] += q * prize
                if place + 1 < k_max:
                    ns = state[:g] + (c - 1,) + state[g + 1:]
                    nxt[ns] = nxt.get(ns, 0.0) + q
        frontier = nxt
    return tuple(eq)


# ---------------------------------------------------------------------------
# cenários
# ---------------------------------------------------------------------------

def _ladder(n_paid, decay=0.85):
    """Premiação típica de MTT em % do que ainda falta pagar: o k-ésimo
    lugar recebe proporcional a 1/k^decay (1o ~6,5x o 9o, ~12x o 18o)."""
    w = [1.0 / (k ** decay) for k in range(1, n_paid + 1)]
    s = sum(w)
    return [100.0 * x / s for x in w]


# players_left = quantos jogadores ainda vivos no torneio (mesa + outras
# mesas); paid = quantos são pagos. Stacks das outras mesas = mesmo stack
# da mesa (média). Prêmios convertidos pra "bb de ICM": o prize pool
# inteiro vale o total de fichas em jogo -- assim os valores ficam na mesma
# escala das fichas (e o limite da checagem, em bb, continua fazendo
# sentido).
SCENARIOS = {
    "bolha": {"desc": "bolha: 1 jogador pra entrar no dinheiro", "players_left": 19, "paid": 18},
    "perto_ft": {"desc": "2 mesas pra mesa final, todos no dinheiro", "players_left": 14, "paid": 14},
    "mesa_final": {"desc": "mesa final (só quem está na mesa)", "players_left": None, "paid": None},
    "satelite": {"desc": "satélite: 10 vagas iguais, 11 vivos", "players_left": 11, "paid": 10,
                 "flat": True},
}


def scenario_payouts(name, table_size, stack):
    """(payouts em bb de ICM, stacks das outras mesas) do cenário."""
    sc = SCENARIOS[name]
    left = sc["players_left"] or table_size
    paid = sc["paid"] or table_size
    if left < table_size:
        raise ValueError(f"cenário {name}: {left} vivos é menos que a mesa ({table_size})")
    if sc.get("flat"):
        pcts = [100.0 / paid] * paid
    else:
        pcts = _ladder(paid)
    total_chips = left * stack
    payouts = [total_chips * p / 100.0 for p in pcts]
    others = [float(stack)] * (left - table_size)
    return payouts, others
