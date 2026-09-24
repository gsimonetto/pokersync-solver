"""
Validação do modo chipEV puro (`use_icm=False`) em RfiJamSolver,
MultiwayRfiSolver, PushFoldSolver/PushFoldICMSolver -- pedido explícito
do usuário: jogador de cash game (ou torneio bem no início, longe de
qualquer pressão de bolha) precisa de EV em fichas puras, sem a
estrutura de premiação do torneio entrando na conta.

Implementação (ver engine/rfi_jam.py::_icm_pair e
engine/multiway_rfi.py::_icm): existe UM ponto só, no motor inteiro,
por onde toda utilidade de terminal passa -- quando `use_icm=False`,
esse ponto devolve o delta de fichas cru em vez de rodar ICM. Isso
propaga pra treino, best-response e compute_action_evs sem duplicar
nada da lógica da árvore, então o teste mais forte que existe aqui é
uma PROPRIEDADE MATEMÁTICA, não um número decorado:

  Caso degenerado -- torneio 1x1 ("quem ganha leva tudo"): ICM
  equivale EXATAMENTE a chipEV (ganhar fichas é proporcional a ganhar
  dinheiro, não tem bolha nem 2º lugar pra complicar a conta). Se os
  dois motores (use_icm=True nesse caso especial vs use_icm=False)
  não baterem aqui, o "interruptor" está ligado no lugar errado.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import build_final_equity_matrix  # noqa: E402
from engine.rfi_jam import RfiJamSolver  # noqa: E402
from engine.pushfold import PushFoldSolver  # noqa: E402
from engine.pushfold_icm import PushFoldICMSolver  # noqa: E402

_EQUITY_MATRIX, _CLASSES, _ = build_final_equity_matrix(fast_iterations=60, blocker_iterations=60, seed=7)


def test_rfi_jam_chipev_bate_com_icm_no_caso_degenerado():
    print("--- RfiJamSolver: chipEV vs ICM no caso degenerado (HU winner-take-all) ---")
    common = dict(sb_idx=0, bb_idx=1, table_stacks=[25, 25], equity_matrix=_EQUITY_MATRIX, classes=_CLASSES,
                  open_size=2.2, effective_stack=25, opener_post=0.5, defender_post=1.0, dead_money=0.0)

    icm_solver = RfiJamSolver(payouts=[1000.0], use_icm=True, **common)
    icm_solver.train(iterations=20_000, seed=42)
    icm_strat = icm_solver.average_strategy()

    chip_solver = RfiJamSolver(payouts=None, use_icm=False, **common)
    chip_solver.train(iterations=20_000, seed=42)
    chip_strat = chip_solver.average_strategy()

    max_diff = 0.0
    for phase in ("sb_open", "bb_jam", "sb_call_jam"):
        for c in _CLASSES:
            max_diff = max(max_diff, abs(icm_strat[phase][c] - chip_strat[phase][c]))
    print(f"  Maior diferenca (todas as classes/fases): {max_diff:.10f}")
    assert max_diff < 1e-6, f"chipEV deveria bater com ICM no HU winner-take-all: diff={max_diff}"
    print("  OK -- chipEV == ICM no caso degenerado, dentro de ruido numerico.\n")


def test_rfi_jam_chipev_sem_payouts_funciona_e_icm_sem_payouts_falha():
    print("--- RfiJamSolver: use_icm=False dispensa payouts; use_icm=True exige ---")
    common = dict(sb_idx=0, bb_idx=1, table_stacks=[25, 25], equity_matrix=_EQUITY_MATRIX, classes=_CLASSES,
                  open_size=2.2, effective_stack=25, opener_post=0.5, defender_post=1.0, dead_money=0.0)

    solver = RfiJamSolver(payouts=None, use_icm=False, **common)
    solver.train(iterations=500)
    print("  OK -- use_icm=False roda sem payouts.")

    try:
        RfiJamSolver(payouts=None, use_icm=True, **common)
        raise AssertionError("Deveria ter levantado ValueError sem payouts em modo ICM")
    except ValueError:
        print("  OK -- use_icm=True sem payouts levanta ValueError, como esperado.\n")


def test_rfi_jam_chipev_sanidade_aa_vs_lixo():
    print("--- RfiJamSolver: chipEV mantem leitura qualitativa (AA >> 72o) ---")
    # Stack profundo de proposito: em fold-ou-jam, com stack raso QUALQUER
    # mao abre quase sempre (foldar depois pro jam e' barato demais pra
    # castigar um open ruim -- ja confirmado antes, nao e' bug, e' o
    # modelo). So' com stack fundo o custo de abrir errado (e enfrentar
    # um jam que dói MUITO mais) separa mao boa de mao ruim de verdade.
    solver = RfiJamSolver(
        sb_idx=0, bb_idx=1, table_stacks=[100, 100], payouts=None, use_icm=False,
        equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, open_size=2.2, effective_stack=100,
        opener_post=0.5, defender_post=1.0, dead_money=0.0,
    )
    solver.train(iterations=15_000, seed=7)
    strat = solver.average_strategy()
    # Correcao (2026-09-24): o teste checava "AA ABRE bem mais que 72o", mas
    # nessa arvore (BB so' folda ou da' all-in de 100bb) o equilibrio e' o
    # SB abrir QUALQUER mao: arrisca 2.2 pra ganhar 1.5 e o BB quase sempre
    # folda (conferido com 300k iteracoes: 72o abre 99.8%, EV +0.39 contra
    # -0.50 de desistir). O teste so' passava porque 15k iteracoes ainda
    # nao tinham convergido. A leitura qualitativa robusta aqui e' a do
    # BB: all-in de 100bb so' com mao forte (AA sempre, 72o nunca).
    aa_jam = strat["bb_jam"]["AA"]
    trash_jam = strat["bb_jam"]["72o"]
    print(f"  BB all-in: AA {aa_jam:.3f}  72o {trash_jam:.3f}  (SB abre 72o {strat['sb_open']['72o']:.3f}, correto ~1)")
    assert aa_jam > 0.9 and trash_jam < 0.1, f"BB deveria dar all-in com AA e nunca com 72o: AA={aa_jam} 72o={trash_jam}"
    print("  OK.\n")


def test_pushfold_chipev_bate_com_icm_no_caso_degenerado():
    print("--- Push/Fold: chipEV (PushFoldSolver) vs ICM (PushFoldICMSolver) no HU winner-take-all ---")
    chip_solver = PushFoldSolver(stack_bb=15, equity_matrix=_EQUITY_MATRIX, classes=_CLASSES)
    chip_solver.train(iterations=4000)
    chip_strat = chip_solver.average_strategy()

    icm_solver = PushFoldICMSolver(
        sb_idx=0, bb_idx=1, table_stacks=[15, 15], payouts=[1000.0],
        equity_matrix=_EQUITY_MATRIX, classes=_CLASSES,
    )
    icm_solver.train(iterations=4000)
    icm_strat = icm_solver.average_strategy()

    max_diff = 0.0
    for phase in ("sb_push", "bb_call"):
        for c in _CLASSES:
            max_diff = max(max_diff, abs(chip_strat[phase][c] - icm_strat[phase][c]))
    print(f"  Maior diferenca (todas as classes/fases): {max_diff:.6f}")
    # Tolerancia mais frouxa que o RFI/Jam -- sao dois motores com
    # implementacoes de CFR independentes (numpy vetorizado vs infoset
    # por classe), nao o MESMO motor com um if a mais -- convergem pro
    # mesmo equilibrio, mas nao bit-a-bit.
    assert max_diff < 0.02, f"chipEV deveria bater com ICM no HU winner-take-all (Push/Fold): diff={max_diff}"
    print("  OK -- chipEV == ICM no caso degenerado, dentro da tolerancia de dois motores independentes.\n")


if __name__ == "__main__":
    test_rfi_jam_chipev_bate_com_icm_no_caso_degenerado()
    test_rfi_jam_chipev_sem_payouts_funciona_e_icm_sem_payouts_falha()
    test_rfi_jam_chipev_sanidade_aa_vs_lixo()
    test_pushfold_chipev_bate_com_icm_no_caso_degenerado()
    print("Todos os testes de rfi_jam_chipev passaram.")
