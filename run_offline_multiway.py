"""
Exemplo de treino offline de longa duração — pensado pra rodar no seu
PC (não no sandbox), por horas, dias ou semanas.

Uso:
    python run_offline_multiway.py                 # treina (e retoma, se já tiver começado)
    python run_offline_multiway.py --iteracoes 200000

Ajuste MATCHUP_CONFIG abaixo pro spot que você quer resolver (squeeze,
CO vs BTN, UTG vs BB, etc). Salva checkpoint a cada ~10 minutos, então
se o processo for interrompido (PC desligou, travou, Ctrl+C), você roda
de novo e ele continua de onde parou -- não perde o progresso. Mesmas
proteções de run_offline_all_positions.py (ver offline_common.py):
checkpoint atômico, versão do motor conferida, arquivo antigo/estragado
renomeado em vez de quebrar.

Se você MUDAR o MATCHUP_CONFIG depois de começar, o checkpoint antigo não
serve pro spot novo: o script detecta, renomeia o antigo e recomeça.

Resultado final: resultado_multiway_exemplo.pkl (dict com strategy,
exploitability por seat, checagem de convergência -- mesmo formato dos
resultado_*.pkl de run_offline_all_positions.py). Até 2026-09-24 era
resultado_final.pkl só com a estratégia, sem a checagem obrigatória.

IMPORTANTE (documentado no motor): mãos "de fronteira" (EV de
fold≈EV de agir, quase indiferentes) podem oscilar bastante entre
rodadas mesmo depois de convergido -- isso é esperado, não é bug.
Mãos claramente fortes/fracas (AA, 72o em posições ruins, etc.)
devem convergir de forma estável; se ISSO não estabilizar mesmo
depois de milhões de iterações, aí sim vale investigar.
"""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from offline_common import GracefulStop, check_python_version, train_and_evaluate  # noqa: E402

check_python_version()  # antes de importar o motor (usa sintaxe de 3.10+)

from engine.hand_classes import all_hand_classes  # noqa: E402
from engine.multiway_rfi import ENGINE_VERSION, MultiwayRfiSolver  # noqa: E402

MATCHUP_CONFIG = {
    "seat_names": ["opener", "MP", "BB"],
    "seat_idx_in_table": [0, 1, 2],
    "seat_posts": [0.0, 0.0, 1.0],
    "table_stacks": [25, 25, 25, 40, 30, 20],
    "payouts": [500.0, 300.0, 200.0],
    "open_size": 2.2,
    "effective_stack": 25,
}

LABEL = "multiway_exemplo"
TOTAL_ITERATIONS = 5_000_000


def main():
    parser = argparse.ArgumentParser(description="Treino offline de um spot multiway (MATCHUP_CONFIG).")
    parser.add_argument("--iteracoes", type=int, default=TOTAL_ITERATIONS)
    parser.add_argument("--pasta", type=Path, default=BASE_DIR)
    args = parser.parse_args()
    if args.iteracoes <= 0:
        sys.exit("ERRO: --iteracoes precisa ser positivo")
    out_dir = args.pasta.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    classes = all_hand_classes()

    def make_solver():
        return MultiwayRfiSolver(equity_matrix=None, classes=classes, **MATCHUP_CONFIG)

    print(f"Motor {ENGINE_VERSION}. Spot: {MATCHUP_CONFIG['seat_names']}, alvo {args.iteracoes:,} iterações. "
          f"Arquivos em: {out_dir}\n", flush=True)
    with GracefulStop() as stop:
        train_and_evaluate(LABEL, MATCHUP_CONFIG, args.iteracoes, out_dir, make_solver, ENGINE_VERSION, stop)


if __name__ == "__main__":
    main()
