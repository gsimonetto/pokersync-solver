"""
Gera os spots RFI/Jam no motor v2 (engine/rfi_jam_v2.py: ante, call do BB
com realização de equity e all-in direto de quem abre) no formato do
Treino do PokerSync (tabela drills). Mesmo spot_id dos spots v1
("rfi_jam_<matchup>_<stack>bb") -- substitui os antigos.

Formato de gto_nodes (cada fase: ev_fold + hands {classe: [freq, ev, gap]},
gap = |ev da ação - ev do fold|; a perda de qualquer escolha é
max(ev das opções) - ev da escolhida):
  sb_open       quem abre: raise (freq do raise)
  sb_jam        quem abre: all-in direto (freq do all-in)
  bb_jam        BB diante do raise: all-in
  bb_call_raise BB diante do raise: call
  sb_call_jam   quem abriu, diante do all-in do BB: call
  bb_call_jam   BB diante do all-in direto: call
  model "v2", ante, open_size, icm_por_bb (valor de 1 bb na escala do
  motor, pro app converter EV em bb) e totals (frequência total de cada
  ação -- o app esconde fase que quase nunca acontece).

Mesa (a mesma dos spots v1, conferida contra os números gravados):
stacks dos outros 6 = [40, 25, 18, 12, 30, 20], prêmios [500, 300, 200].

Uso: python jobs/solve_rfi_jam_v2_batch.py saida.json
"""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import get_production_equity_matrix  # noqa: E402
from engine.rfi_jam_v2 import ENGINE_VERSION, RfiJamV2  # noqa: E402

OTHER_STACKS = [40, 25, 18, 12, 30, 20]
PAYOUTS = [500, 300, 200]
STACKS = [10, 15, 20, 25, 30, 40, 50, 60, 75, 100]
# opener_post, defender_post, dead_money, quem abre tem posição no pós-flop
MATCHUPS = {
    "sb_vs_bb": (0.5, 1.0, 0.0, False),
    "btn_vs_bb": (0.0, 1.0, 0.5, True),
}
ANTE = 1.0
OPEN_SIZE = 2.2
ITERATIONS = 4000


def _phase(classes, freq, ev_action, ev_fold, action):
    return {
        "ev_fold": round(float(ev_fold[0]), 3),
        "action": action,
        "hands": {
            c: [round(float(freq[i]), 4), round(float(ev_action[i]), 3), round(abs(float(ev_action[i] - ev_fold[i])), 3)]
            for i, c in enumerate(classes)
        },
    }


def build_row(matchup, stack, solver, s, expl):
    ev = solver.action_evs(s)
    c = solver.classes
    totals = solver.totals(s)
    gto_nodes = {
        "ev_mode": "icm",
        "model": "v2",
        "ante": ANTE,
        "open_size": OPEN_SIZE,
        "icm_por_bb": round(solver.icm_por_bb, 4),
        "totals": {k: {a: round(v, 4) for a, v in d.items()} for k, d in totals.items()},
        "sb_open": _phase(c, s["root"][:, 1], ev["root"][:, 1], ev["root"][:, 0], "open"),
        "sb_jam": _phase(c, s["root"][:, 2], ev["root"][:, 2], ev["root"][:, 0], "allin"),
        "bb_jam": _phase(c, s["vs_raise"][:, 2], ev["vs_raise"][:, 2], ev["vs_raise"][:, 0], "allin"),
        "bb_call_raise": _phase(c, s["vs_raise"][:, 1], ev["vs_raise"][:, 1], ev["vs_raise"][:, 0], "call"),
        "sb_call_jam": _phase(c, s["vs_bbjam"][:, 1], ev["vs_bbjam"][:, 1], ev["vs_bbjam"][:, 0], "call"),
        "bb_call_jam": _phase(c, s["vs_jam"][:, 1], ev["vs_jam"][:, 1], ev["vs_jam"][:, 0], "call"),
    }
    op, dp, dm, _ = MATCHUPS[matchup]
    return {
        "spot_id": f"rfi_jam_{matchup}_{int(stack)}bb",
        "board": [],
        "pot": op + dp + ANTE + dm,
        "effective_stack": stack,
        "gto_nodes": gto_nodes,
        "solution": None,
        "format": None,
        "stack_bb": int(stack),
        "position": matchup,
        "street": "Preflop",
        "action": "rfi_jam",
        "engine_version": ENGINE_VERSION,
        "exploitability": round(expl, 5),
        "solver_job_id": None,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def run(stacks=STACKS, matchups=tuple(MATCHUPS), iterations=ITERATIONS, log=print):
    m, classes = get_production_equity_matrix()
    rows = []
    for mu in matchups:
        op, dp, dm, ip = MATCHUPS[mu]
        for S in stacks:
            solver = RfiJamV2([S, S] + OTHER_STACKS, PAYOUTS, m, classes, open_size=OPEN_SIZE,
                              effective_stack=S, opener_post=op, defender_post=dp, dead_money=dm,
                              ante=ANTE, opener_in_position=ip)
            solver.train(iterations)
            s = solver.training_strategy()
            eo, eb = solver.exploitability(solver.average_strategy())
            expl_bb = (eo + eb) / solver.icm_por_bb
            rows.append(build_row(mu, S, solver, s, expl_bb))
            t = solver.totals(s)["opener"]
            log(f"{mu} {S}bb: fold {t['fold']:.0%} raise {t['raise']:.0%} jam {t['jam']:.0%}  explorabilidade {expl_bb:.5f} bb")
    return rows


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "spots_v2.json")
    rows = run()
    out.write_text(json.dumps(rows, separators=(",", ":")))
    print(f"{len(rows)} spots -> {out}")
