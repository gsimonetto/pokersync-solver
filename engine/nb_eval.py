"""
Avaliador de mão de 7 cartas compilado com numba (2026-09-30), pra usar
DENTRO de laços numba (o `engine/fast_eval.py` usa dicionários Python,
que o numba não aceita).

Mesma ordem e MESMOS números do `fast_eval.eval7` (maior = melhor):
categoria (0 = carta alta ... 8 = straight flush) seguida de até 5
valores de desempate, 4 bits cada. Conferido em tests/preflop_v5.py
contra o fast_eval (que por sua vez foi conferido contra o treys em
todas as 2.598.960 mãos de 5 cartas).

Cartas: inteiro 0..51 = valor*4 + naipe (convenção do fast_eval).
"""

import numpy as np
from numba import njit


@njit(cache=True)
def _encode(category, r0, r1, r2, r3, r4):
    return (((((category << 4 | r0) << 4 | r1) << 4 | r2) << 4 | r3) << 4) | r4


@njit(cache=True)
def _straight_high(mask):
    for high in range(12, 3, -1):
        need = 0b11111 << (high - 4)
        if mask & need == need:
            return high
    wheel = (1 << 12) | 0b1111
    if mask & wheel == wheel:
        return 3
    return -1


@njit(cache=True)
def eval_cards(cards, n):
    """Força das `n` primeiras cartas de `cards` (5 a 7 cartas). Sem
    alocar memória (roda milhões de vezes por segundo no treino)."""
    counts = 0          # 3 bits por valor (0..4 cartas)
    m0 = 0
    m1 = 0
    m2 = 0
    m3 = 0
    for k in range(n):
        c = cards[k]
        r = c >> 2
        counts += 1 << (3 * r)
        s = c & 3
        if s == 0:
            m0 |= 1 << r
        elif s == 1:
            m1 |= 1 << r
        elif s == 2:
            m2 |= 1 << r
        else:
            m3 |= 1 << r
    fm = -1
    for m in (m0, m1, m2, m3):
        b = 0
        x = m
        while x:
            x &= x - 1
            b += 1
        if b >= 5:
            fm = m
    if fm >= 0:
        sf = _straight_high(fm)
        if sf >= 0:
            return _encode(8, sf, 0, 0, 0, 0)
        t0 = -1
        t1 = -1
        t2 = -1
        t3 = -1
        t4 = -1
        for r in range(12, -1, -1):
            if fm >> r & 1:
                if t0 < 0:
                    t0 = r
                elif t1 < 0:
                    t1 = r
                elif t2 < 0:
                    t2 = r
                elif t3 < 0:
                    t3 = r
                else:
                    t4 = r
                    break
        return _encode(5, t0, t1, t2, t3, t4)
    # sem flush
    quad = -1
    trip1 = -1
    trip2 = -1
    pair1 = -1
    pair2 = -1
    rmask = 0
    for r in range(12, -1, -1):
        c = (counts >> (3 * r)) & 7
        if c > 0:
            rmask |= 1 << r
        if c == 4:
            if quad < 0:
                quad = r
        elif c == 3:
            if trip1 < 0:
                trip1 = r
            elif trip2 < 0:
                trip2 = r
        elif c == 2:
            if pair1 < 0:
                pair1 = r
            elif pair2 < 0:
                pair2 = r
    if quad >= 0:
        for r in range(12, -1, -1):
            if r != quad and rmask >> r & 1:
                return _encode(7, quad, r, 0, 0, 0)
        return _encode(7, quad, 0, 0, 0, 0)
    if trip1 >= 0:
        best = trip2
        if pair1 > best:
            best = pair1
        if best >= 0:
            return _encode(6, trip1, best, 0, 0, 0)
    st = _straight_high(rmask)
    if st >= 0:
        return _encode(4, st, 0, 0, 0, 0)
    # até 5 valores distintos, do maior pro menor, pulando os "usados"
    if trip1 >= 0:
        used = 1 << trip1
        cat = 3
        h0 = trip1
        h1 = -1
        need = 2
    elif pair2 >= 0:
        used = (1 << pair1) | (1 << pair2)
        cat = 2
        h0 = pair1
        h1 = pair2
        need = 1
    elif pair1 >= 0:
        used = 1 << pair1
        cat = 1
        h0 = pair1
        h1 = -1
        need = 3
    else:
        used = 0
        cat = 0
        h0 = -1
        h1 = -1
        need = 5
    k0 = 0
    k1 = 0
    k2 = 0
    k3 = 0
    k4 = 0
    got = 0
    for r in range(12, -1, -1):
        if got == need:
            break
        if rmask >> r & 1 and not used >> r & 1:
            if got == 0:
                k0 = r
            elif got == 1:
                k1 = r
            elif got == 2:
                k2 = r
            elif got == 3:
                k3 = r
            else:
                k4 = r
            got += 1
    if cat == 3:
        return _encode(3, h0, k0, k1, 0, 0)
    if cat == 2:
        return _encode(2, h0, h1, k0, 0, 0)
    if cat == 1:
        return _encode(1, h0, k0, k1, k2, 0)
    return _encode(0, k0, k1, k2, k3, k4)
