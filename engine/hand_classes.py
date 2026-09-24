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


def representative_combo_avoiding(hand_class: str, used_cards) -> str:
    """Primeiro combo da classe (na ordem de naipes s, h, d, c) que não usa
    nenhuma carta de `used_cards`. Sempre existe: uma mão de 2 cartas
    bloqueia no máximo 2 dos combos possíveis de qualquer classe."""
    used = set(used_cards)
    if len(hand_class) == 2:
        r = hand_class[0]
        candidates = [f"{r}{s1}{r}{s2}" for i, s1 in enumerate(SUITS) for s2 in SUITS[i + 1:]]
    elif hand_class[2] == "s":
        candidates = [f"{hand_class[0]}{s}{hand_class[1]}{s}" for s in SUITS]
    else:
        candidates = [f"{hand_class[0]}{s1}{hand_class[1]}{s2}" for s1 in SUITS for s2 in SUITS if s1 != s2]
    for combo in candidates:
        if combo[0:2] not in used and combo[2:4] not in used:
            return combo
    raise ValueError(f"nenhum combo de {hand_class} livre de {sorted(used)}")


def build_equity_matrix(iterations=600, seed=7):
    """Retorna dict[(classe_a, classe_b)] -> equity de a contra b.
    Simetrico: equity(a,b) = 1 - equity(b,a) (aproximado, ignora
    empates residuais de arredondamento).

    Correcao (2026-09-24): o desvio de colisao antigo (trocar 'h' por 'd'
    ou 's' por 'c' no combo de b) nem sempre resolvia -- ex: AA (AsAh)
    contra AKo (AsKh) virava AsAh vs AsKd, as DUAS maos com o As, e a
    equity saia de uma mesa impossivel. Afetava os testes de push/fold e o
    PushFoldSolver sem matriz informada (os jobs de producao sempre passam
    a matriz de engine/equity_final.py, que nao tinha esse problema)."""
    classes = all_hand_classes()
    matrix = {}
    total_pairs = 0
    for a, b in itertools.combinations(classes, 2):
        combo_a = representative_combo(a)
        combo_b = representative_combo_avoiding(b, [combo_a[0:2], combo_a[2:4]])
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
