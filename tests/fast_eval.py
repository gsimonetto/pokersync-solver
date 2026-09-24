"""
Validação de engine/fast_eval.py (avaliador de mão rápido) contra a
biblioteca `treys` (referência já usada no resto do projeto).

O avaliador rápido só pode substituir o treys se ordenar as mãos
EXATAMENTE igual -- qualquer diferença mudaria quem ganha um showdown.
Três checagens:

1. EXAUSTIVA em 5 cartas: todas as 2.598.960 mãos possíveis. As 7.462
   classes de força do treys precisam corresponder 1 a 1 às do avaliador
   rápido, na mesma ordem (invertida: aqui maior = melhor).
2. 7 cartas aleatórias (o caso real de hold'em: 2 da mão + 5 da mesa):
   a versão por tabela (eval7) tem que bater com a versão direta
   (value_any) e manter a mesma ordem do treys.
3. Casos clássicos escritos à mão (roda A-5, flush vs sequência, full
   house com duas trincas, etc).
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from treys import Card, Evaluator  # noqa: E402

from engine.fast_eval import RANK_CHARS, SUIT_CHARS, card_index, eval7, value_any  # noqa: E402

EVALUATOR = Evaluator()
TREYS_CARD = [Card.new(RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]) for c in range(52)]


def _check_order(pairs, label):
    """pairs: lista de (rank_treys, valor_rapido). Confere que a relação é
    uma bijeção que inverte a ordem (menor no treys = maior aqui)."""
    treys_to_fast = {}
    fast_to_treys = {}
    for t, f in pairs:
        if treys_to_fast.setdefault(t, f) != f:
            raise AssertionError(f"{label}: mesma força no treys ({t}) virou valores diferentes aqui")
        if fast_to_treys.setdefault(f, t) != t:
            raise AssertionError(f"{label}: mesmo valor aqui ({f}) veio de forças diferentes no treys")
    ordered = sorted(treys_to_fast.items())
    for (t1, f1), (t2, f2) in zip(ordered, ordered[1:]):
        assert f1 > f2, f"{label}: ordem invertida entre treys {t1} e {t2}"
    return len(treys_to_fast)


def test_exaustivo_5_cartas():
    pairs = set()
    for combo in itertools.combinations(range(52), 5):
        t = EVALUATOR._five([TREYS_CARD[c] for c in combo])
        pairs.add((t, value_any(combo)))
    n_classes = _check_order(pairs, "5 cartas")
    assert n_classes == 7462, f"deveriam existir 7462 classes de força, achei {n_classes}"
    print(f"  OK -- 2.598.960 mãos de 5 cartas, {n_classes} classes de força batem 1 a 1 com o treys")


def test_7_cartas_aleatorias(n=400_000, seed=11):
    rng = random.Random(seed)
    pairs = set()
    for _ in range(n):
        cards = rng.sample(range(52), 7)
        fast = eval7(cards)
        assert fast == value_any(cards), f"eval7 divergiu da versão direta em {cards}"
        t = EVALUATOR.evaluate([TREYS_CARD[c] for c in cards[:2]], [TREYS_CARD[c] for c in cards[2:]])
        pairs.add((t, fast))
    n_classes = _check_order(pairs, "7 cartas")
    print(f"  OK -- {n:,} mãos de 7 cartas: tabela == versão direta, mesma ordem do treys ({n_classes} classes vistas)")


def _v(cards_str):
    return eval7([card_index(c) for c in cards_str.split()])


def test_casos_classicos():
    # roda (A-5) perde pra sequência 6-high
    assert _v("Ah 2c 3d 4s 5h Kc Kd") < _v("2c 3d 4s 5h 6d Kc Kh")
    # roda ganha de trinca
    assert _v("Ah 2c 3d 4s 5h Kc Kd") > _v("Kh Kc Kd 2s 7h 9c Jd")
    # flush ganha de sequência
    assert _v("Ah 2h 7h 9h Jh Ks Qd") > _v("9c Ts Jd Qh Kc 2s 3d")
    # full house com duas trincas: usa a trinca maior + par da menor
    assert _v("Kh Kc Kd 7s 7h 7c 2d") > _v("Kh Kc Kd 6s 6h 6c Ad")
    # quadra: kicker vem da maior carta restante (mesmo que seja de uma trinca)
    assert _v("5h 5c 5d 5s Kh Kc Kd") > _v("5h 5c 5d 5s Qh Qc 2d")
    assert _v("5h 5c 5d 5s Kh Kc Kd") < _v("5h 5c 5d 5s Qh Qc Ad")
    # empate de verdade (mesa joga): mesmo valor
    assert _v("2c 3d Ah Kh Qh Jh Th") == _v("4c 7d Ah Kh Qh Jh Th")
    # straight flush > quadra
    assert _v("5h 6h 7h 8h 9h Ac Ad") > _v("Ah Ac Ad As Kh Qc 2d")
    # carta inválida é rejeitada com mensagem clara
    try:
        card_index("1h")
        raise AssertionError("deveria rejeitar carta inválida")
    except ValueError:
        pass
    print("  OK -- casos clássicos (roda, flush x sequência, full house, quadra, empate, straight flush)")


if __name__ == "__main__":
    test_casos_classicos()
    test_7_cartas_aleatorias()
    test_exaustivo_5_cartas()
    print("Todos os testes de fast_eval passaram.")
