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
  --mesa 9            mesa de 9 jogadores (padrão: 8; a 9 inclui UTG+2)
  --posicoes CO,HJ     só essas posições (padrão: todas, na ordem da fila)
  --stacks 15,25       só esses stacks (padrão: 15,25,40,60)
  --iteracoes 200000   alvo de iterações por combinação, igual pra todas as
                       posições (padrão: depende da posição, ver
                       ITERATIONS_BY_POSITION -- 5M em CO/HJ, 3M no resto)
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

# Ordem de ação preflop por tamanho de mesa (8-max padrão, 9-max opcional
# com --mesa 9). Pra cada posição de abertura, os seats modelados são ela
# mesma + todo mundo entre ela e a BB (na ordem em que agem), + a BB.
ACTION_ORDERS = {
    8: ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO", "BTN", "SB", "BB"],
}
TABLE_SIZE = 8
ACTION_ORDER = ACTION_ORDERS[TABLE_SIZE]


def seats_for_opener(opener: str, table_size: int = TABLE_SIZE) -> list[str]:
    order = ACTION_ORDERS[table_size]
    return order[order.index(opener):order.index("BB") + 1]  # [opener, ..., SB, BB]


def positions_for(table_size: int = TABLE_SIZE) -> list[str]:
    """Aberturas que faltam (tudo antes do BTN), da mais rápida (menos
    seats) pra mais lenta."""
    order = ACTION_ORDERS[table_size]
    return list(reversed(order[:order.index("BTN")]))


ANTE_BB = 0.125
# Stacks (antes do ante) dos jogadores que já foldaram antes do abridor --
# não são modelados, só completam a mesa de ICM. Usa os primeiros que
# forem necessários pra mesa ficar com 8 (ou 9) jogadores.
OTHER_STACKS = [40.0, 25.0, 18.0, 12.0, 30.0, 20.0]


def build_matchup_config(opener: str, stack: float, table_size: int = TABLE_SIZE) -> dict:
    """Correção (2026-09-24, pedido do usuário): a mesa de ICM tem SEMPRE
    `table_size` jogadores (8 ou 9) -- antes era 6 pra CO/HJ/MP e 7/8 pra
    UTG+1/UTG (contextos de ICM diferentes entre posições), enquanto o ante
    era cobrado de 8. E o ante agora SAI das pilhas: cada jogador (inclusive
    quem já foldou) paga ANTE_BB antes da mão, e o pote de antes vai pro
    vencedor -- antes o pote de antes aparecia do nada (a soma de fichas da
    mesa crescia ~1bb por mão jogada, distorcendo o ICM). `stack` é a pilha
    ANTES do ante; o all-in efetivo é stack - ANTE_BB."""
    seats = seats_for_opener(opener, table_size)
    n = len(seats)
    # posts: 0 pra quem nao tem blind, 0.5 pro SB, 1.0 pra BB -- sempre
    # os dois ultimos seats da sequencia (SB, BB), o resto e 0.
    seat_posts = [0.0] * (n - 2) + [0.5, 1.0]
    others = OTHER_STACKS[: table_size - n]
    return {
        "seat_names": seats,
        "seat_idx_in_table": list(range(n)),
        "seat_posts": seat_posts,
        "table_stacks": [stack - ANTE_BB] * n + [s - ANTE_BB for s in others],
        "payouts": [500.0, 300.0, 200.0],
        "open_size": 2.2,
        "effective_stack": stack - ANTE_BB,
        "ante_pool": ANTE_BB * table_size,  # morto desde t=0, vai pro vencedor de qualquer terminal real
    }


# Iterações por posição (2026-09-24). Com 1M o CO já saiu praticamente
# certo (validação: 2 suspeitas em 2.534 decisões, 1 real e numa situação
# que acontece em ~0,01% das mãos); mais iterações servem pra essas
# situações raras. Posições com mais seats são MUITO mais lentas (CO ~990
# it/s, UTG ~38 it/s medidos num núcleo), por isso recebem menos.
ITERATIONS_BY_POSITION = {
    "CO": 5_000_000,
    "HJ": 5_000_000,
    "MP": 3_000_000,
    "UTG+2": 3_000_000,
    "UTG+1": 3_000_000,
    "UTG": 3_000_000,
}
TOTAL_ITERATIONS = 3_000_000  # posição fora da tabela acima
CHECKPOINT_MINUTES = 10

ENGINE_VERSION_MULTIWAY = "pokersync-solver-v0.2.0-multiway-ante"

# Fila do mais rápido (menos seats) pro mais lento (8-max; 9-max inclui UTG+2).
POSITIONS_QUEUE = positions_for(TABLE_SIZE)
STACKS = [15.0, 25.0, 40.0, 60.0]


def label_for(opener: str, stack: float, table_size: int = TABLE_SIZE) -> str:
    return f"{opener.replace('+', 'p')}_vs_BB_{int(stack)}bb_ante{ANTE_BB}_{table_size}max"


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
            # {jammer: {quem ja pagou: {classe: prob de pagar}}} -- "ninguem"
            # quando ninguem pagou antes; senao nomes separados por "+"
            # (ex: "SB+BB"). v4: a decisao depende de quem ja pagou
            # (overcall), ver engine/multiway_rfi.py.
            "phase2_vs_jam": {
                seat_names[j]: {
                    ("+".join(seat_names[x] for x in callers) or "ninguem"):
                        {c: round(p, 4) for c, p in by_class.items()}
                    for callers, by_class in strat["phase2"][i][j].items()
                }
                for j in strat["phase2"][i]
            },
        }
        for i in range(len(seat_names))
    }
    opener = seat_names[0]
    # stack de referência = pilha ANTES do ante (effective_stack já vem sem ele)
    stack_bb = int(round(config["effective_stack"] + ANTE_BB))
    table_size = len(config["table_stacks"])
    return {
        "spot_id": f"rfi_multiway_{opener.lower()}_vs_bb_{stack_bb}bb_ante{ANTE_BB}_{table_size}max",
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


def upload_results(out_dir: Path, positions, stacks, dry_run: bool, table_size: int = TABLE_SIZE):
    rows = []
    for opener in positions:
        for stack in stacks:
            label = label_for(opener, stack, table_size)
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
    parser.add_argument("--mesa", type=int, choices=sorted(ACTION_ORDERS), default=TABLE_SIZE,
                        help="jogadores na mesa (8 = padrão, 9 inclui UTG+2)")
    parser.add_argument("--posicoes", type=lambda t: _parse_list(t, str), default=None)
    parser.add_argument("--stacks", type=lambda t: _parse_list(t, float), default=STACKS)
    parser.add_argument("--iteracoes", type=int, default=None,
                        help="igual pra todas as posições (padrão: 5M em CO/HJ, 3M no resto)")
    parser.add_argument("--pasta", type=Path, default=BASE_DIR)
    args = parser.parse_args()

    queue = positions_for(args.mesa)
    positions = args.posicoes or queue
    for p in positions:
        if p not in queue:
            sys.exit(f"ERRO: posição desconhecida {p!r} pra mesa de {args.mesa} -- use uma de {', '.join(queue)}")
    if args.iteracoes is not None and args.iteracoes <= 0:
        sys.exit("ERRO: --iteracoes precisa ser positivo")
    if any(s_ <= ANTE_BB + 1.0 for s_ in args.stacks):
        sys.exit("ERRO: stacks precisam ser maiores que o blind + ante")
    out_dir = args.pasta.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.upload:
        upload_results(out_dir, positions, args.stacks, args.dry_run, args.mesa)
        return

    def iterations_for(opener):
        return args.iteracoes or ITERATIONS_BY_POSITION.get(opener, TOTAL_ITERATIONS)

    jobs = [(opener, stack) for opener in positions for stack in args.stacks]
    per_pos = ", ".join(f"{p} {iterations_for(p):,}" for p in positions)
    print(f"Motor {ENGINE_VERSION}. Mesa de {args.mesa} jogadores. Fila: {len(jobs)} combinação(ões) "
          f"(posição x stack). Iterações: {per_pos}. Arquivos em: {out_dir}\n"
          f"Pode parar (Ctrl+C) e retomar a qualquer momento.\n", flush=True)

    with GracefulStop() as stop:
        for opener, stack in jobs:
            config = build_matchup_config(opener, stack, args.mesa)
            status = train_and_evaluate(
                label_for(opener, stack, args.mesa), config, iterations_for(opener), out_dir,
                make_solver_factory(config), ENGINE_VERSION, stop,
                checkpoint_minutes=CHECKPOINT_MINUTES,
            )
            if status == "stopped":
                return

    print("Fila inteira concluída! Rode com --upload --dry-run pra conferir e depois --upload pra subir.")


if __name__ == "__main__":
    main()
