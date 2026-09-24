"""
Validação de engine/hand_cev_multiway.py (compute_hand_cev_multiway).
Convertido do bloco __main__ antigo (só imprimia "OK"/"FALHOU" sem
travar o CI) pra um teste de verdade com assert.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_cev import compute_hand_cev  # noqa: E402
from engine.hand_cev_multiway import compute_hand_cev_multiway  # noqa: E402


def test_caso_degenerado_n2_bate_com_heads_up():
    kwargs_common = dict(
        hero_stack_before=3000, villain_stack_before=3000,
        other_stacks=[8000, 5000, 2000, 1500],
        payouts=[500.0, 300.0, 200.0],
    )
    hu = compute_hand_cev(
        hero_combo="AhAd", villain_combo="KsKc",
        hero_seat_idx=0, villain_seat_idx=1,
        iterations=5000, seed=1, **kwargs_common,
    )
    mw = compute_hand_cev_multiway(
        combos=["AhAd", "KsKc"], stacks_before=[3000, 3000],
        other_stacks=[8000, 5000, 2000, 1500], hero_idx=0,
        payouts=[500.0, 300.0, 200.0], iterations=5000, seed=1,
    )
    assert abs(hu["hero_equity_pct"] - mw["hero_equity_pct"]) < 2.0, (
        f"N=2 multiway deveria bater com heads-up ja validado: hu={hu['hero_equity_pct']} mw={mw['hero_equity_pct']}"
    )
    assert abs(hu["hero_expected_icm_delta_dollars"] - mw["hero_expected_icm_delta_dollars"]) < 0.5, (
        f"icm_delta deveria bater entre os dois modelos: hu={hu['hero_expected_icm_delta_dollars']} "
        f"mw={mw['hero_expected_icm_delta_dollars']}"
    )


def test_side_pot_limita_ganho_do_jogador_curto():
    # 3-way com stacks desiguais: o jogador com stack menor so' pode
    # ganhar o pote PRINCIPAL (proporcional ao stack dele), nunca mais
    # que isso, mesmo com a melhor mao -- e' a regra classica de side pot.
    result = compute_hand_cev_multiway(
        combos=["AhAd", "KsKc", "QdQc"],
        stacks_before=[2000, 5000, 5000],  # jogador 0 (AA) e' o curto
        other_stacks=[10000, 8000], hero_idx=0,
        payouts=[500.0, 300.0, 200.0], iterations=3000, seed=2,
    )
    max_possible_win = 2000 * 3  # pote principal, todo mundo cobre o curto
    assert result["hero_expected_chip_delta"] <= (max_possible_win - 2000) + 1, (
        f"Jogador curto nao pode ganhar mais que o pote principal: "
        f"delta={result['hero_expected_chip_delta']:.1f} max={max_possible_win - 2000}"
    )


def test_conservacao_de_fichas_entre_envolvidos():
    # Soma dos deltas de chip de TODOS os jogadores envolvidos precisa
    # ser ~0 -- dinheiro nao pode sumir nem surgir entre eles.
    total_delta = 0.0
    stacks = [2000, 5000, 5000]
    for idx in range(3):
        r = compute_hand_cev_multiway(
            combos=["AhAd", "KsKc", "QdQc"], stacks_before=stacks,
            other_stacks=[10000, 8000], hero_idx=idx,
            payouts=[500.0, 300.0, 200.0], iterations=3000, seed=2,
        )
        total_delta += r["hero_expected_chip_delta"]
    assert abs(total_delta) < 5.0, f"Fichas nao conservadas entre os 3 jogadores: soma={total_delta:.2f}"


def test_dois_eliminados_na_mesma_mao_nao_quebra():
    """Regressão (2026-09-24): 3-way com stacks iguais -- quem ganha
    elimina os outros dois; com poucos jogadores de fora e 3 prêmios, o ICM
    antigo dividia por zero (erro 500 no endpoint)."""
    from engine.icm import icm_equity
    r = compute_hand_cev_multiway(
        combos=["AhAd", "KsKc", "QdQc"], stacks_before=[2000, 2000, 2000],
        other_stacks=[5000], hero_idx=1, payouts=[500.0, 300.0, 200.0], iterations=2000, seed=4,
    )
    assert r["hero_expected_icm_dollars"] == r["hero_expected_icm_dollars"]  # sem NaN
    # KK quebra junto com QQ quando AA ganha: eles dividem o 3o prêmio (100
    # cada); nunca pode valer menos que isso nem mais que o 1o prêmio
    assert 100.0 <= r["hero_expected_icm_dollars"] <= 500.0, r
    baseline = icm_equity([2000, 2000, 2000, 5000], [500.0, 300.0, 200.0])[1]
    assert abs(r["hero_icm_baseline_dollars"] - round(baseline, 4)) < 1e-6


def test_rejeita_combo_invalido():
    from engine.hand_cev_multiway import HandCevMultiwayError
    for combos in (["AhAd", "kskc", "QdQc"], ["AhAd", "KsK", "QdQc"], ["AhAd", "AhKc", "QdQc"]):
        try:
            compute_hand_cev_multiway(combos=combos, stacks_before=[1000, 1000, 1000], other_stacks=[],
                                      hero_idx=0, payouts=[100.0], iterations=10)
            assert False, f"deveria rejeitar {combos}"
        except HandCevMultiwayError:
            pass


if __name__ == "__main__":
    test_caso_degenerado_n2_bate_com_heads_up()
    print("  OK -- caso degenerado N=2 bate com o motor heads-up")
    test_side_pot_limita_ganho_do_jogador_curto()
    print("  OK -- side pot limita o ganho do jogador curto")
    test_conservacao_de_fichas_entre_envolvidos()
    print("  OK -- conservacao de fichas entre os 3 jogadores envolvidos")
    test_dois_eliminados_na_mesma_mao_nao_quebra()
    print("  OK -- 2 eliminados na mesma mao: sem ZeroDivisionError, valor dentro do possivel")
    test_rejeita_combo_invalido()
    print("  OK -- combo mal formado/repetido vira HandCevMultiwayError (422), nao erro 500")
    print("Todos os testes de hand_cev_multiway passaram.")
