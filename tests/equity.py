"""
Validação de engine/equity.py contra números de equity pré-flop
amplamente conhecidos e publicados. Convertido do bloco __main__
antigo (só imprimia "OK"/"DIVERGENTE" sem travar o CI) pra um teste
de verdade com assert.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.equity import hand_vs_hand_equity  # noqa: E402

# (combo_a, combo_b, equity esperada de combo_a, tolerancia, label)
#
# AKo vs QQ: o comentario original deste arquivo (antes de virar teste)
# dizia "~46-47%", mas isso era uma aproximacao de memoria, nao um
# numero conferido -- rodando com 100k iteracoes (bem menos ruido que
# as 20k daqui) o valor converge estavel em ~42.6-42.8% em seeds
# diferentes, batendo com a equity real conhecida de AKo vs QQ (~43%,
# nao e coinflip). Corrigido aqui pra nao travar o teste num valor
# de referencia errado.
CHECKS = [
    ("AhAd", "KsKc", 0.82, 0.03, "AA vs KK (classico, ~82%)"),
    ("AhKd", "QsQc", 0.43, 0.03, "AKo vs QQ (~43%, nao e coinflip)"),
    ("7h2c", "AsKd", 0.32, 0.03, "72o vs AKo (nao e vs AA, equity real ~32%)"),
    ("AhKh", "AsKc", 0.52, 0.03, "AK mesmo par de cartas, naipes diferentes (~coinflip + edge de flush)"),
]


def test_equity_contra_numeros_conhecidos():
    for combo_a, combo_b, expected, tol, label in CHECKS:
        eq = hand_vs_hand_equity(combo_a, combo_b, iterations=20000, seed=1)
        assert abs(eq - expected) < tol, f"{label}: calculado={eq:.3f} esperado~={expected:.3f}"


def test_simetria_a_vs_b_e_b_vs_a():
    # trocar a ordem dos combos deve dar equity complementar (a menos de ruido MC)
    eq_ab = hand_vs_hand_equity("AhAd", "KsKc", iterations=20000, seed=1)
    eq_ba = hand_vs_hand_equity("KsKc", "AhAd", iterations=20000, seed=1)
    assert abs((eq_ab + eq_ba) - 1.0) < 0.02, f"Equity deveria ser complementar: {eq_ab:.3f} + {eq_ba:.3f}"


if __name__ == "__main__":
    for combo_a, combo_b, expected, tol, label in CHECKS:
        eq = hand_vs_hand_equity(combo_a, combo_b, iterations=20000, seed=1)
        status = "OK" if abs(eq - expected) < tol else "DIVERGENTE"
        print(f"  {label:55s} calculado={eq:.3f}  esperado~={expected:.3f}  [{status}]")
    test_equity_contra_numeros_conhecidos()
    test_simetria_a_vs_b_e_b_vs_a()
    print("Todos os testes de equity passaram.")
