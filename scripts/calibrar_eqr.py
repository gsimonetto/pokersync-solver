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
from engine.preflop_v5 import CLASSES, PLAYER, PreflopConfig, PreflopSolver, _avg, hand_adjust  # noqa: E402

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

    write_table(done)


# tipo de pote de cada spot calibrado (ver engine/preflop_v5.pot_category)
SPOT_CATEGORY = {"BTN_vs_BB": "srp_aggr_ip", "CO_vs_BTN": "srp_aggr_oop",
                 "SB_limp_BB": "limp", "BB_3bet_BTN": "3bet_aggr_oop"}


def hand_group(cl):
    """Grupo da mão pra calibração: cada grupo junta várias classes (e
    todos os flops), então o fator medido fica estável -- mão a mão, com 8
    flops, depende demais de quais flops caíram."""
    ranks = "23456789TJQKA"
    hi, lo = ranks.index(cl[0]), ranks.index(cl[1])
    if hi == lo:
        return "par_alto" if hi >= 8 else ("par_medio" if hi >= 4 else "par_baixo")
    suited = cl[2] == "s"
    gap = hi - lo - 1
    if lo >= 8:
        g = "broadway"
    elif hi == 12:
        g = "ax"
    elif gap <= 1:
        g = "conectada"
    elif hi >= 10:
        g = "alta"  # K/Q + carta baixa
    else:
        g = "lixo"
    return g + ("_s" if suited else "_o")


def build_table(done):
    """Tabela por tipo de pote: em cada SPR calibrado (um por stack), o
    fator médio "EV / equity" de cada coluna (oop = age primeiro no flop,
    ip = age por último), somando todas as mãos e flops -- esse é o efeito
    grande e bem medido (papel/posição). Por mão: média da coluna x (1 +
    Por mão: fator medido do GRUPO da mão (ver hand_group) -- mão lixo
    realiza muito menos que a média (72o no BB: ~0,35), o que um ajuste
    leve não captura. A medida mão a mão direta NÃO é usada: com 8 flops
    ela depende de quais flops caíram (ex: T9s saía 1,5-1,9 porque T-9-3,
    8-7-6, K-J-T e T-8-2 estão na amostra); fica gravada em "measured" só
    pra consulta. Grupo com pouca amostra: média da coluna x ajuste leve."""
    groups = {}
    for key, v in done.items():
        stack, name, _flop = key.split("|")
        groups.setdefault((SPOT_CATEGORY[name], round(v["spr"], 2)), []).append(v)
    cats = {}
    for (cat, spr), vs in sorted(groups.items()):
        point = {"spr": spr, "flops": len(vs)}
        scale = spr / (spr + 1.5)
        for col in ("oop", "ip"):
            acc = {}
            for v in vs:
                for cl, (ev, e) in v[col].items():
                    d = acc.setdefault(cl, [0.0, 0.0])
                    d[0] += ev
                    d[1] += e
            tot_ev = sum(x[0] for x in acc.values())
            tot_e = sum(x[1] for x in acc.values())
            avg = tot_ev / tot_e if tot_e > 0 else 1.0
            # fator por grupo de mão (soma EV / soma equity do grupo);
            # grupo sem amostra (ex: mão que nunca está nesse range) fica
            # com a média da coluna x ajuste leve por tipo de mão
            gacc = {}
            for cl, (ev, e) in acc.items():
                d = gacc.setdefault(hand_group(cl), [0.0, 0.0])
                d[0] += ev
                d[1] += e
            min_mass = 0.02 * tot_e  # grupo precisa de >= 2% da equity da coluna
            gfac = {g: ev / e for g, (ev, e) in gacc.items() if e >= min_mass}
            point[col] = {cl: gfac.get(hand_group(cl), avg * (1.0 + hand_adjust(cl) * scale)) for cl in CLASSES}
            point["groups_" + col] = gfac
            point["avg_" + col] = avg
            point["measured_" + col] = {cl: ev / e for cl, (ev, e) in acc.items() if e > 0}
        cats.setdefault(cat, []).append(point)
    table = {"version": 2, "categories": {}}
    for cat, pts in cats.items():
        pts.sort(key=lambda p: p["spr"])
        table["categories"][cat] = {k: [p[k] for p in pts] for k in
                                    ("spr", "flops", "oop", "ip", "avg_oop", "avg_ip", "groups_oop", "groups_ip",
                                     "measured_oop", "measured_ip")}
    return table


def write_table(done):
    table = build_table(done)
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TABLE_PATH.write_text(json.dumps(table, indent=0))
    for cat, c in table["categories"].items():
        pts = ", ".join(f"SPR {s:g}: fora {o:.2f} / em pos. {i:.2f}"
                        for s, o, i in zip(c["spr"], c["avg_oop"], c["avg_ip"]))
        print(f"{cat}: {pts}")
    print(f"tabela gravada em {TABLE_PATH}")


if __name__ == "__main__":
    main()
