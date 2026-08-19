"""
Validação do motor no TURN (board de 4 cartas, falta o river) --
engine/postflop.py::PostflopSolver.

Dois testes:

1. Cross-check EXATO (sem tolerância, é determinístico) do novo
   `runout_equity` -- reimplementado de forma independente aqui (loop
   simples sobre as 46 cartas possíveis do river, sem usar cache nem
   recursão) e comparado byte a byte contra o valor que o motor
   calcula. Isso é o teste de regressão mais importante desta v2: é
   exatamente o código NOVO (nó de chance / equity de "correr o
   board") que não existia na v1 (river-only).

2. Mesma validação de MDF já feita no river (tests/postflop_river.py),
   agora com uma decisão all-in no TURN (falta uma carta pra sair).
   A formula fechada `call_freq = pote/(pote+aposta)` continua valendo
   MESMO com uma carta por vir, DESDE QUE o valor sempre vença e o
   blefe sempre perca em QUALQUER card do river -- por isso as classes
   de blefe aqui foram escolhidas com cuidado pra nao terem NENHUMA
   chance de melhorar o suficiente pra vencer o bluff-catcher (ranks
   que não aparecem no board e que, mesmo emparelhando no river, dão
   um par mais fraco que o par do bluff-catcher).

Rodar: python3 tests/postflop_turn.py
"""

import sys
from pathlib import Path

from treys import Card, Evaluator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.postflop import PostflopSolver, expand_class_combos, RANKS, SUITS  # noqa: E402

EVALUATOR = Evaluator()

BOARD = ("Ah", "Kd", "7s", "2c")  # turn -- falta o river

# OOP: valor que SEMPRE vence QQ neste board (trinca de As/Reis já
# feita, QQ so consegue no maximo trinca de damas no river, que perde
# pra trinca maior) + blefe que NUNCA vence QQ (ranks que nao batem
# com o board -- mesmo emparelhando no river, vira so um par abaixo
# de QQ).
RANGE_OOP = {"AA": 1.0, "KK": 1.0, "93o": 1.0, "84o": 1.0}
RANGE_IP = {"QQ": 1.0}

POT = 20.0


def independent_runout_equity(ca, cb, board4):
    """Reimplementacao standalone (sem cache, sem recursao) da equity
    all-in no turn -- serve de cross-check do runout_equity do motor."""
    dead = set(board4)
    combos_a = expand_class_combos(ca, dead)
    combos_b = expand_class_combos(cb, dead)
    total, n = 0.0, 0
    for r in RANKS:
        for s in SUITS:
            river = r + s
            if river in dead:
                continue
            board5 = [Card.new(c) for c in board4 + (river,)]
            for combo_a in combos_a:
                set_a = set(combo_a)
                ra = EVALUATOR.evaluate(board5, [Card.new(combo_a[0]), Card.new(combo_a[1])])
                for combo_b in combos_b:
                    if set_a & set(combo_b):
                        continue
                    rb = EVALUATOR.evaluate(board5, [Card.new(combo_b[0]), Card.new(combo_b[1])])
                    if ra < rb:
                        total += 1.0
                    elif ra == rb:
                        total += 0.5
                    n += 1
    return total / n if n > 0 else None


def check_mdf_turn(bet_frac, iterations=3000, tol=0.04):
    bet = bet_frac * POT
    expected = POT / (POT + bet)
    solver = PostflopSolver(
        board=BOARD, range_oop=RANGE_OOP, range_ip=RANGE_IP,
        pot=POT, stack_oop=60.0, stack_ip=60.0, bet_sizes=(bet_frac,),
    )
    solver.train(iterations=iterations)
    qq = solver.facing_bet_strategy("oop", 0, "QQ")
    call_freq = qq[1]
    diff = abs(call_freq - expected)
    status = "OK" if diff < tol else "DIVERGENTE"
    print(f"  bet={bet_frac}x pote: call_freq calculado={call_freq:.3f}  "
          f"MDF teorico=P/(P+b)={expected:.3f}  diff={diff:.3f}  [{status}]")
    return diff < tol, solver


if __name__ == "__main__":
    print("--- Teste 1: cross-check exato do runout_equity (AA vs QQ, turn) ---")
    solver = PostflopSolver(
        board=BOARD, range_oop=RANGE_OOP, range_ip=RANGE_IP,
        pot=POT, stack_oop=60.0, stack_ip=60.0, bet_sizes=(0.5,),
    )
    from engine.postflop import runout_equity  # noqa: E402
    engine_val = runout_equity("AA", "QQ", BOARD, solver._runout_cache, solver._showdown_cache)
    independent_val = independent_runout_equity("AA", "QQ", BOARD)
    diff1 = abs(engine_val - independent_val)
    print(f"  motor={engine_val:.6f}  reimplementacao independente={independent_val:.6f}  diff={diff1:.2e}")
    exact_ok = diff1 < 1e-9
    print(f"  Esperado: identico (calculo exato, sem amostragem) -> {'OK' if exact_ok else 'DIVERGENTE'}")

    print("\n--- Teste 2: MDF no turn (all-in, falta o river) vs formula fechada ---")
    ok_small, _ = check_mdf_turn(0.5)
    ok_big, _ = check_mdf_turn(2.0)

    print("\n=== Resumo ===")
    all_ok = exact_ok and ok_small and ok_big
    print("TODOS OS TESTES PASSARAM" if all_ok else "PELO MENOS UM TESTE FALHOU -- revisar")
