"""
Núcleo genérico do motor CFR (Counterfactual Regret Minimization).

Implementa Discounted CFR (Brown & Sandholm, 2019) com regret matching+.
Este módulo é agnóstico ao jogo: qualquer árvore de decisão de informação
imperfeita pode ser resolvida desde que exposta via a interface InfoSet.

Referência do algoritmo: Discounted CFR usa pesos temporais para regrets
positivos/negativos e para a estratégia média, acelerando convergência
em relação ao CFR+ vanilla.
"""

from dataclasses import dataclass, field


@dataclass
class InfoSet:
    """Nó de informação: agrega todos os estados de jogo indistinguíveis
    para o jogador que decide (mesma mão + mesmo histórico observável)."""
    key: str
    n_actions: int
    regret_sum: list = None
    strategy_sum: list = None

    def __post_init__(self):
        if self.regret_sum is None:
            self.regret_sum = [0.0] * self.n_actions
        if self.strategy_sum is None:
            self.strategy_sum = [0.0] * self.n_actions

    def get_strategy(self, realization_weight: float) -> list:
        """Regret matching: estratégia proporcional aos regrets positivos."""
        positive = [max(r, 0.0) for r in self.regret_sum]
        total = sum(positive)
        if total > 0:
            strategy = [r / total for r in positive]
        else:
            strategy = [1.0 / self.n_actions] * self.n_actions
        for a in range(self.n_actions):
            self.strategy_sum[a] += realization_weight * strategy[a]
        return strategy

    def get_average_strategy(self) -> list:
        total = sum(self.strategy_sum)
        if total > 0:
            return [s / total for s in self.strategy_sum]
        return [1.0 / self.n_actions] * self.n_actions


class DiscountedCFRTrainer:
    """
    Wrapper que aplica o discounting do Discounted CFR sobre um conjunto
    de InfoSets, mantido pelo jogo concreto (ex: kuhn_poker.py).

    alpha_pow, beta_pow, gamma_pow: expoentes recomendados no paper
    original (1.5, 0.0, 2.0) — controlam o peso de regrets positivos,
    negativos e da estratégia média ao longo das iterações.
    """

    def __init__(self, alpha_pow=1.5, beta_pow=0.0, gamma_pow=2.0):
        self.alpha_pow = alpha_pow
        self.beta_pow = beta_pow
        self.gamma_pow = gamma_pow
        self.infosets: dict[str, InfoSet] = {}

    def get_infoset(self, key: str, n_actions: int) -> InfoSet:
        if key not in self.infosets:
            self.infosets[key] = InfoSet(key=key, n_actions=n_actions)
        return self.infosets[key]

    def discount(self, iteration: int):
        """Aplica o fator de desconto do DCFR nos regrets e na soma de
        estratégia acumulada, a cada iteração (t começa em 1)."""
        t = iteration
        if t <= 0:
            return
        pos_factor = (t ** self.alpha_pow) / ((t ** self.alpha_pow) + 1)
        neg_factor = (t ** self.beta_pow) / ((t ** self.beta_pow) + 1)
        strat_factor = (t / (t + 1)) ** self.gamma_pow
        for infoset in self.infosets.values():
            for a in range(infoset.n_actions):
                if infoset.regret_sum[a] > 0:
                    infoset.regret_sum[a] *= pos_factor
                else:
                    infoset.regret_sum[a] *= neg_factor
                infoset.strategy_sum[a] *= strat_factor
