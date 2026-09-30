"""
Validação do pré-flop v5 (engine/preflop_v5.py) e do avaliador numba
(engine/nb_eval.py).

1. Avaliador numba == fast_eval (que é == treys) em mãos aleatórias.
2. Árvore: opções certas nos pontos-chave, nunca mais de 3 jogadores no
   final, pagamentos somando zero (chipEV) ou o total de prêmios (ICM).
3. Heads-up só com all-in/fold tem que bater com o PushFoldSolver (motor
   heads-up exato, já validado): nenhuma discordância em mão com
   diferença clara de EV (> 0,05bb), e a checagem de convergência sem
   nenhuma decisão apontada.

Rodar: python tests/preflop_v5.py
"""

import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import get_production_equity_matrix  # noqa: E402
from engine.fast_eval import eval7, value_any  # noqa: E402
from engine.nb_eval import eval_cards  # noqa: E402
from engine.preflop_v5 import (CLASSES, T_FOLD, PreflopConfig, PreflopSolver,  # noqa: E402
                               PreflopTree)
from engine.pushfold import PushFoldSolver  # noqa: E402


def test_avaliador_numba_igual_fast_eval():
    rng = random.Random(11)
    for n in (7, 5):
        for _ in range(50000):
            cards = rng.sample(range(52), n)
            ref = eval7(cards) if n == 7 else value_any(cards)
            assert eval_cards(np.array(cards, dtype=np.int64), n) == ref, cards


def _node(tree, path):
    nid = 0
    for lab in path:
        nid = int(tree.children[tree.cstart[nid] + tree.labels[nid].index(lab)])
    return nid


def test_arvore():
    t15 = PreflopTree(PreflopConfig(15))
    t40 = PreflopTree(PreflopConfig(40))
    assert t15.labels[0] == ("fold", "raise 2", "allin")
    # BTN contra open do CO: 15bb não tem 3-bet sem ser all-in; 40bb tem 3x
    assert t15.labels[_node(t15, ["fold"] * 4 + ["raise 2"])] == ("fold", "call", "allin")
    assert t40.labels[_node(t40, ["fold"] * 4 + ["raise 2.2"])] == ("fold", "call", "raise 6.6", "allin")
    # blinds 3-betam 4x; SB pode dar limp; BB contra limp
    assert "raise 8.8" in t40.labels[_node(t40, ["fold"] * 4 + ["raise 2.2", "fold"])]
    assert t40.labels[_node(t40, ["fold"] * 6)] == ("fold", "limp", "raise 3", "allin")
    assert t40.labels[_node(t40, ["fold"] * 6 + ["limp"])] == ("check", "raise 3.5", "allin")
    for tree, cfg in ((t15, PreflopConfig(15)), (t40, PreflopConfig(40)),
                      (PreflopTree(PreflopConfig(25, payouts=[500.0, 300.0, 200.0])), None)):
        assert all(len(live) <= 3 for _, live, _ in tree.terms)
        for t in range(len(tree.terms)):
            for k in range(tree.tnlive[t] if tree.tkind[t] != T_FOLD else 1):
                tot = tree.tpay[t, k].sum()
                if cfg is not None:  # chipEV: o que um ganha, outros perdem
                    assert abs(tot) < 1e-9, tot
                else:  # ICM: a soma é sempre o total de prêmios
                    assert abs(tot - 1000.0) < 1e-6, tot


def test_heads_up_bate_com_pushfold():
    S = 10.0
    eqm, classes = get_production_equity_matrix()
    ref = PushFoldSolver(S, equity_matrix=eqm, classes=classes)
    ref.train(20000)
    ev = ref.final_evs()
    cfg = PreflopConfig(S, n_players=2, ante=0.0, sb_limp=False, sb_open_size=100)
    s = PreflopSolver(cfg, seed=3)
    assert s.tree.labels[0] == ("fold", "allin")
    s.train(2_000_000)
    jam = s.strategy(0)
    call = s.strategy(s.node(["allin"]))
    clear = []
    for c in CLASSES:
        g = ev["sb_ev_push"][c] + 0.5
        if abs(g) > 0.05 and (jam[c]["allin"] - 0.5) * g < 0:
            clear.append(("jam", c, g, jam[c]["allin"]))
        g = ev["bb_ev_call"][c] + 1.0
        if abs(g) > 0.05 and (call[c]["call"] - 0.5) * g < 0:
            clear.append(("call", c, g, call[c]["call"]))
    print(f"  discordâncias claras com o PushFoldSolver: {clear}")
    assert not clear
    flags = s.check_convergence(deals=20000)
    print(f"  checagem: {s.last_check_summary}")
    assert not flags, flags[:3]
    evs = s.last_check_summary["ev_by_seat"]
    assert abs(evs["SB"] + evs["BB"]) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            print(name)
            fn()
    print("OK")
