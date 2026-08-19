"""
Solver de shove/fold heads-up pré-flop (o caso mais simples de árvore
pré-flop: 2 jogadores, 2 decisões binárias). Reaproveita o núcleo de
regret matching / Discounted CFR já validado em Kuhn Poker — aqui
cada "infoset" é uma classe de mão (169 no total) em vez de uma carta
de baralho, e o número de "deals" possíveis é 169x169 em vez de 6.

Estrutura do jogo (chip EV, sem ICM ainda):
  SB tem stack T bb, decide Push (all-in) ou Fold.
  Se Push: BB decide Call ou Fold.
    Fold -> SB ganha o blind da BB (+1bb pra SB, -1bb pra BB).
    Call -> showdown pelos T bb de cada um, resolvido pela equity.
  Se Fold (SB) -> SB perde o small blind postado (-0.5bb), BB +0.5bb.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, combo_count, build_equity_matrix  # noqa: E402


class PushFoldSolver:
    def __init__(self, stack_bb: float, equity_matrix=None, classes=None):
        self.stack_bb = stack_bb
        if equity_matrix is None or classes is None:
            self.equity_matrix, self.classes = build_equity_matrix(iterations=300)
        else:
            self.equity_matrix, self.classes = equity_matrix, classes
        self.n = len(self.classes)
        self.weights = np.array([combo_count(c) for c in self.classes], dtype=float)
        self.weights_norm = self.weights / self.weights.sum()

        # matriz de equity[i][j] = equity da classe i contra a classe j
        self.equity = np.zeros((self.n, self.n))
        for i, ci in enumerate(self.classes):
            for j, cj in enumerate(self.classes):
                self.equity[i, j] = self.equity_matrix[(ci, cj)]

        # regrets/estrategia acumulada: [classe][0]=fold, [1]=push_ou_call
        self.sb_regret = np.zeros((self.n, 2))
        self.sb_strategy_sum = np.zeros((self.n, 2))
        self.bb_regret = np.zeros((self.n, 2))
        self.bb_strategy_sum = np.zeros((self.n, 2))

    @staticmethod
    def _regret_matching(regret_row):
        positive = np.maximum(regret_row, 0.0)
        total = positive.sum()
        if total > 0:
            return positive / total
        return np.array([0.5, 0.5])

    def _current_strategy(self, regret):
        return np.array([self._regret_matching(regret[i]) for i in range(regret.shape[0])])

    def train(self, iterations=3000, alpha_pow=1.5, beta_pow=0.0, gamma_pow=2.0):
        chip_ev_call = self.stack_bb * (2 * self.equity - 1)  # [sb_class][bb_class], EV do SB no call

        for t in range(1, iterations + 1):
            sb_strategy = self._current_strategy(self.sb_regret)  # [n][2]
            bb_strategy = self._current_strategy(self.bb_regret)  # [n][2]

            bb_call_prob = bb_strategy[:, 1]  # prob de call por classe da BB

            # --- valor de SB por classe ---
            ev_fold_sb = -0.5 * np.ones(self.n)
            # EV de push por classe do SB: media sobre classes da BB, ponderada
            ev_push_sb = (self.weights_norm[np.newaxis, :] *
                          (chip_ev_call * bb_call_prob[np.newaxis, :] +
                           1.0 * (1 - bb_call_prob)[np.newaxis, :])).sum(axis=1)

            node_value_sb = sb_strategy[:, 0] * ev_fold_sb + sb_strategy[:, 1] * ev_push_sb
            self.sb_regret[:, 0] += (ev_fold_sb - node_value_sb)
            self.sb_regret[:, 1] += (ev_push_sb - node_value_sb)

            # --- valor de BB por classe (condicionado a SB ter dado push) ---
            sb_push_prob = sb_strategy[:, 1]
            reach_sb = self.weights_norm * sb_push_prob  # peso de cada classe do SB, dado que empurrou

            ev_fold_bb = -1.0 * np.ones(self.n)  # constante, nao depende da classe da BB
            # chip_ev_call[i][j] = EV do SB (classe i) vs BB (classe j); para BB e o negativo
            chip_ev_call_bb = -chip_ev_call  # [sb_class][bb_class] -> BB perspective
            reach_sum = reach_sb.sum()
            if reach_sum > 0:
                ev_call_bb = (reach_sb[:, np.newaxis] * chip_ev_call_bb).sum(axis=0) / reach_sum
            else:
                ev_call_bb = np.zeros(self.n)

            node_value_bb = bb_strategy[:, 0] * ev_fold_bb + bb_strategy[:, 1] * ev_call_bb
            # regret ponderado pelo alcance (reach_sum) -- reflete o quanto
            # esse infoset da BB "importa" dado a estrategia atual do SB
            self.bb_regret[:, 0] += reach_sum * (ev_fold_bb - node_value_bb)
            self.bb_regret[:, 1] += reach_sum * (ev_call_bb - node_value_bb)

            # acumular estrategia media (Discounted CFR)
            self.sb_strategy_sum += sb_strategy
            self.bb_strategy_sum += bb_strategy

            # discount (Discounted CFR)
            pos_factor = (t ** alpha_pow) / ((t ** alpha_pow) + 1)
            neg_factor = (t ** beta_pow) / ((t ** beta_pow) + 1)
            strat_factor = (t / (t + 1)) ** gamma_pow
            self.sb_regret = np.where(self.sb_regret > 0, self.sb_regret * pos_factor, self.sb_regret * neg_factor)
            self.bb_regret = np.where(self.bb_regret > 0, self.bb_regret * pos_factor, self.bb_regret * neg_factor)
            self.sb_strategy_sum *= strat_factor
            self.bb_strategy_sum *= strat_factor

    def average_strategy(self):
        sb_avg = self.sb_strategy_sum / self.sb_strategy_sum.sum(axis=1, keepdims=True).clip(min=1e-12)
        bb_avg = self.bb_strategy_sum / self.bb_strategy_sum.sum(axis=1, keepdims=True).clip(min=1e-12)
        return {
            "sb_push": {c: sb_avg[i, 1] for i, c in enumerate(self.classes)},
            "bb_call": {c: bb_avg[i, 1] for i, c in enumerate(self.classes)},
        }


if __name__ == "__main__":
    print("Construindo matriz de equity 169x169 (uma vez, reaproveitada em todos os stacks)...")
    equity_matrix, classes = build_equity_matrix(iterations=250)

    for stack in (10, 15, 20):
        solver = PushFoldSolver(stack_bb=stack, equity_matrix=equity_matrix, classes=classes)
        solver.train(iterations=2000)
        strat = solver.average_strategy()

        push_range = sorted(
            [c for c in classes if strat["sb_push"][c] > 0.5],
            key=lambda c: -strat["sb_push"][c],
        )
        n_push_combos = sum(combo_count(c) for c in push_range)
        pct = 100 * n_push_combos / 1326

        print(f"\n=== Stack {stack}bb ===")
        print(f"SB push range: {len(push_range)} classes, {n_push_combos}/1326 combos ({pct:.1f}%)")
        print(f"  Exemplos no topo do range: {push_range[:8]}")
        print(f"  AA push freq: {strat['sb_push']['AA']:.3f} (esperado ~1.0)")
        print(f"  72o push freq: {strat['sb_push']['72o']:.3f} (esperado baixo)")
        print(f"  AKo push freq: {strat['sb_push']['AKo']:.3f} (esperado ~1.0, mao forte)")
