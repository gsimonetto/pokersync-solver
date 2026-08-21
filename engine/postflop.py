"""
Motor pós-flop — CFR heads-up generalizado pra qualquer rua (flop, turn
ou river) a partir de um board parcial ou completo.

Evolução do motor: a v1 só resolvia o RIVER (board de 5 cartas já
completo, sem carta por vir, então dava pra resolver 100% exato). Essa
v2 generaliza pra board de 3 ou 4 cartas (flop/turn) — a diferença é
que agora existem CARTAS AINDA NÃO REVELADAS, então a árvore precisa
de nós de chance:

  - Quando a rua termina SEM ninguém all-in (ex: check-check, ou call
    de uma aposta que não usa o stack inteiro de nenhum dos dois) e
    ainda falta carta pra sair: em vez de ir direto pro showdown, o
    motor SORTEIA uma carta (amostragem — MCCFR de chance, mesmo
    espírito já usado em `rfi_jam.py`/`multiway_rfi.py` pra amostrar
    mão de herói/vilão a cada iteração) e continua a árvore na
    próxima rua, com o mesmo par de classes e os mesmos stacks
    comprometidos até aqui.
  - Quando alguém fica all-in (nenhum dos dois tem mais fichas atrás)
    e ainda falta carta pra sair: não faz mais sentido amostrar (não
    tem mais decisão nenhuma pela frente) — o motor calcula a equity
    EXATA fazendo a média sobre TODAS as cartas que podem completar o
    board (sem amostragem, sem ruído — é rápido o suficiente pra
    river/turn, mais pesado pro flop com 2 cartas por vir).

Isso significa: passar um board de 5 cartas reproduz exatamente o
comportamento da v1 (RiverSolver = PostflopSolver com board completo,
nenhum nó de chance é criado). Passar um board de 4 cartas resolve o
TURN de verdade. Passar um board de 3 cartas resolve o FLOP — funciona
pela mesma lógica, mas é MUITO mais pesado (a equity all-in precisa
enumerar turn x river = ~2300 combinações por par de classes) e não
foi validado num spot real ainda (ver README).

Limitação NOVA desta v2 (documentada, no mesmo espírito das outras):
a carta sorteada nos nós de chance ignora blockers entre ela e as
mãos específicas de herói/vilão (só evita colidir com o board) — a
abstração é por classe, não por combo, então não dá pra saber ainda
quais cartas exatas cada jogador segura nesse ponto da árvore.

Abstração por classe de mão e árvore de apostas (check/bet ->
fold/call/raise-all-in -> fold/call) seguem exatamente como
documentado antes — ver o resto deste docstring nas versões
anteriores do arquivo / README.
"""

import itertools
import random
import sys
from pathlib import Path

from treys import Card, Evaluator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.cfr_core import DiscountedCFRTrainer  # noqa: E402
from engine.hand_classes import all_hand_classes  # noqa: E402

EVALUATOR = Evaluator()
RANKS = "AKQJT98765432"
SUITS = "shdc"


def parse_board(board) -> list:
    """Aceita 'AhKd7s2c9h', 'Ah Kd 7s 2c 9h' ou lista ['Ah','Kd',...].
    Retorna lista de strings de carta de 2 chars (rank+naipe). Aceita
    3 (flop), 4 (turn) ou 5 (river) cartas."""
    if isinstance(board, str):
        board = board.replace(" ", "")
        cards = [board[i:i + 2] for i in range(0, len(board), 2)]
    else:
        cards = list(board)
    if len(set(cards)) != len(cards):
        raise ValueError(f"board com cartas repetidas: {cards}")
    if len(cards) not in (3, 4, 5):
        raise ValueError(f"board precisa ter 3 (flop), 4 (turn) ou 5 (river) cartas, recebeu {len(cards)}")
    return cards


def expand_class_combos(hand_class: str, dead_cards) -> list:
    """Todos os combos reais (cartas com naipe) de uma classe, excluindo
    qualquer combo que use uma carta já no board (ou outra carta morta)."""
    dead = set(dead_cards)
    if len(hand_class) == 2:  # par, ex 'AA'
        r = hand_class[0]
        cards = [r + s for s in SUITS if r + s not in dead]
        return list(itertools.combinations(cards, 2))

    r1, r2, suited = hand_class[0], hand_class[1], hand_class[2] == "s"
    combos = []
    if suited:
        for s in SUITS:
            c1, c2 = r1 + s, r2 + s
            if c1 not in dead and c2 not in dead:
                combos.append((c1, c2))
    else:
        for s1 in SUITS:
            for s2 in SUITS:
                if s1 == s2:
                    continue
                c1, c2 = r1 + s1, r2 + s2
                if c1 not in dead and c2 not in dead:
                    combos.append((c1, c2))
    return combos


def class_pair_win_prob(ca, cb, board5, cache=None):
    """Probabilidade de `ca` vencer o showdown contra `cb` num board
    COMPLETO (5 cartas), media sobre todos os pares de combos validos
    (sem conflito de carta entre board/herói/vilão). None se não
    existir nenhum par valido (classe totalmente bloqueada pelo
    board). `board5`: tupla de 5 strings de carta. Determinístico
    (sem Monte Carlo) — cacheável com segurança."""
    key = (ca, cb, board5)
    if cache is not None and key in cache:
        return cache[key]

    dead = set(board5)
    combos_a = expand_class_combos(ca, dead)
    combos_b = expand_class_combos(cb, dead)
    board_int = [Card.new(c) for c in board5]

    rank_cache = {}

    def get_rank(combo):
        if combo not in rank_cache:
            cards = [Card.new(combo[0]), Card.new(combo[1])]
            rank_cache[combo] = EVALUATOR.evaluate(board_int, cards)
        return rank_cache[combo]

    total, n = 0.0, 0
    for combo_a in combos_a:
        set_a = set(combo_a)
        ra = get_rank(combo_a)
        for combo_b in combos_b:
            if set_a & set(combo_b):
                continue
            rb = get_rank(combo_b)
            if ra < rb:  # treys: menor = melhor
                total += 1.0
            elif ra == rb:
                total += 0.5
            n += 1

    result = (total / n) if n > 0 else None
    if cache is not None:
        cache[key] = result
    return result


def runout_equity(ca, cb, board_partial, cache_runout=None, cache_showdown=None):
    """Equity EXATA (sem amostragem) de `ca` vs `cb`, com o board ainda
    incompleto (3 ou 4 cartas) -- media sobre TODAS as cartas que
    podem completar o board até 5. Usado só quando ninguém tem mais
    decisão pela frente (all-in). `board_partial`: tupla de 3 ou 4
    strings de carta."""
    if len(board_partial) == 5:
        return class_pair_win_prob(ca, cb, board_partial, cache_showdown)

    key = (ca, cb, board_partial)
    if cache_runout is not None and key in cache_runout:
        return cache_runout[key]

    dead = set(board_partial)
    total, n = 0.0, 0
    for r in RANKS:
        for s in SUITS:
            card = r + s
            if card in dead:
                continue
            val = runout_equity(ca, cb, board_partial + (card,), cache_runout, cache_showdown)
            if val is not None:
                total += val
                n += 1

    result = (total / n) if n > 0 else None
    if cache_runout is not None:
        cache_runout[key] = result
    return result


class PostflopSolver:
    """CFR exato sobre classes de mão (full-enumeration entre classes,
    sem amostragem) + nós de chance pra cartas ainda não reveladas
    (amostrados via MCCFR, exceto quando ambos ficam all-in, caso em
    que a equity de "correr o board" é calculada exata). Reaproveita o
    núcleo genérico de regret matching (`cfr_core`).

    board de 5 cartas -> resolve só o RIVER (validado, ver
    tests/postflop_river.py). board de 4 -> resolve o TURN (mais uma
    rua de aposta + a carta do river por vir). board de 3 -> resolve o
    FLOP (mais pesado, não validado ainda -- ver README).
    """

    def __init__(self, board, range_oop: dict, range_ip: dict, pot: float,
                 stack_oop: float, stack_ip: float, bet_sizes=(0.33, 0.75, 1.5), seed=42):
        self.board0 = tuple(parse_board(board))
        self.pot0 = pot
        self.stack_oop = stack_oop
        self.stack_ip = stack_ip
        self.bet_sizes = list(bet_sizes)
        self.rng = random.Random(seed)

        classes = all_hand_classes()
        combos0 = {c: expand_class_combos(c, self.board0) for c in classes}

        self.classes_oop = [c for c in classes if combos0[c] and range_oop.get(c, 0.0) > 0.0]
        self.classes_ip = [c for c in classes if combos0[c] and range_ip.get(c, 0.0) > 0.0]
        if not self.classes_oop or not self.classes_ip:
            raise ValueError("range vazio (ou totalmente bloqueado pelo board) pra OOP ou IP")

        def weights(range_dict, cls_list):
            raw = {c: range_dict[c] * len(combos0[c]) for c in cls_list}
            total = sum(raw.values())
            return {c: w / total for c, w in raw.items()}

        self.w_oop = weights(range_oop, self.classes_oop)
        self.w_ip = weights(range_ip, self.classes_ip)

        self.trainer = DiscountedCFRTrainer()
        self._showdown_cache = {}
        self._runout_cache = {}

    # ---- pote/showdown/chance ----

    @staticmethod
    def _terminal_fold(folder, committed_oop, committed_ip, pot0):
        pot_total = pot0 + committed_oop + committed_ip
        if folder == "oop":
            return -committed_oop, pot_total - committed_ip
        return pot_total - committed_oop, -committed_ip

    def _end_of_action(self, ca, cb, committed_oop, committed_ip, p_oop, p_ip, board, prefix):
        """Chamado sempre que a rodada de apostas da rua atual termina
        sem fold (check-check, ou call que não usa raise). Três casos:
        board ja completo -> showdown exato; alguem all-in com board
        incompleto -> equity exata de "correr o board"; caso contrario
        -> sorteia a proxima carta e segue pra proxima rua."""
        if len(board) == 5:
            result = class_pair_win_prob(ca, cb, board, self._showdown_cache)
            pot_total = self.pot0 + committed_oop + committed_ip
            if result is None:
                return 0.0, 0.0
            return pot_total * result - committed_oop, pot_total * (1 - result) - committed_ip

        remaining_oop = self.stack_oop - committed_oop
        remaining_ip = self.stack_ip - committed_ip
        if remaining_oop <= 1e-9 or remaining_ip <= 1e-9:
            result = runout_equity(ca, cb, board, self._runout_cache, self._showdown_cache)
            pot_total = self.pot0 + committed_oop + committed_ip
            if result is None:
                return 0.0, 0.0
            return pot_total * result - committed_oop, pot_total * (1 - result) - committed_ip

        deck = [r + s for r in RANKS for s in SUITS if (r + s) not in set(board)]
        card = self.rng.choice(deck)
        new_board = board + (card,)
        return self._node_bet_or_check(
            "oop", ca, cb, committed_oop, committed_ip, p_oop, p_ip,
            prefix + f"|deal{card}", is_second=False, board=new_board,
        )

    # ---- árvore ----

    def _node_facing_raise(self, bettor, ca, cb, bet_amt, raise_to,
                            committed_oop, committed_ip, p_oop, p_ip, board, prefix):
        """`bettor` (quem apostou originalmente) decide fold/call contra o
        raise. Call é limitado ao stack do bettor (uncalled excess volta
        pro raiser, regra padrão)."""
        is_oop = bettor == "oop"
        own_class = ca if is_oop else cb
        own_stack = self.stack_oop if is_oop else self.stack_ip
        matched = min(own_stack, raise_to)

        key = f"{prefix}|facing_raise|{bettor}|{own_class}"
        infoset = self.trainer.get_infoset(key, n_actions=2)
        own_p = p_oop if is_oop else p_ip
        strat = infoset.get_strategy(own_p)

        folder = "oop" if is_oop else "ip"
        u_fold = self._terminal_fold(folder, bet_amt, bet_amt, self.pot0)
        u_call = self._end_of_action(ca, cb, matched, matched, p_oop, p_ip, board, prefix + "|allin")

        node_oop = strat[0] * u_fold[0] + strat[1] * u_call[0]
        node_ip = strat[0] * u_fold[1] + strat[1] * u_call[1]
        own_util_fold = u_fold[0] if is_oop else u_fold[1]
        own_util_call = u_call[0] if is_oop else u_call[1]
        own_node = node_oop if is_oop else node_ip

        opp_p = p_ip if is_oop else p_oop
        infoset.regret_sum[0] += opp_p * (own_util_fold - own_node)
        infoset.regret_sum[1] += opp_p * (own_util_call - own_node)

        return node_oop, node_ip

    def _node_facing_bet(self, bettor, ca, cb, bet_amt, committed_oop, committed_ip,
                          p_oop, p_ip, board, prefix):
        """`responder` (o outro jogador) decide fold/call/raise contra a
        aposta de `bettor`."""
        responder = "ip" if bettor == "oop" else "oop"
        is_resp_oop = responder == "oop"
        own_class = ca if is_resp_oop else cb
        own_stack = self.stack_oop if is_resp_oop else self.stack_ip
        own_committed = committed_oop if is_resp_oop else committed_ip
        raise_legal = (own_stack - own_committed - bet_amt) > 1e-9

        n_actions = 3 if raise_legal else 2
        key = f"{prefix}|facing_bet|{responder}|{own_class}"
        infoset = self.trainer.get_infoset(key, n_actions=n_actions)
        own_p = p_oop if is_resp_oop else p_ip
        strat = infoset.get_strategy(own_p)

        new_committed_oop = committed_oop + (bet_amt if bettor == "oop" else 0)
        new_committed_ip = committed_ip + (bet_amt if bettor == "ip" else 0)

        u_fold = self._terminal_fold(responder, new_committed_oop, new_committed_ip, self.pot0)

        call_committed_oop = new_committed_oop + (bet_amt if is_resp_oop else 0)
        call_committed_ip = new_committed_ip + (bet_amt if not is_resp_oop else 0)
        u_call = self._end_of_action(ca, cb, call_committed_oop, call_committed_ip, p_oop, p_ip, board, prefix + "|call")

        if raise_legal:
            raise_to = own_stack  # all-in
            new_p_oop = p_oop * strat[2] if is_resp_oop else p_oop
            new_p_ip = p_ip * strat[2] if not is_resp_oop else p_ip
            u_raise = self._node_facing_raise(
                bettor, ca, cb, bet_amt, raise_to,
                new_committed_oop, new_committed_ip, new_p_oop, new_p_ip, board, prefix,
            )
        else:
            u_raise = (0.0, 0.0)

        node_oop = strat[0] * u_fold[0] + strat[1] * u_call[0] + (strat[2] * u_raise[0] if raise_legal else 0.0)
        node_ip = strat[0] * u_fold[1] + strat[1] * u_call[1] + (strat[2] * u_raise[1] if raise_legal else 0.0)

        own_util = [
            u_fold[0] if is_resp_oop else u_fold[1],
            u_call[0] if is_resp_oop else u_call[1],
        ]
        if raise_legal:
            own_util.append(u_raise[0] if is_resp_oop else u_raise[1])
        own_node = node_oop if is_resp_oop else node_ip

        opp_p = p_ip if is_resp_oop else p_oop
        for a in range(n_actions):
            infoset.regret_sum[a] += opp_p * (own_util[a] - own_node)

        return node_oop, node_ip

    def _node_bet_or_check(self, actor, ca, cb, committed_oop, committed_ip,
                            p_oop, p_ip, prefix, is_second, board):
        """`actor` decide check ou bet(tamanho). `is_second`=True quando
        já é a resposta a um check anterior (check aqui -> fim da rua)."""
        is_oop = actor == "oop"
        own_class = ca if is_oop else cb
        n_actions = 1 + len(self.bet_sizes)
        key = f"{prefix}|bet_or_check|{actor}|{own_class}"
        infoset = self.trainer.get_infoset(key, n_actions=n_actions)
        own_p = p_oop if is_oop else p_ip
        strat = infoset.get_strategy(own_p)

        # acao 0: check
        if is_second:
            u_check = self._end_of_action(ca, cb, committed_oop, committed_ip, p_oop, p_ip, board, prefix + "|xx")
        else:
            new_p_oop = p_oop * strat[0] if is_oop else p_oop
            new_p_ip = p_ip * strat[0] if not is_oop else p_ip
            other = "ip" if is_oop else "oop"
            u_check = self._node_bet_or_check(
                other, ca, cb, committed_oop, committed_ip, new_p_oop, new_p_ip,
                prefix + "-x", is_second=True, board=board,
            )

        util_by_action = [u_check]
        own_stack = self.stack_oop if is_oop else self.stack_ip
        own_committed = committed_oop if is_oop else committed_ip
        current_pot = self.pot0 + committed_oop + committed_ip
        remaining = own_stack - own_committed

        for idx, size in enumerate(self.bet_sizes):
            bet_amt = min(size * current_pot, remaining)
            if bet_amt <= 1e-9:
                util_by_action.append((0.0, 0.0))
                continue
            new_p_oop = p_oop * strat[1 + idx] if is_oop else p_oop
            new_p_ip = p_ip * strat[1 + idx] if not is_oop else p_ip
            u_bet = self._node_facing_bet(
                actor, ca, cb, bet_amt, committed_oop, committed_ip,
                new_p_oop, new_p_ip, board, prefix + f"-b{idx}",
            )
            util_by_action.append(u_bet)

        node_oop = sum(strat[a] * util_by_action[a][0] for a in range(n_actions))
        node_ip = sum(strat[a] * util_by_action[a][1] for a in range(n_actions))
        own_node = node_oop if is_oop else node_ip

        opp_p = p_ip if is_oop else p_oop
        for a in range(n_actions):
            own_util_a = util_by_action[a][0] if is_oop else util_by_action[a][1]
            infoset.regret_sum[a] += opp_p * (own_util_a - own_node)

        return node_oop, node_ip

    # ---- treino ----

    def train(self, iterations=2000):
        for t in range(1, iterations + 1):
            for ca in self.classes_oop:
                p_oop = self.w_oop[ca]
                for cb in self.classes_ip:
                    p_ip = self.w_ip[cb]
                    self._node_bet_or_check(
                        "oop", ca, cb, 0.0, 0.0, p_oop, p_ip, "", is_second=False, board=self.board0,
                    )
            self.trainer.discount(t)
        self.trainer.finalize()

    def strategy(self, actor, node="root", hand_class=None):
        """Acesso à estratégia média de um infoset especifico. `node`:
        'root' (bet_or_check na raiz), 'facing_check' (bet_or_check apos
        oponente checkar), ou uma key completa (avancado)."""
        prefix_map = {"root": "", "facing_check": "-x"}
        if node in prefix_map:
            key = f"{prefix_map[node]}|bet_or_check|{actor}|{hand_class}"
        else:
            key = node
        if key not in self.trainer.infosets:
            return None
        return self.trainer.infosets[key].get_average_strategy()

    def facing_bet_strategy(self, bettor, bet_idx, responder_class, after_check=False):
        """Estrategia media de quem RESPONDE a uma aposta (fold/call ou
        fold/call/raise) -- ex: facing_bet_strategy('oop', 0, 'QQ') = a
        decisao da IP contra o bet_sizes[0] da OOP na raiz.
        after_check=True: quando o bet aconteceu depois de um check
        anterior (ex: OOP checkou, IP apostou, OOP decide agora)."""
        prefix = f"-x-b{bet_idx}" if after_check else f"-b{bet_idx}"
        responder = "ip" if bettor == "oop" else "oop"
        key = f"{prefix}|facing_bet|{responder}|{responder_class}"
        if key not in self.trainer.infosets:
            return None
        return self.trainer.infosets[key].get_average_strategy()

    def facing_raise_strategy(self, bettor, bet_idx, bettor_class, after_check=False):
        """Estrategia media de quem apostou originalmente e agora decide
        fold/call contra um raise -- ex: facing_raise_strategy('oop', 0,
        'AA') = a decisao da OOP com AA depois de apostar bet_sizes[0]
        na raiz e a IP dar raise. after_check: quando quem apostou foi
        a IP depois de a OOP checkar (raise ali é decisao da OOP)."""
        prefix = f"-x-b{bet_idx}" if after_check else f"-b{bet_idx}"
        key = f"{prefix}|facing_raise|{bettor}|{bettor_class}"
        if key not in self.trainer.infosets:
            return None
        return self.trainer.infosets[key].get_average_strategy()

    def average_strategy_root(self):
        """Estrategia media na raiz (check vs cada tamanho de bet) pra
        cada classe de cada jogador -- visao rapida do range de bet."""
        out = {"oop": {}, "ip": {}}
        for c in self.classes_oop:
            s = self.strategy("oop", "root", c)
            if s:
                out["oop"][c] = {"check": s[0], **{f"bet_{self.bet_sizes[i]}": s[1 + i] for i in range(len(self.bet_sizes))}}
        for c in self.classes_ip:
            s = self.strategy("ip", "facing_check", c)
            if s:
                out["ip"][c] = {"check": s[0], **{f"bet_{self.bet_sizes[i]}": s[1 + i] for i in range(len(self.bet_sizes))}}
        return out

    def _showdown_result(self, ca, cb, board):
        """Despacha pra equity exata: board completo -> class_pair_win_prob
        (5 cartas fixas); board incompleto -> runout_equity (media exata
        sobre TODAS as cartas que faltam, sem amostragem). Ambas devolvem
        P(ca vence) na mesma convencao (None se par de classes bloqueado)."""
        if len(board) == 5:
            return class_pair_win_prob(ca, cb, board, self._showdown_cache)
        return runout_equity(ca, cb, board, self._runout_cache, self._showdown_cache)

    def _showdown_util_board(self, ca, cb, committed_oop, committed_ip, board):
        """Generalizacao de _showdown_util pra qualquer board (completo ou
        nao) -- mesma formula de pote usada em _end_of_action."""
        result = self._showdown_result(ca, cb, board)
        pot_total = self.pot0 + committed_oop + committed_ip
        if result is None:
            return 0.0, 0.0
        return pot_total * result - committed_oop, pot_total * (1 - result) - committed_ip

    def compute_exploitability(self):
        """Best-response exato (sem amostragem), agora generalizado pra
        qualquer board (river/turn/flop). Retorna (br_oop, br_ip,
        exploitability):
          - br_oop/br_ip: valor que cada jogador consegue ganhar jogando
            a MELHOR resposta possível contra a estratégia média (já
            treinada) fixa do oponente.
          - exploitability = (br_oop + br_ip) - pot0. IMPORTANTE: por
            causa da convenção de contabilidade usada em todo o motor
            (utility = pote_total*resultado - comprometido_proprio),
            br_oop + br_ip soma pot0 em QUALQUER terminal (não soma 0
            como em kuhn_poker.py/rfi_jam.py) -- é so subtrair a
            constante pra recuperar a mesma leitura de sempre:
            exploitability -> 0 significa equilíbrio de Nash."""
        br_oop = self._best_response("oop")
        br_ip = self._best_response("ip")
        return br_oop, br_ip, (br_oop + br_ip - self.pot0)

    def _br_showdown_value(self, br, own_class, opp_class, committed_oop, committed_ip, board):
        """Valor de showdown pra `br` (own_class fixa, opp_class fixa),
        na convencao oop/ip usada em todo o motor."""
        if br == "oop":
            ca, cb = own_class, opp_class
        else:
            ca, cb = opp_class, own_class
        u_oop, u_ip = self._showdown_util_board(ca, cb, committed_oop, committed_ip, board)
        return u_oop if br == "oop" else u_ip

    def _br_end_of_action(self, br, own_class, committed_oop, committed_ip, opp_reach, board, prefix):
        """Espelha _end_of_action, mas devolve a soma PONDERADA (por
        opp_reach, nao normalizada) do valor pra `br`, e usa enumeracao
        EXATA (nao amostragem) no no de chance -- e' so' aqui que a
        diferenca entre treino (MCCFR, 1 carta por iteracao) e
        best-response (exato, todas as cartas) realmente importa."""
        remaining_oop = self.stack_oop - committed_oop
        remaining_ip = self.stack_ip - committed_ip
        if len(board) == 5 or remaining_oop <= 1e-9 or remaining_ip <= 1e-9:
            return sum(
                w * self._br_showdown_value(br, own_class, opp_class, committed_oop, committed_ip, board)
                for opp_class, w in opp_reach.items()
                if w != 0
            )
        deck = [r + s for r in RANKS for s in SUITS if (r + s) not in set(board)]
        total = 0.0
        for card in deck:
            new_board = board + (card,)
            total += self._br_bet_or_check(
                br, "oop", own_class, committed_oop, committed_ip, opp_reach,
                new_board, prefix + f"|deal{card}", is_second=False,
            )
        return total / len(deck)

    def _br_facing_raise(self, br, bettor, own_class, bet_amt, raise_to,
                          committed_oop, committed_ip, opp_reach, board, prefix):
        """Espelha _node_facing_raise. `bettor` decide fold/call contra o
        raise -- se bettor==br, e' decisao de `br` (pega o maximo); senao
        e' o oponente (le a estrategia media treinada, por classe)."""
        u_fold_pair = self._terminal_fold(bettor, bet_amt, bet_amt, self.pot0)
        u_fold_for_br = u_fold_pair[0] if br == "oop" else u_fold_pair[1]

        if bettor == br:
            own_stack = self.stack_oop if br == "oop" else self.stack_ip
            matched = min(own_stack, raise_to)
            total_reach = sum(opp_reach.values())
            u_call = self._br_end_of_action(br, own_class, matched, matched, opp_reach, board, prefix + "|allin")
            return max(u_fold_for_br * total_reach, u_call)

        opp_stack = self.stack_oop if bettor == "oop" else self.stack_ip
        matched = min(opp_stack, raise_to)
        fold_reach_total = 0.0
        call_reach = {}
        for c, w in opp_reach.items():
            if w == 0:
                continue
            key = f"{prefix}|facing_raise|{bettor}|{c}"
            if key not in self.trainer.infosets:
                continue  # infoset nunca visitado no treino -- exclui (nao "chuta" fold nem call)
            strat = self.trainer.infosets[key].get_average_strategy()
            fold_reach_total += w * strat[0]
            if strat[1] > 0:
                call_reach[c] = w * strat[1]
        total = fold_reach_total * u_fold_for_br
        if call_reach:
            total += self._br_end_of_action(br, own_class, matched, matched, call_reach, board, prefix + "|allin")
        return total

    def _br_facing_bet(self, br, bettor, own_class, bet_amt, committed_oop, committed_ip,
                        opp_reach, board, prefix):
        """Espelha _node_facing_bet. `responder` (o outro jogador em
        relacao a `bettor`) decide fold/call/raise -- mesma logica de
        despacho br-decide vs oponente-decide de _br_facing_raise."""
        responder = "ip" if bettor == "oop" else "oop"
        new_committed_oop = committed_oop + (bet_amt if bettor == "oop" else 0)
        new_committed_ip = committed_ip + (bet_amt if bettor == "ip" else 0)
        u_fold_pair = self._terminal_fold(responder, new_committed_oop, new_committed_ip, self.pot0)
        u_fold_for_br = u_fold_pair[0] if br == "oop" else u_fold_pair[1]

        call_committed_oop = new_committed_oop + (bet_amt if responder == "oop" else 0)
        call_committed_ip = new_committed_ip + (bet_amt if responder == "ip" else 0)

        if responder == br:
            own_stack = self.stack_oop if br == "oop" else self.stack_ip
            own_committed = committed_oop if br == "oop" else committed_ip
            raise_legal = (own_stack - own_committed - bet_amt) > 1e-9
            total_reach = sum(opp_reach.values())
            u_call = self._br_end_of_action(
                br, own_class, call_committed_oop, call_committed_ip, opp_reach, board, prefix + "|call",
            )
            best = max(u_fold_for_br * total_reach, u_call)
            if raise_legal:
                raise_to = own_stack
                u_raise = self._br_facing_raise(
                    br, bettor, own_class, bet_amt, raise_to,
                    new_committed_oop, new_committed_ip, opp_reach, board, prefix,
                )
                best = max(best, u_raise)
            return best

        opp = responder
        opp_stack = self.stack_oop if opp == "oop" else self.stack_ip
        opp_committed = committed_oop if opp == "oop" else committed_ip
        raise_legal = (opp_stack - opp_committed - bet_amt) > 1e-9
        fold_reach_total = 0.0
        call_reach = {}
        raise_reach = {}
        for c, w in opp_reach.items():
            if w == 0:
                continue
            key = f"{prefix}|facing_bet|{opp}|{c}"
            if key not in self.trainer.infosets:
                continue
            strat = self.trainer.infosets[key].get_average_strategy()
            fold_reach_total += w * strat[0]
            if strat[1] > 0:
                call_reach[c] = w * strat[1]
            if raise_legal and len(strat) > 2 and strat[2] > 0:
                raise_reach[c] = w * strat[2]
        total = fold_reach_total * u_fold_for_br
        if call_reach:
            total += self._br_end_of_action(
                br, own_class, call_committed_oop, call_committed_ip, call_reach, board, prefix + "|call",
            )
        if raise_reach:
            raise_to = opp_stack
            total += self._br_facing_raise(
                br, bettor, own_class, bet_amt, raise_to,
                new_committed_oop, new_committed_ip, raise_reach, board, prefix,
            )
        return total

    def _br_bet_or_check(self, br, actor, own_class, committed_oop, committed_ip,
                          opp_reach, board, prefix, is_second):
        """Espelha _node_bet_or_check. `actor` decide check ou bet(tamanho)
        -- br-decide (maximo) vs oponente-decide (le estrategia media,
        divide opp_reach por acao)."""
        if actor == br:
            if is_second:
                u_check = self._br_end_of_action(br, own_class, committed_oop, committed_ip, opp_reach, board, prefix + "|xx")
            else:
                other = "ip" if actor == "oop" else "oop"
                u_check = self._br_bet_or_check(
                    br, other, own_class, committed_oop, committed_ip, opp_reach, board, prefix + "-x", is_second=True,
                )
            best = u_check
            own_stack = self.stack_oop if actor == "oop" else self.stack_ip
            own_committed = committed_oop if actor == "oop" else committed_ip
            current_pot = self.pot0 + committed_oop + committed_ip
            remaining = own_stack - own_committed
            for idx, size in enumerate(self.bet_sizes):
                bet_amt = min(size * current_pot, remaining)
                if bet_amt <= 1e-9:
                    continue
                u_bet = self._br_facing_bet(
                    br, actor, own_class, bet_amt, committed_oop, committed_ip, opp_reach, board, prefix + f"-b{idx}",
                )
                if u_bet > best:
                    best = u_bet
            return best

        opp = actor
        check_reach = {}
        bet_reach = [dict() for _ in self.bet_sizes]
        for c, w in opp_reach.items():
            if w == 0:
                continue
            key = f"{prefix}|bet_or_check|{opp}|{c}"
            if key not in self.trainer.infosets:
                continue
            strat = self.trainer.infosets[key].get_average_strategy()
            if strat[0] > 0:
                check_reach[c] = w * strat[0]
            for idx in range(len(self.bet_sizes)):
                if strat[1 + idx] > 0:
                    bet_reach[idx][c] = w * strat[1 + idx]

        total = 0.0
        if check_reach:
            if is_second:
                total += self._br_end_of_action(br, own_class, committed_oop, committed_ip, check_reach, board, prefix + "|xx")
            else:
                other = "ip" if opp == "oop" else "oop"
                total += self._br_bet_or_check(
                    br, other, own_class, committed_oop, committed_ip, check_reach, board, prefix + "-x", is_second=True,
                )

        own_stack = self.stack_oop if opp == "oop" else self.stack_ip
        own_committed = committed_oop if opp == "oop" else committed_ip
        current_pot = self.pot0 + committed_oop + committed_ip
        remaining = own_stack - own_committed
        for idx, size in enumerate(self.bet_sizes):
            if not bet_reach[idx]:
                continue
            bet_amt = min(size * current_pot, remaining)
            if bet_amt <= 1e-9:
                continue
            total += self._br_facing_bet(
                br, opp, own_class, bet_amt, committed_oop, committed_ip, bet_reach[idx], board, prefix + f"-b{idx}",
            )
        return total

    def _best_response(self, br):
        """Fixa a estrategia media do OPONENTE (ja treinada) e calcula o
        valor da melhor resposta possivel de `br` contra ela, respeitando
        infosets (mesma acao por classe -- nao pode "ver" a classe exata
        do oponente e escolher acao diferente pra cada uma).

        Reescrita (2026-08) como recursao completa que espelha a arvore
        de treino (_node_bet_or_check/_node_facing_bet/_node_facing_raise/
        _end_of_action), em vez da versao anterior que so' cobria river
        (3 niveis fixos, sem no de chance). `opp_reach` carrega o peso
        (nao normalizado) de cada classe do oponente dado o caminho
        percorrido ate' aqui -- cada funcao devolve a soma ponderada do
        valor pra `br` (nao o valor medio), entao o total no topo ja' sai
        certo sem precisar renormalizar (w_opp soma 1 no inicio).

        Infoset nunca visitado no treino (comum no flop, onde a amostra
        de 1 carta/iteracao so' cobre uma fracao das ~2000 combinacoes
        possiveis de turn+river): a classe correspondente e' EXCLUIDA do
        calculo (peso zero) em vez de assumir um comportamento padrao
        (tipo "sempre folda") -- evita viesar o resultado numa direcao
        sem justificativa. Ver README sobre essa decisao."""
        br_classes = self.classes_oop if br == "oop" else self.classes_ip
        opp_classes = self.classes_ip if br == "oop" else self.classes_oop
        w_br = self.w_oop if br == "oop" else self.w_ip
        w_opp = self.w_ip if br == "oop" else self.w_oop

        total = 0.0
        for ca in br_classes:
            opp_reach = {c: w_opp[c] for c in opp_classes}
            val = self._br_bet_or_check(br, "oop", ca, 0.0, 0.0, opp_reach, self.board0, "", is_second=False)
            total += w_br[ca] * val
        return total


# Compatibilidade com o nome usado na v1 (river-only) -- um board de 5
# cartas nunca dispara nó de chance, então o comportamento é idêntico.
RiverSolver = PostflopSolver


if __name__ == "__main__":
    # Spot de exemplo no TURN: falta a carta do river. Board seco,
    # range da OOP polarizada (nuts + air), range da IP so com
    # bluff-catchers medios.
    board = "Ah Kd 7s 2c"  # turn -- falta o river

    # blefes com ranks que NAO aparecem no board -- mesmo emparelhando
    # no river, viram so um par abaixo de QQ (nunca vencem o bluff-catcher)
    range_oop = {"AA": 1.0, "KK": 1.0, "93o": 1.0, "84o": 1.0}
    range_ip = {"QQ": 1.0}

    solver = PostflopSolver(
        board=board, range_oop=range_oop, range_ip=range_ip,
        pot=20.0, stack_oop=60.0, stack_ip=60.0, bet_sizes=(0.5,),
    )
    solver.train(iterations=3000)

    strat = solver.average_strategy_root()
    print(f"Board (turn, falta river): {board}")
    print("\n--- OOP (raiz: check vs bet) ---")
    for c in ["AA", "KK", "93o", "84o"]:
        if c in strat["oop"]:
            row = strat["oop"][c]
            print(f"  {c:5s} " + "  ".join(f"{k}={v:.2f}" for k, v in row.items()))

    qq = solver.facing_bet_strategy("oop", 0, "QQ")
    print(f"\nQQ (bluff-catcher) contra a aposta: fold={qq[0]:.3f} call={qq[1]:.3f}")
    expected = 20.0 / (20.0 + 0.5 * 20.0)
    print(f"MDF teorico (mesma logica do river, valor/blefe sempre vence/perde): {expected:.3f}")
