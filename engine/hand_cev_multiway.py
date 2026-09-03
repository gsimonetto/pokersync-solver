"""
cEV/ICM de uma mão jogada — versão MULTIWAY (3+ jogadores all-in com as
mãos conhecidas, mostradas no showdown). Generaliza engine/hand_cev.py
(que só cobre heads-up) pro caso onde 3 ou mais jogadores foram all-in na
mesma mão.

Diferença de abordagem em relação ao heads-up: lá, só existem 2 desfechos
possíveis (hero ganha ou perde), então dá pra calcular o $ICM esperado
com uma fórmula fechada (equity * icm_se_ganha + (1-equity) * icm_se_perde),
rodando o ICM só 3 vezes. Com 3+ jogadores e stacks desiguais (side pots),
o número de desfechos possíveis explode (cada jogador pode ganhar tudo,
ganhar só o pote principal, ganhar um pote lateral, etc) — não dá pra
enumerar em fórmula fechada de forma simples. Em vez disso, cada iteração
de Monte Carlo resolve o pote (com side pots corretos) pro board sorteado
E roda o ICM naquele resultado especifico; o $EV final é a MÉDIA do ICM
resultante ao longo de todas as iterações. Mesmo princípio de "não inventar
número" do resto do motor — só que aqui o ICM entra dentro do laço de
Monte Carlo em vez de fora.

Custo: ICM para uma mesa de 8 jogadores/3 pagamentos leva ~0.5ms por
chamada (medido) — com as iterações padrão (1500), o cálculo fica na
casa de 1-2s (mais lento que o heads-up, que responde em <1s, mas ainda
uma resposta síncrona razoável pro produto).
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity import parse_combo, EVALUATOR  # noqa: E402
from engine.icm import icm_equity  # noqa: E402
from treys import Deck  # noqa: E402


class HandCevMultiwayError(ValueError):
    pass


def _distribute_allin_pot(stacks_before: list[float], scores: list[int]) -> list[float]:
    """
    Decompõe o pote em camadas (pote principal + potes laterais), do jeito
    clássico de poker multiway all-in com stacks desiguais: cada jogador só
    concorre pelas camadas até o valor do PRÓPRIO stack (não dá pra ganhar
    dinheiro que não colocou). `scores`: treys, MENOR = mão melhor. Retorna
    quanto cada jogador RECEBE de volta no total (0 se não ganhou nenhuma
    camada -- foi eliminado nesse desfecho).

    Caso degenerado N=2 reproduz exatamente engine/hand_cev.py (só a menor
    das duas stacks se move, o resto volta pro stack maior) -- validado em
    __main__ abaixo.
    """
    n = len(stacks_before)
    levels = sorted(set(stacks_before))
    prev = 0.0
    winnings = [0.0] * n
    for level in levels:
        contributors = [i for i in range(n) if stacks_before[i] >= level]
        layer = (level - prev) * len(contributors)
        if layer > 0:
            best = min(scores[i] for i in contributors)
            winners = [i for i in contributors if scores[i] == best]
            share = layer / len(winners)
            for w in winners:
                winnings[w] += share
        prev = level
    return winnings


def compute_hand_cev_multiway(
    combos: list[str],
    stacks_before: list[float],
    other_stacks: list[float],
    hero_idx: int,
    payouts: list[float],
    iterations: int = 1500,
    seed: int | None = None,
) -> dict:
    """
    combos/stacks_before: mesma ordem -- cartas e stack (antes da mão) de
        CADA jogador que foi all-in nessa confrontação (2 ou mais).
    other_stacks: stacks dos demais jogadores da mesa, parados nesse
        momento -- entram no ICM, não no confronto.
    hero_idx: posição do herói dentro de combos/stacks_before.
    payouts: estrutura de premiação do torneio.
    """
    n = len(combos)
    if n < 2:
        raise HandCevMultiwayError("Precisa de pelo menos 2 mãos conhecidas.")
    if len(stacks_before) != n:
        raise HandCevMultiwayError("stacks_before precisa ter o mesmo tamanho de combos.")
    if any(s <= 0 for s in stacks_before):
        raise HandCevMultiwayError("Stacks precisam ser positivos.")
    if not (0 <= hero_idx < n):
        raise HandCevMultiwayError("hero_idx fora do intervalo de combos/stacks_before.")
    if not payouts:
        raise HandCevMultiwayError("Estrutura de premiação vazia — sem payouts não há ICM pra calcular.")

    if seed is not None:
        random.seed(seed)

    cards = [parse_combo(c) for c in combos]
    used = set()
    for hand in cards:
        used.update(hand)
    if len(used) != 2 * n:
        raise HandCevMultiwayError("Cartas repetidas entre as mãos informadas (conflito de combo).")

    baseline_stacks = [*stacks_before, *other_stacks]
    icm_baseline = icm_equity(baseline_stacks, payouts)[hero_idx]

    sum_chips = 0.0
    sum_icm = 0.0
    for _ in range(iterations):
        deck = Deck()
        # sorted() antes do shuffle: mesmo motivo documentado em
        # engine/equity.py -- Deck() do treys embaralha com um Random()
        # PRÓPRIO, não ligado a random.seed(); sem isso o shuffle abaixo
        # não é reprodutível mesmo com `seed` fixo.
        deck.cards = sorted(c for c in deck.cards if c not in used)
        random.shuffle(deck.cards)
        board = deck.cards[:5]
        scores = [EVALUATOR.evaluate(board, hand) for hand in cards]
        winnings = _distribute_allin_pot(stacks_before, scores)
        final_stacks = [*winnings, *other_stacks]

        sum_chips += winnings[hero_idx]
        sum_icm += icm_equity(final_stacks, payouts)[hero_idx]

    hero_expected_chips = sum_chips / iterations
    hero_expected_icm = sum_icm / iterations
    total_at_risk = sum(stacks_before)

    return {
        # "equity" generalizada pra N jogadores/stacks desiguais: fatia do
        # total que os jogadores all-in colocaram na mesa que o herói
        # espera terminar com (não é mais um simples % de vitória binário
        # como no heads-up -- side pots fazem isso deixar de fazer sentido).
        "hero_equity_pct": round(100 * hero_expected_chips / total_at_risk, 2) if total_at_risk > 0 else None,
        "chips_at_risk": stacks_before[hero_idx],
        "hero_expected_chip_delta": round(hero_expected_chips - stacks_before[hero_idx], 2),
        "hero_icm_baseline_dollars": round(icm_baseline, 4),
        "hero_expected_icm_dollars": round(hero_expected_icm, 4),
        "hero_expected_icm_delta_dollars": round(hero_expected_icm - icm_baseline, 4),
        "players_involved": n,
    }


if __name__ == "__main__":
    from engine.hand_cev import compute_hand_cev

    print("--- Validação de compute_hand_cev_multiway ---")

    # 1) Caso degenerado N=2: precisa bater com engine/hand_cev.py (o
    #    modelo heads-up já validado), dentro do ruído de Monte Carlo.
    kwargs_common = dict(
        hero_stack_before=3000,
        villain_stack_before=3000,
        other_stacks=[8000, 5000, 2000, 1500],
        payouts=[500.0, 300.0, 200.0],
    )
    hu = compute_hand_cev(
        hero_combo="AhAd", villain_combo="KsKc",
        hero_seat_idx=0, villain_seat_idx=1,
        iterations=5000, seed=1, **kwargs_common,
    )
    mw = compute_hand_cev_multiway(
        combos=["AhAd", "KsKc"],
        stacks_before=[3000, 3000],
        other_stacks=[8000, 5000, 2000, 1500],
        hero_idx=0,
        payouts=[500.0, 300.0, 200.0],
        iterations=5000, seed=1,
    )
    print(f"Heads-up (fórmula fechada):   equity={hu['hero_equity_pct']:.2f}%  icm_delta={hu['hero_expected_icm_delta_dollars']:.4f}")
    print(f"Multiway N=2 (Monte Carlo):   equity={mw['hero_equity_pct']:.2f}%  icm_delta={mw['hero_expected_icm_delta_dollars']:.4f}")
    ok_degenerate = (
        abs(hu["hero_equity_pct"] - mw["hero_equity_pct"]) < 2.0
        and abs(hu["hero_expected_icm_delta_dollars"] - mw["hero_expected_icm_delta_dollars"]) < 0.5
    )
    print(f"Caso degenerado N=2 bate com o modelo heads-up já validado: {'OK' if ok_degenerate else 'FALHOU'}\n")

    # 2) 3-way com stacks DESIGUAIS (side pot de verdade): o jogador com
    #    stack menor só pode ganhar o pote principal (proporcional ao
    #    stack dele * 3) -- nunca mais que isso, mesmo com a melhor mão.
    result3 = compute_hand_cev_multiway(
        combos=["AhAd", "KsKc", "QdQc"],
        stacks_before=[2000, 5000, 5000],  # jogador 0 (AA) é o curto
        other_stacks=[10000, 8000],
        hero_idx=0,
        payouts=[500.0, 300.0, 200.0],
        iterations=3000, seed=2,
    )
    max_possible_win = 2000 * 3  # pote principal, todo mundo cobre o curto
    print(f"3-way, jogador curto (AA, 2000 vs 5000/5000): chip_delta={result3['hero_expected_chip_delta']:.1f} "
          f"(máximo possível de ganho bruto: pote principal = {max_possible_win})")
    ok_sidepot = result3["hero_expected_chip_delta"] <= (max_possible_win - 2000) + 1  # +1 margem de arredondamento
    print(f"Jogador curto nunca ganha mais que o pote principal (side pot correto): {'OK' if ok_sidepot else 'FALHOU'}\n")

    # 3) Conservação: a soma dos deltas de chip de TODOS os jogadores
    #    envolvidos precisa ser ~0 (dinheiro não pode sumir nem surgir
    #    entre eles -- é sempre um jogo de soma zero no confronto).
    total_delta = 0.0
    stacks_test = [2000, 5000, 5000]
    for idx in range(3):
        r = compute_hand_cev_multiway(
            combos=["AhAd", "KsKc", "QdQc"],
            stacks_before=stacks_test,
            other_stacks=[10000, 8000],
            hero_idx=idx,
            payouts=[500.0, 300.0, 200.0],
            iterations=3000, seed=2,
        )
        total_delta += r["hero_expected_chip_delta"]
    print(f"Soma dos chip_delta dos 3 jogadores envolvidos: {total_delta:.2f} (esperado ~0)")
    print(f"Conservação de fichas entre os envolvidos: {'OK' if abs(total_delta) < 5.0 else 'FALHOU'}")
