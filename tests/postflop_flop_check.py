"""
Checagem pontual do motor no FLOP (board de 3 cartas, faltam turn E
river) -- primeiro spot real testado nessa rua. Diferente de
tests/postflop_river.py e tests/postflop_turn.py (que são suíte
"oficial" de regressão), este é um teste EXPLORATÓRIO de 1 spot só,
pra decidir se o flop está pronto pra virar validação formal.

Mesma lógica de MDF do river/turn, adaptada: com o board no flop,
faltam 2 cartas (não 1), então "valor sempre vence / blefe sempre
perde" já não é 100% literal -- tem uma chance residual bem pequena
de o bluff-catcher completar quads (~0.1%) ou o blefe completar dois
pares/trinca (~poucos %) no turn+river. Por isso a tolerância aqui é
maior que no river/turn.

Rodar: python3 tests/postflop_flop_check.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.postflop import PostflopSolver  # noqa: E402

BOARD = ("Ah", "Kd", "7s")  # flop -- faltam turn e river

RANGE_OOP = {"AA": 1.0, "KK": 1.0, "93o": 1.0, "84o": 1.0}
RANGE_IP = {"QQ": 1.0}

POT = 20.0
BET_FRAC = 0.75


if __name__ == "__main__":
    t0 = time.time()
    solver = PostflopSolver(
        board=BOARD, range_oop=RANGE_OOP, range_ip=RANGE_IP,
        pot=POT, stack_oop=60.0, stack_ip=60.0, bet_sizes=(BET_FRAC,),
    )
    solver.train(iterations=1500)
    elapsed = time.time() - t0

    strat = solver.average_strategy_root()
    print(f"Board (flop, faltam turn+river): {' '.join(BOARD)}  ({elapsed:.1f}s pra treinar)")
    print("\n--- OOP (raiz: check vs bet) ---")
    for c in ["AA", "KK", "93o", "84o"]:
        if c in strat["oop"]:
            row = strat["oop"][c]
            print(f"  {c:5s} " + "  ".join(f"{k}={v:.2f}" for k, v in row.items()))

    qq = solver.facing_bet_strategy("oop", 0, "QQ")
    call_freq = qq[1]
    expected = POT / (POT + BET_FRAC * POT)
    diff = abs(call_freq - expected)
    print(f"\nQQ (bluff-catcher) contra a aposta: fold={qq[0]:.3f} call={call_freq:.3f}")
    print(f"MDF teorico (aproximado -- ver docstring sobre quads/dois pares residuais): {expected:.3f}")
    print(f"diff={diff:.3f}  [{'OK' if diff < 0.06 else 'DIVERGENTE'}]")

    aa_bet = 1 - strat["oop"]["AA"]["check"]
    kk_bet = 1 - strat["oop"]["KK"]["check"]
    print(f"\nSanidade: AA bet={aa_bet:.2f} KK bet={kk_bet:.2f} (esperado: quase sempre)")
