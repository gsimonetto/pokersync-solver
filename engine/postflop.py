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

    def _showdown_util(self, ca, cb, committed_oop, committed_ip):
        """Mesma formula usada durante o treino (_end_of_action, board
        completo) -- reaproveitada aqui pra evitar duplicar a aritmetica
        de pote/showdown num segundo lugar."""
        result = class_pair_win_prob(ca, cb, self.board0, self._showdown_cache)
        pot_total = self.pot0 + committed_oop + committed_ip
        if result is None:
            return 0.0, 0.0
        return pot_total * result - committed_oop, pot_total * (1 - result) - committed_ip

    def compute_exploitability(self):
        """Best-response exato (sem amostragem) -- só implementado pro
        RIVER (board completo, sem nó de chance) por enquanto; turn/flop
        exigiriam enumerar exatamente os nós de chance, o que fica pra
        depois. Retorna (br_oop, br_ip, exploitability):
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
        if len(self.board0) != 5:
            raise NotImplementedError(
                "exploitability exata só implementada pro river (board de 5 cartas, sem nó de chance) por enquanto"
            )
        br_oop = self._best_response("oop")
        br_ip = self._best_response("ip")
        return br_oop, br_ip, (br_oop + br_ip - self.pot0)

    def _best_response(self, br):
        """Fixa a estratégia média do OPONENTE (já treinada) e calcula o
        valor da melhor resposta possível de `br` contra ela, respeitando
        infosets (mesma ação por classe -- não pode "ver" a classe exata
        do oponente e escolher ação diferente pra cada uma).

        Ordem de resolução (mesmo cuidado de kuhn_poker.py/rfi_jam.py):
        primeiro as decisões MAIS PROFUNDAS de `br` -- facing_raise (br
        apostou no seu nó de "primeiro a agir": raiz se br=oop, ou
        facing_check se br=ip; oponente deu raise; br decide fold/call)
        e facing_bet (oponente apostou no nó dele de "primeiro a agir";
        br decide fold/call/raise) -- nenhuma delas depende da outra,
        só da estratégia fixa do oponente. Só DEPOIS disso dá pra
        calcular a decisão mais rasa (bet_or_check), que pode recair em
        qualquer uma das duas."""
        opp = "ip" if br == "oop" else "oop"
        br_classes = self.classes_oop if br == "oop" else self.classes_ip
        opp_classes = self.classes_ip if br == "oop" else self.classes_oop
        w_br = self.w_oop if br == "oop" else self.w_ip
        w_opp = self.w_ip if br == "oop" else self.w_oop
        br_stack = self.stack_oop if br == "oop" else self.stack_ip
        opp_stack = self.stack_ip if br == "oop" else self.stack_oop

        def showdown_util_br(a_br, a_opp, committed_br, committed_opp):
            if br == "oop":
                return self._showdown_util(a_br, a_opp, committed_br, committed_opp)[0]
            return self._showdown_util(a_opp, a_br, committed_opp, committed_br)[1]

        def fold_util_br(folder, committed_br, committed_opp):
            """folder: 'br' ou 'opp' (quem esta foldando). Retorna o
            valor resultante pra `br`."""
            key = "oop" if ((folder == "br" and br == "oop") or (folder == "opp" and opp == "oop")) else "ip"
            committed_oop = committed_br if br == "oop" else committed_opp
            committed_ip = committed_opp if br == "oop" else committed_br
            pair = self._terminal_fold(key, committed_oop, committed_ip, self.pot0)
            return pair[0] if br == "oop" else pair[1]

        raise_after_check = br == "ip"   # br aposta no facing_check (so ip tem esse no); oop aposta na raiz
        bet_after_check = br == "oop"    # br responde a bet -- oop so enfrenta bet depois de checkar

        # ---- nivel 1a: facing_raise de br (br apostou, oponente deu raise) ----
        fr_value = {}
        fr_action = {}
        for b, size in enumerate(self.bet_sizes):
            bet_amt = min(size * self.pot0, br_stack)
            raise_prob = {}
            any_raise = False
            for c in opp_classes:
                s = self.facing_bet_strategy(br, b, c, after_check=raise_after_check)
                if s is not None and len(s) > 2:
                    raise_prob[c] = s[2]
                    any_raise = True
                else:
                    raise_prob[c] = 0.0
            total_reach = sum(w_opp[c] * raise_prob[c] for c in opp_classes)
            for ca in br_classes:
                if not any_raise or total_reach <= 0:
                    fr_value[(b, ca)] = None
                    fr_action[(b, ca)] = None
                    continue
                matched = min(br_stack, opp_stack)
                ev_fold = fold_util_br("br", bet_amt, bet_amt)
                ev_call_num = sum(
                    w_opp[c] * raise_prob[c] * showdown_util_br(ca, c, matched, matched)
                    for c in opp_classes if raise_prob[c] > 0
                )
                ev_call = ev_call_num / total_reach
                if ev_call > ev_fold:
                    fr_action[(b, ca)] = "call"
                    fr_value[(b, ca)] = ev_call
                else:
                    fr_action[(b, ca)] = "fold"
                    fr_value[(b, ca)] = ev_fold

        # ---- nivel 1b: facing_bet de br (oponente apostou, br responde) ----
        fb_value = {}
        fb_action = {}
        for b, size in enumerate(self.bet_sizes):
            bet_amt = min(size * self.pot0, opp_stack)
            bet_prob = {}
            for c in opp_classes:
                s = self.strategy(opp, "facing_check" if bet_after_check else "root", c)
                bet_prob[c] = s[1 + b] if s else 0.0
            total_reach = sum(w_opp[c] * bet_prob[c] for c in opp_classes)
            raise_legal = (br_stack - bet_amt) > 1e-9
            for ca in br_classes:
                if total_reach <= 0:
                    fb_value[(b, ca)] = None
                    fb_action[(b, ca)] = None
                    continue
                # br ainda nao comprometeu nada nessa rodada -- quem apostou foi o oponente
                ev_fold = fold_util_br("br", 0.0, bet_amt)
                ev_call_num = sum(
                    w_opp[c] * bet_prob[c] * showdown_util_br(ca, c, bet_amt, bet_amt)
                    for c in opp_classes if bet_prob[c] > 0
                )
                ev_call = ev_call_num / total_reach
                best_val, best_act = (ev_fold, "fold") if ev_fold >= ev_call else (ev_call, "call")
                if raise_legal:
                    matched = min(br_stack, opp_stack)
                    opp_fold_prob, opp_call_prob = {}, {}
                    for c in opp_classes:
                        s = self.facing_raise_strategy(opp, b, c, after_check=bet_after_check)
                        opp_fold_prob[c] = s[0] if s else 1.0
                        opp_call_prob[c] = s[1] if s else 0.0
                    ev_raise_num = 0.0
                    for c in opp_classes:
                        w = w_opp[c] * bet_prob[c]
                        if w <= 0:
                            continue
                        # oponente folda pro raise de br: contabilidade usa o bet_amt
                        # ORIGINAL (nao o valor do raise) -- o excedente nao pago do
                        # raise volta pra br, mesma regra usada no treino
                        # (_node_facing_raise -- ver docstring do modulo)
                        v_fold_br = fold_util_br("opp", bet_amt, bet_amt)
                        v_call_br = showdown_util_br(ca, c, matched, matched)
                        ev_raise_num += w * (opp_fold_prob[c] * v_fold_br + opp_call_prob[c] * v_call_br)
                    ev_raise = ev_raise_num / total_reach
                    if ev_raise > best_val:
                        best_val, best_act = ev_raise, "raise"
                fb_value[(b, ca)] = best_val
                fb_action[(b, ca)] = best_act

        # ---- nivel 2: bet_or_check de br (raiz se br=oop, facing_check se br=ip) ----
        total = 0.0
        for ca in br_classes:
            ev_check = 0.0
            for c in opp_classes:
                s = self.strategy(opp, "facing_check" if br == "oop" else "root", c)
                if s is None:
                    continue
                w = w_opp[c]
                check_prob = s[0]
                ev_check += w * check_prob * showdown_util_br(ca, c, 0.0, 0.0)
                for b in range(len(self.bet_sizes)):
                    bp = s[1 + b]
                    if bp <= 0:
                        continue
                    val = fb_value.get((b, ca))
                    if val is not None:
                        ev_check += w * bp * val
            best_val = ev_check
            for b, size in enumerate(self.bet_sizes):
                bet_amt = min(size * self.pot0, br_stack)
                fold_prob, call_prob, raise_prob = {}, {}, {}
                for c in opp_classes:
                    s = self.facing_bet_strategy(br, b, c, after_check=raise_after_check)
                    if s is None:
                        fold_prob[c], call_prob[c], raise_prob[c] = 1.0, 0.0, 0.0
                    else:
                        fold_prob[c] = s[0]
                        call_prob[c] = s[1]
                        raise_prob[c] = s[2] if len(s) > 2 else 0.0
                ev_bet = 0.0
                # br apostou (comprometeu bet_amt); se o oponente folda, br
                # so tem seu proprio bet_amt em jogo (nao comprometeu nada extra)
                v_fold_br = fold_util_br("opp", bet_amt, 0.0)
                for c in opp_classes:
                    w = w_opp[c]
                    v_call = showdown_util_br(ca, c, bet_amt, bet_amt)
                    v_raise = fr_value.get((b, ca))
                    contrib = fold_prob[c] * v_fold_br + call_prob[c] * v_call
                    if raise_prob[c] > 0 and v_raise is not None:
                        contrib += raise_prob[c] * v_raise
                    elif raise_prob[c] > 0:
                        contrib += raise_prob[c] * v_call  # fallback (nao deveria ocorrer)
                    ev_bet += w * contrib
                if ev_bet > best_val:
                    best_val = ev_bet
            total += w_br[ca] * best_val
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
