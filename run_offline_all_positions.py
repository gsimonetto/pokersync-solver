"""
Resolve as posições de RFI que ainda faltam (UTG, UTG+1, MP, HJ, CO —
todas contra BB), usando o motor multiway (`engine/multiway_rfi.py`).
SB vs BB e BTN vs BB já estão prontos e em produção; este script cobre
o resto da tabela.

PENSADO PRA RODAR NO SEU COMPUTADOR, NÃO NO SANDBOX.

MEDIDO (2026-08, no sandbox, matchup mais RÁPIDO da fila — CO vs BB,
4 seats): ~9-11 iterações/segundo. Nessa taxa, os 5 milhões de
iterações do alvo padrão levariam a casa de VÁRIOS DIAS só pra essa
combinação -- e é a mais rápida da fila (UTG vs BB, com 8 seats,
deve ser bem mais lenta ainda). "Rodar uma noite" NÃO vai terminar
nem uma combinação inteira -- e tudo bem, é exatamente pra isso que
existe checkpoint: cada noite que você deixar rodando soma progresso,
sem perder nada, não importa quantas vezes for interrompido.
Seu PC provavelmente é mais rápido que o sandbox, mas não espere uma
diferença de ordens de grandeza -- isso aqui é trabalho de dias a
semanas por natureza (mesma expectativa que run_offline_multiway.py
já documentava antes desse script existir).

Se preferir um alvo mais realista pra começar (aceitando convergência
pior, do jeito que aconteceu com o Flop antes de validar), edite
`TOTAL_ITERATIONS` mais abaixo pra um número menor -- o script
funciona igual, só termina mais rápido (e menos confiável).

## Como usar

1. Confere se as dependências estão instaladas (mesma coisa de sempre):
   ```
   python3 -m venv .venv
   source .venv/bin/activate      # no Windows: .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```

2. Roda o script:
   ```
   python3 run_offline_all_positions.py
   ```

3. Deixa rodando (a noite inteira, o quanto der). Ele imprime o
   progresso de tempos em tempos, tipo:
   ```
   [CO_vs_BB @ 15bb]  42.3%  2115000/5000000  ETA ~38min
   ```

4. Pode fechar o terminal/desligar o PC a qualquer momento — na
   próxima vez que rodar `python3 run_offline_all_positions.py`, ele
   CONTINUA de onde parou (não do zero), graças aos arquivos de
   checkpoint (`checkpoint_<posição>_<stack>bb.pkl`, um por
   combinação, salvos nesta mesma pasta).

5. Quando uma combinação posição+stack termina, ele salva o resultado
   final em `resultado_<posição>_<stack>bb.pkl` e passa pra próxima da
   fila sozinho. Não precisa fazer nada — só deixar rodando.

6. Quando quiser parar de vez (ou quando eu for buscar os resultados
   pra subir pro Supabase), me avisa quais arquivos `resultado_*.pkl`
   já existem na pasta.

## Ordem da fila

Da posição mais rápida (menos jogadores pulados) pra mais lenta —
assim, se não der tempo de terminar tudo, o que já rodou é o que
converge mais rápido e sobra mais tempo pras posições difíceis nas
próximas noites:

  CO vs BB (pula BTN, SB)              — mais rápido
  HJ vs BB (pula CO, BTN, SB)
  MP vs BB (pula HJ, CO, BTN, SB)
  UTG+1 vs BB (pula MP, HJ, CO, BTN, SB)
  UTG vs BB (pula UTG+1, MP, HJ, CO, BTN, SB)  — mais lento

Pra cada posição, resolve os 4 stacks já usados em produção: 15bb,
25bb, 40bb, 60bb (também do mais rápido pro mais devagar: stack menor
converge mais rápido que stack maior).

Ajuste `POSITIONS_QUEUE`/`STACKS` no final do arquivo se quiser mudar
a ordem, adicionar/remover alguma combinação, ou focar só numa
posição específica primeiro.
"""

import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.multiway_rfi import MultiwayRfiSolver  # noqa: E402
from engine.hand_classes import build_equity_matrix  # noqa: E402

# Ordem de ação preflop (8-max): UTG, UTG+1, MP, HJ, CO, BTN, SB, BB.
# Pra cada posição de abertura, os seats modelados são ela mesma + todo
# mundo entre ela e a BB (na ordem em que agem), + a BB no final.
ACTION_ORDER = ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"]


def seats_for_opener(opener: str) -> list[str]:
    i = ACTION_ORDER.index(opener)
    bb_i = ACTION_ORDER.index("BB")
    return ACTION_ORDER[i:bb_i + 1]  # [opener, ..., SB, BB]


def build_matchup_config(opener: str, stack: float) -> dict:
    seats = seats_for_opener(opener)
    n = len(seats)
    # posts: 0 pra quem nao tem blind, 0.5 pro SB, 1.0 pra BB -- sempre
    # os dois ultimos seats da sequencia (SB, BB), o resto e 0.
    seat_posts = [0.0] * (n - 2) + [0.5, 1.0]
    # "outros jogadores" que ja foldaram antes do abridor (nao
    # modelados, so contam pro contexto de ICM da mesa) -- mesma
    # convencao ja usada nos jobs de 2 jogadores (other_stacks).
    other_stacks = [40.0, 25.0, 18.0, 12.0][: max(0, 6 - n)]
    return {
        "seat_names": seats,
        "seat_idx_in_table": list(range(n)),
        "seat_posts": seat_posts,
        "table_stacks": [stack] * n + other_stacks,
        "payouts": [500.0, 300.0, 200.0],
        "open_size": 2.2,
        "effective_stack": stack,
    }


TOTAL_ITERATIONS = 5_000_000
CHECKPOINT_EVERY = 50_000
EQUITY_MATRIX_PATH = Path("data/equity_matrix_cache.pkl")


def load_or_build_equity_matrix():
    if EQUITY_MATRIX_PATH.exists():
        print("Carregando matriz de equity já calculada...")
        with open(EQUITY_MATRIX_PATH, "rb") as f:
            d = pickle.load(f)
        return d["matrix"], d["classes"]
    print("Construindo matriz de equity pairwise (só na primeira vez, alguns minutos)...")
    matrix, classes, _stats = build_equity_matrix()
    EQUITY_MATRIX_PATH.parent.mkdir(exist_ok=True)
    with open(EQUITY_MATRIX_PATH, "wb") as f:
        pickle.dump({"matrix": matrix, "classes": classes}, f)
    return matrix, classes


def run_one(label: str, config: dict, equity_matrix, classes):
    result_path = Path(f"resultado_{label}.pkl")
    if result_path.exists():
        print(f"[{label}] já tem resultado final ({result_path}) -- pulando.")
        return

    checkpoint_path = Path(f"checkpoint_{label}.pkl")
    if checkpoint_path.exists():
        print(f"[{label}] retomando checkpoint existente...")
        with open(checkpoint_path, "rb") as f:
            state = pickle.load(f)
        solver = state["solver"]
        done_iterations = state["done_iterations"]
    else:
        print(f"[{label}] começando do zero ({len(config['seat_names'])} seats: {config['seat_names']})...")
        solver = MultiwayRfiSolver(equity_matrix=equity_matrix, classes=classes, **config)
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
        eta_min = (TOTAL_ITERATIONS - done_iterations) / batch * dt / 60
        print(f"  [{label}] {pct:5.1f}%  {done_iterations}/{TOTAL_ITERATIONS}  "
              f"({dt:.1f}s neste lote, ETA ~{eta_min:.0f}min)")

    strat = solver.average_strategy()
    with open(result_path, "wb") as f:
        pickle.dump({"config": config, "strategy": strat, "iterations": done_iterations}, f)
    checkpoint_path.unlink(missing_ok=True)
    print(f"[{label}] CONCLUÍDO -- salvo em {result_path}\n")


def main():
    equity_matrix, classes = load_or_build_equity_matrix()

    # Fila do mais rápido (menos seats) pro mais lento.
    POSITIONS_QUEUE = ["CO", "HJ", "MP", "UTG+1", "UTG"]
    STACKS = [15.0, 25.0, 40.0, 60.0]

    jobs = [(opener, stack) for opener in POSITIONS_QUEUE for stack in STACKS]

    print(f"Fila: {len(jobs)} combinações (posição x stack). "
          f"Deixa rodando -- pode parar e retomar a qualquer momento.\n")

    for opener, stack in jobs:
        label = f"{opener.replace('+', 'p')}_vs_BB_{int(stack)}bb"
        config = build_matchup_config(opener, stack)
        run_one(label, config, equity_matrix, classes)

    print("Fila inteira concluída! Todos os resultado_*.pkl estão prontos.")


if __name__ == "__main__":
    main()
