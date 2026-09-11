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
    mw = MultiwayRfiSolver(seat_names=["opener", "BB"], seat_idx_in_table=[0, 1],
                            seat_posts=[0.5, 1.0], table_stacks=TABLE_STACKS, payouts=PAYOUTS,
                            equity_matrix=_EQUITY_MATRIX, classes=_CLASSES, open_size=2.2,
                            effective_stack=25)

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
        if c in mw.phase2[0][1]:
            max_diff_call = max(max_diff_call, abs(hu_strat["sb_call_jam"][c] - mw_strat["phase2"][0][1][c]))

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


if __name__ == "__main__":
    test_lockstep_2_seats_reproduz_heads_up()
    test_sanidade_3_seats()
    print("Todos os testes de multiway_rfi passaram.")
