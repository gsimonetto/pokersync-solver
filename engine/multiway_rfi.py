"""
Motor multiway de RFI: N jogadores em sequência (não mais só 2).

Substitui a aproximação anterior (dead_money, assumindo que os
jogadores "pulados" já foldaram) por modelagem real: cada jogador
entre o abridor e o último defensor tem sua própria decisão.

Estrutura:
  Fase 1 (pré-jam): o abridor abre (fold/open). Cada jogador seguinte,
  em ordem, decide fold ou jam quando a ação chega nele (sem call
  intermediário -- mesma decisão de arquitetura do heads-up: toda
  decisão termina em fold ou all-in genuíno).
  Fase 2 (pós-jam): assim que alguém dá jam, todos que ainda não
  agiram (incluindo o abridor original, que só tinha aberto, não
  dado jam) decidem fold ou call, em ordem. O showdown final é
  multiway entre o jammer e todos que pagaram.

Validação: com só 2 jogadores (abridor + 1 defensor), este motor
precisa reproduzir os MESMOS resultados do RfiJamSolver heads-up já
validado -- é o teste de consistência usado antes de confiar nele
pra 3+ jogadores.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, combo_count  # noqa: E402
from engine.icm import icm_equity  # noqa: E402
from engine.multiway_equity import multiway_equity  # noqa: E402


class InfoSet:
    def __init__(self, n_actions=2):
        self.n_actions = n_actions
        self.regret_sum = [0.0] * n_actions
        self.strategy_sum = [0.0] * n_actions

    def current_strategy(self):
        positive = [max(r, 0.0) for r in self.regret_sum]
        total = sum(positive)
        if total > 0:
            return [p / total for p in positive]
        return [1.0 / self.n_actions] * self.n_actions

    def average_strategy(self):
        total = sum(self.strategy_sum)
        if total > 0:
            return [s / total for s in self.strategy_sum]
        return [1.0 / self.n_actions] * self.n_actions


class MultiwayRfiSolver:
    def __init__(self, seat_names, seat_idx_in_table, seat_posts, table_stacks, payouts,
                 equity_matrix, classes, open_size=2.2, effective_stack=None,
                 equity_cache=None):
        """
        seat_names: ['opener','MP','CO','BTN','SB','BB'] -- ordem de acao.
        seat_idx_in_table: indice de cada seat dentro de table_stacks/payouts.
        seat_posts: quanto cada seat ja tem investido antes de decidir
                    (0 pra nao-blind, 0.5 SB, 1.0 BB) -- seat_posts[0]
                    (abridor) normalmente 0, exceto se o abridor for SB.
        """
        self.seat_names = seat_names
        self.n_seats = len(seat_names)
        self.seat_idx_in_table = seat_idx_in_table
        self.seat_posts = seat_posts
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.equity_matrix = equity_matrix  # pairwise, usado só pra referência/compat
        self.classes = classes
        self.weights = {c: combo_count(c) for c in classes}
        total_w = sum(self.weights.values())
        self.weights_norm = {c: w / total_w for c, w in self.weights.items()}

        self.R = open_size
        self.T = effective_stack or min(table_stacks[i] for i in seat_idx_in_table)

        # infosets: um por seat por fase (fold/jam pre-jam; fold/call pos-jam)
        self.phase1 = [{c: InfoSet(2) for c in classes} for _ in range(self.n_seats)]
        self.phase2 = [{c: InfoSet(2) for c in classes} for _ in range(self.n_seats)]

        self._icm_cache = {}
        self._equity_cache = equity_cache if equity_cache is not None else {}

    def _icm(self, stack_deltas: dict):
        """stack_deltas: {seat_idx: delta}. Retorna dict {seat_idx: $ICM}."""
        key = tuple(sorted(stack_deltas.items()))
        if key in self._icm_cache:
            return self._icm_cache[key]
        stacks = list(self.table_stacks)
        for seat, delta in stack_deltas.items():
            table_i = self.seat_idx_in_table[seat]
            stacks[table_i] = max(0.0, stacks[table_i] + delta)
        eq = icm_equity(stacks, self.payouts)
        result = {seat: eq[self.seat_idx_in_table[seat]] for seat in stack_deltas}
        self._icm_cache[key] = result
        return result

    def _multiway_eq(self, seat_hand_pairs, iterations=150):
        """seat_hand_pairs: lista de (seat_idx, hand_class). Retorna dict
        seat_idx -> equity.

        Cache chaveado pelo MULTISET de classes (ignorando qual seat
        tem qual mão) -- a equity de cada classe so depende de QUAIS
        classes estao competindo, nao de qual seat especifico as tem.
        Isso reaproveita o cache entre diferentes atribuicoes de seat
        pras mesmas 3 maos (ate 6x mais reaproveitamento pra 3-way sem
        classes repetidas), essencial pra tornar multiway viavel."""
        seats = [s for s, h in seat_hand_pairs]
        hands = [h for s, h in seat_hand_pairs]

        order = sorted(range(len(hands)), key=lambda i: hands[i])
        sorted_hands = tuple(hands[i] for i in order)

        if sorted_hands in self._equity_cache:
            sorted_eqs = self._equity_cache[sorted_hands]
        else:
            sorted_eqs = multiway_equity(list(sorted_hands), iterations=iterations)
            self._equity_cache[sorted_hands] = sorted_eqs

        # remonta na ordem original dos seats (desfaz o sort)
        eqs = [0.0] * len(hands)
        for pos, orig_i in enumerate(order):
            eqs[orig_i] = sorted_eqs[pos]
        return dict(zip(seats, eqs))

    def train(self, iterations=500_000, seed=42):
        random.seed(seed)
        classes_list = self.classes
        weights_list = [self.weights_norm[c] for c in classes_list]
        for _ in range(iterations):
            hands = {i: random.choices(classes_list, weights=weights_list, k=1)[0]
                      for i in range(self.n_seats)}
            self._play_open_or_fold(hands)

    def _icm_fold_root(self, hands):
        """Abridor folda antes de abrir (nunca chega a investir R):
        perde so o post que ja tinha (0 pra posicoes sem blind). Sem
        outros jogadores tendo agido ainda, nao ha vencedor especifico
        -- convencao: se houver algo a ganhar, vai pro seat seguinte
        (proximo a agir), igual o caso heads-up ja validado."""
        op = self.seat_posts[0]
        if op <= 0 or self.n_seats < 2:
            return self._icm({0: 0.0})
        return self._icm({0: -op, 1: op})

    def _play_open_or_fold(self, hands):
        """Decisao do ABRIDOR (seat 0): fold ou abrir (nao e jam --
        e um raise pequeno, R, igual o motor heads-up). So depois de
        abrir e que os demais seats entram na sequencia fold-ou-jam."""
        infoset = self.phase1[0][hands[0]]
        strat = infoset.current_strategy()

        icm_fold = self._icm_fold_root(hands)
        icm_open = self._play_fold_or_jam(1, hands)

        node_val = {}
        all_seats = set(icm_fold.keys()) | set(icm_open.keys())
        for s in all_seats:
            node_val[s] = strat[0] * icm_fold.get(s, 0.0) + strat[1] * icm_open.get(s, 0.0)

        regret = [icm_fold.get(0, 0.0) - node_val.get(0, 0.0),
                  icm_open.get(0, 0.0) - node_val.get(0, 0.0)]
        infoset.regret_sum[0] += regret[0]
        infoset.regret_sum[1] += regret[1]
        infoset.strategy_sum[0] += strat[0]
        infoset.strategy_sum[1] += strat[1]

        return node_val

    def _terminal_all_fold(self, hands):
        """Todo mundo depois do abridor foldou -- abridor ganha os posts
        de quem tinha blind (os outros nao perdem nada alem do que ja
        haviam postado, que ja esta contado)."""
        deltas = {}
        total_won = 0.0
        for i in range(1, self.n_seats):
            p = self.seat_posts[i]
            if p > 0:
                deltas[i] = -p
                total_won += p
        deltas[0] = total_won
        return self._icm(deltas)

    def _play_fold_or_jam(self, seat_i, hands):
        """Decisao de cada seat DEPOIS do abridor (seat_i >= 1): fold
        ou jam (all-in), quando a acao chega nele (todos antes dele
        ja foldaram, por construcao -- essa funcao so e chamada na
        sequencia, nunca fora de ordem)."""
        if seat_i >= self.n_seats:
            return self._terminal_all_fold(hands)

        infoset = self.phase1[seat_i][hands[seat_i]]
        strat = infoset.current_strategy()

        icm_fold = self._play_fold_or_jam(seat_i + 1, hands)
        icm_jam = self._play_phase2(jammer=seat_i, hands=hands)

        node_val = {}
        all_seats = set(icm_fold.keys()) | set(icm_jam.keys())
        for s in all_seats:
            node_val[s] = strat[0] * icm_fold.get(s, 0.0) + strat[1] * icm_jam.get(s, 0.0)

        regret = [icm_fold.get(seat_i, 0.0) - node_val.get(seat_i, 0.0),
                  icm_jam.get(seat_i, 0.0) - node_val.get(seat_i, 0.0)]
        infoset.regret_sum[0] += regret[0]
        infoset.regret_sum[1] += regret[1]
        infoset.strategy_sum[0] += strat[0]
        infoset.strategy_sum[1] += strat[1]

        return node_val

    def _play_phase2(self, jammer, hands):
        """Todos os seats DEPOIS do jammer que ainda nao agiram, em
        ordem, decidem fold/call; no final o abridor (seat 0, que
        sempre abriu -- nunca chega aqui tendo foldado, isso ja e
        outro ramo da arvore) tambem decide fold/call."""
        responders = [i for i in range(self.n_seats) if i > jammer]
        responders.append(0)  # abridor sempre responde (sempre abriu antes)

        return self._resolve_responders(jammer, responders, 0, {jammer}, hands)

    def _resolve_responders(self, jammer, responders, idx, live_set, hands):
        if idx >= len(responders):
            return self._showdown(live_set, hands)

        seat_i = responders[idx]
        infoset = self.phase2[seat_i][hands[seat_i]]
        strat = infoset.current_strategy()

        icm_fold = self._resolve_responders(jammer, responders, idx + 1, live_set, hands)
        icm_call = self._resolve_responders(jammer, responders, idx + 1, live_set | {seat_i}, hands)

        node_val = {}
        all_seats = set(icm_fold.keys()) | set(icm_call.keys())
        for s in all_seats:
            node_val[s] = strat[0] * icm_fold.get(s, 0.0) + strat[1] * icm_call.get(s, 0.0)

        regret = [icm_fold.get(seat_i, 0.0) - node_val.get(seat_i, 0.0),
                  icm_call.get(seat_i, 0.0) - node_val.get(seat_i, 0.0)]
        infoset.regret_sum[0] += regret[0]
        infoset.regret_sum[1] += regret[1]
        infoset.strategy_sum[0] += strat[0]
        infoset.strategy_sum[1] += strat[1]

        return node_val

    def _showdown(self, live_set, hands):
        live = sorted(live_set)
        if len(live) == 1:
            # todos foldaram pro jam -- o unico vivo (o jammer) ganha
            # os posts de quem foldou nessa fase + o open do abridor se
            # o abridor nao for o jammer
            deltas = {}
            total_won = 0.0
            for i in range(self.n_seats):
                if i not in live_set:
                    cost = self.R if i == 0 else self.seat_posts[i]
                    # so conta se esse seat chegou a ter uma decisao de
                    # fold/call (ou seja, nao foldou na fase 1 antes do jam)
                    if i == 0 or i > min(live_set):
                        deltas[i] = -cost
                        total_won += cost
            deltas[live[0]] = total_won
            return self._icm(deltas)

        # multiway showdown entre os "live"
        seat_hand_pairs = [(i, hands[i]) for i in live]
        eqs = self._multiway_eq(seat_hand_pairs)

        # ICM esperado: para cada resultado possivel de vencedor, calcula
        # o ICM e pondera pela equity -- aproximacao razoavel (nao
        # enumeramos boards, usamos a equity agregada por jogador)
        icm_by_winner = {}
        for winner in live:
            deltas = {}
            total_won = 0.0
            for i in live:
                if i != winner:
                    deltas[i] = -self.T
                    total_won += self.T
            deltas[winner] = total_won
            icm_by_winner[winner] = self._icm(deltas)

        result = {}
        for s in range(self.n_seats):
            val = 0.0
            for winner in live:
                val += eqs.get(winner, 0.0) * icm_by_winner[winner].get(s, 0.0)
            if val > 0 or s in live:
                result[s] = val
        return result

    def average_strategy(self):
        return {
            "phase1": [
                {c: self.phase1[i][c].average_strategy()[1] for c in self.classes}
                for i in range(self.n_seats)
            ],
            "phase2": [
                {c: self.phase2[i][c].average_strategy()[1] for c in self.classes}
                for i in range(self.n_seats)
            ],
        }
