"""
cEV/ICM de uma mão jogada (não uma tabela de range offline) — a peça que
faltava pra ligar o motor a uma mão específica do produto: dado que hero e
vilão foram all-in com cartas conhecidas (mostradas no showdown), qual era
o $EV daquele momento, considerando os stacks de TODOS na mesa e a
estrutura de premiação real do torneio?

Isolado de propósito (mesmo espírito de equity.py/icm.py): não treina CFR
nenhum, é cálculo analítico direto — equity real (Monte Carlo, combo a
combo, sem aproximação de classe) + Malmuth-Harville. Por isso responde em
bem menos de 1s, ao contrário dos jobs em lote de pushfold/rfi_jam.

Limitação deliberada desta primeira versão: só cobre confrontos HEADS-UP
(hero vs 1 vilão) com as DUAS mãos conhecidas (foram a showdown e
mostraram). Quando o vilão não mostra, ou o all-in é multiway, não dá pra
estimar com a mesma confiança sem assumir um range — melhor não devolver
um número do que inventar a mão do vilão.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity import hand_vs_hand_equity  # noqa: E402
from engine.icm import icm_equity  # noqa: E402


class HandCevError(ValueError):
    pass


def compute_hand_cev(
    hero_combo: str,
    villain_combo: str,
    hero_stack_before: float,
    villain_stack_before: float,
    other_stacks: list[float],
    hero_seat_idx: int,
    villain_seat_idx: int,
    payouts: list[float],
    iterations: int = 5000,
    seed: int | None = None,
) -> dict:
    """
    hero_combo/villain_combo: ex "AhKd" — cartas reais mostradas no showdown.
    hero_stack_before/villain_stack_before: stack de cada um IMEDIATAMENTE
        antes da mão (em fichas) — a diferença entre eles não importa pro
        cálculo de equity, só pro dimensionamento do all-in (quem cobre
        quem) e pro estado final dos stacks.
    other_stacks: stacks (fichas) de todos os OUTROS jogadores da mesa,
        parados nesse momento — entram no ICM mas não no confronto.
    hero_seat_idx/villain_seat_idx: posição de hero/vilão dentro da lista
        final de stacks (ver `_build_table_stacks` abaixo) — o chamador não
        precisa montar essa lista, só dizer quem é quem.
    payouts: estrutura de premiação (payouts[0]=1º lugar, etc), do
        tournament_payouts do produto.

    Retorna dict com equity do hero, o resultado esperado em fichas (cEV,
    delta vs o stack inicial) e o $EV esperado via ICM (delta vs o $ICM do
    hero ANTES da mão, com o stack intacto) — os dois já como DELTA, prontos
    pra comparar com o resultado real da mão no cliente (ver
    lib/services/analysis-service.ts do produto).
    """
    if hero_stack_before <= 0 or villain_stack_before <= 0:
        raise HandCevError("Stacks precisam ser positivos.")
    if not payouts:
        raise HandCevError("Estrutura de premiação vazia — sem payouts não há ICM pra calcular.")

    at_risk = min(hero_stack_before, villain_stack_before)

    hero_equity = hand_vs_hand_equity(hero_combo, villain_combo, iterations=iterations, seed=seed)

    # Mesa completa, na ordem: [hero, vilão, ...demais jogadores] — os
    # índices recebidos indicam onde hero/vilão ficam nessa lista pra quem
    # chama poder reconstruir o mapeamento de volta (não usamos os índices
    # aqui dentro além de validar que são 0 e 1, ver nota abaixo).
    if {hero_seat_idx, villain_seat_idx} != {0, 1}:
        raise HandCevError("hero_seat_idx/villain_seat_idx precisam ser 0 e 1 (mesa normalizada hero,vilão,resto).")

    stacks_hero_wins = [hero_stack_before + at_risk, villain_stack_before - at_risk, *other_stacks]
    stacks_hero_loses = [hero_stack_before - at_risk, villain_stack_before + at_risk, *other_stacks]
    stacks_baseline = [hero_stack_before, villain_stack_before, *other_stacks]

    icm_if_win = icm_equity(stacks_hero_wins, payouts)[0]
    icm_if_lose = icm_equity(stacks_hero_loses, payouts)[0]
    icm_baseline = icm_equity(stacks_baseline, payouts)[0]

    hero_expected_icm = hero_equity * icm_if_win + (1 - hero_equity) * icm_if_lose
    hero_expected_chips = hero_equity * stacks_hero_wins[0] + (1 - hero_equity) * stacks_hero_loses[0]

    return {
        "hero_equity_pct": round(hero_equity * 100, 2),
        "chips_at_risk": at_risk,
        "hero_expected_chip_delta": round(hero_expected_chips - hero_stack_before, 2),
        "hero_icm_baseline_dollars": round(icm_baseline, 4),
        "hero_icm_if_win_dollars": round(icm_if_win, 4),
        "hero_icm_if_lose_dollars": round(icm_if_lose, 4),
        "hero_expected_icm_dollars": round(hero_expected_icm, 4),
        "hero_expected_icm_delta_dollars": round(hero_expected_icm - icm_baseline, 4),
    }


if __name__ == "__main__":
    # Validação rápida (mesmo espírito de icm.py/pushfold_icm.py): checa
    # propriedades, não número decorado.
    print("--- Validação de compute_hand_cev ---")

    # AA vs KK, 6-handed, sem pressão de bolha forte (payouts espaçados) —
    # equity ~82%, então o $EV esperado do all-in deve ficar bem acima do
    # baseline (não arriscar).
    result = compute_hand_cev(
        hero_combo="AhAd",
        villain_combo="KsKc",
        hero_stack_before=3000,
        villain_stack_before=3000,
        other_stacks=[8000, 5000, 2000, 1500],
        hero_seat_idx=0,
        villain_seat_idx=1,
        payouts=[500.0, 300.0, 200.0],
        iterations=5000,
        seed=1,
    )
    print(result)
    ok_equity = 0.75 < result["hero_equity_pct"] / 100 < 0.90
    ok_positive_ev = result["hero_expected_icm_delta_dollars"] > 0
    print(f"Equity de AA vs KK na faixa esperada (~82%): {'OK' if ok_equity else 'FALHOU'}")
    print(f"AA all-in com 82% de equity tem $EV positivo vs não arriscar: {'OK' if ok_positive_ev else 'FALHOU'}")

    # Caso degenerado: heads-up puro (só 2 jogadores, winner-take-all) —
    # ICM = chip EV exatamente, então hero_expected_icm_delta_dollars deve
    # bater com hero_expected_chip_delta na mesma proporção do payout.
    result_hu = compute_hand_cev(
        hero_combo="AhAd",
        villain_combo="KsKc",
        hero_stack_before=5000,
        villain_stack_before=5000,
        other_stacks=[],
        hero_seat_idx=0,
        villain_seat_idx=1,
        payouts=[1000.0],
        iterations=5000,
        seed=1,
    )
    expected_ratio = 1000.0 / 10000.0  # $ por ficha, heads-up winner-take-all
    implied_chip_delta = result_hu["hero_expected_icm_delta_dollars"] / expected_ratio
    ok_hu = abs(implied_chip_delta - result_hu["hero_expected_chip_delta"]) < 1.0
    print(f"\nHeads-up winner-take-all (ICM == chip EV proporcional): {'OK' if ok_hu else 'FALHOU'} "
          f"(chip_delta={result_hu['hero_expected_chip_delta']:.1f}, implied={implied_chip_delta:.1f})")
