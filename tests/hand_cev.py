"""
Validação de engine/hand_cev.py (compute_hand_cev). Convertido do bloco
__main__ antigo (só imprimia "OK"/"FALHOU" sem travar o CI) pra um
teste de verdade com assert. É cálculo analítico direto (sem CFR),
então roda em segundos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_cev import compute_hand_cev, HandCevError  # noqa: E402


def test_aa_vs_kk_equity_e_ev_positivo():
    result = compute_hand_cev(
        hero_combo="AhAd", villain_combo="KsKc",
        hero_stack_before=3000, villain_stack_before=3000,
        other_stacks=[8000, 5000, 2000, 1500],
        hero_seat_idx=0, villain_seat_idx=1,
        payouts=[500.0, 300.0, 200.0], iterations=5000, seed=1,
    )
    assert 0.75 < result["hero_equity_pct"] / 100 < 0.90, (
        f"Equity de AA vs KK deveria ficar perto de 82%, deu {result['hero_equity_pct']}%"
    )
    assert result["hero_expected_icm_delta_dollars"] > 0, (
        "AA all-in com ~82% de equity deveria ter $EV positivo vs nao arriscar"
    )


def test_heads_up_winner_take_all_icm_igual_chip_ev():
    # Caso degenerado: heads-up puro, winner-take-all -- ICM = chip EV
    # exatamente (mesma propriedade ja validada em tests/icm.py, aqui
    # confirmada ponta a ponta via compute_hand_cev).
    result = compute_hand_cev(
        hero_combo="AhAd", villain_combo="KsKc",
        hero_stack_before=5000, villain_stack_before=5000,
        other_stacks=[], hero_seat_idx=0, villain_seat_idx=1,
        payouts=[1000.0], iterations=5000, seed=1,
    )
    expected_ratio = 1000.0 / 10000.0  # $ por ficha, heads-up winner-take-all
    implied_chip_delta = result["hero_expected_icm_delta_dollars"] / expected_ratio
    assert abs(implied_chip_delta - result["hero_expected_chip_delta"]) < 1.0, (
        f"ICM deveria ser proporcional ao chip EV em HU winner-take-all: "
        f"chip_delta={result['hero_expected_chip_delta']:.1f} implied={implied_chip_delta:.1f}"
    )


def test_rejeita_stacks_invalidos():
    try:
        compute_hand_cev(
            hero_combo="AhAd", villain_combo="KsKc",
            hero_stack_before=0, villain_stack_before=5000,
            other_stacks=[], hero_seat_idx=0, villain_seat_idx=1,
            payouts=[1000.0],
        )
        assert False, "deveria ter levantado HandCevError pra stack <= 0"
    except HandCevError:
        pass


def test_rejeita_payouts_vazios():
    try:
        compute_hand_cev(
            hero_combo="AhAd", villain_combo="KsKc",
            hero_stack_before=5000, villain_stack_before=5000,
            other_stacks=[], hero_seat_idx=0, villain_seat_idx=1,
            payouts=[],
        )
        assert False, "deveria ter levantado HandCevError pra payouts vazio"
    except HandCevError:
        pass


def test_empate_nao_vira_perda_de_icm():
    """Regressão (2026-09-24): pote dividido deixa os stacks como estavam
    (vale o $ICM de antes da mão). O cálculo antigo tratava empate como
    'meia vitória + meia derrota' -- em $ICM (côncavo) isso inventava uma
    perda grande em mão de muito empate, como AK vs AK."""
    r = compute_hand_cev(
        hero_combo="AhKh", villain_combo="AsKs",
        hero_stack_before=3000, villain_stack_before=3000,
        other_stacks=[8000, 5000, 2000, 1500], hero_seat_idx=0, villain_seat_idx=1,
        payouts=[500.0, 300.0, 200.0], iterations=20000, seed=3,
    )
    assert r["hero_tie_pct"] > 85, f"AhKh vs AsKs deveria empatar quase sempre: {r}"
    # o jeito antigo: equity 50% aplicada a ganhar-tudo/perder-tudo
    old_style = 0.5 * r["hero_icm_if_win_dollars"] + 0.5 * r["hero_icm_if_lose_dollars"] - r["hero_icm_baseline_dollars"]
    new_delta = r["hero_expected_icm_delta_dollars"]
    assert old_style < -1.0, old_style  # concavidade do ICM: perda grande no jeito antigo
    assert abs(new_delta) < 0.2 * abs(old_style), (new_delta, old_style)
    assert abs(r["hero_expected_chip_delta"]) < 60, r  # em fichas, empate e' neutro


def test_rejeita_combo_invalido_ou_carta_repetida():
    base = dict(hero_stack_before=3000, villain_stack_before=3000, other_stacks=[],
                hero_seat_idx=0, villain_seat_idx=1, payouts=[1000.0], iterations=100)
    for hero, villain in (("ahkd", "QsQc"), ("AhK", "QsQc"), ("AhAh", "QsQc"), ("AhKd", "AhQc"), ("1hKd", "QsQc")):
        try:
            compute_hand_cev(hero_combo=hero, villain_combo=villain, **base)
            assert False, f"deveria rejeitar {hero} vs {villain}"
        except HandCevError:
            pass


if __name__ == "__main__":
    test_aa_vs_kk_equity_e_ev_positivo()
    print("  OK -- AA vs KK: equity ~82%, EV positivo")
    test_heads_up_winner_take_all_icm_igual_chip_ev()
    print("  OK -- heads-up winner-take-all: ICM == chip EV proporcional")
    test_rejeita_stacks_invalidos()
    print("  OK -- rejeita stack <= 0")
    test_rejeita_payouts_vazios()
    print("  OK -- rejeita payouts vazio")
    test_empate_nao_vira_perda_de_icm()
    print("  OK -- empate (pote dividido) vale o $ICM de antes da mao, nao 'meia vitoria + meia derrota'")
    test_rejeita_combo_invalido_ou_carta_repetida()
    print("  OK -- combo mal formado ou carta repetida vira HandCevError (422), nao erro 500")
    print("Todos os testes de hand_cev passaram.")
