"""
Validação de PostflopSolver.compute_action_evs() -- EV por AÇÃO (não só
frequência) em cada nó de decisão do pós-flop, análogo ao que
rfi_jam.py::compute_action_evs já faz pro pré-flop (gap #12 da auditoria
de "Modo Treino": pós-flop só expunha frequência, não "quanto você
perdeu" escolhendo uma ação não-ótima).

Implementação: reaproveita o mesmo motor de melhor-resposta (_br_*) já
validado por tests/postflop_exploitability.py, só que devolvendo TODAS
as ações de cada nó (não só o máximo) -- ver docstring de
compute_action_evs() no engine pra a lista completa dos 6 nós
possíveis numa única rua.

Duas checagens:

1. Spot clássico (mesmo de tests/postflop_river.py/postflop_exploitability.py):
   range polarizada da OOP (valor puro + blefe) contra bluff-catcher
   puro da IP, board seco -- tem leitura qualitativa conhecida (valor
   aposta quase sempre, QQ fica perto de indiferente entre fold/call
   contra a aposta, exatamente o ponto de equilíbrio de MDF). O "gap"
   calculado tem que refletir isso: gap grande pra decisão óbvia (valor
   checar seria erro grosseiro), gap pequeno pra decisão marginal (QQ
   fold vs call, perto de indiferente por construção do spot).

2. Sanidade no TURN (board de 4 cartas, dispara nó de chance) -- só
   fumaça: não quebra, devolve estrutura não-vazia, e a leitura
   qualitativa básica (valor >> blefe na raiz) ainda vale.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.postflop import PostflopSolver  # noqa: E402

BOARD_RIVER = "Ah Kd 7s 2c 9h"
RANGE_OOP = {"AA": 1.0, "KK": 1.0, "72o": 1.0, "83o": 1.0}
RANGE_IP = {"QQ": 1.0}
POT = 20.0


def test_gap_grande_pra_erro_grosseiro_pequeno_pra_decisao_marginal():
    print("--- compute_action_evs() no spot classico de MDF (river) ---")
    solver = PostflopSolver(
        board=BOARD_RIVER, range_oop=RANGE_OOP, range_ip=RANGE_IP,
        pot=POT, stack_oop=60.0, stack_ip=60.0, bet_sizes=(0.5,),
    )
    solver.train(iterations=3000)
    evs = solver.compute_action_evs()

    assert "root" in evs and "facing_bet_0" in evs, f"nos esperados ausentes: {list(evs.keys())}"

    # AA/KK: apostar e' claramente melhor que checkar (perderiam valor
    # contra o bluff-catcher se checassem) -- gap tem que ser GRANDE
    # (bem maior que o exploitability geral do solver, que fica < 2%
    # do pote segundo tests/postflop_exploitability.py).
    for c in ["AA", "KK"]:
        row = evs["root"][c]
        assert row["best"] == "bet_0.5", f"{c} deveria preferir apostar: {row}"
        gap_checar = row["gaps"]["check"]
        print(f"  {c}: melhor={row['best']}  gap de checar (errado aqui)={gap_checar:.3f}")
        assert gap_checar > 0.15 * POT, (
            f"{c} checar deveria ser um erro grosseiro (gap grande): gap={gap_checar:.3f}"
        )

    # QQ contra a aposta: o spot e' construido pra deixar a IP EXATAMENTE
    # no ponto de indiferenca de MDF (call_freq = P/(P+b)) -- fold e call
    # tem que estar bem pertinho um do outro em EV (gap pequeno = decisao
    # marginal, nao "erro"), bem diferente do caso AA/KK acima.
    qq = evs["facing_bet_0"]["QQ"]
    gap_qq = min(qq["gaps"]["fold"], qq["gaps"].get("call", qq["gaps"]["fold"]))
    print(f"  QQ facing bet: fold={qq['fold']:.3f} call={qq['call']:.3f} gaps={qq['gaps']}")
    assert qq["gaps"]["fold"] < 0.05 * POT, (
        f"QQ deveria estar perto de indiferente entre fold/call (spot de MDF): gaps={qq['gaps']}"
    )
    print("  OK -- gap reflete erro grosseiro (valor checando) vs decisao marginal (QQ no MDF).\n")


def test_turn_nao_quebra_e_mantem_leitura_qualitativa():
    print("--- Sanidade: compute_action_evs() no turn (com no de chance) ---")
    board = "Ah Kd 7s 2c"  # falta o river
    range_oop = {"AA": 1.0, "KK": 1.0, "93o": 1.0, "84o": 1.0}
    range_ip = {"QQ": 1.0}
    solver = PostflopSolver(
        board=board, range_oop=range_oop, range_ip=range_ip,
        pot=20.0, stack_oop=60.0, stack_ip=60.0, bet_sizes=(0.5,),
    )
    solver.train(iterations=2000)
    evs = solver.compute_action_evs()

    assert evs.get("root"), "no raiz vazio"
    aa_row = evs["root"]["AA"]
    trash_row = evs["root"]["93o"]
    print(f"  AA: melhor={aa_row['best']} gaps={aa_row['gaps']}")
    print(f"  93o: melhor={trash_row['best']} gaps={trash_row['gaps']}")
    assert aa_row["best"] == "bet_0.5", f"AA deveria preferir apostar no turn: {aa_row}"

    # Nenhum valor de EV pode ser NaN nem absurdamente fora da faixa do
    # pote+stacks (sintoma de erro de contabilidade/reach mal montado).
    for node, classes in evs.items():
        for c, row in classes.items():
            for action, val in row.items():
                if action in ("best", "gaps"):
                    continue
                assert val == val, f"NaN em {node}/{c}/{action}"
                assert -100 < val < 100, f"EV fora de faixa razoavel em {node}/{c}/{action}: {val}"
    print("  OK -- turn nao quebra, leitura qualitativa preservada, sem NaN/outlier.\n")


if __name__ == "__main__":
    test_gap_grande_pra_erro_grosseiro_pequeno_pra_decisao_marginal()
    test_turn_nao_quebra_e_mantem_leitura_qualitativa()
    print("Testes de postflop_action_evs concluidos.")
