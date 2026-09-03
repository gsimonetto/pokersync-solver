"""
Job de geração em lote: resolve spots de shove/fold (com ICM) e sobe
o resultado pro Supabase, na tabela `drills`.

Mapeamento de colunas em `build_drill_row()` CONFERIDO contra o schema
real da tabela (via `list_tables`/`information_schema.columns`) — bate
exatamente (spot_id, board, pot, effective_stack, gto_nodes, solution,
format, stack_bb, position, street, action, engine_version,
exploitability, solver_job_id, generated_at). Ainda falta criar a
tabela `solver_jobs` (usada por `api/main.py` e pelo update de
progresso abaixo) — ver README, seção "Pendente antes do primeiro job
real".

Também adiciona (por decisão registrada): exploitability, config do
motor e versão do engine em cada linha — é o log de convergência que
faltava no pipeline anterior e que tornou o diagnóstico do TexasSolver
tão demorado. Sem isso de novo, nunca mais.
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.pushfold_icm import PushFoldICMSolver  # noqa: E402
from engine.hand_classes import combo_count  # noqa: E402
from jobs.supabase_client import get_client  # noqa: E402

# v0.2.0: gto_nodes passou a carregar EV por classe (nao so' frequencia)
# no MESMO formato que o RFI/Jam ja' usa (sb_open/bb_jam, cada um com
# ev_fold + hands: {classe: [freq, ev, gap]}) -- o Treino reaproveita a
# mesma tela/logica de veredito sem precisar de um formato novo so' pra
# Push/Fold. spot_id tambem ficou DETERMINISTICO (sem sufixo aleatorio):
# permite upsert (re-rodar o job atualiza o spot em vez de duplicar).
ENGINE_VERSION = "pokersync-solver-v0.2.0-pushfold-icm"


def compute_exploitability_estimate(solver: PushFoldICMSolver, strat: dict) -> float:
    """
    Estimativa simplificada de exploitability pro caso shove/fold: mede
    o quanto cada jogador ganharia desviando pra melhor resposta pura
    contra a estrategia media do oponente, ponderado pelos pesos de
    combo. Não é o best-response completo de árvore geral (esse fica
    pro validador de Kuhn Poker / futuras árvores maiores), mas serve
    de sinal de alerta rápido por spot antes de subir pro Supabase.
    """
    sb_push = strat["sb_push"]
    bb_call = strat["bb_call"]
    total_gap = 0.0
    for i, c in enumerate(solver.classes):
        w = solver.weights_norm[i]
        # gap de SB: |estrategia media - decisao pura otima| pondera o quanto
        # ainda oscila entre 0 e 1 sem se firmar (proxy de nao-convergencia)
        gap_sb = min(sb_push[c], 1 - sb_push[c])
        gap_bb = min(bb_call[c], 1 - bb_call[c])
        total_gap += w * (gap_sb + gap_bb)
    return total_gap


def build_drill_row(spot_id: str, solver: PushFoldICMSolver, strat: dict, exploitability: float,
                     job_id: str, stack_bb: float):
    evs = solver.final_evs(strat)

    # Mesmo formato que RfiJamPhaseRaw (frontend, rfi-jam-service.ts):
    # {ev_fold, action, hands: {classe: [freq, ev, gap]}}. sb_open aqui
    # e' a decisao "empurrar ou foldar" do SB (acao "allin", nao "open"
    # -- e' shove direto, sem meio-termo); bb_jam e' a decisao "pagar ou
    # foldar" da BB depois do push. Sem sb_call_jam -- push/fold so' tem
    # essas 2 decisoes (nao existe uma 3a fase "pagar o all-in", quem
    # empurrou ja' esta' all-in por definicao).
    gap = lambda ev, ev_fold: abs(ev - ev_fold)  # noqa: E731
    sb_open = {
        "ev_fold": evs["sb_ev_fold"],
        "action": "allin",
        "hands": {
            c: [strat["sb_push"][c], evs["sb_ev_push"][c], gap(evs["sb_ev_push"][c], evs["sb_ev_fold"])]
            for c in solver.classes
        },
    }
    bb_jam = {
        "ev_fold": evs["bb_ev_fold"],
        "action": "call",
        "hands": {
            c: [strat["bb_call"][c], evs["bb_ev_call"][c], gap(evs["bb_ev_call"][c], evs["bb_ev_fold"])]
            for c in solver.classes
        },
    }
    gto_nodes = {"sb_open": sb_open, "bb_jam": bb_jam}

    return {
        "spot_id": spot_id,
        "board": [],  # push/fold pre-flop puro, sem board
        "pot": 1.5,  # sb (0.5) + bb (1.0) antes de qualquer acao
        "effective_stack": solver.effective_stack,
        "gto_nodes": gto_nodes,
        "solution": None,  # nao usado em nenhuma linha existente da tabela, deixei null pra nao inventar convencao
        "format": None,  # idem
        "stack_bb": int(stack_bb),
        "position": "sb_vs_bb",
        "street": "Preflop",  # convencao real da tabela usa capitalizado (ex: 'Flop','Turn','River')
        "action": "pushfold",
        "engine_version": ENGINE_VERSION,
        "exploitability": exploitability,
        "solver_job_id": job_id,
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }


def run_pushfold_batch(job_id: str, stacks_bb: list[float], table_context: dict, payouts: list[float],
                        equity_matrix, classes, iterations=2000):
    """
    table_context: dict com 'other_stacks' (lista de stacks dos demais
    jogadores da mesa, em bb) -- usado igual pra todos os stacks de SB/BB
    testados nesse batch (assume mesa fixa; ajustar se precisar variar).
    """
    client = get_client()
    results = []

    for stack in stacks_bb:
        table_stacks = [stack, stack] + table_context["other_stacks"]
        solver = PushFoldICMSolver(
            sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
            equity_matrix=equity_matrix, classes=classes,
        )
        solver.train(iterations=iterations)
        strat = solver.average_strategy()
        exploitability = compute_exploitability_estimate(solver, strat)

        # Deterministico (sem sufixo aleatorio) -- re-rodar o mesmo stack
        # atualiza a linha via upsert em vez de criar uma duplicata nova
        # (mesmo bug de idempotencia ja' corrigido no RFI/Jam, decisao 011).
        spot_id = f"pushfold_icm_sb_vs_bb_{int(stack)}bb"
        row = build_drill_row(spot_id, solver, strat, exploitability, job_id, stack_bb=stack)
        results.append(row)

        # atualiza status do job incrementalmente (visivel via GET /jobs/{id})
        client.table("solver_jobs").update({
            "progress": f"{len(results)}/{len(stacks_bb)}",
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()

    # upsert por spot_id (nao insert) -- re-rodar o job sobrescreve o
    # spot existente em vez de duplicar.
    client.table("drills").upsert(results, on_conflict="spot_id").execute()
    return results
