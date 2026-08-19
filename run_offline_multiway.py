"""
Exemplo de treino offline de longa duração — pensado pra rodar no seu
PC (não no sandbox), por horas, dias ou semanas.

Uso:
    python3 run_offline_multiway.py

Ajuste MATCHUP_CONFIG abaixo pro spot que você quer resolver (squeeze,
CO vs BTN, UTG vs BB, etc). Salva checkpoint a cada N iterações, então
se o processo for interrompido (PC desligou, travou), você roda de
novo e ele continua de onde parou -- não perde o progresso.

IMPORTANTE (documentado no motor): mãos "de fronteira" (EV de
fold≈EV de agir, quase indiferentes) podem oscilar bastante entre
rodadas mesmo depois de convergido -- isso é esperado, não é bug.
Mãos claramente fortes/fracas (AA, 72o em posições ruins, etc.)
devem convergir de forma estável; se ISSO não estabilizar mesmo
depois de milhões de iterações, aí sim vale investigar.
"""

import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.multiway_rfi import MultiwayRfiSolver
from engine.hand_classes import build_equity_matrix

MATCHUP_CONFIG = {
    "seat_names": ["opener", "MP", "BB"],
    "seat_idx_in_table": [0, 1, 2],
    "seat_posts": [0.0, 0.0, 1.0],
    "table_stacks": [25, 25, 25, 40, 30, 20],
    "payouts": [500.0, 300.0, 200.0],
    "open_size": 2.2,
    "effective_stack": 25,
}

TOTAL_ITERATIONS = 5_000_000
CHECKPOINT_EVERY = 50_000
CHECKPOINT_PATH = Path("checkpoint_multiway.pkl")
EQUITY_MATRIX_PATH = Path("data/equity_matrix_cache.pkl")


def load_or_build_equity_matrix():
    if EQUITY_MATRIX_PATH.exists():
        print("Carregando matriz de equity ja calculada...")
        with open(EQUITY_MATRIX_PATH, "rb") as f:
            d = pickle.load(f)
        return d["matrix"], d["classes"]
    print("Construindo matriz de equity pairwise (só na primeira vez, ~4min)...")
    matrix, classes, _stats = build_equity_matrix()
    EQUITY_MATRIX_PATH.parent.mkdir(exist_ok=True)
    with open(EQUITY_MATRIX_PATH, "wb") as f:
        pickle.dump({"matrix": matrix, "classes": classes}, f)
    return matrix, classes


def main():
    equity_matrix, classes = load_or_build_equity_matrix()

    if CHECKPOINT_PATH.exists():
        print(f"Retomando checkpoint existente: {CHECKPOINT_PATH}")
        with open(CHECKPOINT_PATH, "rb") as f:
            state = pickle.load(f)
        solver = state["solver"]
        done_iterations = state["done_iterations"]
    else:
        print("Comecando do zero...")
        solver = MultiwayRfiSolver(
            equity_matrix=equity_matrix, classes=classes, **MATCHUP_CONFIG,
        )
        done_iterations = 0

    print(f"Progresso: {done_iterations}/{TOTAL_ITERATIONS} iteracoes ja feitas")

    while done_iterations < TOTAL_ITERATIONS:
        batch = min(CHECKPOINT_EVERY, TOTAL_ITERATIONS - done_iterations)
        t0 = time.time()
        solver.train(iterations=batch, seed=done_iterations + 1)
        done_iterations += batch
        dt = time.time() - t0

        with open(CHECKPOINT_PATH, "wb") as f:
            pickle.dump({"solver": solver, "done_iterations": done_iterations}, f)

        pct = 100 * done_iterations / TOTAL_ITERATIONS
        eta_min = (TOTAL_ITERATIONS - done_iterations) / batch * dt / 60
        print(f"[{pct:5.1f}%] {done_iterations}/{TOTAL_ITERATIONS} "
              f"({dt:.1f}s neste lote, cache equity={len(solver._equity_cache)}, "
              f"ETA ~{eta_min:.0f}min)")

    print("\nTreino concluido. Estrategia final salva no checkpoint.")
    strat = solver.average_strategy()
    with open("resultado_final.pkl", "wb") as f:
        pickle.dump(strat, f)
    print("Salvo em resultado_final.pkl")


if __name__ == "__main__":
    main()
