"""
Validação do motor RFI/Jam v2 (engine/rfi_jam_v2.py): ante, call do BB
com realização de equity e all-in direto de quem abre.

Checagens (mesma régua do CLAUDE.md -- não basta olhar AA e 72o):
1. Explorabilidade (melhor resposta exata) quase zero em stack curto e
   médio, pros dois matchups em produção.
2. Direção: em toda mão, nas decisões que de fato acontecem, a ação mais
   jogada é a de maior EV (tolerância 0,05 bb).
3. Sanidade de poker:
   - 10 bb: quem abre quase não usa raise pequeno (vai de all-in ou fold)
     -- o bug que motivou o v2 (QQ/AJo saíam "raise" com 10 bb).
   - 20 bb no BTN: mãos fortes dão raise (armadilha), e o BB folda parte
     das mãos contra o raise (sem a realização por força da mão ele nunca
     foldava).
   - AA nunca folda; 72o folda na raiz.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import get_production_equity_matrix  # noqa: E402
from engine.rfi_jam_v2 import RfiJamV2  # noqa: E402

OTHER = [40, 25, 18, 12, 30, 20]
PAY = [500, 300, 200]
MATCH = {"sb_vs_bb": (0.5, 1.0, 0.0, False), "btn_vs_bb": (0.0, 1.0, 0.5, True)}

m, classes = get_production_equity_matrix()
idx = {c: i for i, c in enumerate(classes)}


def solve(mu, S, it=2500):
    op, dp, dm, ip = MATCH[mu]
    s = RfiJamV2([S, S] + OTHER, PAY, m, classes, effective_stack=S, opener_post=op,
                 defender_post=dp, dead_money=dm, opener_in_position=ip)
    s.train(it)
    return s


falhas = []


def check(cond, msg):
    if not cond:
        falhas.append(msg)
    print(("ok   " if cond else "FALHA") + " " + msg)


for mu in MATCH:
    for S in (10, 20, 40):
        s = solve(mu, S)
        st = s.average_strategy()
        ev = s.action_evs(st)
        v = s.icm_por_bb
        eo, eb = s.exploitability(st)
        check((eo + eb) / v < 0.001, f"{mu} {S}bb explorabilidade {(eo + eb) / v:.5f} bb < 0,001")
        t = s.totals(s.training_strategy())
        reach = {"root": 1.0, "vs_raise": t["opener"]["raise"], "vs_jam": t["opener"]["jam"]}
        for k, r in reach.items():
            if r < 0.03:
                continue
            best = ev[k].argmax(1)
            top = st[k].argmax(1)
            gap = (ev[k][np.arange(s.n), best] - ev[k][np.arange(s.n), top]) / v
            n_bad = int(((best != top) & (gap > 0.05)).sum())
            check(n_bad == 0, f"{mu} {S}bb {k}: {n_bad} mãos com a ação mais jogada fora da de maior EV")
        check(st["root"][idx["AA"], 0] < 0.01, f"{mu} {S}bb AA nunca folda")
        check(st["root"][idx["72o"], 0] > 0.99, f"{mu} {S}bb 72o folda")
        if S == 10:
            check(t["opener"]["raise"] < 0.05, f"{mu} 10bb quase sem raise pequeno ({t['opener']['raise']:.1%})")
            for h in ("QQ", "AJo"):
                check(st["root"][idx[h], 2] > 0.9, f"{mu} 10bb {h} vai de all-in")
        if mu == "btn_vs_bb" and S == 20:
            check(st["root"][idx["AA"], 1] > 0.9, "btn 20bb AA dá raise (armadilha)")
            check(0.05 < t["bb_vs_raise"]["fold"] < 0.35, f"btn 20bb BB folda {t['bb_vs_raise']['fold']:.0%} contra o raise")

if falhas:
    sys.exit(f"{len(falhas)} falha(s)")
print("Tudo certo.")
