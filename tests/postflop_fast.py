"""
Validação do motor pós-flop rápido (engine/postflop_fast.py).

1. MDF (mesmo jogo clássico de tests/postflop_river.py): range polarizada
   (valor puro + blefe puro) contra um bluff-catcher puro. A frequência de
   call de equilíbrio tem fórmula fechada: P / (P + b).
2. Exploitability: num river e num turn com ranges largas, a estratégia
   treinada tem que ficar quase inexplorável (best-response exato, sem
   amostragem) -- e cair conforme treina.
3. Contabilidade: EV(OOP) + EV(IP) = pote (jogo de soma constante, cada
   um recebe a parte do pote que ganha).

Rodar: python tests/postflop_fast.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes  # noqa: E402
from engine.postflop_fast import FastPostflopSolver, TreeConfig  # noqa: E402

RIVER = "Ah Kd 7s 2c 9h"
# 83o e 54o não fazem nem par nesse board: sempre perdem pra QQ
R_POLAR = {"AA": 1.0, "KK": 1.0, "83o": 1.0, "54o": 1.0}
R_CATCHER = {"QQ": 1.0}
POT = 20.0

C = all_hand_classes()
R_IP = {c: 1.0 for c in C[:80]}
R_OOP = {c: 1.0 for c in C[20:95]}


def test_mdf():
    for frac in (0.5, 1.0, 2.0):
        cfg = TreeConfig(bet_sizes=((), (), (frac,)), raise_sizes=((), (), ()), max_raises=0, allin=False)
        s = FastPostflopSolver(RIVER, R_POLAR, R_CATCHER, pot=POT, stack=60.0, config=cfg)
        s.train(2000)
        bet_node = s.child(0, s.tb.labels[0][1])
        call = s.root_strategy_by_class(bet_node)["QQ"]["call"]
        esperado = POT / (POT + frac * POT)
        print(f"  aposta {frac}x pote: call QQ={call:.4f} (fórmula {esperado:.4f})")
        assert abs(call - esperado) < 0.01, (frac, call, esperado)
        ev = s.expected_values()
        assert abs(ev[0] + ev[1] - POT) < 1e-6, ev


def _check_spot(board, iters, max_pct):
    s = FastPostflopSolver(board, R_OOP, R_IP, pot=5.5, stack=40.0)
    s.train(iters // 3)
    first = s.exploitability_pct()
    s.train(iters - s.iterations)
    last = s.exploitability_pct()
    ev = s.expected_values()
    print(f"  {board}: exploit {first:.3f}% -> {last:.3f}% do pote ({s.iterations} it), EVs {ev[0]:.3f}/{ev[1]:.3f}")
    assert last < first, (first, last)
    assert last < max_pct, last
    assert abs(ev[0] + ev[1] - 5.5) < 1e-4, ev
    br = s.best_response_values()
    # best-response nunca vale menos que a estratégia treinada
    assert br[0] >= ev[0] - 1e-6 and br[1] >= ev[1] - 1e-6, (br, ev)


def test_exploitability_river():
    _check_spot(RIVER, 300, 0.1)


def test_exploitability_turn():
    _check_spot("Ah Kd 7s 2c", 300, 0.2)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            print(name)
            fn()
    print("OK")
