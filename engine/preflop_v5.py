"""
Pré-flop v5 (2026-09-30): mesa cheia (8 ou 9 jogadores) com flat call,
3-bet e 4-bet de tamanho normal, limp do SB, all-in e até 3 jogadores
vendo o flop.

Diferente do motor v4 (engine/multiway_rfi.py), aqui a mão INTEIRA é
resolvida de uma vez: todo mundo, de UTG ao BB, decide com os ranges de
todos os outros -- abrir, pagar, 3-bet, 4-bet, all-in, limp do SB, iso do
BB. Uma solução por profundidade de stack.

Como é resolvido (MCCFR com "amostragem externa", laço em numba):
  a cada iteração sorteia as cartas de todos (baralho de verdade) e um
  lote de mesas (5 cartas); pra cada jogador, percorre TODAS as ações
  dele e UMA ação sorteada dos outros (pela estratégia atual). Regret com
  piso em zero (CFR+) e média ponderada pela iteração -- mesma receita do
  v4, que já foi validada.

Quando a mão vai pro flop SEM all-in, o pós-flop não é jogado aqui: o
pote é dividido pela "equity realizada" (equity x fator de realização,
EQR) -- ver `eqr_factor`. Os fatores são uma aproximação (posição, tipo de
mão, SPR) pra ser CALIBRADA depois com o solver pós-flop
(engine/postflop_fast.py). Com all-in, é equity pura (showdown).

Valores: chipEV (fichas ganhas/perdidas na mão, contando o ante) ou ICM
($ da mesa, Malmuth-Harville) -- a tabela de pagamento de cada final
possível é pré-calculada na montagem da árvore, então o treino não
calcula ICM nenhum.
"""

import numpy as np
from numba import njit, prange

from engine.card_removal import CLASS_OF
from engine.hand_classes import all_hand_classes
from engine.icm import icm_equity
from engine.nb_eval import eval_cards

ENGINE_VERSION = "preflop-v5-2026-09-30"

POSITIONS = {
    2: ["SB", "BB"],  # só pra testes (comparação com os motores heads-up)
    8: ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO", "BTN", "SB", "BB"],
}

PLAYER, TERM = 0, 1
# tipos de final
T_FOLD, T_ALLIN, T_FLOP = 0, 1, 2

CLASSES = all_hand_classes()
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}
# classe (0..168) de cada dupla de cartas
CLASS_OF_CARDS = np.full((52, 52), -1, dtype=np.int64)
for _a in range(52):
    for _b in range(52):
        if _a != _b:
            CLASS_OF_CARDS[_a, _b] = CLASS_INDEX[CLASS_OF[_a][_b]]


def default_open_size(stack):
    if stack <= 20:
        return 2.0
    if stack <= 40:
        return 2.2
    if stack <= 60:
        return 2.3
    return 2.5


class PreflopConfig:
    """stack = pilha de cada jogador ANTES do ante (todos iguais).
    payouts=None -> chipEV; lista -> ICM com esses prêmios."""

    def __init__(self, stack, n_players=8, ante=0.125, open_size=None, sb_open_size=3.0,
                 bb_iso_size=3.5, threebet_ip=3.0, threebet_oop=4.0, per_caller=1.0,
                 fourbet_mult=2.3, jam_threshold=0.4, max_flop=3, sb_limp=True, payouts=None):
        if n_players not in POSITIONS:
            raise ValueError("n_players precisa ser 8 ou 9 (2 só pra testes)")
        self.stack = float(stack)
        self.n = n_players
        self.ante = float(ante)
        self.open_size = open_size or default_open_size(stack)
        self.sb_open_size = sb_open_size
        self.bb_iso_size = bb_iso_size
        self.threebet_ip = threebet_ip
        self.threebet_oop = threebet_oop
        self.per_caller = per_caller
        self.fourbet_mult = fourbet_mult
        self.jam_threshold = jam_threshold
        self.max_flop = max_flop
        self.sb_limp = sb_limp
        self.payouts = payouts
        self.eff = self.stack - self.ante  # o que cada um pode apostar

    @property
    def positions(self):
        return POSITIONS[self.n]


# ---------------------------------------------------------------------------
# realização de equity (EQR) -- aproximação a calibrar
# ---------------------------------------------------------------------------

def eqr_factor(hand_class, pos_rank, n_live, spr):
    """Fator de realização de equity de `hand_class` num pote de `n_live`
    jogadores, `pos_rank` = 0 pra quem age primeiro no flop (mais fora de
    posição) até n_live-1 (último, em posição). spr = pilha restante /
    pote no flop.

    Aproximação inicial (a ser calibrada com o solver pós-flop):
      - posição: em posição realiza mais que a equity, fora realiza menos;
      - mão: suited e conectada realizam mais; offsuit desconectada menos;
      - SPR: com pouca pilha atrás (pote comprometido) todo mundo realiza
        quase exatamente a equity (vai ao showdown) -> fator tende a 1."""
    if n_live == 2:
        base = (-0.12, 0.06)[pos_rank]
    else:
        base = (-0.14, -0.05, 0.06)[pos_rank]
    r1, r2 = hand_class[0], hand_class[1]
    adj = 0.0
    if r1 == r2:
        adj += 0.02
    else:
        ranks = "23456789TJQKA"
        gap = ranks.index(r1) - ranks.index(r2) - 1
        suited = hand_class[2] == "s"
        adj += 0.05 if suited else -0.04
        adj += {0: 0.03, 1: 0.02, 2: 0.0}.get(gap, -0.03)
        if ranks.index(r2) >= 8:  # duas cartas altas (T+)
            adj += 0.02
    scale = spr / (spr + 1.5)
    return 1.0 + (base + adj) * scale


# ---------------------------------------------------------------------------
# árvore
# ---------------------------------------------------------------------------

class _State:
    __slots__ = ("commit", "folded", "part", "level", "limped", "jammed", "aggr", "to_act", "hist")

    def copy(self):
        s = _State()
        s.commit = list(self.commit)
        s.folded = list(self.folded)
        s.part = list(self.part)
        s.level = self.level
        s.limped = self.limped
        s.jammed = self.jammed
        s.aggr = self.aggr
        s.to_act = list(self.to_act)
        s.hist = list(self.hist)
        return s


class PreflopTree:
    """Árvore de ações. Nós em listas planas (pra numba). `hist[nid]` =
    sequência de (seat, ação) até o nó; `labels[nid]` = nomes das ações."""

    def __init__(self, cfg: PreflopConfig):
        self.cfg = cfg
        n = cfg.n
        self.sb, self.bb = n - 2, n - 1
        self.ntype, self.actor, self.nact, self.cstart = [], [], [], []
        self.children, self.labels, self.hist = [], [], []
        self.term_of = []      # nó -> índice do final (ou -1)
        self.terms = []        # (tipo, live seats, commits)
        st = _State()
        st.commit = [0.0] * n
        st.commit[self.sb] = 0.5
        st.commit[self.bb] = 1.0
        st.folded = [False] * n
        st.part = [False] * n
        st.level = 0
        st.limped = False
        st.jammed = False
        st.aggr = -1
        st.to_act = list(range(n))
        st.hist = []
        self._build(st)
        self._finish()

    # -- posição no pós-flop: SB age primeiro, depois BB, depois UTG..BTN
    def post_rank(self, seat):
        if self.cfg.n == 2:  # heads-up: SB é o botão, age por último no flop
            return 1 if seat == self.sb else 0
        if seat == self.sb:
            return 0
        if seat == self.bb:
            return 1
        return seat + 2

    def _new(self, typ, actor, hist):
        nid = len(self.ntype)
        self.ntype.append(typ)
        self.actor.append(actor)
        self.nact.append(0)
        self.cstart.append(0)
        self.labels.append(())
        self.hist.append(tuple(hist))
        self.term_of.append(-1)
        return nid

    def _build(self, st):
        cfg = self.cfg
        # pula quem já foldou ou está all-in
        while st.to_act and (st.folded[st.to_act[0]] or st.commit[st.to_act[0]] >= cfg.eff - 1e-9):
            st.to_act.pop(0)
        if not st.to_act or sum(1 for f in st.folded if not f) == 1:
            return self._terminal(st)
        a = st.to_act[0]
        nid = self._new(PLAYER, a, st.hist)
        opts = self._options(st, a)
        kids = []
        for label, kind, amount in opts:
            ns = st.copy()
            ns.to_act.pop(0)
            ns.hist.append((a, label))
            if kind == "fold":
                ns.folded[a] = True
            elif kind in ("call", "check", "limp"):
                ns.commit[a] = amount
                ns.part[a] = True
                if kind == "limp":
                    ns.limped = True
            else:  # raise / jam
                ns.commit[a] = amount
                ns.part[a] = True
                ns.aggr = a
                if kind == "jam":
                    ns.jammed = True
                ns.level += 1
                n = cfg.n
                order = [(a + k) % n for k in range(1, n)]
                ns.to_act = [s for s in order if not ns.folded[s] and ns.commit[s] < cfg.eff - 1e-9]
            kids.append(self._build(ns))
        self.nact[nid] = len(kids)
        self.cstart[nid] = len(self.children)
        self.children.extend(kids)
        self.labels[nid] = tuple(o[0] for o in opts)
        return nid

    def _options(self, st, a):
        cfg = self.cfg
        E = cfg.eff
        cur = max(st.commit)
        # limite de jogadores no pote: pagar só se, contando quem já está
        # no valor atual (inclusive quem aumentou), ficar <= max_flop
        n_match = sum(1 for s in range(cfg.n) if not st.folded[s] and st.commit[s] >= cur - 1e-9)
        can_join = n_match + 1 <= cfg.max_flop
        opts = []
        jam = ("allin", "jam", E)

        def raise_to(x):
            x = round(x, 2)
            if x >= cfg.jam_threshold * E or x >= E:
                return None
            return x

        if st.jammed:
            opts.append(("fold", "fold", 0))
            if can_join:
                opts.append(("call", "call", E))
            return opts
        if st.level == 0 and not st.limped:
            # ninguém entrou ainda
            if a == self.bb:
                return []  # não acontece: todo mundo foldou -> final
            opts.append(("fold", "fold", 0))
            if a == self.sb:
                if cfg.sb_limp:
                    opts.append(("limp", "limp", 1.0))
                r = raise_to(cfg.sb_open_size)
            else:
                r = raise_to(cfg.open_size)
            if r is not None:
                opts.append((f"raise {r:g}", "raise", r))
            opts.append(jam)
            return opts
        if st.level == 0 and st.limped:
            # BB contra o limp do SB
            opts.append(("check", "check", cur))
            r = raise_to(cfg.bb_iso_size)
            if r is not None:
                opts.append((f"raise {r:g}", "raise", r))
            opts.append(jam)
            return opts
        # enfrentando aumento (level 1 = open/iso, 2 = 3-bet, 3 = 4-bet)
        opts.append(("fold", "fold", 0))
        cold = not st.part[a]
        if can_join and not (cold and st.level >= 2):
            opts.append(("call", "call", cur))
        r = None
        if st.level == 1:
            callers = sum(1 for s in range(cfg.n) if st.part[s] and not st.folded[s] and s not in (st.aggr, a))
            ip = self.post_rank(a) > self.post_rank(st.aggr)
            mult = cfg.threebet_ip if ip else cfg.threebet_oop
            r = raise_to(cur * (mult + cfg.per_caller * callers))
        elif st.level == 2 and not cold:
            r = raise_to(cur * cfg.fourbet_mult)
        if r is not None:
            opts.append((f"raise {r:g}", "raise", r))
        opts.append(jam)
        return opts

    def _terminal(self, st):
        nid = self._new(TERM, -1, st.hist)
        live = [s for s in range(self.cfg.n) if not st.folded[s]]
        if len(live) == 1:
            kind = T_FOLD
        elif st.jammed:
            kind = T_ALLIN
        else:
            kind = T_FLOP
        self.term_of[nid] = len(self.terms)
        self.terms.append((kind, tuple(live), tuple(st.commit)))
        return nid

    def _finish(self):
        cfg = self.cfg
        n = cfg.n
        self.ntype = np.array(self.ntype, dtype=np.int64)
        self.actor = np.array(self.actor, dtype=np.int64)
        self.nact = np.array(self.nact, dtype=np.int64)
        self.cstart = np.array(self.cstart, dtype=np.int64)
        self.children = np.array(self.children, dtype=np.int64)
        self.term_of = np.array(self.term_of, dtype=np.int64)
        nt = len(self.terms)
        # tkind, número de vivos, seats vivos, pagamento por vencedor
        self.tkind = np.zeros(nt, dtype=np.int64)
        self.tnlive = np.zeros(nt, dtype=np.int64)
        self.tlive = np.full((nt, 3), -1, dtype=np.int64)
        self.tpay = np.zeros((nt, 3, n))       # [final, k-ésimo vivo vence, seat]
        self.teqr = np.ones((nt, 3, 169))      # fator EQR do k-ésimo vivo por classe
        ante_pool = cfg.ante * n
        pay_cache = {}
        for t, (kind, live, commit) in enumerate(self.terms):
            self.tkind[t] = kind
            self.tnlive[t] = len(live)
            pot = sum(commit) + ante_pool
            for k, w in enumerate(live):
                self.tlive[t, k] = w
                final = [cfg.eff - commit[s] + (pot if s == w else 0.0) for s in range(n)]
                key = tuple(round(x, 6) for x in final)
                if key not in pay_cache:
                    if cfg.payouts is None:
                        pay_cache[key] = [x - cfg.stack for x in final]
                    else:
                        pay_cache[key] = icm_equity(final, cfg.payouts, [cfg.stack] * n)
                self.tpay[t, k] = pay_cache[key]
            if kind == T_FLOP:
                c = commit[live[0]]
                spr = (cfg.eff - c) / pot
                ranks = sorted(live, key=self.post_rank)
                for k, w in enumerate(live):
                    pr = ranks.index(w)
                    for ci, cl in enumerate(CLASSES):
                        self.teqr[t, k, ci] = eqr_factor(cl, pr, len(live), spr)
        # offsets dos regrets: nó de jogador -> início do bloco [ação][classe]
        self.regoff = np.zeros(len(self.ntype), dtype=np.int64)
        tot = 0
        for nid in range(len(self.ntype)):
            if self.ntype[nid] == PLAYER:
                self.regoff[nid] = tot
                tot += int(self.nact[nid]) * 169
        self.n_regrets = tot

    @property
    def n_nodes(self):
        return len(self.ntype)


# ---------------------------------------------------------------------------
# núcleo numba
# ---------------------------------------------------------------------------
# Nota sobre cache (2026-09-30): o cache do numba só confere a data do
# PRÓPRIO arquivo -- se engine/nb_eval.py mudar e este não, uma função
# guardada em cache continuaria chamando o avaliador velho (visto aqui:
# falha de memória), e funções recursivas em cache chamadas de funções
# sem cache quebram o numba ("Symbol not found"). Por isso NADA neste
# arquivo usa cache; custa alguns segundos de compilação por execução.

@njit(cache=False)
def _seed(seed):
    np.random.seed(seed)


@njit(cache=False)
def _deal(n, K, class_of, hole, cls, vals):
    """Cartas de todos (baralho de verdade) + K mesas sorteadas das cartas
    que sobraram; vals[b, s] = força da mão do seat s na mesa b."""
    deck = np.arange(52)
    for i in range(2 * n):
        j = i + int(np.random.random() * (52 - i))
        deck[i], deck[j] = deck[j], deck[i]
    for s in range(n):
        hole[s, 0] = deck[2 * s]
        hole[s, 1] = deck[2 * s + 1]
        cls[s] = class_of[hole[s, 0], hole[s, 1]]
    rest = deck[2 * n:].copy()
    m = rest.size
    cards = np.empty(7, dtype=np.int64)
    for b in range(K):
        for i in range(5):
            j = i + int(np.random.random() * (m - i))
            rest[i], rest[j] = rest[j], rest[i]
            cards[i] = rest[i]
        for s in range(n):
            cards[5] = hole[s, 0]
            cards[6] = hole[s, 1]
            vals[b, s] = eval_cards(cards, 7)


@njit(cache=False)
def _shares(t, tkind, tnlive, tlive, teqr, cls, vals):
    """Fração do pote de cada vivo (k-ésimo) num final disputado."""
    nl = tnlive[t]
    K = vals.shape[0]
    eq = np.zeros(nl)
    for b in range(K):
        best = -1
        cnt = 0
        for k in range(nl):
            v = vals[b, tlive[t, k]]
            if v > best:
                best = v
                cnt = 1
            elif v == best:
                cnt += 1
        for k in range(nl):
            if vals[b, tlive[t, k]] == best:
                eq[k] += 1.0 / cnt
    tot = 0.0
    for k in range(nl):
        eq[k] /= K
        if tkind[t] == 2:  # flop: equity realizada
            eq[k] *= teqr[t, k, cls[tlive[t, k]]]
        tot += eq[k]
    for k in range(nl):
        eq[k] /= tot
    return eq


@njit(cache=False)
def _strategy(reg, off, na, c):
    sig = np.empty(na)
    s = 0.0
    for a in range(na):
        r = reg[off + a * 169 + c]
        if r > 0.0:
            s += r
    for a in range(na):
        r = reg[off + a * 169 + c]
        sig[a] = (r / s if r > 0.0 else 0.0) if s > 0.0 else 1.0 / na
    return sig


@njit(cache=False)
def _avg(ssum, off, na, c):
    sig = np.empty(na)
    s = 0.0
    for a in range(na):
        s += ssum[off + a * 169 + c]
    for a in range(na):
        sig[a] = ssum[off + a * 169 + c] / s if s > 0.0 else 1.0 / na
    return sig


@njit(cache=False)
def _traverse(node, p, tw, plus, ntype, actor, nact, cstart, children, term_of, regoff,
              tkind, tnlive, tlive, tpay, teqr, reg, ssum, cls, vals):
    if ntype[node] == 1:
        t = term_of[node]
        if tkind[t] == 0:
            return tpay[t, 0, p]
        sh = _shares(t, tkind, tnlive, tlive, teqr, cls, vals)
        u = 0.0
        for k in range(tnlive[t]):
            u += sh[k] * tpay[t, k, p]
        return u
    a = actor[node]
    c = cls[a]
    na = nact[node]
    off = regoff[node]
    s0 = cstart[node]
    sig = _strategy(reg, off, na, c)
    if a == p:
        ua = np.empty(na)
        u = 0.0
        for k in range(na):
            ua[k] = _traverse(children[s0 + k], p, tw, plus, ntype, actor, nact, cstart, children, term_of,
                              regoff, tkind, tnlive, tlive, tpay, teqr, reg, ssum, cls, vals)
            u += sig[k] * ua[k]
        for k in range(na):
            idx = off + k * 169 + c
            r = reg[idx] + ua[k] - u
            reg[idx] = r if (r > 0.0 or not plus) else 0.0
        return u
    for k in range(na):
        ssum[off + k * 169 + c] += tw * sig[k]
    x = np.random.random()
    k = 0
    acc = sig[0]
    while x >= acc and k < na - 1:
        k += 1
        acc += sig[k]
    return _traverse(children[s0 + k], p, tw, plus, ntype, actor, nact, cstart, children, term_of, regoff,
                     tkind, tnlive, tlive, tpay, teqr, reg, ssum, cls, vals)


@njit(cache=False)
def _train(t0, iters, plus, n, K, class_of, ntype, actor, nact, cstart, children, term_of, regoff,
           tkind, tnlive, tlive, tpay, teqr, reg, ssum):
    hole = np.empty((n, 2), dtype=np.int64)
    cls = np.empty(n, dtype=np.int64)
    vals = np.empty((K, n), dtype=np.int64)
    for it in range(iters):
        tw = 1.0  # o peso do tempo vem do desconto por intervalo (ver PreflopSolver.train)
        _deal(n, K, class_of, hole, cls, vals)
        for p in range(n):
            _traverse(0, p, tw, plus, ntype, actor, nact, cstart, children, term_of, regoff,
                      tkind, tnlive, tlive, tpay, teqr, reg, ssum, cls, vals)


@njit(cache=False, parallel=True)
def _train_par(t0, iters, plus, n, K, class_of, ntype, actor, nact, cstart, children, term_of, regoff,
               tkind, tnlive, tlive, tpay, teqr, reg, ssum):
    """Igual `_train`, mas com as iterações divididas entre os núcleos do
    processador, todos escrevendo nos MESMOS regrets sem trava ("Hogwild",
    técnica padrão em MCCFR grande): de vez em quando duas threads somam
    no mesmo lugar ao mesmo tempo e uma soma se perde -- ruído pequeno
    perto do ruído do próprio sorteio. Não é reproduzível bit a bit."""
    for it in prange(iters):
        hole = np.empty((n, 2), dtype=np.int64)
        cls = np.empty(n, dtype=np.int64)
        vals = np.empty((K, n), dtype=np.int64)
        tw = 1.0
        _deal(n, K, class_of, hole, cls, vals)
        for p in range(n):
            _traverse(0, p, tw, plus, ntype, actor, nact, cstart, children, term_of, regoff,
                      tkind, tnlive, tlive, tpay, teqr, reg, ssum, cls, vals)


@njit(cache=False)
def _discount(reg, ssum, fpos, fneg, fstrat):
    for i in range(reg.size):
        r = reg[i]
        reg[i] = r * fpos if r > 0.0 else r * fneg
        ssum[i] *= fstrat


@njit(cache=False)
def _evaluate(node, n, reach, mode, ntype, actor, nact, cstart, children, term_of, regoff,
              tkind, tnlive, tlive, tpay, teqr, ssum, cls, vals, cv, cw, nw, gb, gm, gmean, sq):
    """Percorre a árvore INTEIRA com as estratégias médias e devolve o
    vetor de valores (um por seat). Pra cada decisão (nó, classe de quem
    age), índice `off + c` (off = início do bloco do nó):
      mode 1: cv[off + a*169 + c] += alcance dos OUTROS x valor da ação a;
              cw[off + c] += alcance dos outros; nw[off + c] += alcance de
              todos (frequência da situação).
      mode 2: pra melhor ação gb (escolhida no mode 1), acumula o erro
              quadrático da perda "melhor ação - mistura treinada" (pra
              calcular o erro-padrão, método delta) e o peso. gm não é
              usado (reservado)."""
    out = np.zeros(n)
    if ntype[node] == 1:
        t = term_of[node]
        if tkind[t] == 0:
            for s in range(n):
                out[s] = tpay[t, 0, s]
            return out
        sh = _shares(t, tkind, tnlive, tlive, teqr, cls, vals)
        for k in range(tnlive[t]):
            for s in range(n):
                out[s] += sh[k] * tpay[t, k, s]
        return out
    a = actor[node]
    c = cls[a]
    na = nact[node]
    off = regoff[node]
    s0 = cstart[node]
    sig = _avg(ssum, off, na, c)
    others = 1.0
    for s in range(n):
        if s != a:
            others *= reach[s]
    own = reach[a]
    va = np.empty(na)
    for k in range(na):
        nr = reach.copy()
        nr[a] = own * sig[k]
        v = _evaluate(children[s0 + k], n, nr, mode, ntype, actor, nact, cstart, children, term_of, regoff,
                      tkind, tnlive, tlive, tpay, teqr, ssum, cls, vals, cv, cw, nw, gb, gm, gmean, sq)
        va[k] = v[a]
        for s in range(n):
            out[s] += sig[k] * v[s]
    j = off + c
    if mode == 0:
        return out
    if mode == 1:
        for k in range(na):
            cv[off + k * 169 + c] += others * va[k]
        cw[j] += others
        nw[j] += others * own
    elif gb[j] >= 0:
        mix = 0.0
        for k in range(na):
            mix += sig[k] * va[k]
        d = others * (va[gb[j]] - mix) - gmean[j] * others
        sq[j] += d * d
        cw[j] += others
    return out


@njit(cache=False)
def _deal_forced(n, K, class_of, combos, fseat, hole, cls, vals):
    """Igual `_deal`, mas o seat `fseat` recebe um combo sorteado de
    `combos` (todos os combos de uma classe) -- pra checagem focada."""
    k = int(np.random.random() * combos.shape[0])
    c1 = combos[k, 0]
    c2 = combos[k, 1]
    deck = np.empty(50, dtype=np.int64)
    m = 0
    for c in range(52):
        if c != c1 and c != c2:
            deck[m] = c
            m += 1
    for i in range(2 * (n - 1)):
        j = i + int(np.random.random() * (50 - i))
        deck[i], deck[j] = deck[j], deck[i]
    q = 0
    for s in range(n):
        if s == fseat:
            hole[s, 0] = c1
            hole[s, 1] = c2
        else:
            hole[s, 0] = deck[2 * q]
            hole[s, 1] = deck[2 * q + 1]
            q += 1
        cls[s] = class_of[hole[s, 0], hole[s, 1]]
    rest = deck[2 * (n - 1):].copy()
    mm = rest.size
    cards = np.empty(7, dtype=np.int64)
    for b in range(K):
        for i in range(5):
            j = i + int(np.random.random() * (mm - i))
            rest[i], rest[j] = rest[j], rest[i]
            cards[i] = rest[i]
        for s in range(n):
            cards[5] = hole[s, 0]
            cards[6] = hole[s, 1]
            vals[b, s] = eval_cards(cards, 7)


@njit(cache=False, nogil=True)
def _eval_focus(deals, n, K, class_of, combos, fseat, path_nodes, path_acts, target, ntype, actor, nact,
                cstart, children, term_of, regoff, tkind, tnlive, tlive, tpay, teqr, ssum):
    """Checagem focada numa decisão (nó `target`, seat fseat com um combo
    de `combos`): toda mesa sorteada dá essa mão pro seat, e só o caminho
    até o nó (path_nodes/path_acts) e a subárvore dele são percorridos --
    o valor das ações ali não depende do resto da árvore. Devolve, por
    mesa, o valor de cada ação pesado pelo alcance dos outros (xs) e o
    peso (ws), pra média e erro-padrão exatos."""
    hole = np.empty((n, 2), dtype=np.int64)
    cls = np.empty(n, dtype=np.int64)
    vals = np.empty((K, n), dtype=np.int64)
    na = nact[target]
    a = actor[target]
    xs = np.zeros((deals, na))
    ws = np.zeros(deals)
    d1 = np.zeros(1)
    di = np.full(1, -1, dtype=np.int64)
    for d in range(deals):
        _deal_forced(n, K, class_of, combos, fseat, hole, cls, vals)
        reach = np.ones(n)
        for i in range(path_nodes.shape[0]):
            nd = path_nodes[i]
            sg = _avg(ssum, regoff[nd], nact[nd], cls[actor[nd]])
            reach[actor[nd]] *= sg[path_acts[i]]
        others = 1.0
        for s in range(n):
            if s != a:
                others *= reach[s]
        ws[d] = others
        if others <= 0.0:
            continue
        s0 = cstart[target]
        for k in range(na):
            v = _evaluate(children[s0 + k], n, reach, 0, ntype, actor, nact, cstart, children, term_of,
                          regoff, tkind, tnlive, tlive, tpay, teqr, ssum, cls, vals,
                          d1, d1, d1, di, di, d1, d1)
            xs[d, k] = others * v[a]
    return xs, ws


@njit(cache=False)
def _eval_many(deals, n, K, mode, class_of, ntype, actor, nact, cstart, children, term_of, regoff,
               tkind, tnlive, tlive, tpay, teqr, ssum, cv, cw, nw, gb, gm, gmean, sq, ev):
    hole = np.empty((n, 2), dtype=np.int64)
    cls = np.empty(n, dtype=np.int64)
    vals = np.empty((K, n), dtype=np.int64)
    reach = np.ones(n)
    for d in range(deals):
        _deal(n, K, class_of, hole, cls, vals)
        v = _evaluate(0, n, reach, mode, ntype, actor, nact, cstart, children, term_of, regoff,
                      tkind, tnlive, tlive, tpay, teqr, ssum, cls, vals, cv, cw, nw, gb, gm, gmean, sq)
        for s in range(n):
            ev[s] += v[s]


# ---------------------------------------------------------------------------
# interface
# ---------------------------------------------------------------------------

class PreflopSolver:
    def __init__(self, cfg: PreflopConfig, boards=16, seed=1, cfr_plus=False, interval=50_000):
        self.cfg = cfg
        self.interval = interval
        self.cfr_plus = cfr_plus
        self.tree = PreflopTree(cfg)
        self.boards = boards
        self.reg = np.zeros(max(self.tree.n_regrets, 1))
        self.ssum = np.zeros(max(self.tree.n_regrets, 1))
        self.iterations = 0
        self.seed = seed
        self.last_check_summary = None

    def _arrays(self):
        tr = self.tree
        return (tr.ntype, tr.actor, tr.nact, tr.cstart, tr.children, tr.term_of, tr.regoff,
                tr.tkind, tr.tnlive, tr.tlive, tr.tpay, tr.teqr)

    def train(self, iterations, parallel=False):
        """Treina mais `iterations` mesas. A cada `interval` iterações aplica
        o desconto do Discounted CFR (alpha=1.5, beta=0, gamma=2) em todos
        os regrets e na soma da estratégia média -- o começo do treino
        (estratégias ruins) vai sendo esquecido.

        Por que (2026-09-30): sem desconto, a 1a solução real (15bb, 20M)
        ficou com UTG AKs 98% all-in na MÉDIA embora a estratégia ATUAL já
        aumentasse 100% (aumentar vale +0,15bb): os regrets acumulados no
        começo levavam milhões de mãos pra ser superados."""
        fn = _train_par if parallel else _train
        left = iterations
        while left > 0:
            to_boundary = self.interval - (self.iterations % self.interval)
            step = min(left, to_boundary)
            _seed(self.seed * 1_000_003 + self.iterations)
            fn(self.iterations, step, self.cfr_plus, self.cfg.n, self.boards, CLASS_OF_CARDS,
               *self._arrays(), self.reg, self.ssum)
            self.iterations += step
            left -= step
            if self.iterations % self.interval == 0:
                k = self.iterations // self.interval
                ka = k ** 1.5
                _discount(self.reg, self.ssum, ka / (ka + 1.0), 0.5, k / (k + 1.0))

    # -- leitura --
    def node(self, path):
        """Nó depois da sequência de ações `path` (lista de labels)."""
        nid = 0
        tr = self.tree
        for lab in path:
            nid = int(tr.children[tr.cstart[nid] + tr.labels[nid].index(lab)])
        return nid

    def strategy(self, nid):
        """{classe: {ação: frequência}} (estratégia média) no nó."""
        tr = self.tree
        na = int(tr.nact[nid])
        off = int(tr.regoff[nid])
        out = {}
        for ci, cl in enumerate(CLASSES):
            sig = _avg(self.ssum, off, na, ci)
            out[cl] = {lab: float(sig[k]) for k, lab in enumerate(tr.labels[nid])}
        return out

    def _focus_recheck(self, flags, focus_deals, boards, seed, gap_threshold, z, threads=None):
        import os
        from concurrent.futures import ThreadPoolExecutor
        from engine.multiway_equity import class_combo_indices
        tr = self.tree
        n = self.cfg.n
        keep, refuted = [], 0
        _seed(seed)

        def run(f):
            nid = f["node"]
            combos = np.array(class_combo_indices(f["hand"]), dtype=np.int64)
            pn, pa = self._path_to(nid)
            return _eval_focus(focus_deals, n, boards, CLASS_OF_CARDS, combos, int(tr.actor[nid]),
                               pn, pa, nid, *self._arrays(), self.ssum)

        for f in flags:
            self._path_to(f["node"])  # monta o índice de pais antes das threads
        with ThreadPoolExecutor(threads or os.cpu_count() or 1) as ex:
            results = list(ex.map(run, flags))
        for f, (xs, ws) in zip(flags, results):
            nid = f["node"]
            c = CLASS_INDEX[f["hand"]]
            na = int(tr.nact[nid])
            off = int(tr.regoff[nid])
            W = ws.sum()
            if W <= 0:
                refuted += 1
                continue
            vals = xs.sum(axis=0) / W
            sig = _avg(self.ssum, off, na, c)
            b = int(np.argmax(vals))
            d = xs[:, b] - xs @ sig          # por mesa: melhor - mistura
            loss = float(d.sum() / W)
            se = float(np.sqrt(((d - loss * ws) ** 2).sum()) / W)
            reached = int((ws > 0).sum())
            if loss > gap_threshold and loss > z * se:
                labels = tr.labels[nid]
                f = dict(f, gap=loss, se=se, focus_reached=reached, best=labels[b],
                         values={labels[k]: float(vals[k]) for k in range(na)})
                keep.append(f)
            else:
                refuted += 1
        return keep, refuted

    def _path_to(self, nid):
        """(nós, índice da ação) do início até `nid`."""
        tr = self.tree
        parent = getattr(self, "_parent", None)
        if parent is None:
            parent = np.full(tr.n_nodes, -1, dtype=np.int64)
            pact = np.zeros(tr.n_nodes, dtype=np.int64)
            for u in np.nonzero(tr.ntype == PLAYER)[0]:
                for k in range(int(tr.nact[u])):
                    ch = tr.children[tr.cstart[u] + k]
                    parent[ch] = u
                    pact[ch] = k
            self._parent, self._pact = parent, pact
        nodes, acts = [], []
        x = nid
        while self._parent[x] >= 0:
            nodes.append(int(self._parent[x]))
            acts.append(int(self._pact[x]))
            x = int(self._parent[x])
        return np.array(nodes[::-1], dtype=np.int64), np.array(acts[::-1], dtype=np.int64)

    def describe(self, nid):
        tr = self.tree
        pos = self.cfg.positions
        h = " / ".join(f"{pos[s]} {lab}" for s, lab in tr.hist[nid]) or "(início)"
        who = pos[tr.actor[nid]] if tr.ntype[nid] == PLAYER else "fim"
        return f"{h} -> {who}"

    # -- validação (CLAUDE.md) --
    def check_convergence(self, deals=20000, gap_threshold=0.1, z=3.0, min_node_freq=1e-4,
                          boards=64, seed=12345, focus_deals=5000, max_focus=300, threads=None):
        """Checagem de EV de TODAS as decisões: pra cada (situação, mão),
        compara o valor de cada ação -- calculado direto, contra as
        estratégias médias de todos -- com a mistura que o treino aprendeu.

        Os valores vêm de percorrer a árvore inteira em `deals` mesas
        sorteadas, pesando cada situação pela chance dos OUTROS chegarem
        nela (é a conta exata do valor condicional; não precisa sortear
        "quem abriu com o quê", o peso já faz isso -- evita o problema de
        condicionamento do v4). Equity com `boards` mesas por sorteio.

        Aponta quando a perda (melhor ação - mistura treinada) passa de
        `gap_threshold` (fichas ou $ do ICM, mesma unidade do pagamento)
        E de `z` erros-padrão (calculados numa SEGUNDA rodada independente,
        com outra seed -- a média e o ruído não vêm das mesmas mesas).
        Situações com frequência < min_node_freq (chance de acontecer por
        mão, contando a mão do jogador) ficam de fora, contadas em
        `rare_nodes_skipped`.

        Confirmação (2026-09-30): situação rara é alcançada poucas vezes
        nas `deals` mesas (ex: 7 vezes com frequência 1e-4) e o erro-padrão
        de 7 amostras de cauda pesada não é confiável (mesma lição de
        _confirm_gap no v4) -- a 1a checagem real deu 17 apontadas e 0
        se confirmaram. Por isso a passada geral só ESCOLHE candidatas; as
        `max_focus` mais importantes (perda x frequência) são refeitas com
        `focus_deals` mesas em que o jogador TEM aquela mão, seguindo só o
        caminho até a situação (checagem focada), e só são apontadas se
        passarem do limite e de z erros-padrão. Candidatas além de
        max_focus contam como inconclusivas; as refeitas que não se
        confirmam, em `refuted`."""
        tr = self.tree
        n = self.cfg.n
        N = self.tree.n_regrets
        cv = np.zeros(N)
        cw = np.zeros(N)
        nw = np.zeros(N)
        gb = np.full(N, -1, dtype=np.int64)
        gm = np.full(N, -1, dtype=np.int64)
        gmean = np.zeros(N)
        sq = np.zeros(N)
        ev = np.zeros(n)
        _seed(seed)
        _eval_many(deals, n, boards, 1, CLASS_OF_CARDS, *self._arrays(), self.ssum,
                   cv, cw, nw, gb, gm, gmean, sq, ev)
        ev /= deals
        cands = []
        rare = 0
        for nid in np.nonzero(tr.ntype == PLAYER)[0]:
            na = int(tr.nact[nid])
            off = int(tr.regoff[nid])
            for c in range(169):
                j = off + c
                if cw[j] <= 0:
                    continue
                vals = np.array([cv[off + k * 169 + c] for k in range(na)]) / cw[j]
                sig = _avg(self.ssum, off, na, c)
                loss = float(vals.max() - np.dot(sig, vals))
                if loss <= gap_threshold:
                    continue
                if nw[j] / deals < min_node_freq:
                    rare += 1
                    continue
                gb[j] = int(np.argmax(vals))
                gmean[j] = loss
                cands.append((int(nid), c, j, vals, sig, loss))
        # confirmação focada nas candidatas mais importantes (perda x frequência)
        cands.sort(key=lambda x: -x[5] * nw[x[2]])
        todo = [{"node": nid, "hand": CLASSES[c], "freq": float(nw[j] / deals),
                 "situacao": self.describe(nid),
                 "trained": {tr.labels[nid][k]: float(sig[k]) for k in range(len(sig))}}
                for nid, c, j, vals, sig, loss in cands[:max_focus]]
        flags, refuted = self._focus_recheck(todo, focus_deals, boards, seed + 2, gap_threshold, z, threads)
        inconclusive = max(len(cands) - max_focus, 0)
        flags.sort(key=lambda f: -f["gap"] * f["freq"])
        self.last_check_summary = {
            "deals": deals, "candidates": len(cands), "flagged": len(flags),
            "refuted": refuted, "inconclusive": inconclusive, "rare_nodes_skipped": rare,
            "ev_by_seat": {self.cfg.positions[s]: float(ev[s]) for s in range(n)},
        }
        return flags
