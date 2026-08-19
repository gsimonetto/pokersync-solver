"""
Motor pós-flop — primeira rua real: RIVER heads-up.

Por que começar pelo river e não pelo flop: river não tem cartas por vir,
então dá pra resolver EXATO (sem Monte Carlo, sem chance node) — o board
já está 100% definido, então a força de cada mão é determinística. Isso
isola o problema novo (árvore de apostas pós-flop de verdade, com
tamanhos variáveis e range vs range) do problema de chance nodes
(turn/flop), que fica pra um próximo incremento (ver README).

Abstração usada (DELIBERADA, documentada — mesmo espírito da limitação
já registrada em hand_classes.py pro pré-flop): as decisões da árvore
são por CLASSE de mão (ex: 'AKs', 'T9o'), não por combo individual. A
força de cada classe nesse board específico, porém, É exata: cada
classe é expandida em todos os seus combos reais válidos (removendo
conflito com as cartas do board), avaliada com o avaliador de mão real
(treys) contra o board real, e o resultado classe-vs-classe é a MÉDIA
sobre todos os pares de combos válidos (sem conflito de carta entre
herói e vilão) — isso já captura efeito de blocker a nível de classe.
O que fica de fora nessa v1: dois combos da MESMA classe (ex AhKh vs
AsKs) são tratados como estrategicamente idênticos (mesma frequência
de bet/call) — não tem discriminação de blocker dentro da classe ainda.

Árvore modelada (heads-up, river, tamanhos de aposta configuráveis):
  OOP (fora de posição, age primeiro): check ou bet(tamanho s, fração do pote).
    bet -> IP: fold, call, ou raise (all-in, tamanho único — mesma
      simplificação já usada no pré-flop pra 3-bet/4-bet: qualquer
      raise pós-bet é tratado como all-in, correto pra stacks curtos/
      médios, não serve pra deep stack multi-raise).
      raise -> OOP: fold ou call (all-in genuíno, showdown real).
    check -> IP: check (showdown) ou bet(tamanho s).
      bet -> OOP: fold, call, ou raise (all-in).
        raise -> IP: fold ou call.

Pote/stacks: `pot` é o dinheiro já no meio ANTES dessa decisão (vindo
de ruas anteriores). `stack_oop`/`stack_ip` são os stacks efetivos
ainda NÃO comprometidos nesta rua (o que cada um pode apostar). Se o
respondente não tem stack suficiente pra pagar um raise all-in por
completo, o call é limitado ao stack dele (regra padrão de poker: a
parte não paga de uma aposta/raise volta pra quem apostou, não conta
no pote final).
"""

import itertools
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
    Retorna lista de strings de carta de 2 chars (rank+naipe)."""
    if isinstance(board, str):
        board = board.replace(" ", "")
        cards = [board[i:i + 2] for i in range(0, len(board), 2)]
    else:
        cards = list(board)
    if len(set(cards)) != len(cards):
        raise ValueError(f"board com cartas repetidas: {cards}")
    return cards


def expand_class_combos(hand_class: str, dead_cards) -> list:
    """Todos os combos reais (cartas com naipe) de uma classe, excluindo
    qualquer combo que use uma carta já no board."""
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


def build_river_showdown_matrix(classes, board):
    """Retorna (matrix, live_classes, combos_by_class).
    matrix[(classe_a, classe_b)] = probabilidade de a vencer o showdown
    contra b nesse board exato (1.0=vence sempre, 0.0=perde sempre,
    0.5=empate), média sobre todos os pares de combos válidos (sem
    conflito de carta entre board/herói/vilão). live_classes = classes
    com pelo menos 1 combo possível nesse board."""
    board_cards = parse_board(board)
    dead = set(board_cards)
    board_int = [Card.new(c) for c in board_cards]

    combos_by_class = {c: expand_class_combos(c, dead) for c in classes}
    live_classes = [c for c in classes if combos_by_class[c]]

    rank_cache = {}

    def get_rank(combo):
        if combo not in rank_cache:
            cards = [Card.new(combo[0]), Card.new(combo[1])]
            rank_cache[combo] = EVALUATOR.evaluate(board_int, cards)
        return rank_cache[combo]

    matrix = {}
    for ca in live_classes:
        for cb in live_classes:
            total, n = 0.0, 0
            for combo_a in combos_by_class[ca]:
                set_a = set(combo_a)
                ra = get_rank(combo_a)
                for combo_b in combos_by_class[cb]:
                    if set_a & set(combo_b):
                        continue
                    rb = get_rank(combo_b)
                    if ra < rb:  # treys: menor = melhor
                        total += 1.0
                    elif ra == rb:
                        total += 0.5
                    n += 1
            if n > 0:
                matrix[(ca, cb)] = total / n
    return matrix, live_classes, combos_by_class


class RiverSolver:
    """CFR exato (full-enumeration, igual kuhn_poker.py/pushfold.py — sem
    amostragem) sobre a árvore de river descrita no docstring do módulo.
    Reaproveita o núcleo genérico de regret matching (cfr_core)."""

    def __init__(self, board, range_oop: dict, range_ip: dict, pot: float,
                 stack_oop: float, stack_ip: float, bet_sizes=(0.33, 0.75, 1.5)):
        self.board = parse_board(board)
        self.pot0 = pot
        self.stack_oop = stack_oop
        self.stack_ip = stack_ip
        self.bet_sizes = list(bet_sizes)

        classes = all_hand_classes()
        self.showdown, live_classes, combos_by_class = build_river_showdown_matrix(classes, self.board)

        # so entram no range classes vivas nesse board E com peso > 0
        self.classes_oop = [c for c in live_classes if range_oop.get(c, 0.0) > 0.0]
        self.classes_ip = [c for c in live_classes if range_ip.get(c, 0.0) > 0.0]
        if not self.classes_oop or not self.classes_ip:
            raise ValueError("range vazio (ou totalmente bloqueado pelo board) pra OOP ou IP")

        def weights(range_dict, cls_list):
            raw = {c: range_dict[c] * len(combos_by_class[c]) for c in cls_list}
            total = sum(raw.values())
            return {c: w / total for c, w in raw.items()}

        self.w_oop = weights(range_oop, self.classes_oop)
        self.w_ip = weights(range_ip, self.classes_ip)

        self.trainer = DiscountedCFRTrainer()

    # ---- pote/showdown ----

    def _showdown(self, ca, cb):
        return self.showdown.get((ca, cb))

    @staticmethod
    def _terminal_fold(folder, committed_oop, committed_ip, pot0):
        pot_total = pot0 + committed_oop + committed_ip
        if folder == "oop":
            return -committed_oop, pot_total - committed_ip
        return pot_total - committed_oop, -committed_ip

    def _terminal_showdown(self, ca, cb, committed_oop, committed_ip):
        pot_total = self.pot0 + committed_oop + committed_ip
        result = self._showdown(ca, cb)
        if result is None:
            return 0.0, 0.0
        return pot_total * result - committed_oop, pot_total * (1 - result) - committed_ip

    # ---- árvore ----

    def _node_facing_raise(self, bettor, ca, cb, bet_amt, raise_to,
                            committed_oop, committed_ip, p_oop, p_ip, prefix):
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

        if is_oop:
            u_fold = self._terminal_fold("oop", bet_amt, bet_amt, self.pot0)
            u_call = self._terminal_showdown(ca, cb, matched, matched)
        else:
            u_fold = self._terminal_fold("ip", bet_amt, bet_amt, self.pot0)
            u_call = self._terminal_showdown(ca, cb, matched, matched)

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
                          p_oop, p_ip, prefix):
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
        u_call = self._terminal_showdown(ca, cb, call_committed_oop, call_committed_ip)

        if raise_legal:
            raise_to = own_stack  # all-in
            new_p_oop = p_oop * strat[2] if is_resp_oop else p_oop
            new_p_ip = p_ip * strat[2] if not is_resp_oop else p_ip
            u_raise = self._node_facing_raise(
                bettor, ca, cb, bet_amt, raise_to,
                new_committed_oop, new_committed_ip, new_p_oop, new_p_ip, prefix,
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
                            p_oop, p_ip, prefix, is_second):
        """`actor` decide check ou bet(tamanho). `is_second`=True quando
        já é a resposta a um check anterior (check aqui -> showdown)."""
        is_oop = actor == "oop"
        own_class = ca if is_oop else cb
        n_actions = 1 + len(self.bet_sizes)
        key = f"{prefix}|bet_or_check|{actor}|{own_class}"
        infoset = self.trainer.get_infoset(key, n_actions=n_actions)
        own_p = p_oop if is_oop else p_ip
        strat = infoset.get_strategy(own_p)

        # acao 0: check
        if is_second:
            u_check = self._terminal_showdown(ca, cb, committed_oop, committed_ip)
        else:
            new_p_oop = p_oop * strat[0] if is_oop else p_oop
            new_p_ip = p_ip * strat[0] if not is_oop else p_ip
            other = "ip" if is_oop else "oop"
            u_check = self._node_bet_or_check(
                other, ca, cb, committed_oop, committed_ip, new_p_oop, new_p_ip,
                prefix + "-x", is_second=True,
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
                new_p_oop, new_p_ip, prefix + f"-b{idx}",
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
                        "oop", ca, cb, 0.0, 0.0, p_oop, p_ip, "", is_second=False,
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


if __name__ == "__main__":
    # Spot de exemplo: board seco (sem draw), range da OOP polarizada
    # (nuts + air), range da IP so com bluff-catchers medios -- serve pra
    # checagem de sanidade (nuts aposta muito mais que air/meio-de-range,
    # e a IP so paga com mao boa o suficiente).
    board = "Ah Kd 7s 2c 9h"

    range_oop = {"AA": 1.0, "AKo": 1.0, "AKs": 1.0, "KK": 1.0, "72o": 1.0, "83o": 1.0, "T9o": 1.0}
    range_ip = {"AQo": 1.0, "AQs": 1.0, "AJo": 1.0, "KQo": 1.0, "KJo": 1.0, "QQ": 1.0, "JJ": 1.0}

    solver = RiverSolver(
        board=board, range_oop=range_oop, range_ip=range_ip,
        pot=20.0, stack_oop=60.0, stack_ip=60.0, bet_sizes=(0.33, 0.75, 1.5),
    )
    solver.train(iterations=1500)

    strat = solver.average_strategy_root()
    print(f"Board: {board}  (top set AA, overpair KK, TPTK-ish AKo/AKs vs ar/blefes 72o/83o/T9o)")
    print("\n--- OOP (raiz: check vs bet) ---")
    for c in ["AA", "KK", "AKo", "AKs", "T9o", "83o", "72o"]:
        if c in strat["oop"]:
            row = strat["oop"][c]
            print(f"  {c:5s} " + "  ".join(f"{k}={v:.2f}" for k, v in row.items()))

    print("\n--- IP (apos check da OOP: check vs bet) ---")
    for c in ["QQ", "JJ", "AQo", "AQs", "AJo", "KQo", "KJo"]:
        if c in strat["ip"]:
            row = strat["ip"][c]
            print(f"  {c:5s} " + "  ".join(f"{k}={v:.2f}" for k, v in row.items()))

    print("\n--- Sanidade ---")
    aa_bet = 1 - strat["oop"]["AA"]["check"]
    air_bet = 1 - strat["oop"]["72o"]["check"]
    print(f"AA (nuts) aposta com freq {aa_bet:.2f}; 72o (ar puro) aposta com freq {air_bet:.2f}")
    print(f"  esperado: nuts aposta MUITO mais que ar puro -> {'OK' if aa_bet > air_bet else 'SUSPEITO'}")
