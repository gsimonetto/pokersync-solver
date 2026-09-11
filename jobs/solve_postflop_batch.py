"""
Job de geracao em lote pra spots pos-flop de RIVER (c-bet do agressor
anterior -- o jogador que já vinha apostando decide apostar/desistir no
rio, o outro decide pagar/desistir/dar raise all-in).

Por que só river por enquanto: é o único estágio pós-flop com
exploitability rigorosa validada (~0,39% do pote, ver
tests/postflop_exploitability.py e README). Turn/flop usam nó de
chance (carta ainda não revelada) e não têm essa mesma validação de
produção ainda -- não usar este job pra eles sem repetir esse processo
de validação primeiro.

Desde que PostflopSolver ganhou compute_action_evs() (equivalente
pós-flop de rfi_jam.py::compute_action_evs), gto_nodes aqui carrega o
mesmo formato compacto [freq, ev, gap] já usado no RFI/Jam -- não só
frequência. "ev"/"gap" ficam null quando o infoset nunca foi
alcançado no treino (ex: uma classe que sempre faz outra coisa antes
de chegar nesse nó -- não tem reach pra condicionar o EV médio, ver
compute_action_evs() no engine).

Range de exemplo: como o motor não modela as ruas anteriores (flop/
turn), quem chama este job precisa fornecer range_oop/range_ip já
prontas (dict classe->peso) representando quem chega no river com o
quê -- não há "range realista" derivada automaticamente ainda. Ver
DEFAULT_CBET_RIVER_SPOT abaixo pra um primeiro spot ilustrativo
(polarizado clássico: valor+blefe vs bluff-catcher).
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.postflop import PostflopSolver  # noqa: E402
from jobs.supabase_client import get_client  # noqa: E402

ENGINE_VERSION = "pokersync-solver-v0.6.0-postflop-river-ev"

# Primeiro spot ilustrativo: c-bet de river num board seco/desconectado,
# pote de tamanho médio, profundidade rasa o bastante pra caber 1 raise
# all-in depois da aposta inicial. OOP chega com um range polarizado
# (valor forte + blefe que não tem mais nenhum showdown), IP com um
# range de bluff-catchers puros (perde pro valor, vence o blefe).
#
# ATENCAO: e' um range ILUSTRATIVO pra provar o pipeline ponta a ponta,
# nao foi derivado de uma simulacao real de flop+turn -- construir
# ranges realistas por spot e' trabalho futuro (precisa ou de um motor
# que jogue flop+turn de verdade, ou de ranges cadastradas a mao por
# alguem que entenda o spot).
DEFAULT_CBET_RIVER_SPOT = {
    "label": "cbet_river_dry_board",
    "board": "Ah Kd 7s 2c 9h",
    "range_oop": {"AA": 1.0, "KK": 1.0, "AKs": 1.0, "AKo": 1.0, "T9s": 0.5, "87s": 0.5},
    "range_ip": {"QQ": 1.0, "JJ": 1.0, "TT": 1.0, "99": 1.0},
    "pot": 20.0,
    "stack_oop": 40.0,
    "stack_ip": 40.0,
    "bet_sizes": (0.33, 0.75, 1.5),
}


def _merge_freq_ev(freq_row: dict, ev_row: dict | None) -> dict:
    """Combina {acao: freq} (da estrategia media) com o {acao: ev, ...,
    "gaps": {...}} de compute_action_evs() -- formato COMPACTO de
    producao [freq, ev, gap] por acao, mesmo espirito de
    solve_rfi_jam_batch.py::_compact_phase. ev/gap ficam None quando o
    infoset nunca foi alcancado no treino (compute_action_evs() so'
    inclui classes com reach > 0 -- ver docstring do metodo)."""
    out = {}
    for action, freq in freq_row.items():
        ev = ev_row.get(action) if ev_row else None
        gap = ev_row["gaps"].get(action) if ev_row else None
        out[action] = [
            round(freq, 4),
            round(ev, 3) if ev is not None else None,
            round(gap, 3) if gap is not None else None,
        ]
    return out


def _facing_bet_by_size(solver: PostflopSolver, bettor: str, responder_classes: list,
                         after_check: bool, evs: dict, node_prefix: str) -> dict:
    out = {}
    for idx, size in enumerate(solver.bet_sizes):
        per_class = {}
        ev_node = evs.get(f"{node_prefix}_{idx}", {})
        for c in responder_classes:
            s = solver.facing_bet_strategy(bettor, idx, c, after_check=after_check)
            if s is None:
                continue
            freq_row = {"fold": s[0], "call": s[1]}
            if len(s) > 2:
                freq_row["raise"] = s[2]
            per_class[c] = _merge_freq_ev(freq_row, ev_node.get(c))
        if per_class:
            out[str(size)] = per_class
    return out


def _facing_raise_by_size(solver: PostflopSolver, bettor: str, bettor_classes: list,
                           after_check: bool, evs: dict, node_prefix: str) -> dict:
    out = {}
    for idx, size in enumerate(solver.bet_sizes):
        per_class = {}
        ev_node = evs.get(f"{node_prefix}_{idx}", {})
        for c in bettor_classes:
            s = solver.facing_raise_strategy(bettor, idx, c, after_check=after_check)
            if s is None:
                continue
            freq_row = {"fold": s[0], "call": s[1]}
            per_class[c] = _merge_freq_ev(freq_row, ev_node.get(c))
        if per_class:
            out[str(size)] = per_class
    return out


def build_drill_row(spot_id: str, board: list, solver: PostflopSolver, exploitability: float,
                     job_id: str | None, matchup_label: str) -> dict:
    """Monta a linha pra `drills`. Cobre os 6 nos de decisao possiveis
    num river de 1 aposta + 1 raise (ver docstring do arquivo pra
    a arvore completa):
      - oop_root: OOP aposta ou passa, primeiro a agir
      - ip_facing_bet: IP responde a aposta da OOP na raiz
      - oop_facing_raise: OOP responde a um raise da IP
      - ip_root_after_oop_check: IP aposta ou passa, depois de OOP passar
      - oop_facing_bet_after_check: OOP responde a aposta da IP (que veio depois do check da OOP)
      - ip_facing_raise_after_check: IP responde a um raise da OOP (nesse ramo)

    Cada mao em cada no vem no formato compacto [freq, ev, gap] (ver
    _merge_freq_ev) -- ev/gap sao o valor calculado por
    compute_action_evs(), reaproveitando o mesmo motor de
    melhor-resposta ja validado por compute_exploitability().
    """
    strat_root = solver.average_strategy_root()
    evs = solver.compute_action_evs()
    gto_nodes = {
        "bet_sizes": list(solver.bet_sizes),
        "oop_root": {c: _merge_freq_ev(s, evs.get("root", {}).get(c)) for c, s in strat_root["oop"].items()},
        "ip_root_after_oop_check": {
            c: _merge_freq_ev(s, evs.get("facing_check", {}).get(c)) for c, s in strat_root["ip"].items()
        },
        "ip_facing_bet": _facing_bet_by_size(solver, "oop", solver.classes_ip, False, evs, "facing_bet"),
        "oop_facing_raise": _facing_raise_by_size(solver, "oop", solver.classes_oop, False, evs, "facing_raise"),
        "oop_facing_bet_after_check": _facing_bet_by_size(
            solver, "ip", solver.classes_oop, True, evs, "facing_bet_after_check",
        ),
        "ip_facing_raise_after_check": _facing_raise_by_size(
            solver, "ip", solver.classes_ip, True, evs, "facing_raise_after_check",
        ),
    }

    return {
        "spot_id": spot_id,
        "board": board,
        "pot": solver.pot0,
        "effective_stack": min(solver.stack_oop, solver.stack_ip),
        "gto_nodes": gto_nodes,
        "solution": None,
        "format": None,
        "stack_bb": None,
        "position": matchup_label,
        "street": "River",
        "action": "cbet_river",
        "engine_version": ENGINE_VERSION,
        "exploitability": round(exploitability, 4),
        "solver_job_id": job_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def run_postflop_river_batch(job_id: str | None, spots: list[dict], iterations: int = 30_000,
                              dry_run: bool = False) -> list[dict]:
    """Roda 1+ spots de c-bet river (cada item de `spots` no formato de
    DEFAULT_CBET_RIVER_SPOT) e sobe pro Supabase, a menos que
    dry_run=True (só retorna as rows, não grava nem precisa de
    credenciais do Supabase -- usado pra validar localmente antes de
    publicar)."""
    client = None if dry_run else get_client()
    results = []

    for i, spot in enumerate(spots):
        solver = PostflopSolver(
            board=spot["board"],
            range_oop=spot["range_oop"],
            range_ip=spot["range_ip"],
            pot=spot["pot"],
            stack_oop=spot["stack_oop"],
            stack_ip=spot["stack_ip"],
            bet_sizes=spot.get("bet_sizes", (0.33, 0.75, 1.5)),
        )
        solver.train(iterations=iterations)
        br_oop, br_ip, exploitability = solver.compute_exploitability()

        board_list = list(solver.board0)
        spot_id = f"postflop_river_{spot['label']}"
        row = build_drill_row(spot_id, board_list, solver, exploitability, job_id, spot["label"])
        results.append(row)

        if client and job_id:
            client.table("solver_jobs").update({
                "progress": f"{i + 1}/{len(spots)}",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }).eq("id", job_id).execute()

    if client:
        client.table("drills").upsert(results, on_conflict="spot_id").execute()
    return results
