"""
Equity engine pré-flop: calcula a probabilidade de vitória de uma mão
(ou classe de mão) contra outra, num all-in pré-flop, via Monte Carlo.

Isso é DELIBERADAMENTE separado do motor CFR — equity é um cálculo
determinístico de "quem ganha o showdown", não faz parte do algoritmo
de equilíbrio. Usamos a lib `treys` (avaliador de mão padrão, testado
e usado amplamente na comunidade) só pra essa parte, evitando
reinventar avaliação de mão — o "cérebro" do solver (CFR) continua
100% nosso.
"""

import random
from treys import Card, Evaluator, Deck

EVALUATOR = Evaluator()

RANKS = "23456789TJQKA"


def parse_combo(combo: str):
    """'AhKd' -> [treys_card_int, treys_card_int]"""
    return [Card.new(combo[0:2]), Card.new(combo[2:4])]


def hand_vs_hand_equity(combo_a: str, combo_b: str, iterations=2000, seed=None) -> float:
    """Equity de combo_a contra combo_b (com cartas específicas, sem
    conflito de suits) via Monte Carlo, enumerando boards aleatórios."""
    if seed is not None:
        random.seed(seed)
    card_a = parse_combo(combo_a)
    card_b = parse_combo(combo_b)
    used = set(card_a + card_b)

    wins = 0.0
    for _ in range(iterations):
        deck = Deck()
        # sorted() antes do shuffle: Deck() do treys usa um Random() PRÓPRIO
        # (nao ligado ao random.seed() global) só pra embaralhar a ordem
        # inicial -- sem ordenar antes, o shuffle abaixo (que usa o `random`
        # global, o único que o parâmetro `seed` desta função controla)
        # parte de uma ordem diferente a cada chamada, e o resultado final
        # não é reprodutível mesmo passando o mesmo `seed` duas vezes.
        deck.cards = sorted(c for c in deck.cards if c not in used)
        random.shuffle(deck.cards)
        board = deck.cards[:5]
        score_a = EVALUATOR.evaluate(board, card_a)
        score_b = EVALUATOR.evaluate(board, card_b)
        # treys: menor score = mao melhor
        if score_a < score_b:
            wins += 1.0
        elif score_a == score_b:
            wins += 0.5
    return wins / iterations


if __name__ == "__main__":
    # Validacao contra numeros de equity amplamente conhecidos e
    # publicados (mesmo principio da Fase 1: nao confiar sem checar
    # contra uma referencia externa conhecida).
    checks = [
        ("AhAd", "KsKc", 0.82, "AA vs KK (classico, ~82%)"),
        ("AhKd", "QsQc", 0.46, "AKo vs QQ (~46-47%, coinflip-ish)"),
        ("7h2c", "AsKd", 0.32, "72o vs AKo (nao e vs AA, equity real ~32%)"),
        ("AhKh", "AsKc", 0.52, "AK mesmo par de cartas, naipes diferentes (~coinflip + edge de flush)"),
    ]
    print("--- Validacao do motor de equity (Monte Carlo, 20k iter) ---")
    for combo_a, combo_b, expected, label in checks:
        eq = hand_vs_hand_equity(combo_a, combo_b, iterations=20000, seed=1)
        status = "OK" if abs(eq - expected) < 0.03 else "DIVERGENTE"
        print(f"  {label:55s} calculado={eq:.3f}  esperado~={expected:.3f}  [{status}]")
