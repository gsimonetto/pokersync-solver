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
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, representative_combo, representative_combo_avoiding, hand_vs_hand_equity  # noqa: E402
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
            # sem valor em comum nunca ha carta repetida entre os
            # representativos -- o helper so' garante isso explicitamente
            combo_a = representative_combo(a)
            combo_b = representative_combo_avoiding(b, [combo_a[0:2], combo_a[2:4]])
            eq = hand_vs_hand_equity(combo_a, combo_b, iterations=fast_iterations, seed=seed)
            n_fast += 1
        matrix[(a, b)] = eq
        matrix[(b, a)] = 1.0 - eq

    return matrix, classes, {"shared_rank_pairs": n_shared, "fast_pairs": n_fast}


# ---------------------------------------------------------------------------
# Matriz de PRODUCAO (2026-09-24)
#
# A matriz acima, no padrao (250 simulacoes por par), tem erro tipico de
# ~3 pontos de equity por par (ex: AKo vs QJs pode sair 58% ou 64%) -- e
# o solver heads-up decide call/fold em cima desses numeros. A de
# producao usa o calculo com carta real pra TODOS os pares (nao so' os
# que dividem um valor) e 4000 simulacoes por par (erro tipico ~0,8
# ponto). Custa ~15 min de CPU, entao vem PRONTA no repositorio
# (engine/data/equity_matrix_169.json) e e' carregada em memoria uma
# vez so'. Se o arquivo sumir, e' recalculada (usando todos os nucleos).
# ---------------------------------------------------------------------------

PRODUCTION_EQUITY_ITERATIONS = 4000
PRODUCTION_EQUITY_SEED = 7
PRODUCTION_EQUITY_FILE = Path(__file__).resolve().parent / "data" / "equity_matrix_169.json"


def _precise_pair(args):
    a, b, iterations, seed = args
    return class_vs_class_equity(a, b, iterations=iterations, seed=seed)


def build_precise_equity_matrix(iterations=PRODUCTION_EQUITY_ITERATIONS, seed=PRODUCTION_EQUITY_SEED,
                                processes=None):
    """Equity de TODOS os pares de classes com carta real (bloqueadores),
    `iterations` simulacoes por par, uma semente fixa por par (mesmo
    resultado em qualquer maquina / numero de processos)."""
    classes = all_hand_classes()
    pairs = list(itertools.combinations(classes, 2))
    jobs = [(a, b, iterations, seed * 1_000_003 + i) for i, (a, b) in enumerate(pairs)]
    if processes == 1:
        values = [_precise_pair(j) for j in jobs]
    else:
        import multiprocessing
        with multiprocessing.Pool(processes) as pool:
            values = pool.map(_precise_pair, jobs, chunksize=64)
    matrix = {(c, c): 0.5 for c in classes}
    for (a, b), eq in zip(pairs, values):
        matrix[(a, b)] = eq
        matrix[(b, a)] = 1.0 - eq
    return matrix, classes


def save_equity_matrix(matrix, classes, path=PRODUCTION_EQUITY_FILE, meta=None):
    pairs = itertools.combinations(classes, 2)
    data = {
        "meta": meta or {},
        "classes": classes,
        # so' o triangulo de cima (a, b) com a antes de b; (b, a) = 1 - (a, b)
        "upper": [round(matrix[(a, b)], 6) for a, b in pairs],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)


def load_equity_matrix(path=PRODUCTION_EQUITY_FILE):
    data = json.loads(Path(path).read_text())
    classes = data["classes"]
    if classes != all_hand_classes():
        raise ValueError(f"{path}: lista de classes diferente da atual -- arquivo de outra versao")
    pairs = list(itertools.combinations(classes, 2))
    if len(data["upper"]) != len(pairs):
        raise ValueError(f"{path}: numero de pares errado ({len(data['upper'])} != {len(pairs)})")
    matrix = {(c, c): 0.5 for c in classes}
    for (a, b), eq in zip(pairs, data["upper"]):
        if not 0.0 <= eq <= 1.0:
            raise ValueError(f"{path}: equity fora de [0,1] em {a} vs {b}: {eq}")
        matrix[(a, b)] = eq
        matrix[(b, a)] = 1.0 - eq
    return matrix, classes


@lru_cache(maxsize=1)
def get_production_equity_matrix():
    """(matrix, classes) de producao -- carregada do arquivo pronto (rapido)
    ou, se ele nao existir/estiver corrompido, recalculada e salva."""
    try:
        return load_equity_matrix()
    except (OSError, ValueError, KeyError) as e:
        print(f"[equity] matriz pronta indisponivel ({e}); recalculando (~15 min de CPU)...", flush=True)
    matrix, classes = build_precise_equity_matrix()
    try:
        save_equity_matrix(matrix, classes, meta={"iterations": PRODUCTION_EQUITY_ITERATIONS,
                                                   "seed": PRODUCTION_EQUITY_SEED})
    except OSError:
        pass  # disco somente leitura: segue so' com a copia em memoria
    return matrix, classes


if __name__ == "__main__" and "--producao" in sys.argv:
    t0 = time.time()
    matrix, classes = build_precise_equity_matrix()
    save_equity_matrix(matrix, classes, meta={"iterations": PRODUCTION_EQUITY_ITERATIONS,
                                               "seed": PRODUCTION_EQUITY_SEED})
    print(f"Matriz de producao gerada em {time.time() - t0:.0f}s -> {PRODUCTION_EQUITY_FILE}")
    sys.exit(0)

if __name__ == "__main__":
    t0 = time.time()
    matrix, classes, stats = build_final_equity_matrix()
    dt = time.time() - t0
    print(f"Matriz final construida em {dt:.1f}s")
    print(f"  Pares com blocker real: {stats['shared_rank_pairs']}")
    print(f"  Pares com calculo rapido: {stats['fast_pairs']}")

    import pickle
    out = Path(__file__).resolve().parent.parent / "data" / "equity_matrix_final.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)  # a pasta data/ não vem no git
    with open(out, "wb") as f:
        pickle.dump({"matrix": matrix, "classes": classes}, f)
    print("Salvo em data/equity_matrix_final.pkl")
