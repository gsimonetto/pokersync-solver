"""
Push/Fold heads-up com ICM: mesma árvore de decisão do pushfold.py,
mas os valores terminais são $EV via Malmuth-Harville (considerando
os stacks de TODOS os jogadores da mesa, não só SB/BB), em vez de
chip EV puro. Isso é o que muda o range perto de bolha/mesa final.

Diferença importante em relação ao chip EV: aqui SB e BB não estão
mais em um jogo estritamente de soma zero entre si (parte do $ pode
"vazar" pra equity dos outros jogadores da mesa dependendo do
resultado), então cada um maximiza sua própria regret de forma
independente — é assim que solvers de ICM reais funcionam.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, combo_count, build_equity_matrix  # noqa: E402
from engine.icm import icm_equity  # noqa: E402


class PushFoldICMSolver:
    def __init__(self, sb_idx, bb_idx, table_stacks, payouts, equity_matrix, classes):
        """
        sb_idx, bb_idx: indices de SB e BB dentro de `table_stacks`.
        table_stacks: lista de stacks (bb) de TODOS os jogadores da mesa,
                       incluindo SB e BB, na ordem que define os indices.
        payouts: lista de premios por posicao (em $ ou qualquer unidade).
        """
        self.sb_idx = sb_idx
        self.bb_idx = bb_idx
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.equity_matrix = equity_matrix
        self.classes = classes
        self.n = len(classes)
        self.weights = np.array([combo_count(c) for c in classes], dtype=float)
        self.weights_norm = self.weights / self.weights.sum()

        self.equity = np.zeros((self.n, self.n))
        for i, ci in enumerate(classes):
            for j, cj in enumerate(classes):
                self.equity[i, j] = equity_matrix[(ci, cj)]

        self.sb_stack = table_stacks[sb_idx]
        self.bb_stack = table_stacks[bb_idx]
        self.effective_stack = min(self.sb_stack, self.bb_stack)

        self._precompute_icm_reference_values()

        self.sb_regret = np.zeros((self.n, 2))
        self.sb_strategy_sum = np.zeros((self.n, 2))
        self.bb_regret = np.zeros((self.n, 2))
        self.bb_strategy_sum = np.zeros((self.n, 2))

    def _stacks_after(self, sb_delta, bb_delta):
        stacks = list(self.table_stacks)
        stacks[self.sb_idx] = max(0.0, stacks[self.sb_idx] + sb_delta)
        stacks[self.bb_idx] = max(0.0, stacks[self.bb_idx] + bb_delta)
        return stacks

    def _precompute_icm_reference_values(self):
        """Calcula o $ICM de cada jogador nos 4 estados finais possiveis
        da mao. So precisa ser feito uma vez (nao depende da classe de
        mao nem da iteracao de treino -- so do resultado em fichas)."""
        T = self.effective_stack

        stacks_fold = self._stacks_after(-0.5, +0.5)
        eq_fold = icm_equity(stacks_fold, self.payouts)

        stacks_push_bbfold = self._stacks_after(+1.0, -1.0)
        eq_push_bbfold = icm_equity(stacks_push_bbfold, self.payouts)

        stacks_call_sbwins = self._stacks_after(+T, -T)
        eq_call_sbwins = icm_equity(stacks_call_sbwins, self.payouts)

        stacks_call_bbwins = self._stacks_after(-T, +T)
        eq_call_bbwins = icm_equity(stacks_call_bbwins, self.payouts)

        self.icm_sb_fold = eq_fold[self.sb_idx]
        self.icm_bb_fold = eq_fold[self.bb_idx]
        self.icm_sb_push_bbfold = eq_push_bbfold[self.sb_idx]
        self.icm_bb_push_bbfold = eq_push_bbfold[self.bb_idx]
        self.icm_sb_call_sbwins = eq_call_sbwins[self.sb_idx]
        self.icm_bb_call_sbwins = eq_call_sbwins[self.bb_idx]
        self.icm_sb_call_bbwins = eq_call_bbwins[self.sb_idx]
        self.icm_bb_call_bbwins = eq_call_bbwins[self.bb_idx]

    @staticmethod
    def _regret_matching(regret_row):
        positive = np.maximum(regret_row, 0.0)
        total = positive.sum()
        if total > 0:
            return positive / total
        return np.array([0.5, 0.5])

    def _current_strategy(self, regret):
        return np.array([self._regret_matching(regret[i]) for i in range(regret.shape[0])])

    def train(self, iterations=2000, alpha_pow=1.5, beta_pow=0.0, gamma_pow=2.0):
        sb_call_icm = (self.equity * self.icm_sb_call_sbwins +
                       (1 - self.equity) * self.icm_sb_call_bbwins)
        bb_call_icm = (self.equity * self.icm_bb_call_sbwins +
                       (1 - self.equity) * self.icm_bb_call_bbwins)

        for t in range(1, iterations + 1):
            sb_strategy = self._current_strategy(self.sb_regret)
            bb_strategy = self._current_strategy(self.bb_regret)
            bb_call_prob = bb_strategy[:, 1]

            ev_fold_sb = self.icm_sb_fold * np.ones(self.n)
            ev_push_sb = (self.weights_norm[np.newaxis, :] *
                          (sb_call_icm * bb_call_prob[np.newaxis, :] +
                           self.icm_sb_push_bbfold * (1 - bb_call_prob)[np.newaxis, :])).sum(axis=1)

            node_value_sb = sb_strategy[:, 0] * ev_fold_sb + sb_strategy[:, 1] * ev_push_sb
            self.sb_regret[:, 0] += (ev_fold_sb - node_value_sb)
            self.sb_regret[:, 1] += (ev_push_sb - node_value_sb)

            sb_push_prob = sb_strategy[:, 1]
            reach_sb = self.weights_norm * sb_push_prob
            reach_sum = reach_sb.sum()

            ev_fold_bb = self.icm_bb_push_bbfold
            if reach_sum > 0:
                ev_call_bb = (reach_sb[:, np.newaxis] * bb_call_icm).sum(axis=0) / reach_sum
            else:
                ev_call_bb = np.full(self.n, self.icm_bb_fold)

            ev_fold_bb_arr = ev_fold_bb * np.ones(self.n)
            node_value_bb = bb_strategy[:, 0] * ev_fold_bb_arr + bb_strategy[:, 1] * ev_call_bb
            self.bb_regret[:, 0] += reach_sum * (ev_fold_bb_arr - node_value_bb)
            self.bb_regret[:, 1] += reach_sum * (ev_call_bb - node_value_bb)

            self.sb_strategy_sum += sb_strategy
            self.bb_strategy_sum += bb_strategy

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

    def final_evs(self, strat=None):
        """
        EV ($ ICM) de cada decisao, POR CLASSE de mao, usando a
        ESTRATEGIA MEDIA final (a mesma de average_strategy()) -- nao a
        estrategia da ULTIMA iteracao isolada, que train() usa
        internamente pra regret-matching e e' sempre mais ruidosa.
        Mesmo calculo que já roda dentro de train() a cada iteracao,
        so' que rodado UMA vez a mais no final com a media convergida.

        Existe pra dar ao Push/Fold o mesmo dado que o RFI/Jam ja'
        expõe (EV por classe, nao so' frequencia) -- sem isso não dava
        pra mostrar "quanto você perdeu" no Treino pra esses spots, so'
        pra RFI/Jam.
        """
        if strat is None:
            strat = self.average_strategy()

        sb_call_icm = (self.equity * self.icm_sb_call_sbwins +
                       (1 - self.equity) * self.icm_sb_call_bbwins)
        bb_call_icm = (self.equity * self.icm_bb_call_sbwins +
                       (1 - self.equity) * self.icm_bb_call_bbwins)

        bb_call_prob = np.array([strat["bb_call"][c] for c in self.classes])
        ev_push_sb = (self.weights_norm[np.newaxis, :] *
                      (sb_call_icm * bb_call_prob[np.newaxis, :] +
                       self.icm_sb_push_bbfold * (1 - bb_call_prob)[np.newaxis, :])).sum(axis=1)

        sb_push_prob = np.array([strat["sb_push"][c] for c in self.classes])
        reach_sb = self.weights_norm * sb_push_prob
        reach_sum = reach_sb.sum()
        if reach_sum > 0:
            ev_call_bb = (reach_sb[:, np.newaxis] * bb_call_icm).sum(axis=0) / reach_sum
        else:
            ev_call_bb = np.full(self.n, self.icm_bb_fold)

        return {
            "sb_ev_fold": float(self.icm_sb_fold),
            "sb_ev_push": {c: float(ev_push_sb[i]) for i, c in enumerate(self.classes)},
            "bb_ev_fold": float(self.icm_bb_push_bbfold),
            "bb_ev_call": {c: float(ev_call_bb[i]) for i, c in enumerate(self.classes)},
        }


if __name__ == "__main__":
    from engine.pushfold import PushFoldSolver

    print("Construindo matriz de equity (reaproveitada em ambos os testes)...")
    equity_matrix, classes = build_equity_matrix(iterations=250)

    other_stacks = [40, 25, 18, 12]
    sb_stack, bb_stack = 15, 15
    table_stacks = [sb_stack, bb_stack] + other_stacks
    payouts = [500.0, 300.0, 200.0]

    print("\n=== Comparando chip EV vs ICM no mesmo spot (15bb, bolha, 6-handed) ===")

    chip_solver = PushFoldSolver(stack_bb=15, equity_matrix=equity_matrix, classes=classes)
    chip_solver.train(iterations=2000)
    chip_strat = chip_solver.average_strategy()
    chip_push_combos = sum(combo_count(c) for c in classes if chip_strat["sb_push"][c] > 0.5)

    icm_solver = PushFoldICMSolver(
        sb_idx=0, bb_idx=1, table_stacks=table_stacks, payouts=payouts,
        equity_matrix=equity_matrix, classes=classes,
    )
    icm_solver.train(iterations=2000)
    icm_strat = icm_solver.average_strategy()
    icm_push_combos = sum(combo_count(c) for c in classes if icm_strat["sb_push"][c] > 0.5)

    print(f"Chip EV push range: {chip_push_combos}/1326 combos ({100*chip_push_combos/1326:.1f}%)")
    print(f"ICM (bolha)  push range: {icm_push_combos}/1326 combos ({100*icm_push_combos/1326:.1f}%)")
    print(f"  Esperado: ICM mais apertado que chip EV (pressao de bolha desincentiva risco)")
    print(f"  [{'OK -- ICM mais apertado' if icm_push_combos < chip_push_combos else 'INESPERADO -- revisar'}]")

    print("\nExemplos de maos na fronteira (perto do call/fold da BB):")
    for c in ["55", "A5o", "K9o", "T9s", "76s"]:
        print(f"  {c:5s} chip_push={chip_strat['sb_push'][c]:.2f}  icm_push={icm_strat['sb_push'][c]:.2f}")
