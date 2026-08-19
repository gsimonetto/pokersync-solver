"""
Equity multiway: probabilidade de vitória de CADA mão entre N mãos
simultâneas (não apenas 2), incluindo empate (split pot). Necessário
pra resolver showdowns onde mais de 2 jogadores foram all-in.
"""

import random
import sys
from pathlib import Path

from treys import Card, Evaluator, Deck

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_blockers import class_combos  # noqa: E402

EVALUATOR = Evaluator()


def multiway_equity(hand_classes: list, iterations=1500, seed=None):
    if seed is not None:
        random.seed(seed)
    n = len(hand_classes)
    combos_per_class = [class_combos(c) for c in hand_classes]

    wins = [0.0] * n
    valid_iters = 0
    attempts = 0
    max_attempts = iterations * 8

    while valid_iters < iterations and attempts < max_attempts:
        attempts += 1
        chosen = [random.choice(combos) for combos in combos_per_class]
        cards = []
        used = set()
        conflict = False
        for combo_str in chosen:
            c1 = Card.new(combo_str[0:2])
            c2 = Card.new(combo_str[2:4])
            if c1 in used or c2 in used or c1 == c2:
                conflict = True
                break
            used.add(c1)
            used.add(c2)
            cards.append([c1, c2])
        if conflict:
            continue

        deck = Deck()
        deck.cards = [c for c in deck.cards if c not in used]
        random.shuffle(deck.cards)
        board = deck.cards[:5]

        scores = [EVALUATOR.evaluate(board, hand) for hand in cards]
        best_score = min(scores)
        winners = [i for i, s in enumerate(scores) if s == best_score]
        share = 1.0 / len(winners)
        for i in winners:
            wins[i] += share
        valid_iters += 1

    if valid_iters == 0:
        return [1.0 / n] * n
    return [w / valid_iters for w in wins]


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
