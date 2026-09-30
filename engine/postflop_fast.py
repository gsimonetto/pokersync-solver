"""
Solver pós-flop rápido (2026-09-30) -- heads-up, flop/turn/river.

Por que existe: o `PostflopSolver` (engine/postflop.py) percorre a árvore
de apostas uma vez para CADA dupla de classes de mão (até 169 x 169 =
28.561 percursos por iteração). Medido: 0,44 s/iteração no river, 18 s no
turn e mais de vários minutos por iteração no flop -- inviável pra gerar
uma biblioteca de milhares de spots.

Aqui é a técnica dos solvers comerciais ("árvore pública" vetorizada):
a árvore de apostas é percorrida UMA vez por iteração, com um vetor que
carrega TODAS as mãos (combos de verdade, com naipe) ao mesmo tempo, e o
laço quente é compilado com numba.

- Algoritmo: Discounted CFR (alpha=1.5, beta=0, gamma=2), atualizações
  alternadas por jogador.
- Mãos: combos reais (até 1.326), com remoção de cartas exata entre as
  mãos dos dois jogadores e as cartas da mesa.
- Cartas por vir (turn/river): TODAS enumeradas (sem amostragem) -- o
  resultado é determinístico.
- Showdown em O(n) por mesa (ordenação pré-calculada + somas por carta
  bloqueada), o mesmo truque usado nos solvers de referência.
- Valores em fichas (chipEV), na convenção: cada jogador recebe o que
  ganha do pote a partir do início do pós-flop; a soma dos dois é sempre
  `pot` (jogo de soma constante).

Validação: ver tests/postflop_fast.py (exploitability -> 0, MDF exata em
spot polarizado, comparação com engine/postflop.py no river).
"""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from numba import njit

from engine.fast_eval import card_index, eval7
from engine.hand_classes import all_hand_classes

ENGINE_VERSION = "postflop-fast-v1-2026-09-30"

FOLD, SHOWDOWN, CHANCE, PLAYER = 0, 1, 2, 3
OOP, IP = 0, 1

# todas as 1.326 duplas de cartas (índices 0..51, convenção de fast_eval)
ALL_COMBOS = [(a, b) for a in range(52) for b in range(a + 1, 52)]


def _class_of(a, b):
    ranks = "23456789TJQKA"
    hi, lo = max(a >> 2, b >> 2), min(a >> 2, b >> 2)
    name = ranks[hi] + ranks[lo]
    if hi != lo:
        name += "s" if (a & 3) == (b & 3) else "o"
    return name


def parse_board(board):
    if isinstance(board, str):
        board = board.split()
    cards = [card_index(c) if isinstance(c, str) else int(c) for c in board]
    if not 3 <= len(cards) <= 5:
        raise ValueError("board precisa ter 3, 4 ou 5 cartas")
    if len(set(cards)) != len(cards):
        raise ValueError("board com carta repetida")
    return cards


class TreeConfig:
    """Tamanhos de aposta por rua (índice 0=flop, 1=turn, 2=river), como
    fração do pote. Raise: fração do pote DEPOIS de pagar a aposta
    (padrão de mercado). `allin_threshold`: se uma aposta/raise deixaria
    menos que essa fração do stack original atrás, vira all-in."""

    def __init__(self, bet_sizes=((0.33, 0.75), (0.66,), (0.75,)),
                 raise_sizes=((0.75,), (0.75,), (0.75,)),
                 max_raises=2, allin=True, allin_threshold=0.15):
        self.bet_sizes = [list(s) for s in bet_sizes]
        self.raise_sizes = [list(s) for s in raise_sizes]
        self.max_raises = max_raises
        self.allin = allin
        self.allin_threshold = allin_threshold


class _TreeBuilder:
    def __init__(self, board, pot, stack, cfg):
        self.board = list(board)
        self.pot = float(pot)
        self.S = float(stack)
        self.cfg = cfg
        self.ntype, self.nplayer, self.nact, self.cstart = [], [], [], []
        self.children, self.ncard, self.c0, self.c1 = [], [], [], []
        self.nbkey, self.labels, self.hist = [], [], []
        self.bid_of = {}

    def _new(self, typ, player, commit, card, hist):
        nid = len(self.ntype)
        self.ntype.append(typ)
        self.nplayer.append(player)
        self.nact.append(0)
        self.cstart.append(0)
        self.ncard.append(card)
        self.c0.append(commit[0])
        self.c1.append(commit[1])
        self.nbkey.append(-1)
        self.labels.append(())
        self.hist.append(hist)
        return nid

    def _set_children(self, nid, kids, labels=()):
        self.cstart[nid] = len(self.children)
        self.nact[nid] = len(kids)
        self.children.extend(kids)
        self.labels[nid] = tuple(labels)

    def street(self, extra):
        return len(self.board) + len(extra) - 3

    # -- construção --
    def build(self):
        root = self._player(OOP, (), [0.0, 0.0], facing=False, nraises=0, checked=False, card=-1, hist="")
        return root

    def _sizes_to_commits(self, actor, commit, facing, fracs, extra):
        """Converte frações em quanto o `actor` terá colocado no total."""
        S = self.S
        opp = 1 - actor
        pot = self.pot + commit[0] + commit[1]
        out = []
        for f in fracs:
            if facing:
                to_call = commit[opp] - commit[actor]
                target = commit[opp] + f * (pot + to_call)
                min_target = commit[opp] + max(to_call, 1e-9)
                target = max(target, min_target)
            else:
                target = commit[actor] + f * pot
            if target >= S or (S - target) < self.cfg.allin_threshold * S:
                target = S
            out.append(target)
        if self.cfg.allin:
            out.append(S)
        # remove duplicados mantendo ordem
        uniq = []
        for t in out:
            if all(abs(t - u) > 1e-9 for u in uniq) and t > commit[actor] + 1e-9:
                uniq.append(t)
        return uniq

    def _player(self, actor, extra, commit, facing, nraises, checked, card, hist):
        nid = self._new(PLAYER, actor, commit, card, hist)
        st = self.street(extra)
        opp = 1 - actor
        kids, labels = [], []
        if not facing:
            if actor == OOP:
                kids.append(self._player(IP, extra, commit, False, 0, True, -1, hist + "x"))
            else:
                kids.append(self._end_street(extra, commit, hist + "x"))
            labels.append("check")
            for target in self._sizes_to_commits(actor, commit, False, self.cfg.bet_sizes[st], extra):
                nc = list(commit)
                nc[actor] = target
                lab = "allin" if target >= self.S else f"bet{target - commit[actor]:.2f}"
                kids.append(self._player(opp, extra, nc, True, 0, checked, -1, hist + "b"))
                labels.append(lab)
        else:
            kids.append(self._new(FOLD, actor, commit, -1, hist + "f"))
            labels.append("fold")
            nc = list(commit)
            nc[actor] = min(commit[opp], self.S)
            kids.append(self._end_street(extra, nc, hist + "c"))
            labels.append("call")
            can_raise = (nraises < self.cfg.max_raises and commit[opp] < self.S - 1e-9)
            if can_raise:
                for target in self._sizes_to_commits(actor, commit, True, self.cfg.raise_sizes[st], extra):
                    if target <= commit[opp] + 1e-9:
                        continue
                    nc = list(commit)
                    nc[actor] = target
                    lab = "allin" if target >= self.S else f"raise{target:.2f}"
                    kids.append(self._player(opp, extra, nc, True, nraises + 1, checked, -1, hist + "r"))
                    labels.append(lab)
        self._set_children(nid, kids, labels)
        return nid

    def _end_street(self, extra, commit, hist):
        st = self.street(extra)
        allin = commit[0] >= self.S - 1e-9 or commit[1] >= self.S - 1e-9
        if st == 2:
            nid = self._new(SHOWDOWN, -1, commit, -1, hist)
            self.nbkey[nid] = self._bid(extra)
            return nid
        return self._chance(extra, commit, allin, hist)

    def _chance(self, extra, commit, runout, hist):
        nid = self._new(CHANCE, -1, commit, -1, hist + "/")
        used = set(self.board) | set(extra)
        kids = []
        for c in range(52):
            if c in used:
                continue
            ne = extra + (c,)
            if runout:
                if self.street(ne) == 2:
                    k = self._new(SHOWDOWN, -1, commit, c, hist + "/")
                    self.nbkey[k] = self._bid(ne)
                else:
                    k = self._chance(ne, commit, True, hist)
                    self.ncard[k] = c
            else:
                k = self._player(OOP, ne, list(commit), False, 0, False, c, hist + "/")
            kids.append(k)
        self._set_children(nid, kids)
        return nid

    def _bid(self, extra):
        key = tuple(sorted(extra))
        if key not in self.bid_of:
            self.bid_of[key] = len(self.bid_of)
        return self.bid_of[key]


# ---------------------------------------------------------------------------
# núcleo compilado
# ---------------------------------------------------------------------------

@njit(cache=True)
def _regret_match(reg, off, na, n):
    sig = np.empty((na, n))
    for i in range(n):
        s = 0.0
        for a in range(na):
            r = reg[off + a * n + i]
            if r > 0.0:
                s += r
        if s > 0.0:
            for a in range(na):
                r = reg[off + a * n + i]
                sig[a, i] = r / s if r > 0.0 else 0.0
        else:
            for a in range(na):
                sig[a, i] = 1.0 / na
    return sig


@njit(cache=True)
def _avg_strategy(ssum, off, na, n):
    sig = np.empty((na, n))
    for i in range(n):
        s = 0.0
        for a in range(na):
            s += ssum[off + a * n + i]
        if s > 0.0:
            for a in range(na):
                sig[a, i] = ssum[off + a * n + i] / s
        else:
            for a in range(na):
                sig[a, i] = 1.0 / na
    return sig


@njit(cache=True)
def _nonconflict(opp_reach, nopp, oc1, oc2, trav_n, tc1, tc2, same):
    """N(h) = soma do alcance do oponente em combos que NÃO usam as
    cartas de h."""
    card = np.zeros(52)
    tot = 0.0
    for j in range(nopp):
        r = opp_reach[j]
        tot += r
        card[oc1[j]] += r
        card[oc2[j]] += r
    out = np.empty(trav_n)
    for i in range(trav_n):
        v = tot - card[tc1[i]] - card[tc2[i]]
        s = same[i]
        if s >= 0:
            v += opp_reach[s]
        out[i] = v
    return out


@njit(cache=True)
def _showdown(opp_reach, nopp, osd, ovs, trav_n, tsd, tvs, same, win_amt, lose_amt, tie_amt):
    """Valor de showdown de cada mão de trav contra o alcance do oponente,
    em O(n): percorre as mãos por força somando o alcance do oponente
    abaixo/acima, e desconta as mãos do oponente que usam alguma carta de
    h (soma por carta). Empates = total sem conflito - mais fracas - mais
    fortes. sd[0] = índice da mão, sd[1] = força, sd[2]/sd[3] = cartas,
    já ordenados da mais fraca pra mais forte; só as posições >= vs são
    mãos válidas nessa mesa (as outras usam carta da mesa)."""
    out = np.zeros(trav_n)
    al = np.zeros(52)   # por carta: alcance de TODAS as mãos do oponente
    lt = np.zeros(52)   # por carta: alcance do oponente com força < st
    le = np.zeros(52)   # por carta: alcance do oponente com força <= st
    oi, ostr, o1, o2 = osd[0], osd[1], osd[2], osd[3]
    ti, tstr, t1, t2 = tsd[0], tsd[1], tsd[2], tsd[3]
    r_s = np.empty(nopp)  # alcance do oponente já na ordem de força
    tot_al = 0.0
    for j in range(ovs, nopp):
        r = opp_reach[oi[j]]
        r_s[j] = r
        tot_al += r
        al[o1[j]] += r
        al[o2[j]] += r
    tot_lt = 0.0
    tot_le = 0.0
    j_lt = ovs
    j_le = ovs
    # uma passada crescente: "mais fracas" (<) e "mais fracas ou iguais" (<=)
    for k in range(tvs, trav_n):
        st = tstr[k]
        while j_lt < nopp and ostr[j_lt] < st:
            r = r_s[j_lt]
            tot_lt += r
            lt[o1[j_lt]] += r
            lt[o2[j_lt]] += r
            j_lt += 1
        while j_le < nopp and ostr[j_le] <= st:
            r = r_s[j_le]
            tot_le += r
            le[o1[j_le]] += r
            le[o2[j_le]] += r
            j_le += 1
        c1 = t1[k]
        c2 = t2[k]
        weaker = tot_lt - lt[c1] - lt[c2]
        we = tot_le - le[c1] - le[c2]
        stronger = (tot_al - al[c1] - al[c2]) - we
        i = ti[k]
        # a MESMA mão no oponente (mesma força) foi descontada duas vezes
        # (usa c1 e c2): devolve uma vez -- ela conflita, não empata
        sm = same[i]
        ties = we - weaker
        if sm >= 0:
            ties += opp_reach[sm]
        out[i] = weaker * win_amt - stronger * lose_amt + ties * tie_amt
    return out


@njit(cache=True, nogil=True)
def _cfr(node, trav, opp_reach, own_reach, mode,
         ntype, nplayer, nact, cstart, children, ncard, commit, nbid, cfac, regoff,
         reg, ssum, hc, nh, same, sd, vs, pot, fpos, fneg, fstrat):
    """mode 0 = treino (DCFR, atualiza trav); mode 1 = best-response de
    trav contra a estratégia MÉDIA do oponente; mode 2 = avaliação da
    estratégia média dos dois (valor do jogo)."""
    opp = 1 - trav
    tn = nh[trav]
    on = nh[opp]
    t = ntype[node]
    if t == FOLD:
        folder = nplayer[node]
        if folder == trav:
            u = -commit[node, trav]
        else:
            u = pot + commit[node, opp]
        nc = _nonconflict(opp_reach, on, hc[opp, 0], hc[opp, 1], tn, hc[trav, 0], hc[trav, 1], same[trav])
        return nc * u
    if t == SHOWDOWN:
        b = nbid[node]
        c = commit[node, trav]
        return _showdown(opp_reach, on, sd[b, opp], vs[b, opp], tn, sd[b, trav], vs[b, trav], same[trav],
                         pot + c, c, pot * 0.5)
    if t == CHANCE:
        res = np.zeros(tn)
        s0 = cstart[node]
        for k in range(nact[node]):
            ch = children[s0 + k]
            cd = ncard[ch]
            nopp = opp_reach.copy()
            for j in range(on):
                if hc[opp, 0, j] == cd or hc[opp, 1, j] == cd:
                    nopp[j] = 0.0
            nown = own_reach.copy()
            for i in range(tn):
                if hc[trav, 0, i] == cd or hc[trav, 1, i] == cd:
                    nown[i] = 0.0
            v = _cfr(ch, trav, nopp, nown, mode, ntype, nplayer, nact, cstart, children, ncard, commit,
                     nbid, cfac, regoff, reg, ssum, hc, nh, same, sd, vs, pot, fpos, fneg, fstrat)
            for i in range(tn):
                if not (hc[trav, 0, i] == cd or hc[trav, 1, i] == cd):
                    res[i] += v[i]
        f = cfac[node]
        for i in range(tn):
            res[i] *= f
        return res
    # nó de jogador
    actor = nplayer[node]
    na = nact[node]
    s0 = cstart[node]
    off = regoff[node]
    if actor == trav:
        if mode == 0:
            sig = _regret_match(reg, off, na, tn)
        else:
            sig = _avg_strategy(ssum, off, na, tn)
        vals = np.empty((na, tn))
        for a in range(na):
            child_own = own_reach * sig[a]
            vals[a] = _cfr(children[s0 + a], trav, opp_reach, child_own, mode, ntype, nplayer, nact, cstart,
                           children, ncard, commit, nbid, cfac, regoff, reg, ssum, hc, nh, same, sd,
                           vs, pot, fpos, fneg, fstrat)
        nodev = np.zeros(tn)
        if mode == 1:
            for i in range(tn):
                m = vals[0, i]
                for a in range(1, na):
                    if vals[a, i] > m:
                        m = vals[a, i]
                nodev[i] = m
            return nodev
        for a in range(na):
            for i in range(tn):
                nodev[i] += sig[a, i] * vals[a, i]
        if mode == 0:
            for a in range(na):
                for i in range(tn):
                    idx = off + a * tn + i
                    r = reg[idx]
                    r = r * fpos if r > 0.0 else r * fneg
                    reg[idx] = r + (vals[a, i] - nodev[i])
                    ssum[idx] = ssum[idx] * fstrat + own_reach[i] * sig[a, i]
        return nodev
    else:
        if mode == 0:
            sig = _regret_match(reg, off, na, on)
        else:
            sig = _avg_strategy(ssum, off, na, on)
        res = np.zeros(tn)
        for a in range(na):
            # sem "poda" quando o oponente não chega aqui: a média da
            # estratégia de trav nesse ramo TEM que continuar sendo
            # atualizada (senão congela no ruído das primeiras iterações e
            # um adversário que desvia pra cá explora isso)
            nopp = opp_reach * sig[a]
            v = _cfr(children[s0 + a], trav, nopp, own_reach, mode, ntype, nplayer, nact, cstart, children,
                     ncard, commit, nbid, cfac, regoff, reg, ssum, hc, nh, same, sd, vs, pot,
                     fpos, fneg, fstrat)
            res += v
        return res


@njit(cache=True)
def _update(reg, ssum, off, na, tn, vals, nodev, sig, own_reach, fpos, fneg, fstrat):
    for a in range(na):
        for i in range(tn):
            idx = off + a * tn + i
            r = reg[idx]
            r = r * fpos if r > 0.0 else r * fneg
            reg[idx] = r + (vals[a, i] - nodev[i])
            ssum[idx] = ssum[idx] * fstrat + own_reach[i] * sig[a, i]


# ---------------------------------------------------------------------------
# interface
# ---------------------------------------------------------------------------

class FastPostflopSolver:
    """board: 3, 4 ou 5 cartas ('Ah Kd 7s' ou lista). ranges: {classe:
    peso} (ex {'AKs': 1.0, 'QQ': 0.5}) ou {combo: peso} com combos tipo
    'AhKd'. pot/stack em fichas (big blinds), stack = efetivo que ainda
    resta ATRÁS no início do pós-flop."""

    def __init__(self, board, range_oop, range_ip, pot, stack, config=None, threads=None):
        if pot <= 0 or stack <= 0:
            raise ValueError("pot e stack precisam ser positivos")
        self.board = parse_board(board)
        self.pot = float(pot)
        self.stack = float(stack)
        self.cfg = config or TreeConfig()
        self.hands = [self._combos(range_oop, "range_oop"), self._combos(range_ip, "range_ip")]
        if not self.hands[0][0] or not self.hands[1][0]:
            raise ValueError("range vazio depois de remover as cartas da mesa")
        self._build()
        self.iterations = 0
        self.threads = threads or os.cpu_count() or 1
        self._pool = None

    # -- ranges --
    def _combos(self, rng, label):
        classes = set(all_hand_classes())
        board = set(self.board)
        weights = {}
        for key, w in rng.items():
            if w < 0:
                raise ValueError(f"{label}: peso negativo em {key}")
            if w == 0:
                continue
            if key in classes:
                for a, b in ALL_COMBOS:
                    if _class_of(a, b) == key:
                        weights[(a, b)] = weights.get((a, b), 0.0) + w
            elif len(key) == 4:
                a, b = card_index(key[:2]), card_index(key[2:])
                if a == b:
                    raise ValueError(f"{label}: combo inválido {key}")
                weights[(min(a, b), max(a, b))] = weights.get((min(a, b), max(a, b)), 0.0) + w
            else:
                raise ValueError(f"{label}: mão inválida {key!r} (use 'AKs', 'QQ' ou 'AhKd')")
        combos = [c for c in sorted(weights) if c[0] not in board and c[1] not in board]
        return combos, np.array([weights[c] for c in combos], dtype=np.float64)

    # -- árvore e tabelas --
    def _build(self):
        tb = _TreeBuilder(self.board, self.pot, self.stack, self.cfg)
        tb.build()
        self.tb = tb
        n = len(tb.ntype)
        self.ntype = np.array(tb.ntype, dtype=np.int64)
        self.nplayer = np.array(tb.nplayer, dtype=np.int64)
        self.nact = np.array(tb.nact, dtype=np.int64)
        self.cstart = np.array(tb.cstart, dtype=np.int64)
        self.children = np.array(tb.children if tb.children else [0], dtype=np.int64)
        self.ncard = np.array(tb.ncard, dtype=np.int64)
        self.commit = np.stack([np.array(tb.c0), np.array(tb.c1)], axis=1).astype(np.float64)
        self.nbid = np.array(tb.nbkey, dtype=np.int64)
        # fator de chance: 1 / (cartas não vistas por NENHUM dos dois)
        cfac = np.zeros(n)
        for nid in range(n):
            if tb.ntype[nid] == CHANCE:
                cfac[nid] = 1.0 / (tb.nact[nid] - 4)
        self.cfac = cfac
        nh = np.array([len(self.hands[0][0]), len(self.hands[1][0])], dtype=np.int64)
        self.nh = nh
        nmax = int(nh.max())
        hc = np.full((2, 2, nmax), -1, dtype=np.int64)
        for p in range(2):
            for i, (a, b) in enumerate(self.hands[p][0]):
                hc[p, 0, i] = a
                hc[p, 1, i] = b
        self.hc = hc
        same = np.full((2, nmax), -1, dtype=np.int64)
        idx = [{c: i for i, c in enumerate(self.hands[p][0])} for p in range(2)]
        for p in range(2):
            for i, c in enumerate(self.hands[p][0]):
                same[p, i] = idx[1 - p].get(c, -1)
        self.same = same
        # offsets de regret por nó de jogador
        regoff = np.zeros(n, dtype=np.int64)
        tot = 0
        for nid in range(n):
            if tb.ntype[nid] == PLAYER:
                regoff[nid] = tot
                tot += tb.nact[nid] * int(nh[tb.nplayer[nid]])
        self.regoff = regoff
        self.reg = np.zeros(max(tot, 1), dtype=np.float32)
        self.ssum = np.zeros(max(tot, 1), dtype=np.float32)
        # força de cada mão em cada mesa final (river)
        nb = max(len(tb.bid_of), 1)
        strength = np.full((nb, 2, nmax), -1, dtype=np.int64)
        order = np.zeros((nb, 2, nmax), dtype=np.int64)
        for key, b in tb.bid_of.items():
            full = self.board + list(key)
            fs = set(full)
            for p in range(2):
                for i, (c1, c2) in enumerate(self.hands[p][0]):
                    if c1 in fs or c2 in fs:
                        continue
                    strength[b, p, i] = eval7(full + [c1, c2])
                o = np.argsort(strength[b, p, :nh[p]], kind="stable")
                order[b, p, :nh[p]] = o
        self.strength = strength
        # mesma informação ordenada por força, pro showdown ler em sequência
        sd = np.zeros((nb, 2, 4, nmax), dtype=np.int64)
        vs = np.zeros((nb, 2), dtype=np.int64)
        for b in range(nb):
            for p in range(2):
                n_p = int(nh[p])
                o = order[b, p, :n_p]
                sd[b, p, 0, :n_p] = o
                sd[b, p, 1, :n_p] = strength[b, p, o]
                sd[b, p, 2, :n_p] = self.hc[p, 0, o]
                sd[b, p, 3, :n_p] = self.hc[p, 1, o]
                vs[b, p] = int(np.sum(strength[b, p, :n_p] < 0))
        self.sd = sd
        self.vs = vs

    @property
    def n_nodes(self):
        return len(self.ntype)

    def _run(self, trav, mode, fpos=1.0, fneg=1.0, fstrat=1.0):
        opp = 1 - trav
        f = (fpos, fneg, fstrat)
        return self._drive(0, trav, self.hands[opp][1].copy(), self.hands[trav][1].copy(), mode, f)

    def _numba(self, node, trav, opp_reach, own_reach, mode, f):
        return _cfr(node, trav, opp_reach, own_reach, mode,
                    self.ntype, self.nplayer, self.nact, self.cstart, self.children, self.ncard,
                    self.commit, self.nbid, self.cfac, self.regoff, self.reg, self.ssum, self.hc,
                    self.nh, self.same, self.sd, self.vs, self.pot, f[0], f[1], f[2])

    def _drive(self, node, trav, opp_reach, own_reach, mode, f):
        """Mesma conta de `_cfr`, mas feita em Python nos nós de ANTES da
        primeira carta por vir, pra dividir as cartas (turn/river) entre
        vários núcleos do processador: cada carta é uma subárvore
        independente (regrets em posições diferentes), então as threads
        não se atrapalham. Resultado idêntico ao `_cfr` puro."""
        t = self.ntype[node]
        if t == CHANCE:
            if self.threads <= 1:
                return self._numba(node, trav, opp_reach, own_reach, mode, f)
            hc = self.hc
            s0 = self.cstart[node]
            kids = [int(self.children[s0 + k]) for k in range(self.nact[node])]

            def one(ch):
                cd = self.ncard[ch]
                o_ok = (hc[1 - trav, 0] != cd) & (hc[1 - trav, 1] != cd)
                t_ok = (hc[trav, 0] != cd) & (hc[trav, 1] != cd)
                v = self._numba(ch, trav, opp_reach * o_ok[:len(opp_reach)],
                                own_reach * t_ok[:len(own_reach)], mode, f)
                return v * t_ok[:len(own_reach)]

            if self._pool is None:
                self._pool = ThreadPoolExecutor(self.threads)
            parts = list(self._pool.map(one, kids))
            return np.sum(parts, axis=0) * self.cfac[node]
        if t != PLAYER:
            return self._numba(node, trav, opp_reach, own_reach, mode, f)
        actor = self.nplayer[node]
        na = int(self.nact[node])
        s0 = self.cstart[node]
        off = int(self.regoff[node])
        n = int(self.nh[actor])
        sig = _regret_match(self.reg, off, na, n) if mode == 0 else _avg_strategy(self.ssum, off, na, n)
        kids = [int(self.children[s0 + a]) for a in range(na)]
        if actor != trav:
            return sum(self._drive(kids[a], trav, opp_reach * sig[a], own_reach, mode, f) for a in range(na))
        vals = np.array([self._drive(kids[a], trav, opp_reach, own_reach * sig[a], mode, f) for a in range(na)])
        if mode == 1:
            return vals.max(axis=0)
        nodev = (sig * vals).sum(axis=0)
        if mode == 0:
            _update(self.reg, self.ssum, off, na, n, vals, nodev, sig, own_reach, f[0], f[1], f[2])
        return nodev

    def train(self, iterations, alpha=1.5, beta=0.0, gamma=2.0):
        for _ in range(iterations):
            self.iterations += 1
            t = self.iterations
            ta = t ** alpha
            fpos = ta / (ta + 1.0)
            fneg = (t ** beta) / (t ** beta + 1.0)
            fstrat = (t / (t + 1.0)) ** gamma
            for trav in (OOP, IP):
                self._run(trav, 0, fpos, fneg, fstrat)

    # -- avaliação --
    def _pair_mass(self, p):
        """Soma dos pesos de todas as duplas (mão de p, mão do oponente)
        sem carta em comum -- normalizador do valor esperado."""
        opp = 1 - p
        nc = _nonconflict(self.hands[opp][1], self.nh[opp], self.hc[opp, 0], self.hc[opp, 1],
                          self.nh[p], self.hc[p, 0], self.hc[p, 1], self.same[p])
        return float(np.dot(self.hands[p][1], nc))

    def expected_values(self):
        """Valor esperado (fichas) de cada jogador com as estratégias
        médias dos dois. Soma = pot."""
        out = []
        for p in (OOP, IP):
            cfv = self._run(p, 2)
            out.append(float(np.dot(self.hands[p][1], cfv)) / self._pair_mass(p))
        return out

    def best_response_values(self):
        out = []
        for p in (OOP, IP):
            cfv = self._run(p, 1)
            out.append(float(np.dot(self.hands[p][1], cfv)) / self._pair_mass(p))
        return out

    def exploitability(self):
        """Quanto (em fichas, média dos dois jogadores) um adversário
        perfeito ganharia a mais contra a estratégia média. 0 = equilíbrio."""
        br = self.best_response_values()
        return (br[0] + br[1] - self.pot) / 2.0

    def exploitability_pct(self):
        return 100.0 * self.exploitability() / self.pot

    # -- leitura da estratégia --
    def node_strategy(self, nid):
        """Estratégia média num nó de jogador: (labels, matriz [ações x combos], combos)."""
        if self.ntype[nid] != PLAYER:
            raise ValueError("não é nó de jogador")
        p = int(self.nplayer[nid])
        n = int(self.nh[p])
        sig = _avg_strategy(self.ssum, int(self.regoff[nid]), int(self.nact[nid]), n)
        return self.tb.labels[nid], sig, self.hands[p][0]

    def child(self, nid, label):
        labels = self.tb.labels[nid]
        return int(self.children[self.cstart[nid] + labels.index(label)])

    def root_strategy_by_class(self, nid=0):
        """{classe: {ação: frequência}} ponderando cada combo pelo peso do
        range (só vale exatamente na raiz; nós mais fundos precisariam do
        alcance de cada combo)."""
        labels, sig, combos = self.node_strategy(nid)
        p = int(self.nplayer[nid])
        w = self.hands[p][1]
        agg = {}
        for i, (a, b) in enumerate(combos):
            cl = _class_of(a, b)
            d = agg.setdefault(cl, [0.0, np.zeros(len(labels))])
            d[0] += w[i]
            d[1] += w[i] * sig[:, i]
        return {cl: {lab: float(v[1][k] / v[0]) for k, lab in enumerate(labels)} for cl, v in agg.items() if v[0] > 0}
