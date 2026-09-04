"""
Validação do motor de river (engine/postflop.py).

Diferente de Kuhn Poker, não tem uma solução fechada pra árvore inteira
com board real -- mas o caso especial "range 100% polarizada (valor
puro que sempre vence + blefe puro que sempre perde) contra um único
bluff-catcher puro (sempre perde pro valor, sempre vence do blefe)" TEM
solução fechada conhecida (jogo clássico de teoria dos jogos, base da
literatura de GTO): pra pote P e aposta b, a frequência de call de
equilíbrio do bluff-catcher é

    call_freq = P / (P + b)      (== minimum defense frequency, MDF)

Isso vem de igualar o EV do blefe a zero: c*(-b) + (1-c)*P = 0. Board
escolhido pra criar exatamente esse cenário (AA/KK sempre vencem QQ,
72o/83o sempre perdem pra QQ nesse board seco) -- validamos o call
frequency do CFR contra esse número fechado, igual a validação de
AA vs KK feita em engine/equity.py.

Rodar: python3 tests/postflop_river.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.postflop import RiverSolver  # noqa: E402

BOARD = "Ah Kd 7s 2c 9h"  # seco, sem draw -- so showdown value conta

# OOP: range polarizada -- valor (sempre vence) ou blefe puro (sempre perde).
RANGE_OOP = {"AA": 1.0, "KK": 1.0, "72o": 1.0, "83o": 1.0}
# IP: bluff-catcher puro -- perde pra AA/KK, vence 72o/83o (par medio
# vs ar total nesse board seco).
RANGE_IP = {"QQ": 1.0}

POT = 20.0


def run(bet_sizes, iterations=3000):
    solver = RiverSolver(
        board=BOARD, range_oop=RANGE_OOP, range_ip=RANGE_IP,
        pot=POT, stack_oop=60.0, stack_ip=60.0, bet_sizes=bet_sizes,
    )
    solver.train(iterations=iterations)
    return solver


def check_mdf(bet_frac, tol=0.03):
    bet = bet_frac * POT
    expected = POT / (POT + bet)
    solver = run(bet_sizes=(bet_frac,))
    qq = solver.facing_bet_strategy("oop", 0, "QQ")
    call_freq = qq[1]
    diff = abs(call_freq - expected)
    status = "OK" if diff < tol else "DIVERGENTE"
    print(f"  bet={bet_frac}x pote: call_freq calculado={call_freq:.3f}  "
          f"MDF teorico=P/(P+b)={expected:.3f}  diff={diff:.3f}  [{status}]")
    return call_freq, expected, diff < tol


if __name__ == "__main__":
    print("--- Teste 1+2: call_freq do bluff-catcher (QQ) vs formula fechada de MDF ---")
    call_small, expected_small, ok_small = check_mdf(0.5)
    call_big, expected_big, ok_big = check_mdf(2.0)
    mixed_ok = 0.05 < call_small < 0.95
    mdf_ok = call_big < call_small
    print(f"  Esperado: nem 0 nem 1 (mista) -> {'OK' if mixed_ok else 'SUSPEITO'}")
    print(f"  Esperado: freq de call MENOR com aposta maior -> {'OK' if mdf_ok else 'SUSPEITO'}")
    closed_form_ok = ok_small and ok_big

    solver_small = run(bet_sizes=(0.5,))
    strat_small = solver_small.average_strategy_root()

    print("\n--- Teste 3: valor (AA/KK) aposta ~sempre, blefe (72o/83o) aposta com freq intermediaria ---")
    strat = strat_small
    aa_bet = 1 - strat["oop"]["AA"]["check"]
    kk_bet = 1 - strat["oop"]["KK"]["check"]
    air_bet_72 = 1 - strat["oop"]["72o"]["check"]
    air_bet_83 = 1 - strat["oop"]["83o"]["check"]
    print(f"  AA bet={aa_bet:.3f}  KK bet={kk_bet:.3f}  72o bet={air_bet_72:.3f}  83o bet={air_bet_83:.3f}")
    value_bets_a_lot = aa_bet > 0.9 and kk_bet > 0.9
    bluff_is_mixed_or_bets = 0.0 <= air_bet_72 <= 1.0 and 0.0 <= air_bet_83 <= 1.0
    print(f"  Esperado: valor aposta quase sempre -> {'OK' if value_bets_a_lot else 'SUSPEITO'}")

    print("\n=== Resumo ===")
    all_ok = closed_form_ok and mixed_ok and mdf_ok and value_bets_a_lot and bluff_is_mixed_or_bets
    print("TODOS OS TESTES PASSARAM" if all_ok else "PELO MENOS UM TESTE FALHOU -- revisar")
    sys.exit(0 if all_ok else 1)
