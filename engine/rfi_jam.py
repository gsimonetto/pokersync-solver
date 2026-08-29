"""
Árvore de RFI + resposta, heads-up, com ICM — versão CORRIGIDA, agora
com múltiplos tamanhos de abertura.

Decisão de arquitetura (registrada, veio de um problema real encontrado
em teste): a versão anterior desse motor tinha um nó de "call simples"
(BB paga a abertura sem ser all-in) que era avaliado como showdown
imediato usando a equity pré-flop crua. Isso é ERRADO — pagar uma
abertura não all-in não termina a mão, tem pós-flop inteiro pela
frente, e a equity crua superestima muito o valor de mãos fracas que
não conseguem "realizar" essa equity jogando contra um range mais
forte em várias ruas. O sintoma foi um range de call de 100% (nunca
foldava), inclusive com 72o — claramente errado.

Correção: cada decisão agora só tem duas saídas por ramo -- fold, ou
uma ação que LEVA A UM ALL-IN GENUÍNO (que sabemos calcular certo via
equity + ICM, igual o push/fold). Sem nó de "call intermediário" em
lugar nenhum. Isso significa que, nesse modelo, um 3-bet e um
4-bet-shove são a MESMA decisão de all-in — é uma simplificação
deliberada, correta pra stacks curtos/médios (onde 3-bet e 4-bet já
seriam essencialmente all-in mesmo), mas não serve pra stacks
profundos com 3-bet "de verdade" (não all-in) até existir pós-flop de
verdade.

Múltiplos tamanhos de abertura (2026-08): o único ponto da árvore onde
uma escolha de TAMANHO faz sentido é a abertura do SB -- jam e call-jam
são all-in por definição (só existe um "tamanho" possível: o stack
inteiro). `open_sizes` agora aceita uma LISTA (ex [2.0, 2.5, 3.0]) em
vez de um único float; o SB ganha um nó de decisão com 1+N ações (fold
+ uma por tamanho), e BB responde a CADA tamanho com sua própria
subárvore fold-ou-jam (o tamanho da abertura afeta o equilíbrio: um
open maior deixa o SB mais "grudado" ao pote -- ele perde mais fold-ando
depois pro jam -- o que muda o quanto vale pro BB blefar ali; ver
`icm_sb_fold_vs_jam` por tamanho). Continua 100% compatível com o uso
antigo: passar um único float em `open_size` (ou uma lista de 1
elemento em `open_sizes`) reproduz exatamente o comportamento de antes,
inclusive o formato de saída de `average_strategy()`/`compute_action_evs()`
(dict achatado por classe, sem a dimensão de tamanho) -- só quando
`open_sizes` tem 2+ elementos que a saída ganha essa dimensão extra.
Validado por `tests/rfi_jam_multisize.py`: com uma lista de 1 elemento,
os números batem com a versão anterior (pré-multi-size) até a última
casa decimal.

Árvore (com N tamanhos de abertura):
  1. SB (raiz): fold, ou raise(tamanho_1), ..., ou raise(tamanho_N).
  2. BB (facing raise de tamanho_i): fold ou jam (all-in, T) -- uma
     subárvore/infoset POR tamanho, já que a resposta ótima do BB pode
     (e costuma) mudar dependendo de qual tamanho o SB escolheu.
  3. SB (facing jam, depois de ter aberto tamanho_i): fold ou call
     (all-in genuíno, showdown real) -- também por tamanho, porque o
     custo de foldar depois de ter aberto maior é maior.
"""

import random
import sys
from pathlib import Path
from typing import Sequence

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


class RfiJamSolver:
    """Open-or-fold (1 ou mais tamanhos) -> facing raise: fold-or-jam ->
    facing jam: fold-or-call. Toda decisao termina em fold ou all-in
    genuino -- sem approximacao de 'call intermediario'.

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

    ante_pool (2026-08, bug real: motor nunca modelava ante nenhum --
    toda mao real de torneio do produto tem ante, so' os spots gerados
    nao contavam) representa o ante de TODOS os jogadores ainda na mao
    (os N assentos da mesa, incluindo os 2 modelados) somado. Parece
    dead_money a primeira vista mas tem uma diferenca de fundo: blind
    de terceiro so' fica "isolado" se alguem de fato brigar por ele --
    se o abridor desiste de cara aqui, na vida real quem tinha aquele
    blind (SB/BB nao-modelado) ainda esta na mao e pode fazer qualquer
    coisa, entao nao da pra cravar que o defensor modelado vai ficar
    com ele (por isso dead_money fica de fora do no' de fold na raiz,
    ver icm_fold_root). Ante e' diferente: e' forcado de TODO MUNDO
    ANTES de qualquer decisao, ja esta morto desde o t=0 da mao --
    n incide em quem desiste ou nao depois. Se o abridor desiste de
    cara aqui, o defensor ainda leva o ante de todo mundo (inclusive
    do proprio abridor) por W.O., entao ante_pool ENTRA em icm_fold_root
    tambem (unica diferenca de tratamento vs dead_money). Convencao de
    contabilidade igual a de dead_money nos outros 3 terminais: fichas
    que nao vem do bolso rastreado de nenhum dos 2 jogadores modelados
    (mesma aproximacao ja aceita/validada pra dead_money).
    """

    def __init__(self, sb_idx, bb_idx, table_stacks, payouts, equity_matrix, classes,
                 open_size=2.2, open_sizes: Sequence[float] | None = None,
                 effective_stack=None, opener_post=0.5, defender_post=1.0,
                 dead_money=0.0, ante_pool=0.0):
        self.sb_idx = sb_idx  # "opener" (nome mantido por compatibilidade)
        self.bb_idx = bb_idx  # "defender"
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.equity_matrix = equity_matrix
        self.classes = classes
        self.weights = {c: combo_count(c) for c in classes}
        total_w = sum(self.weights.values())
        self.weights_norm = {c: w / total_w for c, w in self.weights.items()}

        # `open_sizes` (lista) tem prioridade; `open_size` (escalar,
        # compatibilidade com todo chamador existente) vira lista de 1.
        self.sizes: list[float] = list(open_sizes) if open_sizes else [open_size]
        # "Legado": só 1 tamanho -- average_strategy()/compute_action_evs()
        # devolvem o formato achatado antigo (sem dimensao de tamanho),
        # pra nao quebrar nenhum chamador (jobs/solve_rfi_jam_batch.py,
        # o frontend) que ainda espera esse formato.
        self._legacy_single_size = len(self.sizes) == 1

        self.T = effective_stack or min(table_stacks[sb_idx], table_stacks[bb_idx])
        self.opener_post = opener_post
        self.defender_post = defender_post
        self.dead_money = dead_money
        self.ante_pool = ante_pool

        n_root_actions = 1 + len(self.sizes)  # fold + 1 por tamanho
        self.sb_root = {c: InfoSet(n_root_actions) for c in classes}
        # Por tamanho: fold-ou-jam (BB) e fold-ou-call (SB, ja tendo aberto esse tamanho)
        self.bb_facing_raise = {s: {c: InfoSet(2) for c in classes} for s in self.sizes}
        self.sb_facing_jam = {s: {c: InfoSet(2) for c in classes} for s in self.sizes}

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
        T, dm, ap = self.T, self.dead_money, self.ante_pool
        op, dp = self.opener_post, self.defender_post
        # opener folda na raiz: dead_money NAO entra aqui (contingente --
        # ver docstring da classe), mas ante_pool SIM -- ja estava morto
        # desde antes de qualquer decisao, o defensor leva por W.O.
        self.icm_fold_root = self._icm_pair(-op, +op + ap)
        # opener abriu (qualquer tamanho), defender folda: opener ganha o
        # que a defender postou MAIS os blinds mortos de quem ja foldou
        # antes MAIS o ante de todo mundo -- NAO depende do tamanho da
        # abertura (se todo mundo folda, o opener so recupera o proprio
        # dinheiro, que era dele mesmo; o tamanho da abertura em si nao
        # muda esse resultado).
        self.icm_bb_fold_vs_raise = self._icm_pair(+dp + dm + ap, -dp)
        # opener folda pro jam DEPOIS de ter aberto tamanho R: opener
        # perde R (o que ja tinha posto), defender ganha R + dead money +
        # ante. Isso SIM depende do tamanho -- abrir maior custa mais caro
        # se sair foldando depois.
        self.icm_sb_fold_vs_jam = {s: self._icm_pair(-s, +s + dm + ap) for s in self.sizes}
        # showdown: o vencedor leva os dois stacks efetivos + dead money +
        # ante -- nao depende do tamanho da abertura (quem paga o jam poe
        # o stack efetivo inteiro, independente de quanto tinha aberto).
        self.icm_showdown_sbwins = self._icm_pair(+T + dm + ap, -T)
        self.icm_showdown_bbwins = self._icm_pair(-T, +T + dm + ap)

    def _equity(self, sb_class, bb_class):
        return self.equity_matrix[(sb_class, bb_class)]

    def _node_sb_facing_jam(self, sb_class, bb_class, p_sb, p_bb, size):
        infoset = self.sb_facing_jam[size][sb_class]
        strat = infoset.current_strategy()
        eq = self._equity(sb_class, bb_class)

        util_fold_sb, util_fold_bb = self.icm_sb_fold_vs_jam[size]
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

    def _node_bb_facing_raise(self, sb_class, bb_class, p_sb, p_bb, size):
        infoset = self.bb_facing_raise[size][bb_class]
        strat = infoset.current_strategy()

        util_fold_sb, util_fold_bb = self.icm_bb_fold_vs_raise
        util_jam_sb, util_jam_bb = self._node_sb_facing_jam(sb_class, bb_class, p_sb, p_bb * strat[1], size)

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
        utils_sb = [util_fold_sb]
        utils_bb = [util_fold_bb]
        for i, size in enumerate(self.sizes):
            u_sb, u_bb = self._node_bb_facing_raise(sb_class, bb_class, p_sb * strat[i + 1], p_bb, size)
            utils_sb.append(u_sb)
            utils_bb.append(u_bb)

        node_sb = sum(strat[a] * utils_sb[a] for a in range(infoset.n_actions))
        node_bb = sum(strat[a] * utils_bb[a] for a in range(infoset.n_actions))

        regret = [utils_sb[a] - node_sb for a in range(infoset.n_actions)]
        for a in range(infoset.n_actions):
            infoset.regret_sum[a] += p_bb * regret[a]
        for a in range(infoset.n_actions):
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
        if self._legacy_single_size:
            size = self.sizes[0]
            return {
                "sb_open": {c: self.sb_root[c].average_strategy()[1] for c in self.classes},
                "bb_jam": {c: self.bb_facing_raise[size][c].average_strategy()[1] for c in self.classes},
                "sb_call_jam": {c: self.sb_facing_jam[size][c].average_strategy()[1] for c in self.classes},
            }
        return {
            "sb_open": {
                c: {s: self.sb_root[c].average_strategy()[i + 1] for i, s in enumerate(self.sizes)}
                for c in self.classes
            },
            "bb_jam": {s: {c: self.bb_facing_raise[s][c].average_strategy()[1] for c in self.classes} for s in self.sizes},
            "sb_call_jam": {s: {c: self.sb_facing_jam[s][c].average_strategy()[1] for c in self.classes} for s in self.sizes},
        }

    def _sb_open_probs_raw(self):
        """[{tamanho: prob}, ...] por classe -- prob de abrir CADA
        tamanho especificamente (nao "prob de abrir" agregada)."""
        return {
            c: {s: self.sb_root[c].average_strategy()[i + 1] for i, s in enumerate(self.sizes)}
            for c in self.classes
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

        Com multiplos tamanhos, cada tamanho tem seu proprio gap
        fold-vs-abrir-ESSE-tamanho (comparavel entre tamanhos: qual
        tamanho tem o EV mais alto pra essa mao).
        """
        sb_open_raw = self._sb_open_probs_raw()

        evs_by_size = {}
        for size in self.sizes:
            bb_jam_prob = {c: self.bb_facing_raise[size][c].average_strategy()[1] for c in self.classes}
            sb_call_prob = {c: self.sb_facing_jam[size][c].average_strategy()[1] for c in self.classes}
            sb_open_prob = {c: sb_open_raw[c][size] for c in self.classes}

            evs = {"sb_open": {}, "bb_jam": {}, "sb_call_jam": {}}

            # sb_facing_jam: condicionar na distribuicao da BB DADO que
            # ela escolheu dar jam contra ESSE tamanho.
            total_jam_reach = sum(self.weights_norm[c] * bb_jam_prob[c] for c in self.classes)
            icm_fold_vs_jam = self.icm_sb_fold_vs_jam[size]
            for sb_class in self.classes:
                ev_fold = icm_fold_vs_jam[0]
                ev_call = 0.0
                for bb_class in self.classes:
                    w = self.weights_norm[bb_class] * bb_jam_prob[bb_class]
                    eq = self._equity(sb_class, bb_class)
                    ev_call += w * (eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0])
                if total_jam_reach > 0:
                    ev_call = ev_call / total_jam_reach
                evs["sb_call_jam"][sb_class] = {"fold": ev_fold, "call": ev_call, "gap": abs(ev_fold - ev_call)}

            # bb_facing_raise: condicionar na distribuicao do SB DADO que
            # ele escolheu abrir ESSE tamanho especificamente.
            total_open_reach = sum(self.weights_norm[c] * sb_open_prob[c] for c in self.classes)
            for bb_class in self.classes:
                ev_fold = self.icm_bb_fold_vs_raise[1]
                ev_jam = 0.0
                for sb_class in self.classes:
                    w = self.weights_norm[sb_class] * sb_open_prob[sb_class]
                    eq = self._equity(sb_class, bb_class)
                    call_p = sb_call_prob[sb_class]
                    ev_showdown = eq * self.icm_showdown_sbwins[1] + (1 - eq) * self.icm_showdown_bbwins[1]
                    ev_fold_to_jam = icm_fold_vs_jam[1]
                    ev_jam += w * (call_p * ev_showdown + (1 - call_p) * ev_fold_to_jam)
                if total_open_reach > 0:
                    ev_jam = ev_jam / total_open_reach
                evs["bb_jam"][bb_class] = {"fold": ev_fold, "jam": ev_jam, "gap": abs(ev_fold - ev_jam)}

            # sb_open (raiz): EV de abrir ESSE tamanho especificamente,
            # por classe do SB (fold e' o mesmo pra todos os tamanhos).
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
                    ev_fold_to_jam = icm_fold_vs_jam[0]
                    ev_vs_jam = call_p * ev_showdown + (1 - call_p) * ev_fold_to_jam
                    ev_open += w * (jam_p * ev_vs_jam + (1 - jam_p) * ev_bb_fold)
                evs["sb_open"][sb_class] = {"fold": ev_fold, "open": ev_open, "gap": abs(ev_fold - ev_open)}

            evs_by_size[size] = evs

        if self._legacy_single_size:
            return evs_by_size[self.sizes[0]]

        # Multi-tamanho: sb_open vira {classe: {tamanho: {fold, open, gap}}}
        # (fold repete o mesmo valor em todo tamanho -- e' a mesma acao,
        # so' serve pra nao quebrar quem espera {fold,open,gap} por chave).
        # bb_jam/sb_call_jam continuam indexados por tamanho (cada
        # tamanho tem sua propria subarvore).
        merged_sb_open = {
            c: {s: evs_by_size[s]["sb_open"][c] for s in self.sizes}
            for c in self.classes
        }
        return {
            "sb_open": merged_sb_open,
            "bb_jam": {s: evs_by_size[s]["bb_jam"] for s in self.sizes},
            "sb_call_jam": {s: evs_by_size[s]["sb_call_jam"] for s in self.sizes},
        }

    def best_response_value(self, strat, br_player):
        """
        Best-response exato, respeitando infosets corretamente -- mesmo
        cuidado necessario no Kuhn Poker: o SB tem DOIS pontos de
        decisao (raiz e facing_jam), entao o mais profundo precisa ser
        resolvido primeiro e FIXADO antes de calcular a raiz, senao a
        raiz "enxergaria" a carta do oponente por baixo dos panos.
        BB so decide uma vez (por tamanho), entao nao tem esse risco.

        Generalizado pra multiplos tamanhos: o SB, na raiz, escolhe a
        MELHOR entre fold e cada tamanho (nao so' fold-vs-um-raise); o
        BB, ao decidir melhor resposta pra um tamanho especifico, so'
        pondera pela chance de ESSE tamanho ter sido aberto (nao pela
        chance de "algum" raise ter acontecido).
        """
        sb_open_raw = strat["sb_open"] if not self._legacy_single_size else {
            c: {self.sizes[0]: strat["sb_open"][c]} for c in self.classes
        }
        bb_jam_by_size = strat["bb_jam"] if not self._legacy_single_size else {self.sizes[0]: strat["bb_jam"]}
        sb_call_by_size = strat["sb_call_jam"] if not self._legacy_single_size else {self.sizes[0]: strat["sb_call_jam"]}

        if br_player == 0:  # SB
            # Por tamanho: melhor resposta do SB facing jam (fold ou call),
            # condicionado no range de BB que de fato daria jam NESSE tamanho.
            best_call_by_size = {}
            ev_call_by_size = {}
            for size in self.sizes:
                bb_jam_prob = bb_jam_by_size[size]
                total_jam_reach = sum(self.weights_norm[c] * bb_jam_prob[c] for c in self.classes)
                icm_fold_vs_jam = self.icm_sb_fold_vs_jam[size]
                best_call = {}
                ev_call_map = {}
                for sb_class in self.classes:
                    ev_fold = icm_fold_vs_jam[0]
                    ev_call = 0.0
                    for bb_class in self.classes:
                        w = self.weights_norm[bb_class] * bb_jam_prob[bb_class]
                        eq = self._equity(sb_class, bb_class)
                        ev_call += w * (eq * self.icm_showdown_sbwins[0] + (1 - eq) * self.icm_showdown_bbwins[0])
                    if total_jam_reach > 0:
                        ev_call = ev_call / total_jam_reach
                    best_call[sb_class] = 1 if ev_call > ev_fold else 0
                    ev_call_map[sb_class] = ev_call
                best_call_by_size[size] = best_call
                ev_call_by_size[size] = ev_call_map

            total = 0.0
            for sb_class in self.classes:
                w_sb = self.weights_norm[sb_class]
                ev_fold_root = self.icm_fold_root[0]

                best_root = ev_fold_root
                for size in self.sizes:
                    icm_fold_vs_jam = self.icm_sb_fold_vs_jam[size]
                    if best_call_by_size[size][sb_class] == 1:
                        ev_facing_jam = ev_call_by_size[size][sb_class]
                    else:
                        ev_facing_jam = icm_fold_vs_jam[0]

                    bb_jam_prob = bb_jam_by_size[size]
                    ev_open = 0.0
                    for bb_class in self.classes:
                        w_bb = self.weights_norm[bb_class]
                        jam_p = bb_jam_prob[bb_class]
                        ev_bb_fold = self.icm_bb_fold_vs_raise[0]
                        ev_open += w_bb * (jam_p * ev_facing_jam + (1 - jam_p) * ev_bb_fold)

                    if ev_open > best_root:
                        best_root = ev_open

                total += w_sb * best_root
            return total

        else:  # BB, decisao unica por tamanho -- sem risco de vazamento entre infosets
            total = 0.0
            # Reach de "SB abre ALGUM tamanho" (pra ponderar o caso
            # "SB foldou na raiz", que independe de qual tamanho).
            total_open_reach_any = sum(
                self.weights_norm[c] * sum(sb_open_raw[c][s] for s in self.sizes) for c in self.classes
            )
            for bb_class in self.classes:
                w_bb = self.weights_norm[bb_class]
                ev_fold_root_bb = self.icm_fold_root[1]

                # Por tamanho: melhor resposta do BB (fold ou jam),
                # condicionado no range do SB que abriu ESSE tamanho.
                value_given_open_by_size = {}
                reach_by_size = {}
                for size in self.sizes:
                    sb_open_prob = {c: sb_open_raw[c][size] for c in self.classes}
                    sb_call_prob = sb_call_by_size[size]
                    total_open_reach = sum(self.weights_norm[c] * sb_open_prob[c] for c in self.classes)
                    reach_by_size[size] = total_open_reach

                    ev_fold = self.icm_bb_fold_vs_raise[1]
                    icm_fold_vs_jam = self.icm_sb_fold_vs_jam[size]
                    ev_jam_numer = 0.0
                    for sb_class in self.classes:
                        w_sb = self.weights_norm[sb_class]
                        open_p = sb_open_prob[sb_class]
                        call_p = sb_call_prob[sb_class]
                        eq = self._equity(sb_class, bb_class)
                        ev_showdown = eq * self.icm_showdown_sbwins[1] + (1 - eq) * self.icm_showdown_bbwins[1]
                        ev_fold_to_jam = icm_fold_vs_jam[1]
                        ev_if_reached = call_p * ev_showdown + (1 - call_p) * ev_fold_to_jam
                        ev_jam_numer += w_sb * open_p * ev_if_reached
                    ev_jam_conditional = ev_jam_numer / total_open_reach if total_open_reach > 0 else ev_fold
                    value_given_open_by_size[size] = ev_jam_conditional if ev_jam_conditional > ev_fold else ev_fold

                # BB nao escolhe o tamanho (quem abre e' o SB) -- o valor
                # esperado do BB e' a MEDIA ponderada pela chance real de
                # cada tamanho ter sido aberto (BB so' reage ao que
                # chega), mais o caso em que SB folda na raiz.
                weighted_open_value = 0.0
                if total_open_reach_any > 0:
                    for size in self.sizes:
                        weighted_open_value += reach_by_size[size] * value_given_open_by_size[size]
                    weighted_open_value /= total_open_reach_any

                value_bb_class = (
                    total_open_reach_any * weighted_open_value
                    + (1 - total_open_reach_any) * ev_fold_root_bb
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

    solver = RfiJamSolver(
        sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
        equity_matrix=equity_matrix, classes=classes,
        open_sizes=[2.0, 2.5, 3.0], effective_stack=25,
    )
    solver.train(iterations=800000)
    strat = solver.average_strategy()

    for size in solver.sizes:
        open_range = sorted([c for c in classes if strat["sb_open"][c][size] > 0.5], key=lambda c: -strat["sb_open"][c][size])
        open_combos = sum(combo_count(c) for c in open_range)
        print(f"Abrir {size}bb: {len(open_range)} classes, {open_combos}/1326 ({100*open_combos/1326:.1f}%)")

    print("\n--- Sanidade (AA deve preferir o tamanho maior; 72o quase nunca abre) ---")
    for size in solver.sizes:
        print(f"  {size}bb: AA open={strat['sb_open']['AA'][size]:.3f}  72o open={strat['sb_open']['72o'][size]:.3f}")

    br_sb, br_bb = solver.compute_exploitability(strat)
    print(f"\nExploitability (br_sb + br_bb): {br_sb + br_bb:.4f}")
