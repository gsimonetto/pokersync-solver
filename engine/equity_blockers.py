"""
Equity classe-vs-classe com blockers reais.

A versão anterior (engine/hand_classes.py) usava UM combo fixo por
classe (ex: sempre 'AsAh' pra representar AA), o que ignora o efeito
de blocker: ter um Ás na mão reduz a chance do oponente ter AA, e
isso muda a equity em alguns matchups (principalmente quando as
classes compartilham uma carta, tipo AKo vs AQo).

Correção: em vez de fixar um combo, sorteamos um combo VÁLIDO
(respeitando par/suited/offsuit da classe) a cada iteração de Monte
Carlo, junto com o board. Isso dá uma média corretamente ponderada
sobre os combos reais sem precisar enumerar todos os pares
explicitamente — o mesmo raciocínio de amostragem que já usamos na
equity mão-a-mão, só que agora também amostrando QUAL combo da classe.
"""

import random
import sys
from pathlib import Path

from treys import Card, Evaluator, Deck

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, combo_count  # noqa: E402

EVALUATOR = Evaluator()
RANKS = "AKQJT98765432"
SUITS = "shdc"


def class_combos(hand_class: str):
    """Lista de todos os combos (com naipe) de uma classe, ex 'AKs' ->
    ['AsKs','AhKh','AdKd','AcKc']."""
    if len(hand_class) == 2:
        r = hand_class[0]
        return [f"{r}{s1}{r}{s2}" for i, s1 in enumerate(SUITS) for s2 in SUITS[i + 1:]]
    r1, r2 = hand_class[0], hand_class[1]
    suited = hand_class[2] == "s"
    if suited:
        return [f"{r1}{s}{r2}{s}" for s in SUITS]
    return [f"{r1}{s1}{r2}{s2}" for s1 in SUITS for s2 in SUITS if s1 != s2]


def class_vs_class_equity(class_a: str, class_b: str, iterations=800, seed=None) -> float:
    """Equity de class_a contra class_b, com blocker real: sorteia um
    combo valido de cada classe (sem conflito de carta entre os dois)
    a cada iteracao, junto com o board."""
    if seed is not None:
        random.seed(seed)
    combos_a = class_combos(class_a)
    combos_b = class_combos(class_b)

    wins = 0.0
    valid_iters = 0
    attempts = 0
    max_attempts = iterations * 5
    while valid_iters < iterations and attempts < max_attempts:
        attempts += 1
        combo_a_str = random.choice(combos_a)
        combo_b_str = random.choice(combos_b)
        card_a = [Card.new(combo_a_str[0:2]), Card.new(combo_a_str[2:4])]
        card_b = [Card.new(combo_b_str[0:2]), Card.new(combo_b_str[2:4])]
        used = set(card_a + card_b)
        if len(used) < 4:
            continue  # conflito de carta entre os combos sorteados, tenta outro par

        deck = Deck()
        deck.cards = [c for c in deck.cards if c not in used]
        random.shuffle(deck.cards)
        board = deck.cards[:5]

        score_a = EVALUATOR.evaluate(board, card_a)
        score_b = EVALUATOR.evaluate(board, card_b)
        if score_a < score_b:
            wins += 1.0
        elif score_a == score_b:
            wins += 0.5
        valid_iters += 1

    if valid_iters == 0:
        return 0.5
    return wins / valid_iters


def build_equity_matrix_blockers(iterations=800, seed=7):
    classes = all_hand_classes()
    matrix = {}
    for idx_a, a in enumerate(classes):
        for b in classes[idx_a + 1:]:
            eq = class_vs_class_equity(a, b, iterations=iterations, seed=seed)
            matrix[(a, b)] = eq
            matrix[(b, a)] = 1.0 - eq
    for c in classes:
        matrix[(c, c)] = 0.5
    return matrix, classes


if __name__ == "__main__":
    print("--- Comparando equity COM blocker vs SEM blocker (combo fixo) ---")
    from engine.hand_classes import hand_vs_hand_equity, representative_combo

    pairs_to_check = [
        ("AKo", "AQo", "Hero tem A e K; villain tem A e Q -> Hero bloqueia 2 dos 3 Ases restantes pro villain"),
        ("AA", "AKs", "Hero tem os 2 Ases restantes bloqueados pro villain ter AKs com As"),
        ("KQs", "AKo", "Hero bloqueia um K especifico que o villain as vezes precisa"),
        ("22", "99", "sem carta compartilhada -- blocker nao deveria mudar quase nada aqui"),
    ]

    for a, b, note in pairs_to_check:
        combo_a = representative_combo(a)
        combo_b = representative_combo(b)
        if set([combo_a[0:2], combo_a[2:4]]) & set([combo_b[0:2], combo_b[2:4]]):
            combo_b = combo_b.replace("h", "d") if "h" in combo_b else combo_b.replace("s", "c")
        eq_no_blocker = hand_vs_hand_equity(combo_a, combo_b, iterations=3000, seed=1)
        eq_blocker = class_vs_class_equity(a, b, iterations=3000, seed=1)
        diff = eq_blocker - eq_no_blocker
        print(f"\n{a} vs {b}: {note}")
        print(f"  sem blocker (combo fixo): {eq_no_blocker:.4f}")
        print(f"  com blocker (amostrado):  {eq_blocker:.4f}")
        print(f"  diferenca: {diff:+.4f}  ({'blocker teve efeito' if abs(diff) > 0.005 else 'diferenca desprezivel'})")
