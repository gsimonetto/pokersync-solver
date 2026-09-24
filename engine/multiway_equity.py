"""
Equity multiway: probabilidade de vitória de CADA mão entre N mãos
simultâneas (não apenas 2), incluindo empate (split pot). Necessário
pra resolver showdowns onde mais de 2 jogadores foram all-in.

Performance (2026-09): este é o laço mais quente do treino multiway
(medido com cProfile: ~100% do tempo de `train()` passava aqui). A
versão anterior criava um `treys.Deck()` por simulação (que monta um
gerador aleatório novo e embaralha as 52 cartas), embaralhava de novo,
e avaliava cada mão com o `treys.Evaluator` (21 combinações de 5 cartas
por mão). Agora: cartas como inteiros 0..51, mesa sorteada direto das
cartas livres, avaliação por tabela (engine/fast_eval.py, com ordem de
mãos idêntica à do treys -- ver tests/fast_eval.py). Mesma estatística
(mesma distribuição de combos e de mesas), ~10-20x mais rápido.

Efeito colateral bom: agora o resultado é REPRODUZÍVEL com a mesma
semente (o `treys.Deck()` usava um gerador próprio, semeado pelo
sistema operacional, que o `random.seed()` não controlava).
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.fast_eval import RANK_BIT, RANK_KEY, SUIT_KEY, tables  # noqa: E402
from engine.hand_classes import RANKS  # noqa: E402

_SUITS = "shdc"
_RANK_VALUE = {r: 12 - i for i, r in enumerate(RANKS)}  # 'A' -> 12 ... '2' -> 0
_COMBOS: dict[str, list[tuple[int, int]]] = {}


def class_combo_indices(hand_class: str) -> list[tuple[int, int]]:
    """Todos os combos (pares de cartas 0..51) de uma classe, ex 'AKs'
    -> 4 combos, 'AKo' -> 12, 'AA' -> 6. Mesmo conjunto que
    engine/equity_blockers.py::class_combos, em formato numérico."""
    combos = _COMBOS.get(hand_class)
    if combos is not None:
        return combos
    r1 = _RANK_VALUE[hand_class[0]]
    r2 = _RANK_VALUE[hand_class[1]]
    if len(hand_class) == 2:
        combos = [(r1 * 4 + s1, r1 * 4 + s2) for s1 in range(4) for s2 in range(s1 + 1, 4)]
    elif hand_class[2] == "s":
        combos = [(r1 * 4 + s, r2 * 4 + s) for s in range(4)]
    else:
        combos = [(r1 * 4 + s1, r2 * 4 + s2) for s1 in range(4) for s2 in range(4) if s1 != s2]
    _COMBOS[hand_class] = combos
    return combos


def multiway_equity_counts(hand_classes: list, iterations: int, rng=None):
    """Núcleo do cálculo. Devolve (vitorias, n_validas): `vitorias[i]` é
    a soma das frações de pote ganhas pela mão i (empate divide) e
    `n_validas` quantas simulações realmente rodaram.

    Rejeição de conflito de cartas (ex: 'AKs' vs 'AA' não podem usar o
    mesmo Ás) igual à versão anterior: sorteia um combo de cada classe e,
    se colidir, tenta de novo -- isso dá a distribuição correta de combos
    dado as classes. Limite de tentativas (8x `iterations`) pra nunca
    travar: combinações IMPOSSÍVEIS (ex: 3x 'AA' -- só existem 4 ases)
    devolvem n_validas=0, e quem chama decide o que fazer."""
    n = len(hand_classes)
    combos = [class_combo_indices(c) for c in hand_classes]
    sizes = [len(c) for c in combos]
    flush_suit, flush_value, nonflush = tables()
    rand = (rng or random).random
    rk_key, sk_key, rbit = RANK_KEY, SUIT_KEY, RANK_BIT

    wins = [0.0] * n
    valid = 0
    attempts = 0
    max_attempts = iterations * 8
    holes = [None] * n
    while valid < iterations and attempts < max_attempts:
        attempts += 1
        used = 0
        conflict = False
        for i in range(n):
            c1, c2 = combos[i][int(rand() * sizes[i])]
            bits = (1 << c1) | (1 << c2)
            if used & bits:
                conflict = True
                break
            used |= bits
            holes[i] = (c1, c2)
        if conflict:
            continue

        board = []
        while len(board) < 5:
            c = int(rand() * 52)
            bit = 1 << c
            if used & bit:
                continue
            used |= bit
            board.append(c)
        b0, b1, b2, b3, b4 = board
        brk = rk_key[b0] + rk_key[b1] + rk_key[b2] + rk_key[b3] + rk_key[b4]
        bsk = sk_key[b0] + sk_key[b1] + sk_key[b2] + sk_key[b3] + sk_key[b4]

        best = -1
        n_best = 0
        for i in range(n):
            c1, c2 = holes[i]
            fs = flush_suit[bsk + sk_key[c1] + sk_key[c2]]
            if fs < 0:
                v = nonflush[brk + rk_key[c1] + rk_key[c2]]
            else:
                m = 0
                for c in (b0, b1, b2, b3, b4, c1, c2):
                    if c & 3 == fs:
                        m |= rbit[c]
                v = flush_value[m]
            if v > best:
                best = v
                n_best = 1
                winners = [i]
            elif v == best:
                n_best += 1
                winners.append(i)
        share = 1.0 / n_best
        for i in winners:
            wins[i] += share
        valid += 1

    return wins, valid


def multiway_equity(hand_classes: list, iterations=1500, seed=None):
    """Equity de cada classe (mesma ordem de `hand_classes`), somando 1.
    `seed`: usa um gerador PRÓPRIO com essa semente (não mexe no
    `random` global de quem chama). Combinação impossível de cartas
    (nenhuma simulação válida) devolve divisão igual -- comportamento
    mantido por compatibilidade; o motor multiway nunca mais chega
    nesse caso desde que passou a dar as cartas de verdade (ver
    engine/multiway_rfi.py::_deal_hands)."""
    rng = random.Random(seed) if seed is not None else None
    wins, valid = multiway_equity_counts(hand_classes, iterations, rng)
    n = len(hand_classes)
    if valid == 0:
        return [1.0 / n] * n
    return [w / valid for w in wins]


if __name__ == "__main__":
    print("--- Validacao: 3-way com uma mao claramente melhor ---")
    eq = multiway_equity(["AA", "KK", "72o"], iterations=5000, seed=1)
    print(f"AA={eq[0]:.3f}  KK={eq[1]:.3f}  72o={eq[2]:.3f}  soma={sum(eq):.3f}")

    print("\n--- Validacao: heads-up (2 maos) deve bater com o motor pairwise ja validado ---")
    from engine.equity_blockers import class_vs_class_equity
    eq3 = multiway_equity(["AKo", "AQo"], iterations=8000, seed=3)
    eq_pairwise = class_vs_class_equity("AKo", "AQo", iterations=8000, seed=3)
    print(f"multiway (2 maos): AKo={eq3[0]:.4f}")
    print(f"pairwise (ja validado): AKo={eq_pairwise:.4f}")
    print(f"diferenca: {abs(eq3[0]-eq_pairwise):.4f}")
