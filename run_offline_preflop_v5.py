"""
Treino offline do pré-flop v5 (engine/preflop_v5.py): a mão INTEIRA da
mesa cheia -- open, call, 3-bet, 4-bet, all-in, limp do SB -- uma solução
por profundidade de stack.

PENSADO PRA RODAR NO SEU COMPUTADOR (usa todos os núcleos do processador).

## Como usar

1. Dependências (Python 3.10 ou mais novo):
   ```
   pip install -r requirements.txt
   ```
   (precisa do numba -- já está no requirements.txt)

2. Roda:
   ```
   python run_offline_preflop_v5.py
   ```
   Treina 15, 25, 40, 60 e 100bb, nessa ordem (do mais rápido pro mais
   lento). Mostra o progresso a cada checkpoint (~10 minutos).

3. Pode fechar/desligar a qualquer momento: na próxima vez ele CONTINUA de
   onde parou (perde no máximo ~10 minutos). Ctrl+C salva antes de sair.

4. Quando um stack termina o treino, roda a checagem obrigatória de todas
   as decisões (ver CLAUDE.md) e grava resultado_preflop_v5_<stack>bb_<mesa>max.pkl.

Opções:
  --stacks 15,25        só esses stacks
  --mesa 9              mesa de 9 jogadores (padrão 8)
  --icm                 valores em ICM (prêmios 50/30/20% da mesa) em vez de fichas
  --iteracoes 50000000  alvo de iterações (padrão: depende do stack, ver ITERATIONS_BY_STACK)
  --pasta CAMINHO       onde ficam checkpoints/resultados (padrão: pasta deste script)
  --nucleos 8           quantos núcleos usar (padrão: todos)
  --checagem-mesas N    mesas sorteadas na checagem final (padrão 100 mil)
"""

import argparse
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from offline_common import (GracefulStop, atomic_pickle_dump, check_python_version,  # noqa: E402
                            format_duration, move_aside)

STACKS = [15.0, 25.0, 40.0, 60.0, 100.0]
# Iterações (mesas sorteadas) por stack. Árvores mais fundas têm mais
# situações e cada situação é alcançada menos vezes -> precisam de mais.
ITERATIONS_BY_STACK = {15.0: 100_000_000, 25.0: 150_000_000, 40.0: 200_000_000,
                       60.0: 200_000_000, 100.0: 300_000_000}
DEFAULT_ITERATIONS = 200_000_000
ICM_PAYOUTS = [500.0, 300.0, 200.0]
CHECKPOINT_MINUTES = 10
RESULT_FORMAT = 1


def label_for(stack, mesa, icm):
    return f"preflop_v5_{int(stack)}bb_{mesa}max" + ("_icm" if icm else "")


def config_key(cfg):
    """O que precisa bater pra um checkpoint poder ser retomado."""
    return {k: getattr(cfg, k) for k in ("stack", "n", "ante", "open_size", "sb_open_size", "bb_iso_size",
                                         "threebet_ip", "threebet_oop", "per_caller", "fourbet_mult",
                                         "jam_threshold", "max_flop", "sb_limp", "payouts")}


def export_strategy(solver):
    """Estratégia média de cada situação: histórico (posição, ação),
    quem decide, nomes das ações e frequência [classe][ação]."""
    import numpy as np
    from engine.preflop_v5 import CLASSES, PLAYER, _avg
    tr = solver.tree
    pos = solver.cfg.positions
    nodes = []
    for nid in np.nonzero(tr.ntype == PLAYER)[0]:
        na = int(tr.nact[nid])
        off = int(tr.regoff[nid])
        freq = np.array([_avg(solver.ssum, off, na, c) for c in range(169)], dtype=np.float32)
        nodes.append({
            "node": int(nid),
            "hist": [(pos[s], lab) for s, lab in tr.hist[nid]],
            "actor": pos[int(tr.actor[nid])],
            "labels": list(tr.labels[nid]),
            "freq": freq,
        })
    return {"classes": list(CLASSES), "nodes": nodes}


def run_one(stack, mesa, icm, iterations, out_dir, stop, check_deals=100_000):
    from engine.preflop_v5 import ENGINE_VERSION, PreflopConfig, PreflopSolver
    label = label_for(stack, mesa, icm)
    result_path = out_dir / f"resultado_{label}.pkl"
    ckpt_path = out_dir / f"checkpoint_{label}.pkl"
    cfg = PreflopConfig(stack, n_players=mesa, payouts=ICM_PAYOUTS if icm else None)
    key = config_key(cfg)

    if result_path.exists():
        try:
            data = pickle.load(open(result_path, "rb"))
            ok = data.get("engine_version") == ENGINE_VERSION and data.get("config") == key
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            print(f"[{label}] já tem resultado da versão atual -- pulando.")
            return "skipped"
        moved = move_aside(result_path, "versao-antiga")
        print(f"[{label}] resultado existente é de outra versão/configuração -- guardado como {moved.name}.")

    solver = PreflopSolver(cfg)
    for cand in (ckpt_path, ckpt_path.with_name(ckpt_path.name + ".bak")):
        if not cand.exists():
            continue
        try:
            st = pickle.load(open(cand, "rb"))
            if st.get("engine_version") != ENGINE_VERSION or st.get("config") != key:
                raise ValueError("versão do motor ou configuração diferente")
            if st["reg"].shape != solver.reg.shape:
                raise ValueError("tamanho da árvore diferente")
            solver.reg[:] = st["reg"]
            solver.ssum[:] = st["ssum"]
            solver.iterations = int(st["iterations"])
            print(f"[{label}] retomando: {solver.iterations:,}/{iterations:,} iterações já feitas.")
            break
        except Exception as e:  # noqa: BLE001
            moved = move_aside(cand, "incompativel")
            print(f"  AVISO: {cand.name} não pode ser retomado ({e}) -- renomeado para {moved.name}.")
    else:
        print(f"[{label}] começando do zero ({solver.tree.n_nodes:,} situações na árvore).")

    def save():
        atomic_pickle_dump({"engine_version": ENGINE_VERSION, "config": key, "reg": solver.reg,
                            "ssum": solver.ssum, "iterations": solver.iterations,
                            "saved_at": datetime.now().isoformat(timespec="seconds")},
                           ckpt_path, keep_backup=True)

    chunk = 200_000
    t0 = time.time()
    start = solver.iterations
    last = time.time()
    while solver.iterations < iterations:
        if stop.requested:
            save()
            print(f"[{label}] parado em {solver.iterations:,} iterações -- checkpoint salvo.")
            return "stopped"
        solver.train(min(chunk, iterations - solver.iterations), parallel=True)
        if time.time() - last >= CHECKPOINT_MINUTES * 60 or solver.iterations >= iterations:
            save()
            last = time.time()
            rate = (solver.iterations - start) / max(time.time() - t0, 1e-9)
            eta = (iterations - solver.iterations) / rate if rate > 0 else 0
            print(f"  [{label}] {100 * solver.iterations / iterations:5.1f}%  {solver.iterations:,}  "
                  f"{rate:,.0f} it/s  falta ~{format_duration(eta)}  (checkpoint salvo)", flush=True)

    print(f"  [{label}] treino concluído. Checagem obrigatória de todas as decisões (ver CLAUDE.md)...",
          flush=True)
    stop.immediate = True
    t = time.time()
    flags = solver.check_convergence(deals=check_deals)
    summary = solver.last_check_summary
    print(f"  [{label}] checagem em {format_duration(time.time() - t)}: {summary['flagged']} apontada(s), "
          f"{summary['refuted']} alarme(s) desmentido(s) na reconferência, {summary['inconclusive']} "
          f"inconclusiva(s), {summary['rare_nodes_skipped']} situação(ões) rara(s) demais pra checar.")
    for f in flags[:20]:
        print(f"    {f['hand']:>4}  {f['situacao']}: melhor {f['best']} (+{f['gap']:.3f}), "
              f"treino {', '.join(f'{k} {v:.0%}' for k, v in f['trained'].items())}")
    atomic_pickle_dump({
        "format": RESULT_FORMAT,
        "engine_version": ENGINE_VERSION,
        "config": key,
        "iterations": solver.iterations,
        "strategy": export_strategy(solver),
        "sanity_flags": flags,
        "sanity_summary": summary,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }, result_path)
    print(f"[{label}] resultado salvo em {result_path.name}.")
    return "done"


def _parse_list(text, cast):
    return [cast(x.strip()) for x in text.split(",") if x.strip()]


def main():
    check_python_version()
    ap = argparse.ArgumentParser(description="Treino offline do pré-flop v5 (mesa cheia).")
    ap.add_argument("--stacks", type=lambda t: _parse_list(t, float), default=STACKS)
    ap.add_argument("--mesa", type=int, choices=(8, 9), default=8)
    ap.add_argument("--icm", action="store_true")
    ap.add_argument("--iteracoes", type=int, default=None)
    ap.add_argument("--pasta", type=Path, default=BASE_DIR)
    ap.add_argument("--nucleos", type=int, default=None)
    ap.add_argument("--checagem-mesas", type=int, default=100_000,
                    help="mesas sorteadas na checagem final (padrão 100 mil)")
    args = ap.parse_args()
    if args.nucleos:
        import numba
        numba.set_num_threads(args.nucleos)
    out_dir = args.pasta.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    from engine.preflop_v5 import ENGINE_VERSION
    print(f"Motor {ENGINE_VERSION}. Mesa de {args.mesa}, {'ICM' if args.icm else 'fichas (chipEV)'}. "
          f"Stacks: {', '.join(f'{s:g}' for s in args.stacks)}. Arquivos em {out_dir}.\n"
          f"Pode parar (Ctrl+C) e retomar quando quiser.\n", flush=True)
    with GracefulStop() as stop:
        for stack in args.stacks:
            it = args.iteracoes or ITERATIONS_BY_STACK.get(stack, DEFAULT_ITERATIONS)
            if run_one(stack, args.mesa, args.icm, it, out_dir, stop, args.checagem_mesas) == "stopped":
                return
    print("Todos os stacks concluídos!")


if __name__ == "__main__":
    main()
