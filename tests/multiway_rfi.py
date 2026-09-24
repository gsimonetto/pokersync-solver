"""
Validação de engine/multiway_rfi.py (MultiwayRfiSolver).

Contexto (2026-09): achamos um bug real aqui via auditoria -- o
regret_sum não era pesado pela probabilidade dos jogadores anteriores
terem realmente escolhido o caminho até aquele infoset ("reach
probability"/"counterfactual reach" em CFR), só o motor heads-up
(rfi_jam.py, já validado) fazia isso certo. Isso fazia o caso
degenerado de 2 jogadores (que a própria docstring do arquivo diz que
precisa reproduzir EXATAMENTE o motor heads-up) divergir bastante.
Esse arquivo existe pra essa regressão NUNCA mais passar batido —
antes deste bug, engine/multiway_rfi.py não tinha nenhum teste
automatizado (era o único motor do projeto nessa situação, rodando
sem essa rede de segurança por dias no PC do usuário).

Duas checagens:

1. LOCKSTEP (determinístico, sem ruído de amostragem) -- alimenta os
   DOIS motores (heads-up já validado + multiway com 2 seats) com a
   MESMA sequência de mãos sorteadas, iteração por iteração. Se a
   lógica dos dois é equivalente no caso degenerado, o resultado tem
   que bater EXATAMENTE (não "aproximadamente") a cada passo -- não há
   ruído de amostragem independente pra confundir a comparação (esse
   foi o erro do primeiro diagnóstico: comparar duas rodadas
   independentes de Monte Carlo escondia a diferença real atrás de
   ruído). Roda rápido (determinístico, não precisa de milhões de
   iterações pra "convergir" -- só precisa reproduzir a MESMA soma).

2. SANIDADE MULTIWAY (3 seats) -- checagens qualitativas básicas que
   qualquer motor de poker correto deve satisfazer: mão premium (AA)
   abre/paga muito mais que lixo (72o), e o abridor original não pode
   ter probabilidade negativa nem exploitability muito maior que os
   outros seats (sintoma do bug de reach probability por peso duplicado
   quando o mesmo jogador decide duas vezes -- ver commit que corrigiu
   isso).
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity_final import build_final_equity_matrix  # noqa: E402
from engine.rfi_jam import RfiJamSolver  # noqa: E402
from engine.multiway_rfi import MultiwayRfiSolver  # noqa: E402

TABLE_STACKS = [25, 25, 40, 30, 20, 15]
PAYOUTS = [500.0, 300.0, 200.0]
ITERATIONS_LOCKSTEP = 20_000

# Fidelidade BAIXA de proposito (bem menor que o padrao de producao,
# 250/250) -- este arquivo testa LOGICA da arvore (o lockstep e'
# invariante a qualidade de equity, os dois motores usam a MESMA
# tabela; a sanidade so' precisa de direcao qualitativa certa: AA >>
# 72o), nao precisao numerica. Isso mantem o teste rapido o bastante
# pro CI (a mesma tabela em fidelidade de producao levaria ~4min so'
# pra montar).
_EQUITY_MATRIX, _CLASSES, _ = build_final_equity_matrix(fast_iterations=40, blocker_iterations=40, seed=7)


def _patch_multiway_eq_to_use_matrix(matrix):
    """Faz o showdown de 2 jogadores do multiway usar a MESMA tabela
    pairwise que o motor heads-up usa (em vez de recalcular via Monte
    Carlo, mais lento e com sua própria fonte de ruído) -- isola 100%
    a comparação na LÓGICA da árvore, não na fonte de equity."""
    def patched(self, seat_hand_pairs, iterations=150):
        if len(seat_hand_pairs) == 2:
            (sa, ha), (sb, hb) = seat_hand_pairs
            return {sa: matrix[(ha, hb)], sb: matrix[(hb, ha)]}
        from engine.multiway_equity import multiway_equity
        seats = [s for s, h in seat_hand_pairs]
        hands = [h for s, h in seat_hand_pairs]
        eqs = multiway_equity(hands, iterations=iterations)
        return dict(zip(seats, eqs))
    MultiwayRfiSolver._multiway_eq = patched


def test_lockstep_2_seats_reproduz_heads_up():
    print("--- 1. Lockstep (2 seats) vs motor heads-up ja validado ---")
    _patch_multiway_eq_to_use_matrix(_EQUITY_MATRIX)

    hu = RfiJamSolver(sb_idx=0, bb_idx=1, table_stacks=TABLE_STACKS, payouts=PAYOUTS,
                       equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, open_size=2.2,
                       effective_stack=25, opener_post=0.5, defender_post=1.0, dead_money=0.0)
    # use_cfr_plus=False: o motor heads-up (rfi_jam.py) usa CFR classico
    # (sem piso de regret nem media ponderada por iteracao) -- os dois só
    # reproduzem o MESMO resultado em lockstep se rodarem o MESMO
    # algoritmo de regret matching. O CFR+ (default do multiway em
    # producao) e' testado separadamente na sanidade de 3 seats abaixo.
    mw = MultiwayRfiSolver(seat_names=["opener", "BB"], seat_idx_in_table=[0, 1],
                            seat_posts=[0.5, 1.0], table_stacks=TABLE_STACKS, payouts=PAYOUTS,
                            equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, open_size=2.2,
                            effective_stack=25, use_cfr_plus=False)

    random.seed(7)
    weights = [hu.weights_norm[c] for c in _CLASSES]
    for _ in range(ITERATIONS_LOCKSTEP):
        sb_c = random.choices(_CLASSES, weights=weights, k=1)[0]
        bb_c = random.choices(_CLASSES, weights=weights, k=1)[0]
        hu._node_root(sb_c, bb_c, 1.0, 1.0)
        mw._play_open_or_fold({0: sb_c, 1: bb_c})

    hu_strat = hu.average_strategy()
    mw_strat = mw.average_strategy()

    max_diff_open, max_diff_jam, max_diff_call = 0.0, 0.0, 0.0
    for c in _CLASSES:
        max_diff_open = max(max_diff_open, abs(hu_strat["sb_open"][c] - mw_strat["phase1"][0][c]))
        max_diff_jam = max(max_diff_jam, abs(hu_strat["bb_jam"][c] - mw_strat["phase1"][1][c]))
        if c in mw.phase2[0][1][()]:
            max_diff_call = max(max_diff_call, abs(hu_strat["sb_call_jam"][c] - mw_strat["phase2"][0][1][()][c]))

    print(f"  max diff (169 classes): open={max_diff_open:.8f} jam={max_diff_jam:.8f} call_vs_jam={max_diff_call:.8f}")
    # Lockstep = mesma sequencia de maos nos dois -- sem ruido de
    # amostragem independente, entao a tolerancia pode (e deve) ser
    # bem apertada; qualquer diff > 1e-6 aqui e' bug de logica, nao
    # convergencia insuficiente.
    assert max_diff_open < 1e-6, f"sb_open divergiu do motor heads-up em lockstep: {max_diff_open}"
    assert max_diff_jam < 1e-6, f"bb_jam divergiu do motor heads-up em lockstep: {max_diff_jam}"
    assert max_diff_call < 1e-6, f"sb_call_jam divergiu do motor heads-up em lockstep: {max_diff_call}"
    print("  OK -- multiway com 2 seats reproduz o motor heads-up EXATAMENTE em lockstep.\n")


def test_sanidade_3_seats():
    print("--- 2. Sanidade multiway (3 seats: abridor, MP, BB) ---")
    # (o patch da matriz só vale pra mesa SEM cartas de verdade; aqui o
    # treino usa card_removal=True, padrão, e a equity sai do oráculo de
    # mesas -- ver engine/multiway_rfi.py::_BoardOracle)
    _patch_multiway_eq_to_use_matrix(_EQUITY_MATRIX)

    config = {
        "seat_names": ["opener", "MP", "BB"],
        "seat_idx_in_table": [0, 1, 2],
        "seat_posts": [0.0, 0.0, 1.0],
        "table_stacks": [25, 25, 25, 40, 30, 20],
        "payouts": PAYOUTS,
        "open_size": 2.2,
        "effective_stack": 25,
    }
    solver = MultiwayRfiSolver(equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, **config)
    solver.train(iterations=3_000, seed=42)
    strat = solver.average_strategy()

    aa_open = strat["phase1"][0]["AA"]
    trash_open = strat["phase1"][0]["72o"]
    print(f"  Abridor: AA abre={aa_open:.3f}  72o abre={trash_open:.3f}")
    assert aa_open > trash_open + 0.5, (
        f"AA deveria abrir MUITO mais que 72o: AA={aa_open:.3f} 72o={trash_open:.3f}"
    )

    # Exploitability por seat nao deve ter nenhum seat MUITO destoante
    # dos outros -- foi exatamente esse sintoma (abridor com
    # exploitability muito maior, por causa do peso de reach duplicado)
    # que apontou pro bug original. Usa poucas iteracoes de best-response
    # (rapido, so' termometro -- nao e' o teste de precisao final).
    # policy_samples bem reduzido de proposito: a partir da correcao do
    # vazamento de informacao (2026-09), compute_exploitability fixa a
    # politica de cada classe de mao via reamostragem dos adversarios
    # (ver engine/multiway_rfi.py) -- com 3+ seats isso envolve showdown
    # multiway de verdade (Monte Carlo com carta real via treys), bem
    # mais caro que o caso de 2 seats. Aqui so' precisamos de um
    # termometro grosseiro, nao precisao.
    br = solver.compute_exploitability(iterations=150, seed=1, policy_samples=3)
    print(f"  Exploitability por seat (Monte Carlo, termometro): {br}")
    br_values = list(br.values())
    br_max, br_min_abs = max(abs(v) for v in br_values), min(abs(v) for v in br_values)
    # Generoso de proposito (best_response_value aqui e' so' Monte Carlo,
    # ruidoso por natureza com poucas iteracoes) -- so' pra pegar uma
    # regressao GROSSEIRA tipo "abridor 10x pior que os outros", nao
    # exigir paridade fina entre seats.
    assert br_max < br_min_abs * 15 + 5.0, (
        f"Um seat com exploitability muito destoante dos outros pode indicar "
        f"peso de reach errado (sintoma do bug original): {br}"
    )
    print("  OK -- abridor abre premium >> lixo, exploitability sem outlier grosseiro.\n")


def _solver_8_seats(**kwargs):
    import run_offline_all_positions as offline
    config = offline.build_matchup_config("UTG", 15.0)
    return MultiwayRfiSolver(equity_matrix=None, classes=_CLASSES, **config, **kwargs)


def test_cartas_de_verdade_sem_mao_impossivel():
    print("--- 3. Cartas dadas de verdade (card_removal) ---")
    solver = _solver_8_seats()
    rng = random.Random(3)
    # 8 seats, 20 mil mesas: nunca mais de 4 cartas do mesmo valor (antes,
    # sorteando a classe de cada seat independente, saia ex 3x AA)
    for _ in range(20_000):
        hands = solver._deal_hands(rng)
        count = {}
        for h in hands.values():
            for r in (h[0], h[1]):
                count[r] = count.get(r, 0) + 1
        assert max(count.values()) <= 4, f"mesa impossivel: {hands}"
    # condicionado: quem tem AA deixa só 2 ases pros outros 7 seats
    for _ in range(5_000):
        hands = solver._sample_other_hands(0, "AA", rng)
        aces = sum(h.count("A") for s, h in hands.items() if s != 0)
        assert aces <= 2, f"sobraram só 2 ases, mas os outros têm {aces}: {hands}"
    # frequência de AA num seat ~ 6/1326 (0,45%)
    n = 60_000
    freq_aa = sum(solver._deal_hands(rng)[0] == "AA" for _ in range(n)) / n
    assert abs(freq_aa - 6 / 1326) < 0.0015, freq_aa
    print(f"  OK -- 20 mil mesas de 8 seats sem mão impossível; AA sai {100 * freq_aa:.2f}% (esperado 0,45%)\n")


def test_checagem_sorteia_adversarios_condicionados_ao_historico():
    print("--- 4. Checagens/best-response: adversários condicionados ao que já aconteceu ---")
    solver = _solver_8_seats()
    rng = random.Random(9)
    # estratégia fictícia: abridor só abre mão com Ás; seats 1 e 2 jammam
    # qualquer par; o seat 3 jamma só par (e nada mais jamma)
    def is_pair(c):
        return len(c) == 2

    avg = {
        "phase1": [{c: 0.0 for c in _CLASSES} for _ in range(solver.n_seats)],
        "phase2": [{j: {k: {c: 0.0 for c in _CLASSES} for k in solver.phase2[i][j]} for j in solver.phase2[i]}
                   for i in range(solver.n_seats)],
    }
    for c in _CLASSES:
        avg["phase1"][0][c] = 1.0 if "A" in c else 0.0
        for seat in (1, 2, 3):
            avg["phase1"][seat][c] = 1.0 if is_pair(c) else 0.0
    # decisão de fase 1 do seat 5: abridor TEM Ás; seats 1..4 foldaram
    # (então 1, 2, 3 NÃO têm par)
    got = solver._sample_posterior(5, "72o", avg, rng, 30)
    assert len(got) == 30, len(got)
    for hands in got:
        assert "A" in hands[0] and not any(is_pair(hands[s]) for s in (1, 2, 3)), hands
    # resposta do seat 6 ao jam do seat 3: abridor com Ás, seats 1-2 sem
    # par (foldaram), seat 3 COM par (jammou)
    got = solver._sample_posterior(6, "QQ", avg, rng, 20, jammer=3)
    assert len(got) == 20, len(got)
    for hands in got:
        assert "A" in hands[0] and is_pair(hands[3]), hands
        assert not is_pair(hands[1]) and not is_pair(hands[2]), hands
    # o próprio abridor respondendo: a mão DELE é a fixa (não passa pelo
    # filtro de "abriu"); o resto do histórico continua valendo
    for hands in solver._sample_posterior(0, "72o", avg, rng, 10, jammer=3):
        assert hands[0] == "72o" and is_pair(hands[3]), hands
    print("  OK -- mesas sorteadas respeitam 'abridor abriu', 'quem estava no meio foldou' e 'jammer jammou'\n")


def test_oraculo_de_mesas_bate_com_calculo_independente():
    print("--- 6. Oráculo de mesas (equity de qualquer grupo a partir das mesmas mesas) ---")
    import math
    from engine.equity import hand_vs_hand_outcomes
    from engine.fast_eval import card_index, eval7
    from engine.multiway_rfi import _BoardOracle

    def holes_of(*combos):
        return [(card_index(c[:2]), card_index(c[2:])) for c in combos]

    n = 60_000
    # 2 jogadores: contra o cálculo heads-up (código independente, equity.py)
    oracle = _BoardOracle(holes_of("AhKd", "QsQc"), n, random.Random(1))
    eq = oracle.equities([0, 1])[0]
    pw, pt, _ = hand_vs_hand_outcomes("AhKd", "QsQc", iterations=n, seed=2)
    se = math.sqrt(2 * 0.25 / n)
    assert abs(eq - (pw + pt / 2)) < 4 * se, (eq, pw + pt / 2)

    # cartas de quem FOLDOU saem do baralho: seat 2 tem os outros dois ases
    # -> nunca sai Ás na mesa pro showdown entre 0 e 1 (conferido contra
    # um Monte Carlo escrito aqui, que tira as 6 cartas do baralho)
    holes = holes_of("AhAd", "KsKc", "AsAc")
    oracle = _BoardOracle(holes, n, random.Random(3))
    eq_oracle = oracle.equities([0, 1])
    rng = random.Random(4)
    deck = [c for c in range(52) if c not in {c for h in holes for c in h}]
    wins = 0.0
    for _ in range(n):
        board = rng.sample(deck, 5)
        a = eval7([*holes[0], *board])
        b = eval7([*holes[1], *board])
        wins += 1.0 if a > b else (0.5 if a == b else 0.0)
    assert abs(eq_oracle[0] - wins / n) < 4 * se, (eq_oracle, wins / n)
    # grupos diferentes da MESMA mesa: equities somam 1, memo devolve igual
    for live in ([0, 1], [0, 2], [1, 2], [0, 1, 2]):
        eqs = oracle.equities(live)
        assert abs(sum(eqs.values()) - 1.0) < 1e-9 and oracle.equities(live) is eqs
    print(f"  OK -- bate com cálculo independente; cartas de quem foldou ficam fora da mesa "
          f"(AA vs KK com os outros 2 ases mortos: {eq_oracle[0]:.3f})\n")


def test_overcall_decisao_separada_por_quem_ja_pagou():
    print("--- 7. Overcall: decisão de pagar depende de quem já pagou antes ---")
    import run_offline_all_positions as offline
    config = offline.build_matchup_config("CO", 15.0)
    solver = MultiwayRfiSolver(equity_matrix=None, classes=_CLASSES, **config)
    # CO=0, BTN=1, SB=2, BB=3. Jam do BTN: responde SB, depois BB, depois CO.
    assert solver._possible_callers(3, 1) == [(), (2,)]
    assert solver._possible_callers(0, 1) == [(), (2,), (3,), (2, 3)]
    assert solver._possible_callers(2, 1) == [()]
    solver.train(iterations=3000, seed=5)
    for callers in ((), (2,)):
        visited = sum(sum(inf.strategy_sum) for inf in solver.phase2[3][1][callers].values())
        assert visited > 0, f"BB vs jam do BTN com {callers} ja' tendo pago nunca foi treinado"
    # sorteio condicionado: SB (seat 2) só paga o jam do BTN com AA
    avg = solver.average_strategy()
    for c in _CLASSES:
        avg["phase2"][2][1][()][c] = 1.0 if c == "AA" else 0.0
    rng = random.Random(8)
    got = solver._sample_posterior(3, "KK", avg, rng, 15, jammer=1, callers=(2,))
    assert got and all(h[2] == "AA" for h in got), "com SB tendo pago, o SB tem que ter AA"
    got = solver._sample_posterior(3, "KK", avg, rng, 15, jammer=1, callers=())
    assert got and all(h[2] != "AA" for h in got), "com SB tendo foldado, o SB não pode ter AA"
    print("  OK -- grupos de 'quem já pagou' certos, treinados separadamente e usados no sorteio condicionado\n")


def test_estado_exporta_e_importa_igual():
    print("--- 5. Checkpoint: exportar/importar estado reproduz o treino exatamente ---")
    import run_offline_all_positions as offline
    config = offline.build_matchup_config("CO", 15.0)
    a = MultiwayRfiSolver(equity_matrix=None, classes=_CLASSES, **config)
    a.train(iterations=300, seed=1, start_t=1)
    b = MultiwayRfiSolver(equity_matrix=None, classes=_CLASSES, **config)
    b.import_state(a.export_state())
    a.train(iterations=200, seed=301, start_t=301)
    b.train(iterations=200, seed=301, start_t=301)
    assert a.average_strategy() == b.average_strategy(), "retomar do estado exportado deveria dar o MESMO treino"
    print("  OK -- treino retomado do estado exportado é idêntico ao treino direto\n")


if __name__ == "__main__":
    test_lockstep_2_seats_reproduz_heads_up()
    test_sanidade_3_seats()
    test_cartas_de_verdade_sem_mao_impossivel()
    test_checagem_sorteia_adversarios_condicionados_ao_historico()
    test_oraculo_de_mesas_bate_com_calculo_independente()
    test_overcall_decisao_separada_por_quem_ja_pagou()
    test_estado_exporta_e_importa_igual()
    print("Todos os testes de multiway_rfi passaram.")
