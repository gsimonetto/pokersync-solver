"""
Núcleo genérico do motor CFR (Counterfactual Regret Minimization).

Implementa Discounted CFR (Brown & Sandholm, 2019) com regret matching+.
Este módulo é agnóstico ao jogo: qualquer árvore de decisão de informação
imperfeita pode ser resolvida desde que exposta via a interface InfoSet.

Referência do algoritmo: Discounted CFR usa pesos temporais para regrets
positivos/negativos e para a estratégia média, acelerando convergência
em relação ao CFR+ vanilla.
"""

import math
from dataclasses import dataclass, field


@dataclass
class InfoSet:
    """Nó de informação: agrega todos os estados de jogo indistinguíveis
    para o jogador que decide (mesma mão + mesmo histórico observável)."""
    key: str
    n_actions: int
    regret_sum: list = None
    strategy_sum: list = None
    # Fix (2026-08, perf): até que iteração o desconto já foi aplicado
    # neste infoset especificamente. Ver DiscountedCFRTrainer._catch_up
    # -- é o que permite decair "sob demanda" em vez de toda iteração.
    last_discounted_t: int = 0

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

    Fix (2026-08, perf): a versão original varria TODOS os infosets já
    criados a cada chamada de discount() -- em jogos onde cada iteração
    cria infosets novos (ex: postflop com 2 ruas por vir, sorteando
    turn+river a cada iteração), essa lista só cresce, e o treino ficava
    progressivamente mais lento (quadrático no numero de iteracoes, nao
    linear -- medido: postflop_flop_check.py foi de 0.017s/iter com 250
    iteracoes pra 0.183s/iter com 3000, ~11x mais lento por iteracao, so
    por causa dessa varredura). A matematica do desconto e' so' uma
    multiplicacao por um fator que depende so' de `t` (nao do estado do
    infoset), entao decays sucessivos comutam: em vez de aplicar o fator
    de CADA iteracao em CADA infoset, guardamos o produto acumulado (em
    log, pra nao estourar float) e cada infoset so' "se atualiza" (via
    _catch_up) na proxima vez que for tocado, multiplicando de uma vez
    só o produto acumulado desde a ultima vez -- matematicamente IDENTICO
    ao original (mesma sequencia de multiplicacoes, só que agrupada),
    mas custa O(1) por toque em vez de O(infosets existentes) por
    iteracao. Infosets nunca mais tocados (comuns no postflop, onde um
    runout especifico so' aparece uma vez em milhoes de deals possiveis)
    ficam pendentes ate' finalize() ser chamado, no final do treino.
    """

    def __init__(self, alpha_pow=1.5, beta_pow=0.0, gamma_pow=2.0):
        self.alpha_pow = alpha_pow
        self.beta_pow = beta_pow
        self.gamma_pow = gamma_pow
        self.infosets: dict[str, InfoSet] = {}
        self.t = 0
        # cum_log_pos[t] = soma de ln(pos_factor(τ)) pra τ=1..t (índice 0
        # = 0.0, "nenhum desconto aplicado ainda"). Produto acumulado
        # entre duas iterações t0<t1 = exp(cum_log[t1] - cum_log[t0]) --
        # é isso que faz o catch-up ser O(1) mesmo pra um hiato grande.
        self._cum_log_pos = [0.0]
        self._cum_log_neg = [0.0]
        self._cum_log_strat = [0.0]

    def get_infoset(self, key: str, n_actions: int) -> InfoSet:
        if key not in self.infosets:
            infoset = InfoSet(key=key, n_actions=n_actions, last_discounted_t=self.t)
            self.infosets[key] = infoset
            return infoset
        infoset = self.infosets[key]
        self._catch_up(infoset)
        return infoset

    def discount(self, iteration: int):
        """Registra o fator de desconto do DCFR pra iteração `iteration`
        (t começa em 1) nas tabelas acumuladas. NÃO varre os infosets --
        eles se atualizam sozinhos em get_infoset()/finalize() (ver
        docstring da classe)."""
        t = iteration
        if t <= 0:
            return
        # Chamadas fora de ordem (t <= self.t) quebrariam a suposição de
        # que cum_log é estritamente crescente em t -- nunca deveria
        # acontecer no uso normal (loop de treino incrementa t sempre).
        if t <= self.t:
            raise ValueError(f"discount() chamado com t={t} <= t atual ({self.t}); iterações devem ser estritamente crescentes")
        pos_factor = (t ** self.alpha_pow) / ((t ** self.alpha_pow) + 1)
        neg_factor = (t ** self.beta_pow) / ((t ** self.beta_pow) + 1)
        strat_factor = (t / (t + 1)) ** self.gamma_pow
        self._cum_log_pos.append(self._cum_log_pos[-1] + math.log(pos_factor))
        self._cum_log_neg.append(self._cum_log_neg[-1] + math.log(neg_factor))
        self._cum_log_strat.append(self._cum_log_strat[-1] + math.log(strat_factor))
        self.t = t

    def _catch_up(self, infoset: InfoSet):
        """Aplica de uma vez o desconto acumulado desde a última vez que
        este infoset foi tocado até a iteração atual do trainer."""
        t0, t1 = infoset.last_discounted_t, self.t
        if t0 >= t1:
            return
        pos_mult = math.exp(self._cum_log_pos[t1] - self._cum_log_pos[t0])
        neg_mult = math.exp(self._cum_log_neg[t1] - self._cum_log_neg[t0])
        strat_mult = math.exp(self._cum_log_strat[t1] - self._cum_log_strat[t0])
        for a in range(infoset.n_actions):
            infoset.regret_sum[a] *= pos_mult if infoset.regret_sum[a] > 0 else neg_mult
            infoset.strategy_sum[a] *= strat_mult
        infoset.last_discounted_t = t1

    def finalize(self):
        """Aplica o desconto pendente em TODOS os infosets, trazendo
        cada um pro estado que teria com a varredura antiga. Chamar uma
        única vez, depois do loop de treino, antes de ler qualquer
        estratégia final (get_average_strategy / facing_bet_strategy /
        etc.) -- sem isso, infosets tocados pela última vez há muitas
        iterações ficam com desconto pendente aplicado."""
        for infoset in self.infosets.values():
            self._catch_up(infoset)
