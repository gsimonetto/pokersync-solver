"""
Regera os spots de RFI/Jam (sb_vs_bb, btn_vs_bb) JÁ EM PRODUÇÃO, agora
com ante — ver engine/rfi_jam.py::ante_pool e README.md ("Ante", seção
de status do motor) pro contexto completo do bug corrigido.

PENSADO PRA RODAR NO SEU COMPUTADOR (mas ao contrário de
run_offline_multiway.py/run_offline_all_positions.py, este é o motor
HEADS-UP -- bem mais rápido, deve terminar as 8 combinações em minutos,
não dias; ainda assim salva checkpoint por segurança, igual os outros
scripts offline, caso seu PC seja mais lento ou você rode mais
iterações que o padrão).

## Como usar

1. Confere se as dependências estão instaladas (mesma coisa de sempre):
   ```
   python3 -m venv .venv
   source .venv/bin/activate      # no Windows: .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```

2. Roda o script:
   ```
   python3 run_offline_rfi_jam_ante.py
   ```

3. Ele resolve sb_vs_bb e btn_vs_bb x 15/25/40/60bb (as 8 combinações
   já em produção sem ante) com o ante configurado em ANTE_BB/TABLE_SIZE
   abaixo, e salva cada resultado em `resultado_rfi_jam_ante_<matchup>_
   <stack>bb.pkl` nesta mesma pasta. Se parar no meio, rodar de novo
   continua de onde parou (checkpoint por combinação).

4. Quando todos os `resultado_rfi_jam_ante_*.pkl` existirem, rode a
   etapa de upload (grava no Supabase, tabela `drills`, com spot_id
   sufixado "_ante{X}" -- NUNCA sobrescreve os spots sem ante já em
   produção):
   ```
   python3 run_offline_rfi_jam_ante.py --upload
   ```
   Precisa de SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no ambiente
   (mesmo .env do resto do projeto, ver README.md "Setup local").

## Ajustando o ante

ANTE_BB é o ante de CADA jogador, em bb (fração do big blind). O
default abaixo (0.125 = 12,5%) é a média observada nas mãos reais
analisadas da conta do usuário (30/250=12%, 35/300=11.7%, 20/160=12.5%,
25/200=12.5%, 36/250=14.4%) -- ajuste se o seu jogo tiver uma estrutura
de ante diferente (torneios turbo/hyper costumam ter ante maior
relativo ao bb). TABLE_SIZE é quantos assentos pagam ante nessa mão
(8 = a maioria das suas mãos reais; ajuste pra 9 se jogar full-ring,
ou menos perto da bolha/mesa final).
"""

import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.equity_final import build_final_equity_matrix  # noqa: E402
from engine.rfi_jam import RfiJamSolver  # noqa: E402
from jobs.solve_rfi_jam_batch import MATCHUPS, build_drill_row, ENGINE_VERSION_ANTE  # noqa: E402

ANTE_BB = 0.125
TABLE_SIZE = 8
ANTE_POOL = ANTE_BB * TABLE_SIZE

STACKS = [15.0, 25.0, 40.0, 60.0]
MATCHUP_NAMES = ["sb_vs_bb", "btn_vs_bb"]
OTHER_STACKS = [40.0, 25.0, 18.0, 12.0]  # mesmo perfil de mesa usado em produção
PAYOUTS = [500.0, 300.0, 200.0]  # placeholder -- estrutura de premiação não muda o formato do range, só a magnitude do $EV; troque se quiser $EV exato pro seu formato de torneio

TOTAL_ITERATIONS = 2_500_000  # mesmo valor default de jobs/solve_rfi_jam_batch.py
CHECKPOINT_EVERY = 250_000
EQUITY_MATRIX_PATH = Path("data/equity_matrix_cache.pkl")


def load_or_build_equity_matrix():
    if EQUITY_MATRIX_PATH.exists():
        print("Carregando matriz de equity já calculada...")
        with open(EQUITY_MATRIX_PATH, "rb") as f:
            d = pickle.load(f)
        return d["matrix"], d["classes"]
    print("Construindo matriz de equity pairwise (só na primeira vez, alguns minutos)...")
    matrix, classes, _stats = build_final_equity_matrix()
    EQUITY_MATRIX_PATH.parent.mkdir(exist_ok=True)
    with open(EQUITY_MATRIX_PATH, "wb") as f:
        pickle.dump({"matrix": matrix, "classes": classes}, f)
    return matrix, classes


def run_one(matchup: str, stack: float, equity_matrix, classes):
    label = f"{matchup}_{int(stack)}bb"
    result_path = Path(f"resultado_rfi_jam_ante_{label}.pkl")
    if result_path.exists():
        print(f"[{label}] já tem resultado final ({result_path}) -- pulando.")
        return

    checkpoint_path = Path(f"checkpoint_rfi_jam_ante_{label}.pkl")
    opener_post, defender_post, dead_money = MATCHUPS[matchup]

    if checkpoint_path.exists():
        print(f"[{label}] retomando checkpoint existente...")
        with open(checkpoint_path, "rb") as f:
            state = pickle.load(f)
        solver = state["solver"]
        done_iterations = state["done_iterations"]
    else:
        print(f"[{label}] começando do zero (ante_pool={ANTE_POOL:.3f}bb)...")
        table_stacks = [stack, stack] + OTHER_STACKS
        solver = RfiJamSolver(
            sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=PAYOUTS,
            equity_matrix=equity_matrix, classes=classes,
            open_size=2.2, effective_stack=stack,
            opener_post=opener_post, defender_post=defender_post,
            dead_money=dead_money, ante_pool=ANTE_POOL,
        )
        done_iterations = 0

    while done_iterations < TOTAL_ITERATIONS:
        batch = min(CHECKPOINT_EVERY, TOTAL_ITERATIONS - done_iterations)
        t0 = time.time()
        solver.train(iterations=batch, seed=done_iterations + 1)
        done_iterations += batch
        dt = time.time() - t0

        with open(checkpoint_path, "wb") as f:
            pickle.dump({"solver": solver, "done_iterations": done_iterations}, f)

        pct = 100 * done_iterations / TOTAL_ITERATIONS
        eta_min = (TOTAL_ITERATIONS - done_iterations) / batch * dt / 60 if batch else 0
        print(f"  [{label}] {pct:5.1f}%  {done_iterations}/{TOTAL_ITERATIONS}  "
              f"({dt:.1f}s neste lote, ETA ~{eta_min:.1f}min)")

    strat = solver.average_strategy()
    evs = solver.compute_action_evs(strat)
    br_sb, br_bb = solver.compute_exploitability(strat)

    spot_id = f"rfi_jam_{matchup}_{int(stack)}bb_ante{ANTE_BB}"
    row = build_drill_row(spot_id, matchup, solver, strat, evs, br_sb + br_bb, job_id=None, stack_bb=stack)
    row["engine_version"] = ENGINE_VERSION_ANTE

    with open(result_path, "wb") as f:
        pickle.dump(row, f)
    checkpoint_path.unlink(missing_ok=True)
    print(f"[{label}] CONCLUÍDO -- exploitability={br_sb + br_bb:.3f} -- salvo em {result_path}\n")


def upload_results():
    from jobs.supabase_client import get_client

    client = get_client()
    rows = []
    for matchup in MATCHUP_NAMES:
        for stack in STACKS:
            label = f"{matchup}_{int(stack)}bb"
            result_path = Path(f"resultado_rfi_jam_ante_{label}.pkl")
            if not result_path.exists():
                print(f"[{label}] resultado_*.pkl ainda não existe -- rode sem --upload primeiro.")
                return
            with open(result_path, "rb") as f:
                rows.append(pickle.load(f))

    print(f"Subindo {len(rows)} spots pra tabela drills (spot_id com sufixo _ante{ANTE_BB})...")
    client.table("drills").insert(rows).execute()
    print("OK -- upload concluído.")


def main():
    if "--upload" in sys.argv:
        upload_results()
        return

    equity_matrix, classes = load_or_build_equity_matrix()
    jobs = [(matchup, stack) for matchup in MATCHUP_NAMES for stack in STACKS]
    print(f"Fila: {len(jobs)} combinações (matchup x stack), ante_pool={ANTE_POOL:.3f}bb "
          f"({ANTE_BB}bb x {TABLE_SIZE} assentos). Deixa rodando -- pode parar e retomar a qualquer momento.\n")

    for matchup, stack in jobs:
        run_one(matchup, stack, equity_matrix, classes)

    print("Fila inteira concluída! Rode com --upload pra subir os spots pro Supabase.")


if __name__ == "__main__":
    main()
