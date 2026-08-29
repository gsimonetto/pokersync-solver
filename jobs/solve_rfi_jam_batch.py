"""
Job de geração em lote pra spots RFI/jam (com ICM). Gera o formato
COMPACTO de verdade usado em produção: cada mão vira [freq, ev, gap]
em vez de um objeto, pra caber num JSON razoável (~16KB por spot em
vez de ~74KB) -- ev_fold fica uma vez só por fase, não repetido por
mão.

MATCHUPS já validados e testados end-to-end (ver README):
  sb_vs_bb:  opener_post=0.5, defender_post=1.0, dead_money=0.0
  btn_vs_bb: opener_post=0.0, defender_post=1.0, dead_money=0.5

co_vs_btn e utg_vs_bb NÃO estão aqui -- exigem o modelo multiway
completo (ver engine/multiway_rfi.py), que ficou provado inviável
computacionalmente com Monte Carlo em tempo real (ver decisão
registrada). Não usar dead_money como aproximação pra esses dois sem
validar de novo -- foi descartado por imprecisão.

Ante (2026-08, bug real): até aqui nenhum spot gerado contava ante --
toda mão real de MTT do produto tem ante (conferido contra 203 mãos
reais da conta do usuário: NENHUMA sem ante), mas o motor resolvia
como se o pote fosse só blind. `ante_bb` (novo parâmetro de
run_rfi_jam_batch, default 0.0 = comportamento antigo intacto) é o
ante de CADA jogador em bb; `table_size` (default 8, tamanho de mesa
mais comum nas mãos reais analisadas) é quantos assentos estão
pagando ante nessa mão -- `ante_pool = ante_bb * table_size` é
repassado pro solver (ver engine/rfi_jam.py::ante_pool). Com
ante_bb=0 os spots saem BIT A BIT iguais aos gerados antes dessa
mudança (mesmo teste de regressão já usado pra multi-size, ver
tests/rfi_jam_ante.py).
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.rfi_jam import RfiJamSolver  # noqa: E402
from jobs.supabase_client import get_client  # noqa: E402

ENGINE_VERSION = "pokersync-solver-v0.3.0-rfi-jam-validated"
ENGINE_VERSION_MULTISIZE = "pokersync-solver-v0.4.0-rfi-jam-multisize"
ENGINE_VERSION_ANTE = "pokersync-solver-v0.5.0-rfi-jam-ante"

# posts/dead_money por matchup -- só adicionar um matchup novo aqui
# depois de validar exploitability com compute_exploitability()
# (ver engine/rfi_jam.py) e confirmar que os números fazem sentido,
# igual fizemos pra sb_vs_bb e btn_vs_bb.
MATCHUPS: dict[str, tuple[float, float, float]] = {
    "sb_vs_bb": (0.5, 1.0, 0.0),
    "btn_vs_bb": (0.0, 1.0, 0.5),
}


def _compact_phase(phase_hands: dict, action_name: str, ev_fold: float) -> dict:
    return {
        "ev_fold": round(ev_fold, 3),
        "action": action_name,
        "hands": {
            c: [round(freq, 4), round(ev, 3), round(gap, 3)]
            for c, (freq, ev, gap) in phase_hands.items()
        },
    }


def build_drill_row(spot_id: str, matchup: str, solver: RfiJamSolver, strat: dict,
                     evs: dict, exploitability: float, job_id: str | None, stack_bb: float):
    # + dead_money + ante_pool: sem isso o "pot" exibido pro usuario ficava
    # so' os blinds, escondendo o ante que ja esta contado na estrategia
    # (solver.ante_pool eh 0.0 quando ante_bb=0, entao nao muda nada pros
    # spots antigos).
    pot = solver.opener_post + solver.defender_post + solver.dead_money + solver.ante_pool

    def phase_hands(prob_key: str, ev_key: str):
        return {
            c: (strat[prob_key][c], evs[prob_key][c][ev_key], evs[prob_key][c]["gap"])
            for c in solver.classes
        }

    first_class = solver.classes[0]
    gto_nodes = {
        "sb_open": _compact_phase(phase_hands("sb_open", "open"), "open", evs["sb_open"][first_class]["fold"]),
        "bb_jam": _compact_phase(phase_hands("bb_jam", "jam"), "allin", evs["bb_jam"][first_class]["fold"]),
        "sb_call_jam": _compact_phase(phase_hands("sb_call_jam", "call"), "call", evs["sb_call_jam"][first_class]["fold"]),
    }

    return {
        "spot_id": spot_id,
        "board": [],
        "pot": pot,
        "effective_stack": solver.T,
        "gto_nodes": gto_nodes,
        "solution": None,
        "format": None,
        "stack_bb": int(stack_bb),
        "position": matchup,
        "street": "Preflop",
        "action": "rfi_jam",
        "engine_version": ENGINE_VERSION,
        "exploitability": round(exploitability, 3),
        "solver_job_id": job_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _compact_phase_by_size(phase_hands_by_size: dict, action_name: str, ev_fold_by_size: dict) -> dict:
    return {
        "by_size": {
            str(size): {
                "ev_fold": round(ev_fold_by_size[size], 3),
                "action": action_name,
                "hands": {
                    c: [round(freq, 4), round(ev, 3), round(gap, 3)]
                    for c, (freq, ev, gap) in hands.items()
                },
            }
            for size, hands in phase_hands_by_size.items()
        }
    }


def build_drill_row_multisize(spot_id: str, matchup: str, solver: RfiJamSolver, strat: dict,
                               evs: dict, exploitability: float, job_id: str | None, stack_bb: float):
    """
    Mesma ideia de build_drill_row(), mas com uma dimensao de tamanho a
    mais -- cada fase vira {"by_size": {"2.0": {ev_fold, action, hands},
    "2.5": {...}, ...}} em vez de um objeto unico. `sizes` no topo do
    gto_nodes eh o jeito do frontend detectar "isso eh multi-tamanho"
    sem precisar inspecionar a forma de cada fase.
    """
    pot = solver.opener_post + solver.defender_post + solver.dead_money + solver.ante_pool
    sizes = solver.sizes
    first_class = solver.classes[0]

    def hands_for_size(prob_key: str, ev_key: str, size: float) -> dict:
        if prob_key == "sb_open":
            return {c: (strat["sb_open"][c][size], evs["sb_open"][c][size][ev_key], evs["sb_open"][c][size]["gap"]) for c in solver.classes}
        return {c: (strat[prob_key][size][c], evs[prob_key][size][c][ev_key], evs[prob_key][size][c]["gap"]) for c in solver.classes}

    def ev_fold_for_size(prob_key: str, size: float) -> float:
        if prob_key == "sb_open":
            return evs["sb_open"][first_class][size]["fold"]
        return evs[prob_key][size][first_class]["fold"]

    def phase(prob_key: str, ev_key: str, action_name: str) -> dict:
        return _compact_phase_by_size(
            {size: hands_for_size(prob_key, ev_key, size) for size in sizes},
            action_name,
            {size: ev_fold_for_size(prob_key, size) for size in sizes},
        )

    gto_nodes = {
        "sizes": sizes,
        "sb_open": phase("sb_open", "open", "open"),
        "bb_jam": phase("bb_jam", "jam", "allin"),
        "sb_call_jam": phase("sb_call_jam", "call", "call"),
    }

    return {
        "spot_id": spot_id,
        "board": [],
        "pot": pot,
        "effective_stack": solver.T,
        "gto_nodes": gto_nodes,
        "solution": None,
        "format": None,
        "stack_bb": int(stack_bb),
        "position": matchup,
        "street": "Preflop",
        "action": "rfi_jam",
        "engine_version": ENGINE_VERSION_MULTISIZE,
        "exploitability": round(exploitability, 3),
        "solver_job_id": job_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def run_rfi_jam_batch(job_id: str | None, matchups: list[str], stacks_bb: list[float],
                       other_stacks: list[float], payouts: list[float], equity_matrix, classes,
                       open_size=2.2, open_sizes: list[float] | None = None,
                       iterations=2_500_000, dry_run=False,
                       ante_bb: float = 0.0, table_size: int = 8):
    """
    Roda o batch completo (matchups x stacks) e sobe pro Supabase --
    a menos que dry_run=True, aí só retorna as rows sem inserir (útil
    pra conferir antes de gravar).

    `open_sizes` (lista, ex [2.0, 2.5, 3.0]) gera spots multi-tamanho
    -- formato NOVO em gto_nodes (ver build_drill_row_multisize), grava
    numa linha SEPARADA (spot_id com sufixo "_msize") pra não colidir
    nem substituir os spots de 1 tamanho já validados/em produção.
    Sem `open_sizes`, comportamento idêntico a antes (`open_size`
    escalar, formato antigo) -- nenhuma mudança pro que já existe.

    `ante_bb` (2026-08): ante de CADA jogador, em bb (ex 0.125 pra um
    ante de 12,5% do BB, típico de MTT real -- conferido contra mãos
    reais da conta do usuário: 30/250, 35/300, 20/160, 25/200, 36/250 --
    todas na faixa 12-15%). `table_size` é quantos assentos pagam ante
    nessa mão (default 8, o mais comum nas mãos reais analisadas).
    `ante_pool = ante_bb * table_size` vai pro solver (ver
    engine/rfi_jam.py). Default ante_bb=0.0 mantém o comportamento de
    sempre — spot_id só ganha o sufixo "_ante" quando ante_bb>0, pra
    NUNCA sobrescrever os spots sem ante já em produção (mesma cautela
    já usada pro sufixo "_msize").
    """
    client = None if dry_run else get_client()
    results = []
    multisize = bool(open_sizes and len(open_sizes) > 1)
    ante_pool = ante_bb * table_size
    ante_suffix = f"_ante{ante_bb}" if ante_pool > 0 else ""
    engine_version = ENGINE_VERSION_ANTE if ante_pool > 0 else ENGINE_VERSION

    for matchup in matchups:
        if matchup not in MATCHUPS:
            raise ValueError(f"Matchup '{matchup}' nao validado ainda -- ver MATCHUPS neste arquivo.")
        opener_post, defender_post, dead_money = MATCHUPS[matchup]

        for stack in stacks_bb:
            table_stacks = [stack, stack] + other_stacks
            solver = RfiJamSolver(
                sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
                equity_matrix=equity_matrix, classes=classes,
                open_size=open_size, open_sizes=open_sizes,
                effective_stack=stack, opener_post=opener_post, defender_post=defender_post,
                dead_money=dead_money, ante_pool=ante_pool,
            )
            solver.train(iterations=iterations)
            strat = solver.average_strategy()
            evs = solver.compute_action_evs(strat)
            br_sb, br_bb = solver.compute_exploitability(strat)

            if multisize:
                spot_id = f"rfi_jam_{matchup}_{int(stack)}bb_msize{ante_suffix}"
                row = build_drill_row_multisize(spot_id, matchup, solver, strat, evs, br_sb + br_bb, job_id, stack)
                if ante_pool > 0:
                    row["engine_version"] = engine_version
            else:
                spot_id = f"rfi_jam_{matchup}_{int(stack)}bb{ante_suffix}"
                row = build_drill_row(spot_id, matchup, solver, strat, evs, br_sb + br_bb, job_id, stack)
                row["engine_version"] = engine_version
            results.append(row)

            if client and job_id:
                client.table("solver_jobs").update({
                    "progress": f"{len(results)}/{len(matchups) * len(stacks_bb)}",
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }).eq("id", job_id).execute()

    if client:
        client.table("drills").insert(results).execute()
    return results
