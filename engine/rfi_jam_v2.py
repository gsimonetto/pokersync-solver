"""
RFI/Jam heads-up v2 -- ante, call do BB com realização de equity e
all-in direto de quem abre (2026-10).

Por que existe (reportado no Treino do PokerSync, BTN vs BB com 10 bb):
o motor v1 (engine/rfi_jam.py) só deixava quem abre escolher entre fold
e raise 2,2 -- o all-in direto não existia, e o BB, diante do raise, só
podia foldar ou dar all-in (pagar exigiria pós-flop, que o motor não
calcula). Resultado: com stack curto o raise pequeno ficava bom demais e
o "GTO" mandava dar raise em mãos que, na prática, vão de all-in. E não
havia ante, que todo torneio atual usa.

Árvore (um tamanho de abertura R):
  1. Quem abre (opener): fold, raise R ou all-in.
  2a. BB diante do raise: fold, call ou all-in.
      - call: a mão vai pro flop. Sem pós-flop no motor, o pote é dividido
        pela EQUITY REALIZADA (ver abaixo) -- aproximação declarada.
      - all-in: quem abriu decide fold ou call (showdown).
  2b. BB diante do all-in direto: fold ou call (showdown).

Ante: BB ante (o BB paga `ante` bb de ante, dinheiro morto no pote) -- o
formato padrão dos torneios atuais. O ante NÃO entra no all-in (é morto):
o BB disputa no máximo T - ante.

Realização de equity (só no call do BB): quanto da equity cada um
consegue transformar em fichas jogando as ruas seguintes. Duas coisas
pesam, como nas tabelas de realização dos solvers:
  - posição: quem joga sem posição aproveita menos. Base do jogador sem
    posição: 1 - 0.15 * min(1, SPR / 4) (SPR = fichas atrás / pote depois
    do call; SPR baixo = a mão vai quase toda pro showdown, ~100%;
    fundo, ~85%). Com posição: 1.
  - força da mão: mão fraca (pouca equity) desiste mais nas ruas
    seguintes e realiza menos; mão forte ganha mais que a equity crua.
    Fator 1 + k * (eq - 0.5) (limitado entre 0,4 e 1,25), k = 2 pra quem
    está sem posição e k/2 pra quem tem posição. k foi calibrado pra o BB
    foldar ~10-20% contra o raise do BTN (20-40 bb, com ante), a faixa
    que os solvers de referência mostram -- sem esse fator o BB nunca
    foldava, já que com ante o preço do call é muito bom.
A fatia do pote de quem abre é s = eq*r_o / (eq*r_o + (1-eq)*r_b).
Sob ICM o pote é tratado como uma loteria (ganha o pote inteiro com
probabilidade s) -- respeita o risco de ICM melhor que dividir fichas.

Algoritmo: CFR+ com todas as duplas de classes de uma vez (169 x 169,
numpy), pesos de remoção de cartas reais (engine.card_removal) -- sem
sorteio, então não há mão "esquecida" num nó pouco visitado (o problema
recorrente do v1 registrado no CLAUDE.md). Melhor resposta exata pra
medir o quanto a estratégia pode ser explorada.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.card_removal import pair_counts  # noqa: E402
from engine.icm import icm_equity  # noqa: E402

ENGINE_VERSION = "pokersync-solver-v0.5.0-rfi-jam-v2-ante-eqr"


def _normalize(regret):
    pos = np.maximum(regret, 0.0)
    tot = pos.sum(axis=1, keepdims=True)
    n = regret.shape[1]
    return np.where(tot > 0, pos / np.where(tot > 0, tot, 1.0), 1.0 / n)


class RfiJamV2:
    # índices das ações
    ROOT = ("fold", "raise", "jam")
    VS_RAISE = ("fold", "call", "jam")
    VS_JAM = ("fold", "call")

    def __init__(self, table_stacks, payouts, equity_matrix, classes, open_size=2.2,
                 effective_stack=None, opener_post=0.5, defender_post=1.0, dead_money=0.0,
                 ante=1.0, opener_in_position=False, use_icm=True, oop_realization_drop=0.15,
                 strength_k=2.0):
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.use_icm = use_icm
        self.classes = list(classes)
        n = len(self.classes)
        self.n = n
        self.R = float(open_size)
        self.T = float(effective_stack or min(table_stacks[0], table_stacks[1]))
        self.op, self.dp, self.dm, self.A = float(opener_post), float(defender_post), float(dead_money), float(ante)
        # all-in efetivo: o BB tem T - ante pra apostar (o ante é morto)
        self.E = self.T - self.A

        counts = pair_counts(self.classes)
        W = np.array([[counts[a][b] for b in self.classes] for a in self.classes], dtype=float)
        self.W = W / W.sum()  # P(opener i, BB j) com remoção de cartas
        self.eq = np.array([[equity_matrix[(a, b)] if a != b else 0.5 for b in self.classes] for a in self.classes])

        # --- terminais (deltas de fichas -> utilidade de cada um) ---
        op, dp, dm, A, E, R = self.op, self.dp, self.dm, self.A, self.E, self.R
        self.u_fold_root = self._pair(-op, +op)
        self.u_bb_fold = self._pair(+dp + A + dm, -dp - A)
        self.u_sd_o = self._pair(+E + A + dm, -E - A)   # opener ganha o all-in
        self.u_sd_b = self._pair(-E, +E + dm)           # BB ganha o all-in
        self.u_ofold_vs_bbjam = self._pair(-R, +R + dm)
        pot_call = 2 * R + A + dm
        self.u_cr_o = self._pair(pot_call - R, -R - A)  # opener leva o pote do call
        self.u_cr_b = self._pair(-R, pot_call - R - A)  # BB leva o pote do call

        # realização de equity no call do BB
        spr = max(0.0, (self.E - R)) / pot_call
        r_oop = 1.0 - oop_realization_drop * min(1.0, spr / 4.0)
        base_o, base_b = (1.0, r_oop) if opener_in_position else (r_oop, 1.0)
        k_o, k_b = (strength_k / 2, strength_k) if opener_in_position else (strength_k, strength_k / 2)
        self.realization = (base_o, base_b)
        r_o = base_o * np.clip(1 + k_o * (self.eq - 0.5), 0.4, 1.25)
        r_b = base_b * np.clip(1 + k_b * ((1 - self.eq) - 0.5), 0.4, 1.25)
        num = self.eq * r_o
        self.share_o = num / (num + (1 - self.eq) * r_b)

        # matrizes de utilidade por dupla (opener i, BB j)
        self.SD_o = self.eq * self.u_sd_o[0] + (1 - self.eq) * self.u_sd_b[0]
        self.SD_b = self.eq * self.u_sd_o[1] + (1 - self.eq) * self.u_sd_b[1]
        self.CR_o = self.share_o * self.u_cr_o[0] + (1 - self.share_o) * self.u_cr_b[0]
        self.CR_b = self.share_o * self.u_cr_o[1] + (1 - self.share_o) * self.u_cr_b[1]

        # valor de 1 bb (escala do motor) perto do stack do opener
        up = self._util_o_stack(+1.0)
        down = self._util_o_stack(-1.0)
        self.icm_por_bb = (up - down) / 2.0

        # regrets / médias
        self.reg = {k: np.zeros((n, m)) for k, m in (("root", 3), ("vs_raise", 3), ("vs_bbjam", 2), ("vs_jam", 2))}
        self.avg = {k: np.zeros_like(v) for k, v in self.reg.items()}

    # ------------------------------------------------------------------
    def _pair(self, d_o, d_b):
        if not self.use_icm:
            return (d_o, d_b)
        st = list(self.table_stacks)
        st[0] = max(0.0, st[0] + d_o)
        st[1] = max(0.0, st[1] + d_b)
        e = icm_equity(st, self.payouts)
        return (e[0], e[1])

    def _util_o_stack(self, d):
        if not self.use_icm:
            return d
        st = list(self.table_stacks)
        st[0] += d
        st[1] -= d
        return icm_equity(st, self.payouts)[0]

    # ------------------------------------------------------------------
    def _values(self, s):
        """Valores por dupla (i, j) dado o perfil s (dict de estratégias)."""
        root, vr, vbj, vj = s["root"], s["vs_raise"], s["vs_bbjam"], s["vs_jam"]
        # depois do jam do BB (opener decide)
        BJ_o = vbj[:, [0]] * self.u_ofold_vs_bbjam[0] + vbj[:, [1]] * self.SD_o
        BJ_b = vbj[:, [0]] * self.u_ofold_vs_bbjam[1] + vbj[:, [1]] * self.SD_b
        # depois do raise (BB decide; vr indexado por j -> colunas)
        f, c, j = vr[:, 0][None, :], vr[:, 1][None, :], vr[:, 2][None, :]
        RA_o = f * self.u_bb_fold[0] + c * self.CR_o + j * BJ_o
        RA_b = f * self.u_bb_fold[1] + c * self.CR_b + j * BJ_b
        # depois do jam direto (BB decide)
        jf, jc = vj[:, 0][None, :], vj[:, 1][None, :]
        JA_o = jf * self.u_bb_fold[0] + jc * self.SD_o
        JA_b = jf * self.u_bb_fold[1] + jc * self.SD_b
        return BJ_o, BJ_b, RA_o, RA_b, JA_o, JA_b

    def train(self, iterations=3000):
        W = self.W
        for t in range(1, iterations + 1):
            s = {k: _normalize(r) for k, r in self.reg.items()}
            root, vr, vbj, vj = s["root"], s["vs_raise"], s["vs_bbjam"], s["vs_jam"]
            BJ_o, BJ_b, RA_o, RA_b, JA_o, JA_b = self._values(s)

            # opener na raiz: cfv por ação (alcance do BB = 1)
            cf_root = np.stack([
                W.sum(axis=1) * self.u_fold_root[0],
                (W * RA_o).sum(axis=1),
                (W * JA_o).sum(axis=1),
            ], axis=1)
            # opener diante do jam do BB: alcance do BB = prob de jam dele
            Wbj = W * vr[:, 2][None, :]
            cf_bj = np.stack([Wbj.sum(axis=1) * self.u_ofold_vs_bbjam[0], (Wbj * self.SD_o).sum(axis=1)], axis=1)
            # BB diante do raise: alcance do opener = prob de raise
            Wr = W * root[:, [1]]
            cf_vr = np.stack([
                Wr.sum(axis=0) * self.u_bb_fold[1],
                (Wr * self.CR_b).sum(axis=0),
                (Wr * BJ_b).sum(axis=0),
            ], axis=1)
            # BB diante do jam direto: alcance do opener = prob de jam
            Wj = W * root[:, [2]]
            cf_vj = np.stack([Wj.sum(axis=0) * self.u_bb_fold[1], (Wj * self.SD_b).sum(axis=0)], axis=1)

            for key, cf, strat, own in (
                ("root", cf_root, root, None),
                ("vs_bbjam", cf_bj, vbj, root[:, 1]),
                ("vs_raise", cf_vr, vr, None),
                ("vs_jam", cf_vj, vj, None),
            ):
                node = (cf * strat).sum(axis=1, keepdims=True)
                self.reg[key] = np.maximum(self.reg[key] + (cf - node), 0.0)  # CFR+
                w = t if own is None else t * own[:, None]
                self.avg[key] += w * strat

    def average_strategy(self):
        out = {}
        for k, a in self.avg.items():
            tot = a.sum(axis=1, keepdims=True)
            cur = _normalize(self.reg[k])
            out[k] = np.where(tot > 1e-12, a / np.where(tot > 1e-12, tot, 1.0), cur)
        return out

    # ------------------------------------------------------------------
    def action_evs(self, s=None):
        """EV (escala do motor) de cada ação, por classe, contra o perfil s.
        Retorna dict de matrizes [n, ações]; nós de quem responde são
        condicionados no range que chega neles (se ninguém chega, usa a
        distribuição sem filtro)."""
        s = s or self.average_strategy()
        W = self.W
        BJ_o, BJ_b, RA_o, RA_b, JA_o, JA_b = self._values(s)
        root = s["root"]
        mo = W.sum(axis=1)
        ev_root = np.stack([np.full(self.n, self.u_fold_root[0]), (W * RA_o).sum(1) / mo, (W * JA_o).sum(1) / mo], axis=1)

        def cond(Wx, M, axis):
            reach = Wx.sum(axis=axis)
            base = W.sum(axis=axis)
            num = (Wx * M).sum(axis=axis)
            alt = (W * M).sum(axis=axis)
            return np.where(reach > 1e-12, num / np.where(reach > 1e-12, reach, 1.0), alt / base)

        Wbj = W * s["vs_raise"][:, 2][None, :]
        ev_bj = np.stack([np.full(self.n, self.u_ofold_vs_bbjam[0]), cond(Wbj, self.SD_o, 1)], axis=1)
        Wr = W * root[:, [1]]
        ev_vr = np.stack([np.full(self.n, self.u_bb_fold[1]), cond(Wr, self.CR_b, 0), cond(Wr, BJ_b, 0)], axis=1)
        Wj = W * root[:, [2]]
        ev_vj = np.stack([np.full(self.n, self.u_bb_fold[1]), cond(Wj, self.SD_b, 0)], axis=1)
        return {"root": ev_root, "vs_bbjam": ev_bj, "vs_raise": ev_vr, "vs_jam": ev_vj}

    def exploitability(self, s=None):
        """Quanto cada jogador ganharia (escala do motor, média por mão)
        trocando sozinho pra melhor resposta. (expl_opener, expl_bb)."""
        s = s or self.average_strategy()
        W = self.W
        BJ_o, BJ_b, RA_o, RA_b, JA_o, JA_b = self._values(s)
        root = s["root"]
        # valor do perfil
        Vo = (W * (root[:, [0]] * self.u_fold_root[0] + root[:, [1]] * RA_o + root[:, [2]] * JA_o)).sum()
        Vb = (W * (root[:, [0]] * self.u_fold_root[1] + root[:, [1]] * RA_b + root[:, [2]] * JA_b)).sum()
        # melhor resposta do opener: primeiro o nó diante do jam do BB
        Wbj = W * s["vs_raise"][:, 2][None, :]
        best_bj = np.maximum(Wbj.sum(1) * self.u_ofold_vs_bbjam[0], (Wbj * self.SD_o).sum(1))
        vr = s["vs_raise"]
        raise_br = (W * (vr[:, 0][None, :] * self.u_bb_fold[0] + vr[:, 1][None, :] * self.CR_o)).sum(1) + best_bj
        jam_v = (W * JA_o).sum(1)
        fold_v = W.sum(1) * self.u_fold_root[0]
        BRo = np.maximum(np.maximum(fold_v, raise_br), jam_v).sum()
        # melhor resposta do BB
        Wr = W * root[:, [1]]
        Wj = W * root[:, [2]]
        br_r = np.maximum(np.maximum(Wr.sum(0) * self.u_bb_fold[1], (Wr * self.CR_b).sum(0)), (Wr * BJ_b).sum(0))
        br_j = np.maximum(Wj.sum(0) * self.u_bb_fold[1], (Wj * self.SD_b).sum(0))
        Wf = W * root[:, [0]]
        BRb = (Wf.sum(0) * self.u_fold_root[1] + br_r + br_j).sum()
        return BRo - Vo, BRb - Vb

    def training_strategy(self, min_reach=0.10):
        """Estratégia pra gravar/treinar. Igual à média, exceto no nó de
        quem abriu diante do all-in do BB: pra mão que quase nunca dá raise
        (< min_reach), a média nesse nó não aprendeu nada (quase não é
        alcançado) -- usa a melhor ação pelo EV, o que um solver mostra num
        nó pouco visitado. Mesmo cuidado do fix_rarely_reached_call do v1."""
        s = self.average_strategy()
        ev = self.action_evs(s)
        rare = s["root"][:, 1] < min_reach
        best = np.zeros_like(s["vs_bbjam"])
        best[np.arange(self.n), ev["vs_bbjam"].argmax(axis=1)] = 1.0
        s["vs_bbjam"] = np.where(rare[:, None], best, s["vs_bbjam"])
        return s

    def totals(self, s=None):
        """Frequência total de cada ação (ponderada pelos combos)."""
        s = s or self.average_strategy()
        wm, wb = self.W.sum(1), self.W.sum(0)
        return {
            "opener": {a: float(wm @ s["root"][:, k]) for k, a in enumerate(self.ROOT)},
            "bb_vs_raise": {a: float(wb @ s["vs_raise"][:, k]) for k, a in enumerate(self.VS_RAISE)},
            "bb_vs_jam": {a: float(wb @ s["vs_jam"][:, k]) for k, a in enumerate(self.VS_JAM)},
        }
