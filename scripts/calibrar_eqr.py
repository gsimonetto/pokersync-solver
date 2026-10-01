"""
Calibra a realização de equity (EQR) do pré-flop v5 com o solver pós-flop.

Pra cada stack: treina o pré-flop (chipEV, mesa de 8), pega os ranges de
spots típicos que vão pro flop heads-up, resolve CALIB_FLOPS flops de cada
um e acumula, por papel (em posição / fora de posição) e faixa de SPR, o
fator "EV jogando / equity" de cada classe de mão. Grava a tabela em
engine/data/eqr_table.json (usada por engine/preflop_v5.eqr_factor).

Retomável: cada (spot, flop) resolvido fica gravado em
calib_parcial.json na pasta indicada -- rodar de novo pula o que já foi.

Uso: python scripts/calibrar_eqr.py [--pasta DIR] [--flops 8] [--iteracoes 50]

Repetições do pós-flop: `--iteracoes` nos potes com pouca pilha atrás
(SPR < 3); 2x com SPR 3-8 e 3x com SPR > 8 -- pilha funda tem árvore
mais longa e precisa de mais treino (com 50 o erro chegava a 5-6% do pote).

Tempo estimado num i9 de 8 núcleos: 3 a 5 horas (80 flops; os de 100bb são
os mais lentos). Pode parar com Ctrl+C e rodar de novo: continua de onde
parou (cada flop resolvido fica salvo na hora).
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import numpy as np  # noqa: E402

from engine.eqr_calibration import CALIB_FLOPS, spot_realization  # noqa: E402
from engine.preflop_v5 import CLASSES, PLAYER, PreflopConfig, PreflopSolver, _avg  # noqa: E402

TABLE_PATH = BASE / "engine" / "data" / "eqr_table.json"
# spots por stack: sequência de ações (labels) até o flop heads-up
SPOTS = {
    15.0: {"BTN_vs_BB": ["fold"] * 5 + ["raise 2", "fold", "call"],
           "SB_limp_BB": ["fold"] * 6 + ["limp", "check"]},
    40.0: {"BTN_vs_BB": ["fold"] * 5 + ["raise 2.2", "fold", "call"],
           "CO_vs_BTN": ["fold"] * 4 + ["raise 2.2", "call", "fold", "fold"],
           "SB_limp_BB": ["fold"] * 6 + ["limp", "check"],
           "BB_3bet_BTN": ["fold"] * 5 + ["raise 2.2", "fold", "raise 8.8", "call"]},
    100.0: {"BTN_vs_BB": ["fold"] * 5 + ["raise 2.5", "fold", "call"],
            "CO_vs_BTN": ["fold"] * 4 + ["raise 2.5", "call", "fold", "fold"],
            "SB_limp_BB": ["fold"] * 6 + ["limp", "check"],
            "BB_3bet_BTN": ["fold"] * 5 + ["raise 2.5", "fold", "raise 10", "call"]},
}
SPR_BUCKETS = [(0.0, 3.0), (3.0, 8.0), (8.0, 1e9)]  # baixo, médio, alto


def spot_ranges(solver, path):
    """(pot, stack atrás, {seat: range por classe}) no fim de `path`."""
    tr = solver.tree
    nid = 0
    reach = {}
    for lab in path:
        a = int(tr.actor[nid])
        k = tr.labels[nid].index(lab)
        off, na = int(tr.regoff[nid]), int(tr.nact[nid])
        r = reach.setdefault(a, np.ones(169))
        for c in range(169):
            r[c] *= _avg(solver.ssum, off, na, c)[k]
        nid = int(tr.children[tr.cstart[nid] + k])
    if tr.ntype[nid] == PLAYER:
        raise ValueError(f"{path}: não termina a mão")
    kind, live, commit = tr.terms[tr.term_of[nid]]
    if len(live) != 2:
        raise ValueError(f"{path}: precisa de 2 jogadores no flop")
    cfg = solver.cfg
    pot = sum(commit) + cfg.ante * cfg.n
    stack = cfg.eff - commit[live[0]]
    ranges = {s: {CLASSES[c]: float(reach.get(s, np.ones(169))[c]) for c in range(169)
                  if reach.get(s, np.ones(169))[c] > 0.005} for s in live}
    return pot, stack, ranges, live


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", type=Path, default=BASE / "calibracao_eqr")
    ap.add_argument("--flops", type=int, default=8)
    ap.add_argument("--iteracoes", type=int, default=50)
    ap.add_argument("--treino-preflop", type=int, default=30_000_000)
    args = ap.parse_args()
    args.pasta.mkdir(parents=True, exist_ok=True)
    part_path = args.pasta / "calib_parcial.json"
    done = json.loads(part_path.read_text()) if part_path.exists() else {}
    flops = CALIB_FLOPS[:args.flops]
    total = sum(len(sp) for sp in SPOTS.values()) * len(flops)
    print(f"Calibração da realização de equity: {len(done)}/{total} flops já prontos "
          f"(salvos em {part_path}).", flush=True)

    for stack, spots in SPOTS.items():
        solver = None
        for name, path in spots.items():
            todo = [f for f in flops if f"{stack:g}|{name}|{f}" not in done]
            if not todo:
                continue
            if solver is None:
                t = time.time()
                solver = PreflopSolver(PreflopConfig(stack))
                solver.train(args.treino_preflop, parallel=True)
                print(f"[{stack:g}bb] pré-flop treinado em {time.time() - t:.0f}s", flush=True)
            pot, behind, ranges, live = spot_ranges(solver, path)
            oop, ip = sorted(live, key=solver.tree.post_rank)
            spr = behind / pot
            iters = args.iteracoes * (1 if spr < 3 else 2 if spr < 8 else 3)
            for f in todo:
                t = time.time()
                o, i, ex = spot_realization(f, ranges[oop], ranges[ip], pot, behind, iterations=iters)
                done[f"{stack:g}|{name}|{f}"] = {"spr": spr, "oop": o, "ip": i, "exploit_pct": ex}
                part_path.write_text(json.dumps(done))
                print(f"  [{len(done)}/{total}] {stack:g}bb {name} {f}: SPR {spr:.1f}, {time.time() - t:.0f}s, "
                      f"erro {ex:.2f}% do pote", flush=True)

    # tabela: por faixa de SPR e papel, soma EV / soma equity por classe
    table = {"spr_buckets": SPR_BUCKETS, "spr_center": [], "oop": [], "ip": []}
    for lo, hi in SPR_BUCKETS:
        sprs = [v["spr"] for v in done.values() if lo <= v["spr"] < hi]
        # centro da faixa em escala log (a interpolação do motor é em log(SPR))
        table["spr_center"].append(float(np.exp(np.mean(np.log(sprs)))) if sprs else (lo + min(hi, 30.0)) / 2)
        for role in ("oop", "ip"):
            acc = {}
            for v in done.values():
                if lo <= v["spr"] < hi:
                    for cl, (ev, e) in v[role].items():
                        d = acc.setdefault(cl, [0.0, 0.0])
                        d[0] += ev
                        d[1] += e
            tot_ev = sum(x[0] for x in acc.values())
            tot_e = sum(x[1] for x in acc.values())
            avg = tot_ev / tot_e if tot_e > 0 else 1.0
            # classes com pouca amostra puxadas pra média do papel
            # (encolhimento: soma "k" de equity com o fator médio)
            k = 0.02 * tot_e / max(len(acc), 1) * 5
            fac = {cl: (acc.get(cl, [0, 0])[0] + k * avg) / (acc.get(cl, [0, 0])[1] + k) for cl in CLASSES}
            table[role].append({"avg": avg, "classes": fac})
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TABLE_PATH.write_text(json.dumps(table, indent=0))
    for b, (lo, hi) in enumerate(SPR_BUCKETS):
        print(f"SPR {lo:g}-{hi:g}: fator médio fora de posição {table['oop'][b]['avg']:.3f}, "
              f"em posição {table['ip'][b]['avg']:.3f}")
    print(f"tabela gravada em {TABLE_PATH}")


if __name__ == "__main__":
    main()
