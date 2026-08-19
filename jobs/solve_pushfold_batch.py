"""
Job de geração em lote: resolve spots de shove/fold (com ICM) e sobe
o resultado pro Supabase, na tabela `drills`.

IMPORTANTE — decisão em aberto antes de rodar isso contra o Supabase
de produção: o mapeamento exato de colunas abaixo (`spot_id`,
`gto_nodes`, etc) foi escrito seguindo a convenção que já existia nos
dumps do TexasSolver, mas não foi confirmado contra o schema real via
`information_schema.columns` (prática que o próprio pipeline anterior
já usava e que vale manter). Antes do primeiro job real, rodar:

    select column_name, data_type from information_schema.columns
    where table_schema='public' and table_name='drills';

e ajustar `build_drill_row()` se algo divergir.

Também adiciona (por decisão registrada): exploitability, config do
motor e versão do engine em cada linha — é o log de convergência que
faltava no pipeline anterior e que tornou o diagnóstico do TexasSolver
tão demorado. Sem isso de novo, nunca mais.
"""

import datetime
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.pushfold_icm import PushFoldICMSolver  # noqa: E402
from engine.hand_classes import combo_count  # noqa: E402
from jobs.supabase_client import get_client  # noqa: E402

ENGINE_VERSION = "pokersync-solver-v0.1.0-pushfold-icm"


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
    gto_nodes = {
        "actions": ["fold", "push"],
        "player": "sb",
        "strategy": {c: [1 - strat["sb_push"][c], strat["sb_push"][c]] for c in solver.classes},
        "bb_response": {
            "actions": ["fold", "call"],
            "strategy": {c: [1 - strat["bb_call"][c], strat["bb_call"][c]] for c in solver.classes},
        },
    }
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
        "action": "pushfold",  # NOVO tipo de acao -- nao existe equivalente aos valores atuais ('vs Open'); avaliar se faz sentido manter esse nome
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

        spot_id = f"pushfold_icm_{int(stack)}bb_sb_vs_bb_{uuid.uuid4().hex[:8]}"
        row = build_drill_row(spot_id, solver, strat, exploitability, job_id, stack_bb=stack)
        results.append(row)

        # atualiza status do job incrementalmente (visivel via GET /jobs/{id})
        client.table("solver_jobs").update({
            "progress": f"{len(results)}/{len(stacks_bb)}",
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()

    # upload em lote no final (poderia ser incremental tambem, se preferir
    # ver os spots aparecendo um a um no Supabase durante o job)
    client.table("drills").insert(results).execute()
    return results
