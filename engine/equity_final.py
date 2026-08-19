"""
Matriz de equity final (169x169), híbrida por performance:
- Pares de classes que COMPARTILHAM UM RANK (ex: AKo vs AQo, ambos têm
  Ás) recebem o cálculo com blocker real (amostra combo específico a
  cada iteração) — é onde o blocker de fato muda a equity.
- Pares sem rank em comum (ex: 22 vs 99) usam o cálculo mais rápido
  (combo fixo), porque o efeito de blocker aí é desprezível (validado
  em engine/equity_blockers.py: diferença dentro do ruído de Monte
  Carlo).

Isso reduz o trabalho caro de ~14.196 pares pra ~3.822 (27%), mantendo
a correção onde ela importa.
"""

import itertools
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, representative_combo, hand_vs_hand_equity  # noqa: E402
from engine.equity_blockers import class_vs_class_equity  # noqa: E402


def ranks_of(hand_class: str):
    if len(hand_class) == 2:
        return {hand_class[0]}
    return {hand_class[0], hand_class[1]}


def build_final_equity_matrix(fast_iterations=250, blocker_iterations=250, seed=7):
    classes = all_hand_classes()
    matrix = {}

    for c in classes:
        matrix[(c, c)] = 0.5

    n_shared, n_fast = 0, 0
    for a, b in itertools.combinations(classes, 2):
        if ranks_of(a) & ranks_of(b):
            eq = class_vs_class_equity(a, b, iterations=blocker_iterations, seed=seed)
            n_shared += 1
        else:
            combo_a = representative_combo(a)
            combo_b = representative_combo(b)
            if set([combo_a[0:2], combo_a[2:4]]) & set([combo_b[0:2], combo_b[2:4]]):
                combo_b = combo_b.replace("h", "d") if "h" in combo_b else combo_b.replace("s", "c")
            eq = hand_vs_hand_equity(combo_a, combo_b, iterations=fast_iterations, seed=seed)
            n_fast += 1
        matrix[(a, b)] = eq
        matrix[(b, a)] = 1.0 - eq

    return matrix, classes, {"shared_rank_pairs": n_shared, "fast_pairs": n_fast}


if __name__ == "__main__":
    t0 = time.time()
    matrix, classes, stats = build_final_equity_matrix()
    dt = time.time() - t0
    print(f"Matriz final construida em {dt:.1f}s")
    print(f"  Pares com blocker real: {stats['shared_rank_pairs']}")
    print(f"  Pares com calculo rapido: {stats['fast_pairs']}")

    import pickle
    with open(str(Path(__file__).resolve().parent.parent / "data" / "equity_matrix_final.pkl"), "wb") as f:
        pickle.dump({"matrix": matrix, "classes": classes}, f)
    print("Salvo em data/equity_matrix_final.pkl")
