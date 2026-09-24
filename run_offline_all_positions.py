"""
Resolve as posições de RFI que ainda faltam (UTG, UTG+1, MP, HJ, CO —
todas contra BB), usando o motor multiway (`engine/multiway_rfi.py`).
SB vs BB e BTN vs BB já estão prontos e em produção; este script cobre
o resto da tabela.

PENSADO PRA RODAR NO SEU COMPUTADOR, NÃO NO SANDBOX.

## O que mudou em 2026-09-24 (auditoria)

- HJ, MP, UTG+1 e UTG TRAVAVAM logo na primeira mão (ZeroDivisionError no
  ICM quando 3+ jogadores quebram na mesma mão). Corrigido em engine/icm.py.
- Treino ~15-20x mais rápido (avaliador de mão novo, engine/fast_eval.py,
  com a MESMA ordem de mãos do treys -- testado nas 2,6 milhões de mãos de
  5 cartas). Memória limitada (antes UTG enchia dezenas de GB).
- Checkpoint à prova de queda de energia e de mudança de versão (ver
  offline_common.py): arquivo antigo/estragado é renomeado, nunca apagado,
  e o treino recomeça com um aviso claro em vez de quebrar.
- Resultados (resultado_*.pkl) gerados ANTES dessas correções são
  refeitos automaticamente (o arquivo antigo é renomeado pra
  resultado_*.pkl.versao-antiga-<data>, não é apagado).
- Ctrl+C agora salva o checkpoint e sai limpo.

## Como usar

1. Dependências (Python 3.10 ou mais novo). Pra SÓ treinar no PC basta:
   ```
   python -m venv .venv
   .venv\\Scripts\\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
   pip install -r requirements-offline.txt
   ```
   (requirements.txt completo também serve; o offline só precisa do treys
   e do numpy. Pra usar --upload precisa do supabase também.)

2. Roda:
   ```
   python run_offline_all_positions.py
   ```

3. Deixa rodando. Ele mostra o progresso (%, iterações/segundo, tempo que
   falta) a cada checkpoint (~10 minutos).

4. Pode fechar o terminal/desligar o PC a qualquer momento — na próxima
   vez ele CONTINUA de onde parou (perde no máximo os ~10 minutos desde o
   último checkpoint). Ctrl+C salva antes de sair.

5. Quando uma combinação posição+stack termina o treino, ele roda a
   avaliação final obrigatória (exploitability + checagem de convergência
   de todas as decisões, ver CLAUDE.md), salva resultado_<posição>_<stack>bb
   _ante0.125.pkl e passa pra próxima da fila sozinho.

6. Pra subir pro Supabase: `python run_offline_all_positions.py --upload`
   (use `--upload --dry-run` antes pra conferir o que vai subir, sem enviar).

Opções úteis:
  --posicoes CO,HJ     só essas posições (padrão: todas, na ordem da fila)
  --stacks 15,25       só esses stacks (padrão: 15,25,40,60)
  --iteracoes 200000   alvo de iterações por combinação (padrão: 1.000.000)
  --pasta CAMINHO      onde ficam checkpoints/resultados (padrão: a pasta
                       deste script, mesmo lugar de antes)

## Ordem da fila

Da posição mais rápida (menos jogadores) pra mais lenta:

  CO vs BB (4 seats: CO, BTN, SB, BB)      — mais rápido
  HJ vs BB (5 seats)
  MP vs BB (6 seats)
  UTG+1 vs BB (7 seats)
  UTG vs BB (8 seats)                      — mais lento

Pra cada posição, os 4 stacks já usados em produção: 15, 25, 40 e 60bb.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from offline_common import (  # noqa: E402
    GracefulStop, check_python_version, load_result, train_and_evaluate,
)

check_python_version()  # antes de importar o motor (usa sintaxe de 3.10+)

from engine.hand_classes import all_hand_classes  # noqa: E402
from engine.multiway_rfi import ENGINE_VERSION, MultiwayRfiSolver  # noqa: E402

# Ordem de ação preflop (8-max): UTG, UTG+1, MP, HJ, CO, BTN, SB, BB.
# Pra cada posição de abertura, os seats modelados são ela mesma + todo
# mundo entre ela e a BB (na ordem em que agem), + a BB no final.
ACTION_ORDER = ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"]


def seats_for_opener(opener: str) -> list[str]:
    i = ACTION_ORDER.index(opener)
    bb_i = ACTION_ORDER.index("BB")
    return ACTION_ORDER[i:bb_i + 1]  # [opener, ..., SB, BB]


ANTE_BB = 0.125
TABLE_SIZE = 8
ANTE_POOL = ANTE_BB * TABLE_SIZE  # morto desde t=0, vai pro vencedor de qualquer terminal real


def build_matchup_config(opener: str, stack: float) -> dict:
    seats = seats_for_opener(opener)
    n = len(seats)
    # posts: 0 pra quem nao tem blind, 0.5 pro SB, 1.0 pra BB -- sempre
    # os dois ultimos seats da sequencia (SB, BB), o resto e 0.
    seat_posts = [0.0] * (n - 2) + [0.5, 1.0]
    # "outros jogadores" que ja foldaram antes do abridor (nao
    # modelados, so contam pro contexto de ICM da mesa) -- mesma
    # convencao ja usada nos jobs de 2 jogadores (other_stacks): mesa de
    # ICM com 6 jogadores enquanto os seats modelados cabem (CO/HJ/MP);
    # UTG+1 e UTG modelam 7 e 8 seats, entao a mesa de ICM fica com 7/8.
    other_stacks = [40.0, 25.0, 18.0, 12.0][: max(0, 6 - n)]
    return {
        "seat_names": seats,
        "seat_idx_in_table": list(range(n)),
        "seat_posts": seat_posts,
        "table_stacks": [stack] * n + other_stacks,
        "payouts": [500.0, 300.0, 200.0],
        "open_size": 2.2,
        "effective_stack": stack,
        "ante_pool": ANTE_POOL,
    }


TOTAL_ITERATIONS = 1_000_000
CHECKPOINT_MINUTES = 10

ENGINE_VERSION_MULTIWAY = "pokersync-solver-v0.2.0-multiway-ante"

# Fila do mais rápido (menos seats) pro mais lento.
POSITIONS_QUEUE = ["CO", "HJ", "MP", "UTG+1", "UTG"]
STACKS = [15.0, 25.0, 40.0, 60.0]


def label_for(opener: str, stack: float) -> str:
    return f"{opener.replace('+', 'p')}_vs_BB_{int(stack)}bb_ante{ANTE_BB}"


def make_solver_factory(config: dict):
    classes = all_hand_classes()

    def make():
        # equity_matrix=None: o motor multiway calcula a equity de cada
        # showdown na hora (ver _multiway_eq) -- a matriz pairwise que os
        # scripts montavam antes (3-4 min na primeira vez, cache em
        # data/equity_matrix_cache.pkl) nunca era usada por ele.
        return MultiwayRfiSolver(equity_matrix=None, classes=classes, **config)
    return make


def build_drill_row(label: str, config: dict, strat: dict, exploitability: float) -> dict:
    """Formato ainda mais simples que o do motor heads-up
    (jobs/solve_rfi_jam_batch.py::build_drill_row): so' frequencia por
    mao/seat/fase, sem EV nem gap por mao -- esse motor multiway nao tem
    (ainda) um equivalente de compute_action_evs (isso exigiria EV exato
    por classe de mao, que aqui so' da pra estimar por Monte Carlo, igual
    o best_response_value). Documentado como limitacao conhecida no
    README ate isso ser necessario de verdade (o frontend ainda nao
    consome spot nenhum desse motor multiway)."""
    seat_names = config["seat_names"]
    pot = sum(p for p in config["seat_posts"] if p > 0) + config.get("ante_pool", 0.0)
    # phase2 tem uma ficha de fold/call por seat POR jammer (quem deu o
    # all-in e informacao publica, entao a resposta certa depende disso --
    # ver comentario em engine/multiway_rfi.py). Aqui isso vira um nivel a
    # mais no gto_nodes, chaveado pelo nome do seat que jammou (mais
    # legivel que o indice numerico usado internamente pelo motor).
    gto_nodes = {
        seat_names[i]: {
            "phase1": {c: round(strat["phase1"][i][c], 4) for c in strat["phase1"][i]},
            "phase2_vs_jam": {
                seat_names[j]: {c: round(strat["phase2"][i][j][c], 4) for c in strat["phase2"][i][j]}
                for j in strat["phase2"][i]
            },
        }
        for i in range(len(seat_names))
    }
    opener = seat_names[0]
    stack_bb = int(config["effective_stack"])
    return {
        "spot_id": f"rfi_multiway_{opener.lower()}_vs_bb_{stack_bb}bb_ante{ANTE_BB}",
        "board": [],
        "pot": pot,
        "effective_stack": config["effective_stack"],
        "gto_nodes": gto_nodes,
        "solution": None,
        "format": None,
        "stack_bb": stack_bb,
        "position": f"{opener}_vs_BB",
        "street": "Preflop",
        "action": "rfi_multiway",
        "engine_version": f"{ENGINE_VERSION_MULTIWAY}+{ENGINE_VERSION}",
        "exploitability": round(exploitability, 3),
        "solver_job_id": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def upload_results(out_dir: Path, positions, stacks, dry_run: bool):
    rows = []
    for opener in positions:
        for stack in stacks:
            label = label_for(opener, stack)
            result_path = out_dir / f"resultado_{label}.pkl"
            if not result_path.exists():
                print(f"[{label}] resultado ainda não existe -- pulando (rode o treino primeiro).")
                continue
            data, problem = load_result(result_path, ENGINE_VERSION)
            if problem is not None:
                print(f"[{label}] NÃO vou subir: {problem}. Rode o treino de novo pra refazer.")
                continue
            n_flags = sum(len(v) for v in data.get("sanity_flags", {}).values())
            if n_flags:
                print(f"[{label}] AVISO: {n_flags} decisão(ões) apontada(s) pela checagem de convergência "
                      f"(ver CLAUDE.md) -- confira antes de usar no produto.")
            rows.append(build_drill_row(label, data["config"], data["strategy"], data["exploitability"]))

    if not rows:
        print("Nenhum resultado da versão atual encontrado -- nada pra subir.")
        return

    print(f"{len(rows)} spot(s) prontos: " + ", ".join(r["spot_id"] for r in rows))
    if dry_run:
        print("--dry-run: nada foi enviado. Rode sem --dry-run pra subir de verdade.")
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass
    import os
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit(f"ERRO: faltam as variáveis {', '.join(missing)} (coloque no arquivo .env na pasta "
                 f"do projeto ou exporte no terminal) -- nada foi enviado.")
    try:
        from jobs.supabase_client import get_client
    except ImportError:
        sys.exit("ERRO: biblioteca 'supabase' não instalada -- rode `pip install -r requirements.txt` "
                 "(o requirements-offline.txt não inclui o que o upload precisa).")

    # upsert por spot_id (não insert): subir de novo o mesmo spot ATUALIZA a
    # linha em vez de dar erro de chave duplicada / criar duplicata.
    get_client().table("drills").upsert(rows, on_conflict="spot_id").execute()
    print(f"OK -- {len(rows)} spot(s) enviados (spot_id com prefixo rfi_multiway_).")


def _parse_list(text, cast):
    return [cast(x.strip()) for x in text.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="Treino offline do RFI multiway (todas as posições vs BB).")
    parser.add_argument("--upload", action="store_true", help="sobe os resultados prontos pro Supabase")
    parser.add_argument("--dry-run", action="store_true", help="com --upload: só mostra, não envia")
    parser.add_argument("--posicoes", type=lambda t: _parse_list(t, str), default=POSITIONS_QUEUE)
    parser.add_argument("--stacks", type=lambda t: _parse_list(t, float), default=STACKS)
    parser.add_argument("--iteracoes", type=int, default=TOTAL_ITERATIONS)
    parser.add_argument("--pasta", type=Path, default=BASE_DIR)
    args = parser.parse_args()

    for p in args.posicoes:
        if p not in POSITIONS_QUEUE:
            sys.exit(f"ERRO: posição desconhecida {p!r} -- use uma de {', '.join(POSITIONS_QUEUE)}")
    if args.iteracoes <= 0:
        sys.exit("ERRO: --iteracoes precisa ser positivo")
    out_dir = args.pasta.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.upload:
        upload_results(out_dir, args.posicoes, args.stacks, args.dry_run)
        return

    jobs = [(opener, stack) for opener in args.posicoes for stack in args.stacks]
    print(f"Motor {ENGINE_VERSION}. Fila: {len(jobs)} combinação(ões) (posição x stack), "
          f"{args.iteracoes:,} iterações cada. Arquivos em: {out_dir}\n"
          f"Pode parar (Ctrl+C) e retomar a qualquer momento.\n", flush=True)

    with GracefulStop() as stop:
        for opener, stack in jobs:
            config = build_matchup_config(opener, stack)
            status = train_and_evaluate(
                label_for(opener, stack), config, args.iteracoes, out_dir,
                make_solver_factory(config), ENGINE_VERSION, stop,
                checkpoint_minutes=CHECKPOINT_MINUTES,
            )
            if status == "stopped":
                return

    print("Fila inteira concluída! Rode com --upload --dry-run pra conferir e depois --upload pra subir.")


if __name__ == "__main__":
    main()
