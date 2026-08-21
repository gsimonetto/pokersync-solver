"""
CÓPIA CONGELADA da versão anterior de engine/rfi_jam.py (a de tamanho
único), preservada só pra `tests/rfi_jam_multisize.py` comparar contra
ela e garantir que a generalização pra múltiplos tamanhos não mudou
NADA do comportamento já validado/em produção. Não importar em código
de verdade -- é referência de teste, não motor ativo.

Árvore de RFI + resposta, heads-up, com ICM — versão CORRIGIDA.

Decisão de arquitetura (registrada, veio de um problema real encontrado
em teste): a versão anterior desse motor tinha um nó de "call simples"
(BB paga a abertura sem ser all-in) que era avaliado como showdown
imediato usando a equity pré-flop crua. Isso é ERRADO — pagar uma
abertura não all-in não termina a mão, tem pós-flop inteiro pela
frente, e a equity crua superestima muito o valor de mãos fracas que
não conseguem "realizar" essa equity jogando contra um range mais
forte em várias ruas. O sintoma foi um range de call de 100% (nunca
foldava), inclusive com 72o — claramente errado.

Correção: cada decisão agora só tem duas saídas — fold, ou uma ação
que LEVA A UM ALL-IN GENUÍNO (que sabemos calcular certo via equity +
ICM, igual o push/fold). Sem nó de "call intermediário" em lugar
nenhum. Isso significa que, nesse modelo, um 3-bet e um 4-bet-shove
são a MESMA decisão de all-in — é uma simplificação deliberada,
correta pra stacks curtos/médios (onde 3-bet e 4-bet já seriam
essencialmente all-in mesmo), mas não serve pra stacks profundos com
3-bet "de verdade" (não all-in) até existir pós-flop de verdade.

Árvore:
  1. SB (raiz): fold ou raise (tamanho R, NAO all-in).
  2. BB (facing raise): fold ou jam (all-in, T).
  3. SB (facing jam): fold ou call (all-in genuino, showdown real).
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, combo_count  # noqa: E402
from engine.icm import icm_equity  # noqa: E402


class InfoSet:
    def __init__(self, n_actions):
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


class RfiJamSolverLegacy:
    """Open-or-fold -> facing raise: fold-or-jam -> facing jam: fold-or-call.
    Toda decisao termina em fold ou all-in genuino -- sem approximacao
    de 'call intermediario'.

    Generalizado pra qualquer par de posicoes (nao so SB vs BB):
    opener_post/defender_post representam quanto cada jogador ja tem
    investido no pote ANTES de decidir (0 pra posicoes sem blind, ex
    CO ou BTN quando nao estao no blind; 0.5 pro SB; 1.0 pra BB).

    dead_money representa fichas de OUTROS jogadores (blinds de SB/BB
    quando nenhum dos dois modelados esta no blind) que ja foldaram
    antes dessa decisao -- vai pro vencedor da mao, mas nao vem do
    bolso de nenhum dos dois jogadores modelados. Sem isso, matchups
    tipo CO vs BTN ficam sem sentido (abrir e ganhar sem war da 0 de
    lucro em fichas, o que so faz sentido se SB/BB nao existissem).
    """

    def __init__(self, sb_idx, bb_idx, table_stacks, payouts, equity_matrix, classes,
                 open_size=2.2, effective_stack=None, opener_post=0.5, defender_post=1.0,
                 dead_money=0.0):
        self.sb_idx = sb_idx  # "opener" (nome mantido por compatibilidade)
        self.bb_idx = bb_idx  # "defender"
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.equity_matrix = equity_matrix
        self.classes = classes
        self.weights = {c: combo_count(c) for c in classes}
        total_w = sum(self.weights.values())
        self.weights_norm = {c: w / total_w for c, w in self.weights.items()}

        self.R = open_size
        self.T = effective_stack or min(table_stacks[sb_idx], table_stacks[bb_idx])
        self.opener_post = opener_post
        self.defender_post = defender_post
        self.dead_money = dead_money

        self.sb_root = {c: InfoSet(2) for c in classes}          # fold, raise
        self.bb_facing_raise = {c: InfoSet(2) for c in classes}  # fold, jam
        self.sb_facing_jam = {c: InfoSet(2) for c in classes}    # fold, call

        self._precompute_icm_terminals()

    def _stacks_after(self, sb_delta, bb_delta):
        stacks = list(self.table_stacks)
        stacks[self.sb_idx] = max(0.0, stacks[self.sb_idx] + sb_delta)
        stacks[self.bb_idx] = max(0.0, stacks[self.bb_idx] + bb_delta)
        return stacks

    def _icm_pair(self, sb_delta, bb_delta):
        stacks = self._stacks_after(sb_delta, bb_delta)
        eq = icm_equity(stacks, self.payouts)
        return eq[self.sb_idx], eq[self.bb_idx]

    def _precompute_icm_terminals(self):
        R, T, dm = self.R, self.T, self.dead_money
        op, dp = self.opener_post, self.defender_post
        # opener folda na raiz: dead_money nao entra aqui -- so se aplica
        # quando o opener efetivamente abre e "isola" os blinds mortos
        self.icm_fold_root = self._icm_pair(-op, +op)
        # opener abriu, defender folda: opener ganha o que a defender
        # postou MAIS os blinds mortos de quem ja foldou antes
        self.icm_bb_fold_vs_raise = self._icm_pair(+dp + dm, -dp)
        # opener folda pro jam: defender ganha o R do opener + dead money
        self.icm_sb_fold_vs_jam = self._icm_pair(-R, +R + dm)
        # showdown: o vencedor leva os dois stacks efetivos + dead money
        self.icm_showdown_sbwins = self._icm_pair(+T + dm, -T)
        self.icm_showdown_bbwins = self._icm_pair(-T, +T + dm)



    def _equity(self, sb_class, bb_class):
        return self.equity_matrix[(sb_class, bb_class)]

    def _node_sb_facing_jam(self, sb_class, bb_class, p_sb, p_bb):
        infoset = self.sb_facing_jam[sb_class]
        strat = infoset.current_strategy()
        eq = self._equity(sb_class, bb_class)

        util_fold_sb, util_fold_bb = self.icm_sb_fold_vs_jam
        util_call_sb = eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0]
        util_call_bb = eq * self.icm_showdown_sbwins[1] + (1 - eq) * self.icm_showdown_bbwins[1]

        node_sb = strat[0] * util_fold_sb + strat[1] * util_call_sb
        node_bb = strat[0] * util_fold_bb + strat[1] * util_call_bb

        regret = [util_fold_sb - node_sb, util_call_sb - node_sb]
        for a in range(2):
            infoset.regret_sum[a] += p_bb * regret[a]
        for a in range(2):
            infoset.strategy_sum[a] += p_sb * strat[a]

        return node_sb, node_bb

    def _node_bb_facing_raise(self, sb_class, bb_class, p_sb, p_bb):
        infoset = self.bb_facing_raise[bb_class]
        strat = infoset.current_strategy()

        util_fold_sb, util_fold_bb = self.icm_bb_fold_vs_raise
        util_jam_sb, util_jam_bb = self._node_sb_facing_jam(sb_class, bb_class, p_sb, p_bb * strat[1])

        node_sb = strat[0] * util_fold_sb + strat[1] * util_jam_sb
        node_bb = strat[0] * util_fold_bb + strat[1] * util_jam_bb

        regret = [util_fold_bb - node_bb, util_jam_bb - node_bb]
        for a in range(2):
            infoset.regret_sum[a] += p_sb * regret[a]
        for a in range(2):
            infoset.strategy_sum[a] += p_bb * strat[a]

        return node_sb, node_bb

    def _node_root(self, sb_class, bb_class, p_sb, p_bb):
        infoset = self.sb_root[sb_class]
        strat = infoset.current_strategy()

        util_fold_sb, util_fold_bb = self.icm_fold_root
        util_raise_sb, util_raise_bb = self._node_bb_facing_raise(sb_class, bb_class, p_sb * strat[1], p_bb)

        node_sb = strat[0] * util_fold_sb + strat[1] * util_raise_sb
        node_bb = strat[0] * util_fold_bb + strat[1] * util_raise_bb

        regret = [util_fold_sb - node_sb, util_raise_sb - node_sb]
        for a in range(2):
            infoset.regret_sum[a] += p_bb * regret[a]
        for a in range(2):
            infoset.strategy_sum[a] += p_sb * strat[a]

        return node_sb, node_bb

    def train(self, iterations=800000, seed=42):
        random.seed(seed)
        classes_list = self.classes
        weights_list = [self.weights_norm[c] for c in classes_list]
        for _ in range(iterations):
            sb_class = random.choices(classes_list, weights=weights_list, k=1)[0]
            bb_class = random.choices(classes_list, weights=weights_list, k=1)[0]
            self._node_root(sb_class, bb_class, 1.0, 1.0)

    def average_strategy(self):
        return {
            "sb_open": {c: self.sb_root[c].average_strategy()[1] for c in self.classes},
            "bb_jam": {c: self.bb_facing_raise[c].average_strategy()[1] for c in self.classes},
            "sb_call_jam": {c: self.sb_facing_jam[c].average_strategy()[1] for c in self.classes},
        }

    def compute_action_evs(self, strat=None):
        """
        Calcula o EV (em $ICM) de CADA ação por classe de mão, usando a
        estrategia media final (ja convergida) como fixa -- diferente do
        valor usado durante o treino (que muda a cada iteracao). Serve
        pra expor o "gap" entre as duas opcoes em cada decisao: um gap
        pequeno significa mao marginal (o solver esta proximo de
        indiferente), o que o produto deve tratar como "decisao
        marginal" em vez de certo/errado rigido.
        """
        if strat is None:
            strat = self.average_strategy()

        bb_jam_prob = strat["bb_jam"]
        sb_call_prob = strat["sb_call_jam"]
        sb_open_prob = strat["sb_open"]

        evs = {"sb_open": {}, "bb_jam": {}, "sb_call_jam": {}}

        # sb_facing_jam: condicionar na distribuicao da BB DADO que ela
        # escolheu dar jam (nao a distribuicao bruta de maos da BB)
        total_jam_reach = sum(self.weights_norm[c] * bb_jam_prob[c] for c in self.classes)
        for sb_class in self.classes:
            ev_fold = self.icm_sb_fold_vs_jam[0]
            ev_call = 0.0
            for bb_class in self.classes:
                w = self.weights_norm[bb_class] * bb_jam_prob[bb_class]
                eq = self._equity(sb_class, bb_class)
                ev_call += w * (eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0])
            if total_jam_reach > 0:
                ev_call = ev_call / total_jam_reach
            evs["sb_call_jam"][sb_class] = {"fold": ev_fold, "call": ev_call, "gap": abs(ev_fold - ev_call)}

        # bb_facing_raise: condicionar na distribuicao do SB DADO que ele
        # escolheu abrir (nao a distribuicao bruta de maos do SB)
        total_open_reach = sum(self.weights_norm[c] * sb_open_prob[c] for c in self.classes)
        for bb_class in self.classes:
            ev_fold = self.icm_bb_fold_vs_raise[1]
            ev_jam = 0.0
            for sb_class in self.classes:
                w = self.weights_norm[sb_class] * sb_open_prob[sb_class]
                eq = self._equity(sb_class, bb_class)
                call_p = sb_call_prob[sb_class]
                ev_showdown = eq * self.icm_showdown_sbwins[1] + (1 - eq) * self.icm_showdown_bbwins[1]
                ev_fold_to_jam = self.icm_sb_fold_vs_jam[1]
                ev_jam += w * (call_p * ev_showdown + (1 - call_p) * ev_fold_to_jam)
            if total_open_reach > 0:
                ev_jam = ev_jam / total_open_reach
            evs["bb_jam"][bb_class] = {"fold": ev_fold, "jam": ev_jam, "gap": abs(ev_fold - ev_jam)}

        # sb_open (raiz): EV de fold vs EV de abrir, por classe do SB
        for sb_class in self.classes:
            ev_fold = self.icm_fold_root[0]
            ev_open = 0.0
            for bb_class in self.classes:
                w = self.weights_norm[bb_class]
                jam_p = bb_jam_prob[bb_class]
                ev_bb_fold = self.icm_bb_fold_vs_raise[0]
                eq = self._equity(sb_class, bb_class)
                call_p = sb_call_prob[sb_class]
                ev_showdown = eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0]
                ev_fold_to_jam = self.icm_sb_fold_vs_jam[0]
                ev_vs_jam = call_p * ev_showdown + (1 - call_p) * ev_fold_to_jam
                ev_open += w * (jam_p * ev_vs_jam + (1 - jam_p) * ev_bb_fold)
            evs["sb_open"][sb_class] = {"fold": ev_fold, "open": ev_open, "gap": abs(ev_fold - ev_open)}

        return evs

    def best_response_value(self, strat, br_player):
        """
        Best-response exato, respeitando infosets corretamente -- mesmo
        cuidado necessario no Kuhn Poker: o SB tem DOIS pontos de
        decisao (raiz e facing_jam), entao o mais profundo precisa ser
        resolvido primeiro e FIXADO antes de calcular a raiz, senao a
        raiz "enxergaria" a carta do oponente por baixo dos panos.
        BB so decide uma vez, entao nao tem esse risco.
        """
        bb_jam_prob = strat["bb_jam"]
        sb_call_prob = strat["sb_call_jam"]
        sb_open_prob = strat["sb_open"]

        if br_player == 0:  # SB
            # peso de cada classe da BB, condicionado a ela ter escolhido
            # dar jam -- NAO a distribuicao bruta de maos da BB. Sem isso,
            # o SB "acha" que esta enfrentando qualquer mao da BB (incluindo
            # as fracas que nunca dariam jam), o que deixa call parecer
            # pior do que realmente e.
            total_jam_reach = sum(self.weights_norm[c] * bb_jam_prob[c] for c in self.classes)

            best_call = {}
            for sb_class in self.classes:
                ev_fold = self.icm_sb_fold_vs_jam[0]
                ev_call = 0.0
                for bb_class in self.classes:
                    w = self.weights_norm[bb_class] * bb_jam_prob[bb_class]
                    eq = self._equity(sb_class, bb_class)
                    ev_call += w * (eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0])
                if total_jam_reach > 0:
                    ev_call = ev_call / total_jam_reach
                best_call[sb_class] = 1 if ev_call > ev_fold else 0

            total = 0.0
            for sb_class in self.classes:
                w_sb = self.weights_norm[sb_class]
                ev_fold_root = self.icm_fold_root[0]

                if best_call[sb_class] == 1:
                    ev_call = 0.0
                    for bb_class in self.classes:
                        w_bb = self.weights_norm[bb_class] * bb_jam_prob[bb_class]
                        eq = self._equity(sb_class, bb_class)
                        ev_call += w_bb * (eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0])
                    if total_jam_reach > 0:
                        ev_call = ev_call / total_jam_reach
                    ev_facing_jam = ev_call
                else:
                    ev_facing_jam = self.icm_sb_fold_vs_jam[0]

                ev_open = 0.0
                for bb_class in self.classes:
                    w_bb = self.weights_norm[bb_class]
                    jam_p = bb_jam_prob[bb_class]
                    ev_bb_fold = self.icm_bb_fold_vs_raise[0]
                    ev_open += w_bb * (jam_p * ev_facing_jam + (1 - jam_p) * ev_bb_fold)

                best_root = ev_open if ev_open > ev_fold_root else ev_fold_root
                total += w_sb * best_root
            return total

        else:  # BB, decisao unica -- sem risco de vazamento entre infosets
            total_open_reach = sum(self.weights_norm[c] * sb_open_prob[c] for c in self.classes)
            total = 0.0
            for bb_class in self.classes:
                w_bb = self.weights_norm[bb_class]
                ev_fold = self.icm_bb_fold_vs_raise[1]
                ev_jam_numer = 0.0
                for sb_class in self.classes:
                    w_sb = self.weights_norm[sb_class]
                    open_p = sb_open_prob[sb_class]
                    call_p = sb_call_prob[sb_class]
                    eq = self._equity(sb_class, bb_class)
                    ev_showdown = eq * self.icm_showdown_sbwins[1] + (1 - eq) * self.icm_showdown_bbwins[1]
                    ev_fold_to_jam = self.icm_sb_fold_vs_jam[1]
                    ev_if_reached = call_p * ev_showdown + (1 - call_p) * ev_fold_to_jam
                    ev_jam_numer += w_sb * open_p * ev_if_reached
                ev_jam_conditional = ev_jam_numer / total_open_reach if total_open_reach > 0 else ev_fold
                best_conditional = ev_jam_conditional if ev_jam_conditional > ev_fold else ev_fold
                # reconecta o valor condicional (dado que SB abriu) ao
                # resto da arvore: pondera pela chance real de SB abrir,
                # e soma o caso complementar onde SB folda na raiz (BB
                # ganha o pote automaticamente, sem decisao nenhuma)
                value_bb_class = (
                    total_open_reach * best_conditional
                    + (1 - total_open_reach) * self.icm_fold_root[1]
                )
                total += w_bb * value_bb_class
            return total

    def compute_exploitability(self, strat=None):
        if strat is None:
            strat = self.average_strategy()
        br_sb = self.best_response_value(strat, br_player=0)
        br_bb = self.best_response_value(strat, br_player=1)
        return br_sb, br_bb


if __name__ == "__main__":
    import pickle

    with open(str(Path(__file__).resolve().parent.parent / "data" / "equity_matrix_final.pkl"), "rb") as f:
        d = pickle.load(f)
    equity_matrix, classes = d["matrix"], d["classes"]

    table_stacks = [25, 25, 40, 30, 20, 15]
    payouts = [500.0, 300.0, 200.0]

    solver = RfiJamSolverLegacy(
        sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
        equity_matrix=equity_matrix, classes=classes,
        open_size=2.2, effective_stack=25,
    )
    solver.train(iterations=800000)
    strat = solver.average_strategy()

    open_range = sorted([c for c in classes if strat["sb_open"][c] > 0.5], key=lambda c: -strat["sb_open"][c])
    open_combos = sum(combo_count(c) for c in open_range)
    jam_range = sorted([c for c in classes if strat["bb_jam"][c] > 0.5], key=lambda c: -strat["bb_jam"][c])
    jam_combos = sum(combo_count(c) for c in jam_range)
    call_range = sorted([c for c in classes if strat["sb_call_jam"][c] > 0.5], key=lambda c: -strat["sb_call_jam"][c])
    call_combos = sum(combo_count(c) for c in call_range)

    print(f"SB open: {len(open_range)} classes, {open_combos}/1326 ({100*open_combos/1326:.1f}%)")
    print(f"BB jam vs open: {len(jam_range)} classes, {jam_combos}/1326 ({100*jam_combos/1326:.1f}%)")
    print(f"SB call vs jam: {len(call_range)} classes, {call_combos}/1326 ({100*call_combos/1326:.1f}%)")

    print("\n--- Sanidade ---")
    print(f"AA: open={strat['sb_open']['AA']:.3f} jam={strat['bb_jam']['AA']:.3f} call={strat['sb_call_jam']['AA']:.3f}")
    print(f"72o: open={strat['sb_open']['72o']:.3f} jam={strat['bb_jam']['72o']:.3f} call={strat['sb_call_jam']['72o']:.3f}")
    print(f"KQo: open={strat['sb_open']['KQo']:.3f} jam={strat['bb_jam']['KQo']:.3f} call={strat['sb_call_jam']['KQo']:.3f}")

    # checagem de monotonicidade: mao mais forte nunca deveria ter frequencia
    # de call/jam MENOR que uma mao mais fraca (checagem simples com pares)
    problems = 0
    pairs_rank = ["22","33","44","55","66","77","88","99","TT","JJ","QQ","KK","AA"]
    for i in range(len(pairs_rank)-1):
        weaker, stronger = pairs_rank[i], pairs_rank[i+1]
        if strat["sb_call_jam"][stronger] < strat["sb_call_jam"][weaker] - 0.01:
            problems += 1
            print(f"  MONOTONICIDADE QUEBRADA: {stronger} call={strat['sb_call_jam'][stronger]:.3f} < {weaker} call={strat['sb_call_jam'][weaker]:.3f}")
    print(f"\nChecagem de monotonicidade em pares (22..AA): {'OK, nenhum problema' if problems==0 else f'{problems} problemas'}")
