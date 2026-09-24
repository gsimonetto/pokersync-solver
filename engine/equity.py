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
import sys
from pathlib import Path

from treys import Card, Evaluator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.fast_eval import card_index, eval7  # noqa: E402

EVALUATOR = Evaluator()

RANKS = "23456789TJQKA"


def parse_combo(combo: str):
    """'AhKd' -> [treys_card_int, treys_card_int]"""
    return [Card.new(combo[0:2]), Card.new(combo[2:4])]


def parse_combo_indices(combo: str) -> tuple[int, int]:
    """'AhKd' -> (índice, índice) no formato 0..51 de engine/fast_eval.py.
    Levanta ValueError com mensagem clara pra combo mal formado (ex 'AhK',
    'ahkd', '1hKd') ou com a mesma carta duas vezes ('AhAh') -- antes isso
    virava um KeyError solto do treys (erro 500 na API)."""
    if not isinstance(combo, str) or len(combo.strip()) != 4:
        raise ValueError(f"combo invalido: {combo!r} (formato esperado: 2 cartas, ex 'AhKd')")
    combo = combo.strip()
    c1, c2 = card_index(combo[0:2]), card_index(combo[2:4])
    if c1 == c2:
        raise ValueError(f"combo com a mesma carta duas vezes: {combo!r}")
    return c1, c2


def _sample_board(used_mask: int, rng):
    """5 cartas distintas fora de `used_mask` (bits 0..51)."""
    board = []
    rand = rng.random
    while len(board) < 5:
        c = int(rand() * 52)
        bit = 1 << c
        if used_mask & bit:
            continue
        used_mask |= bit
        board.append(c)
    return board


def hand_vs_hand_outcomes(combo_a: str, combo_b: str, iterations=2000, seed=None):
    """(P(a vence), P(empate), P(b vence)) de combo_a contra combo_b, via
    Monte Carlo sobre a mesa. `seed`: gerador próprio com essa semente (não
    mexe no `random` global de quem chama). Levanta ValueError se as duas
    mãos dividem uma carta."""
    a1, a2 = parse_combo_indices(combo_a)
    b1, b2 = parse_combo_indices(combo_b)
    if len({a1, a2, b1, b2}) != 4:
        raise ValueError(f"as duas mãos dividem uma carta: {combo_a!r} vs {combo_b!r}")
    rng = random.Random(seed) if seed is not None else random
    used = (1 << a1) | (1 << a2) | (1 << b1) | (1 << b2)
    wins = ties = 0
    for _ in range(iterations):
        board = _sample_board(used, rng)
        va = eval7([a1, a2, *board])
        vb = eval7([b1, b2, *board])
        if va > vb:
            wins += 1
        elif va == vb:
            ties += 1
    return wins / iterations, ties / iterations, (iterations - wins - ties) / iterations


def hand_vs_hand_equity(combo_a: str, combo_b: str, iterations=2000, seed=None) -> float:
    """Equity de combo_a contra combo_b (vitória + metade do empate), com
    cartas específicas, via Monte Carlo sobre a mesa.

    2026-09: avaliador próprio (engine/fast_eval.py, ordem de mãos idêntica
    à do treys) e mesa sorteada direto das cartas livres -- ~10x mais
    rápido que criar um treys.Deck() por simulação, e reprodutível com
    `seed` sem precisar do truque de ordenar o baralho."""
    p_win, p_tie, _ = hand_vs_hand_outcomes(combo_a, combo_b, iterations, seed)
    return p_win + 0.5 * p_tie


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
