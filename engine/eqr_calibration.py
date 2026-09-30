"""
Calibração da realização de equity (EQR) do pré-flop v5 com o solver
pós-flop (engine/postflop_fast.py) -- 2026-09-30.

O pré-flop v5 não joga o pós-flop: quando a mão vai pro flop sem all-in,
cada um leva "equity x fator de realização" do pote. Aqui o fator é
MEDIDO: resolve flops de verdade com os ranges que o pré-flop v5 produz
e compara, pra cada tipo de mão,
    valor jogando o pós-flop (EV)  /  valor se só fosse ao showdown (equity).
>1 = a mão ganha mais que a equity (posição, jogabilidade); <1 = menos.

Os dois valores saem do MESMO solver: a equity é o valor numa árvore em
que ninguém aposta (só check até o showdown) -- mesma remoção de cartas,
mesmas mesas, então a razão é limpa.
"""

import numpy as np

from engine.postflop_fast import FastPostflopSolver, TreeConfig, _class_of

# árvore enxuta (a mesma do benchmark): flop 33%, turn 66%, river 75%, 1 raise
CALIB_TREE = TreeConfig(bet_sizes=((0.33,), (0.66,), (0.75,)), raise_sizes=((0.75,), (0.75,), (0.75,)),
                        max_raises=1)
CHECKDOWN = TreeConfig(bet_sizes=((), (), ()), raise_sizes=((), (), ()), max_raises=0, allin=False)

# flops variados (alto/baixo, pareado, monotone, dois naipes, conectado)
CALIB_FLOPS = ["As Kd 7c", "Kh Qd 4s", "Th 9h 3c", "8s 7d 6c", "5h 4h 2d", "Jc Jd 5s",
               "Qs 9s 2s", "Ad 6h 6c", "Td 8c 2h", "7s 3h 2c", "Kc Js Ts", "9d 5d 4c"]


def spot_realization(board, range_oop, range_ip, pot, stack, iterations=60, tree=CALIB_TREE, threads=None):
    """Devolve ({classe: [soma EV, soma equity]} de OOP, idem de IP,
    exploitability em % do pote). As somas já vêm pesadas pela chance de
    cada combo estar ali (peso no range x mãos do oponente sem carta em
    comum), então dá pra somar entre flops e dividir no fim."""
    s = FastPostflopSolver(board, range_oop, range_ip, pot, stack, config=tree, threads=threads)
    s.train(iterations)
    eq = FastPostflopSolver(board, range_oop, range_ip, pot, stack, config=CHECKDOWN, threads=threads)
    out = []
    for p in (0, 1):
        cfv = s._run(p, 2)
        cfe = eq._run(p, 2)
        w = s.hands[p][1]
        acc = {}
        for i, (a, b) in enumerate(s.hands[p][0]):
            d = acc.setdefault(_class_of(a, b), [0.0, 0.0])
            d[0] += w[i] * cfv[i]
            d[1] += w[i] * cfe[i]
        out.append(acc)
    return out[0], out[1], s.exploitability_pct()


def merge(total, part):
    for cl, (ev, e) in part.items():
        d = total.setdefault(cl, [0.0, 0.0])
        d[0] += ev
        d[1] += e
    return total


def factors(acc, min_equity_mass=0.0):
    """{classe: fator} a partir das somas acumuladas."""
    return {cl: ev / e for cl, (ev, e) in acc.items() if e > min_equity_mass}
