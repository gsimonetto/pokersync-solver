"""
Kuhn Poker — jogo de validação do núcleo CFR.

Por que Kuhn Poker e não um spot real de Hold'em:
Kuhn Poker (Kuhn, 1950) é o benchmark padrão da literatura de CFR porque
tem solução analítica fechada e conhecida. Antes de confiar o motor a
qualquer spot de Hold'em (onde não temos a resposta certa de antemão),
validamos que o algoritmo converge para o equilíbrio teórico correto
neste jogo simples. Isso isola bugs de implementação do CFR em si,
separado de qualquer bug de modelagem da árvore de poker real.

Regras: baralho de 3 cartas (J, Q, K), cada jogador recebe 1, aposta
obrigatória (ante) de 1. P1 age primeiro: check ou bet(1).
- Se check: P2 pode check (showdown) ou bet(1) -> P1 decide fold/call.
- Se bet: P2 decide fold/call.

Equilíbrio conhecido (um parâmetro alpha em [0, 1/3], família de Nash;
ver Neller & Lanctot, "An Introduction to Counterfactual Regret
Minimization"):
  P1 com J: aposta com prob. alpha (blefe); se apostado contra, sempre fold.
  P1 com Q: nunca aposta primeiro; se apostado contra, paga com prob.
    alpha + 1/3 (depende de alpha, não é 1/3 fixo).
  P1 com K: aposta com prob. 3*alpha; se apostado contra, sempre paga.
  P2 com J: aposta com prob. 1/3 (blefe, fixo); se P1 apostou, sempre
    fold. (Fix 2026-08: docstring antigo dizia "nunca aposta" -- errado,
    o motor já convergia certo, só o texto estava trocado.)
  P2 com Q: se checado, sempre check; se P1 apostou, paga com prob. 1/3 (fixo).
  P2 com K: se checado, sempre aposta; se P1 apostou, sempre paga.
  Valor do jogo (para P1) = -1/18 ≈ -0.0556.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.cfr_core import DiscountedCFRTrainer  # noqa: E402

CARDS = ["J", "Q", "K"]
CARD_RANK = {"J": 0, "Q": 1, "K": 2}  # força real da carta, não ordem alfabética
ACTIONS = ["check_or_fold", "bet_or_call"]  # 0 = pass, 1 = bet/call


def cfr(trainer, cards, history, p0, p1):
    """Retorna o payoff esperado para o jogador que agiu primeiro na
    chamada raiz (player 0), via recursão de árvore de jogo completa."""
    plays = len(history)
    player = plays % 2

    terminal, payoff = terminal_utility(cards, history)
    if terminal:
        return payoff if player == 0 else -payoff

    key = cards[player] + history
    infoset = trainer.get_infoset(key, n_actions=2)
    reach = p0 if player == 0 else p1
    strategy = infoset.get_strategy(reach)

    util = [0.0, 0.0]
    node_util = 0.0
    for a in range(2):
        next_history = history + ("0" if a == 0 else "1")
        if player == 0:
            util[a] = -cfr(trainer, cards, next_history, p0 * strategy[a], p1)
        else:
            util[a] = -cfr(trainer, cards, next_history, p0, p1 * strategy[a])
        node_util += strategy[a] * util[a]

    for a in range(2):
        regret = util[a] - node_util
        cf_reach = p1 if player == 0 else p0
        infoset.regret_sum[a] += cf_reach * regret

    return node_util


def terminal_utility(cards, history):
    """Payoff para o player 0 (P1) em estados terminais. Retorna
    (is_terminal, payoff_para_player0)."""
    plays = len(history)
    if plays < 2:
        return False, 0.0

    is_player_card_higher = CARD_RANK[cards[0]] > CARD_RANK[cards[1]]

    if history == "00":  # check, check -> showdown
        return True, 1.0 if is_player_card_higher else -1.0
    if history == "01":  # check, bet -> ainda não terminal (falta decisão de P1)
        return False, 0.0
    if history == "10":  # bet, fold -> P1 ganha o ante de P2
        return True, 1.0
    if history == "11":  # bet, call -> showdown, pote maior
        return True, 2.0 if is_player_card_higher else -2.0
    if history == "010":  # check, bet, fold -> P2 ganha
        return True, -1.0
    if history == "011":  # check, bet, call -> showdown, pote maior
        return True, 2.0 if is_player_card_higher else -2.0
    return False, 0.0


def get_strategy_profile(trainer):
    """Extrai a estratégia média final de cada infoset como dict simples."""
    return {k: v.get_average_strategy() for k, v in trainer.infosets.items()}


def best_response_value(strategy_profile, br_player):
    """
    Calcula o valor exato do melhor contra-ataque (best response) de
    `br_player` contra a estratégia fixa do oponente. Padrão-ouro pra
    medir convergência: exploitability = soma dos best-response values
    dos dois jogadores. Exploitability -> 0 significa equilíbrio de Nash.

    Cuidado central (é fácil errar isso): a ação escolhida pelo best
    responder em cada infoset precisa ser ÚNICA por infoset — ele não
    pode "ver" a carta exata do oponente e escolher uma ação diferente
    pra cada carta possível, senão viola a regra de informação
    imperfeita e infla o valor artificialmente. Por isso o cálculo é
    em duas passadas: (1) acumula o valor de cada ação em cada infoset
    do br_player, somando sobre todos os deals compatíveis, ponderado
    pelo alcance do oponente (chance x estratégia do oponente); (2)
    escolhe a melhor ação por infoset (fixa) e só então avalia o valor
    final contra o oponente.
    """
    deals = [(a, b) for a in CARDS for b in CARDS if a != b]
    chance_prob = 1.0 / len(deals)

    def opponent_strategy(card, history):
        key = card + history
        if key in strategy_profile:
            return strategy_profile[key]
        return [0.5, 0.5]  # infoset nunca visitado (prob. de chegada ~0)

    def is_deep_infoset(history):
        """Infosets 'profundos' do br_player não têm nenhuma decisão
        própria abaixo deles (só terminais) — podem ser resolvidos numa
        passada isolada, sem risco de usar um valor de continuação
        ainda não decidido."""
        return len(history) >= 2

    # ---- Passada 1: resolver infosets profundos do br_player primeiro ----
    # (Kuhn Poker: só o player 0 tem uma segunda decisão, em histórias
    # tipo "01". Player 1 nunca decide duas vezes na mesma mão.)
    deep_action_value = {}

    def accumulate_deep(cards, history, opp_reach):
        plays = len(history)
        player = plays % 2
        terminal, payoff = terminal_utility(cards, history)
        if terminal:
            return
        if player == br_player and is_deep_infoset(history):
            key = cards[player] + history
            deep_action_value.setdefault(key, [0.0, 0.0])
            for a in range(2):
                next_history = history + str(a)
                _, next_payoff = terminal_utility(cards, next_history)
                v = next_payoff if br_player == 0 else -next_payoff
                deep_action_value[key][a] += opp_reach * v
            return
        if player == br_player:
            for a in range(2):
                accumulate_deep(cards, history + str(a), opp_reach)
        else:
            strat = opponent_strategy(cards[player], history)
            for a in range(2):
                accumulate_deep(cards, history + str(a), opp_reach * strat[a])

    for deal in deals:
        accumulate_deep(list(deal), "", chance_prob)

    deep_best_action = {
        key: (0 if vals[0] >= vals[1] else 1) for key, vals in deep_action_value.items()
    }

    # ---- Passada 2: infosets rasos do br_player, usando os profundos já fixos ----
    shallow_action_value = {}

    def accumulate_shallow(cards, history, opp_reach):
        plays = len(history)
        player = plays % 2
        terminal, payoff = terminal_utility(cards, history)
        if terminal:
            return payoff if br_player == 0 else -payoff

        if player == br_player and is_deep_infoset(history):
            # já decidido na passada 1: segue a ação fixa
            key = cards[player] + history
            a = deep_best_action.get(key, 0)
            return accumulate_shallow(cards, history + str(a), opp_reach)

        if player == br_player:
            key = cards[player] + history
            shallow_action_value.setdefault(key, [0.0, 0.0])
            vals = []
            for a in range(2):
                v = accumulate_shallow(cards, history + str(a), opp_reach)
                vals.append(v)
                shallow_action_value[key][a] += opp_reach * v
            # valor de retorno provisório (só usado se houvesse um nível
            # ainda mais raso acima, o que não ocorre em Kuhn Poker)
            return max(vals)
        else:
            strat = opponent_strategy(cards[player], history)
            total = 0.0
            for a in range(2):
                total += strat[a] * accumulate_shallow(cards, history + str(a), opp_reach * strat[a])
            return total

    for deal in deals:
        accumulate_shallow(list(deal), "", chance_prob)

    shallow_best_action = {
        key: (0 if vals[0] >= vals[1] else 1) for key, vals in shallow_action_value.items()
    }

    def best_action_for(key, history):
        if is_deep_infoset(history):
            return deep_best_action.get(key, 0)
        return shallow_best_action.get(key, 0)

    # ---- Passada final: avaliar o valor real jogando as ações fixas ----
    def evaluate(cards, history):
        plays = len(history)
        player = plays % 2
        terminal, payoff = terminal_utility(cards, history)
        if terminal:
            return payoff if br_player == 0 else -payoff
        if player == br_player:
            key = cards[player] + history
            a = best_action_for(key, history)
            return evaluate(cards, history + str(a))
        strat = opponent_strategy(cards[player], history)
        return sum(strat[a] * evaluate(cards, history + str(a)) for a in range(2))

    total_value = 0.0
    for deal in deals:
        total_value += evaluate(list(deal), "")
    return total_value / len(deals)


ALL_DEALS = [(a, b) for a in CARDS for b in CARDS if a != b]


def train(iterations=20_000, seed=42):
    """
    Full-enumeration CFR: cada iteração percorre os 6 deals possíveis
    (não amostra 1 deal aleatório). Jogo de 3 cartas é pequeno o
    suficiente pra isso ser trivial computacionalmente, e evita a
    interação ruim entre amostragem de chance e o desconto por
    iteração global do Discounted CFR (todo infoset precisa ser
    visitado a cada iteração pra o expoente de tempo fazer sentido).
    """
    random.seed(seed)
    trainer = DiscountedCFRTrainer()
    util_sum = 0.0
    for t in range(1, iterations + 1):
        iter_util = 0.0
        for deal in ALL_DEALS:
            iter_util += cfr(trainer, list(deal), "", 1.0, 1.0)
        util_sum += iter_util / len(ALL_DEALS)
        trainer.discount(t)
    trainer.finalize()
    return trainer, util_sum / iterations


if __name__ == "__main__":
    trainer, avg_util = train()

    print(f"Valor do jogo calculado (player 0): {avg_util:.5f}")
    print(f"Valor do jogo teorico esperado:      {-1/18:.5f}")
    print()

    def show(card, history, label):
        key = card + history
        if key in trainer.infosets:
            strat = trainer.infosets[key].get_average_strategy()
            print(f"  {label:35s} check/fold={strat[0]:.3f}  bet/call={strat[1]:.3f}")

    print("P1 (age primeiro, história=''):")
    show("J", "", "com J (blefe esperado ~[0,0.33])")
    show("Q", "", "com Q (esperado ~0.0 de bet)")
    show("K", "", "com K (esperado ~3x o bluff de J)")

    print("\nP1 apos check-bet de P2 (história='01'):")
    show("J", "01", "com J (esperado ~0.0 de call = sempre fold)")
    show("Q", "01", "com Q (esperado alpha+0.33 de call)")
    show("K", "01", "com K (esperado ~1.0 de call)")

    print("\nP2 apos check de P1 (história='0'):")
    show("J", "0", "com J (esperado ~0.33 de bet, blefe)")
    show("Q", "0", "com Q (esperado ~0.0 de bet)")
    show("K", "0", "com K (esperado ~1.0 de bet)")

    print("\nP2 apos bet de P1 (história='1'):")
    show("J", "1", "com J (esperado ~0.0 de call = sempre fold)")
    show("Q", "1", "com Q (esperado ~0.33 de call)")
    show("K", "1", "com K (esperado ~1.0 de call)")

    print("\n--- Teste rigoroso de convergencia (exploitability via best-response exato) ---")
    profile = get_strategy_profile(trainer)
    br0 = best_response_value(profile, br_player=0)  # melhor resposta de P1 contra P2 fixo
    br1 = best_response_value(profile, br_player=1)  # melhor resposta de P2 contra P1 fixo
    exploitability = br0 + br1  # em jogo de soma zero, ambos nao podem ganhar > valor do jogo
    print(f"Best-response value para P1 (contra P2 fixo): {br0:.5f}")
    print(f"Best-response value para P2 (contra P1 fixo): {br1:.5f}")
    print(f"Exploitability total (soma dos dois, deve -> 0):    {exploitability:.5f}")
    exploit_mbb = exploitability * 1000 / 2
    print(f"Exploitability em mbb/hand (padrao industria):       {exploit_mbb:.3f}")

    # Tolerancia generosa (valor de referencia observado: ~1.24 mbb/hand)
    # -- so' falha se o treino parar de convergir de verdade.
    ok = exploit_mbb < 5.0
    print("OK" if ok else "FALHOU: exploitability acima do esperado, CFR pode ter regredido")
    sys.exit(0 if ok else 1)
