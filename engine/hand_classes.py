"""
169 classes de mão pré-flop (ex: 'AKs', 'AKo', 'TT') + matriz de equity
classe-vs-classe, usada pela árvore de shove/fold.

IMPORTANTE — limitação conhecida desta primeira versão:
A equity aqui é calculada com UM combo representativo por classe (não
a média ponderada sobre todos os combos reais, considerando blockers
entre a mão do herói e a do vilão). Isso é uma aproximação deliberada
pra validar a árvore de decisão rápido — o efeito de blocker (ex: ter
um Ás reduz a chance do vilão ter AA) muda a equity em alguns pontos
percentuais em certos matchups. Antes de qualquer spot ir pro produto,
isso precisa virar equity combo-a-combo ponderada corretamente.
"""

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity import hand_vs_hand_equity  # noqa: E402

RANKS = "AKQJT98765432"  # ordem decrescente
SUITS = "shdc"


def all_hand_classes():
    classes = []
    for i, r1 in enumerate(RANKS):
        for j, r2 in enumerate(RANKS):
            if i == j:
                classes.append(f"{r1}{r2}")  # par, ex 'AA'
            elif i < j:
                classes.append(f"{r1}{r2}s")  # suited, maior rank primeiro
                classes.append(f"{r1}{r2}o")  # offsuit
    return classes  # 169 classes


def combo_count(hand_class: str) -> int:
    if len(hand_class) == 2:
        return 6  # par: C(4,2)
    if hand_class.endswith("s"):
        return 4  # suited: 4 naipes possiveis
    return 12  # offsuit: 4*3


def representative_combo(hand_class: str) -> str:
    """Um combo concreto (com naipes) que representa a classe, evitando
    conflito de naipe entre os dois cartoes da mesma mao."""
    if len(hand_class) == 2:
        r = hand_class[0]
        return f"{r}s{r}h"
    r1, r2 = hand_class[0], hand_class[1]
    suited = hand_class[2] == "s"
    if suited:
        return f"{r1}s{r2}s"
    return f"{r1}s{r2}h"


def build_equity_matrix(iterations=600, seed=7):
    """Retorna dict[(classe_a, classe_b)] -> equity de a contra b.
    Simetrico: equity(a,b) = 1 - equity(b,a) (aproximado, ignora
    empates residuais de arredondamento)."""
    classes = all_hand_classes()
    matrix = {}
    total_pairs = 0
    for a, b in itertools.combinations(classes, 2):
        combo_a = representative_combo(a)
        combo_b = representative_combo(b)
        # evita conflito de carta entre representativos de classes diferentes
        if set([combo_a[0:2], combo_a[2:4]]) & set([combo_b[0:2], combo_b[2:4]]):
            # tenta naipes alternativos pro combo_b pra evitar colisao
            combo_b = combo_b.replace("h", "d") if "h" in combo_b else combo_b.replace("s", "c")
        eq = hand_vs_hand_equity(combo_a, combo_b, iterations=iterations, seed=seed)
        matrix[(a, b)] = eq
        matrix[(b, a)] = 1.0 - eq
        total_pairs += 1
    for c in classes:
        matrix[(c, c)] = 0.5  # mesma classe (ex AKs vs AKs de outro jogador): coinflip aproximado
    return matrix, classes


if __name__ == "__main__":
    classes = all_hand_classes()
    print(f"Total de classes geradas: {len(classes)} (esperado 169)")
    print(f"Soma de combos (deve dar 1326): {sum(combo_count(c) for c in classes)}")

    print("\nCalculando matriz de equity (169x169 pares, pode levar alguns minutos)...")
    matrix, classes = build_equity_matrix(iterations=300)

    print("\n--- Checagens de sanidade ---")
    print(f"AA vs 72o: {matrix[('AA', '72o')]:.3f} (esperado bem alto, >0.85)")
    print(f"AKs vs AKo: {matrix[('AKs', 'AKo')]:.3f} (esperado ~coinflip)")
    print(f"KK vs AKo: {matrix[('KK', 'AKo')]:.3f} (esperado ~0.7 -- par grande vs dois overcards)")
