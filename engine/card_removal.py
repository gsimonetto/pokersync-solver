"""
Remoção de cartas (card removal) entre as mãos dos jogadores -- 2026-09-24.

Os motores sorteavam a CLASSE de cada jogador de forma independente
(ex: SB com AA e BB com AA tinha a mesma chance que qualquer outra
dupla). Na mesa real as cartas saem de UM baralho: se o SB tem AA, sobram
só 2 ases, e o BB tem AA 5,5x menos vezes (1/1225 em vez de 6/1326), tem
Ás na mão bem menos vezes, etc. É o efeito "bloqueador" que ferramentas
como HRC/ICMIZER consideram.

Aqui ficam as peças compartilhadas:
- CLASS_OF[c1][c2]: classe ('AKs', 'AKo', 'AA') de duas cartas reais
  (índices 0..51, convenção de engine/fast_eval.py).
- pair_counts(classes): quantos pares de combos (sem carta repetida)
  existem pra cada dupla de classes -- proporcional à chance real da
  dupla sair num baralho de verdade.
- conditional_opponent_weights(classes): P(classe do oponente | minha
  classe), com remoção de cartas.
"""

import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.fast_eval import RANK_CHARS  # noqa: E402


def _build_class_of_cards():
    table = [[None] * 52 for _ in range(52)]
    for c1 in range(52):
        for c2 in range(52):
            if c1 == c2:
                continue
            hi, lo = max(c1 >> 2, c2 >> 2), min(c1 >> 2, c2 >> 2)
            name = RANK_CHARS[hi] + RANK_CHARS[lo]
            if hi != lo:
                name += "s" if (c1 & 3) == (c2 & 3) else "o"
            table[c1][c2] = name
    return table


CLASS_OF = _build_class_of_cards()


@lru_cache(maxsize=None)
def _pair_counts_cached(classes: tuple):
    from engine.multiway_equity import class_combo_indices
    masks = {c: [(1 << a) | (1 << b) for a, b in class_combo_indices(c)] for c in classes}
    counts = {}
    for a in classes:
        ma = masks[a]
        row = {}
        for b in classes:
            mb = masks[b]
            row[b] = sum(1 for x in ma for y in mb if not x & y)
        counts[a] = row
    return counts


def pair_counts(classes):
    """{a: {b: número de pares (combo de a, combo de b) sem carta em comum}}.
    Simétrico. Soma total = 1326 * 1225 (todas as duplas de mãos)."""
    return _pair_counts_cached(tuple(classes))


def conditional_opponent_weights(classes):
    """{minha: {dele: P(dele | minha)}} com remoção de cartas -- cada linha
    soma 1. Como o baralho é um só, a mesma tabela serve pros dois lados
    (P(b|a) pro SB olhando o BB e P(a|b) pro BB olhando o SB)."""
    counts = pair_counts(classes)
    out = {}
    for a, row in counts.items():
        total = sum(row.values())
        out[a] = {b: n / total for b, n in row.items()}
    return out
