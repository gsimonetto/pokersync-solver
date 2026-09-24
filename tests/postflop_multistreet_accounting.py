"""
Regressão de contabilidade do motor pós-flop (engine/postflop.py) --
dois erros achados na auditoria de 2026-09-24, que só apareciam fora do
caso "river com stacks iguais" (o único em produção hoje, por isso nunca
tinham sido notados):

1. FOLD CONTRA RAISE DEPOIS DE UMA RUA ANTERIOR: quem folda perde TUDO
   que já colocou na mão (ruas anteriores + a aposta desta rua). O motor
   usava só a aposta desta rua -- ex: bet-call de 5 no turn, bet de 10 no
   river, raise all-in, fold: perdia 10 em vez de 15. Afetava o
   treino (_node_facing_raise) e o best-response/EV (_br_facing_raise)
   em qualquer spot de turn/flop.

2. STACKS DIFERENTES: heads-up só importa o stack EFETIVO. O motor
   deixava uma aposta maior que o stack do oponente ser "paga" por
   inteiro (ex: IP com 10 fichas perdendo 15 num call).

Também confere que o river (produção) ficou idêntico -- a correção 1 não
muda nada quando não há dinheiro de rua anterior.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.postflop import PostflopSolver  # noqa: E402

RIVER = "Ah Kd 7s 2c 9h"


def test_fold_contra_raise_perde_tudo_que_colocou():
    solver = PostflopSolver(board=RIVER, range_oop={"32o": 1.0}, range_ip={"QQ": 1.0},
                            pot=10.0, stack_oop=100.0, stack_ip=100.0, bet_sizes=(0.5,))
    # OOP já colocou 5 (rua anterior) + 10 (aposta desta rua) = 15; IP
    # colocou 5. IP dá raise all-in; OOP (32o, perde sempre pra QQ) folda.
    value = solver._br_facing_raise("oop", "oop", "32o", bet_amt=10.0, raise_to=100.0,
                                    committed_oop=15.0, committed_ip=5.0, opp_reach={"QQ": 1.0},
                                    board=solver.board0, prefix="-b0")
    assert abs(value - (-15.0)) < 1e-9, f"fold deveria perder 15 (tudo que colocou), deu {value}"

    # mesma coisa pelo lado de quem dá o raise (IP): recebe o pote todo
    # (pote inicial + 15 de cada lado; o excesso do raise volta pra ele)
    value_ip = solver._br_facing_raise("ip", "oop", "QQ", bet_amt=10.0, raise_to=100.0,
                                       committed_oop=15.0, committed_ip=5.0, opp_reach={"32o": 1.0},
                                       board=solver.board0, prefix="-b0")
    # IP é o oponente de quem decide aqui; sem infoset treinado de OOP
    # nesse prefixo, a classe é excluída (peso 0) -- então só confere
    # que não quebra e não inventa valor.
    assert value_ip == 0.0, value_ip
    print("  OK -- fold contra raise perde tudo que já foi colocado (15), não só a aposta da rua (10)")


def test_river_sem_rua_anterior_continua_igual():
    solver = PostflopSolver(board=RIVER, range_oop={"32o": 1.0}, range_ip={"QQ": 1.0},
                            pot=10.0, stack_oop=100.0, stack_ip=100.0, bet_sizes=(0.5,))
    value = solver._br_facing_raise("oop", "oop", "32o", bet_amt=5.0, raise_to=100.0,
                                    committed_oop=5.0, committed_ip=0.0, opp_reach={"QQ": 1.0},
                                    board=solver.board0, prefix="-b0")
    assert abs(value - (-5.0)) < 1e-9, value
    print("  OK -- sem dinheiro de rua anterior, o valor é o mesmo de antes (-5)")


def test_stacks_diferentes_usam_stack_efetivo():
    solver = PostflopSolver(board=RIVER, range_oop={"AA": 1.0}, range_ip={"QQ": 1.0},
                            pot=10.0, stack_oop=100.0, stack_ip=10.0, bet_sizes=(1.5,))
    assert solver.stack_oop == solver.stack_ip == 10.0
    assert solver.stack_oop_input == 100.0 and solver.stack_ip_input == 10.0
    # aposta de 1.5x o pote (15) fica limitada ao stack efetivo (10)
    bet = solver._bet_amount("oop", 0.0, 0.0, 0)
    assert abs(bet - 10.0) < 1e-9, bet
    u_oop, u_ip = solver._end_of_action("AA", "QQ", bet, bet, 1.0, 1.0, solver.board0, "")
    assert abs(u_ip - (-10.0)) < 1e-9, f"IP tem 10 fichas, não pode perder mais que 10: {u_ip}"
    assert abs(u_oop - 20.0) < 1e-9, u_oop
    # treino inteiro roda e a soma dos EVs de melhor resposta fica
    # coerente (sem valores absurdos)
    solver.train(iterations=300)
    br_oop, br_ip, expl = solver.compute_exploitability()
    assert -1.0 < expl < solver.pot0, (br_oop, br_ip, expl)
    print("  OK -- stacks 100 vs 10 viram stack efetivo 10 (aposta limitada, perda limitada)")


def test_turn_treina_e_mede_exploitability():
    solver = PostflopSolver(board="Ah Kd 7s 2c", range_oop={"AA": 1.0, "KK": 1.0, "93o": 1.0, "84o": 1.0},
                            range_ip={"QQ": 1.0}, pot=20.0, stack_oop=60.0, stack_ip=60.0, bet_sizes=(0.5,))
    solver.train(iterations=1500)
    br_oop, br_ip, expl = solver.compute_exploitability()
    assert expl == expl and -0.5 < expl < 0.25 * solver.pot0, (br_oop, br_ip, expl)
    print(f"  OK -- turn: exploitability {expl:.3f} ({100 * expl / solver.pot0:.2f}% do pote) após 1500 iterações")


if __name__ == "__main__":
    test_fold_contra_raise_perde_tudo_que_colocou()
    test_river_sem_rua_anterior_continua_igual()
    test_stacks_diferentes_usam_stack_efetivo()
    test_turn_treina_e_mede_exploitability()
    print("Todos os testes de postflop_multistreet_accounting passaram.")
