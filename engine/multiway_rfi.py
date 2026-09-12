"""
Motor multiway de RFI: N jogadores em sequência (não mais só 2).

Substitui a aproximação anterior (dead_money, assumindo que os
jogadores "pulados" já foldaram) por modelagem real: cada jogador
entre o abridor e o último defensor tem sua própria decisão.

Estrutura:
  Fase 1 (pré-jam): o abridor abre (fold/open). Cada jogador seguinte,
  em ordem, decide fold ou jam quando a ação chega nele (sem call
  intermediário -- mesma decisão de arquitetura do heads-up: toda
  decisão termina em fold ou all-in genuíno).
  Fase 2 (pós-jam): assim que alguém dá jam, todos que ainda não
  agiram (incluindo o abridor original, que só tinha aberto, não
  dado jam) decidem fold ou call, em ordem. O showdown final é
  multiway entre o jammer e todos que pagaram.

Validação: com só 2 jogadores (abridor + 1 defensor), este motor
precisa reproduzir os MESMOS resultados do RfiJamSolver heads-up já
validado -- é o teste de consistência usado antes de confiar nele
pra 3+ jogadores.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.hand_classes import all_hand_classes, combo_count  # noqa: E402
from engine.icm import icm_equity  # noqa: E402
from engine.multiway_equity import multiway_equity  # noqa: E402


class InfoSet:
    def __init__(self, n_actions=2):
        self.n_actions = n_actions
        self.regret_sum = [0.0] * n_actions
        self.strategy_sum = [0.0] * n_actions

    def update_regret(self, regret):
        """CFR+: o arrependimento acumulado eh sempre travado em >= 0 logo
        apos cada atualizacao (nao so' na hora de montar a estrategia
        atual). O CFR classico deixava regret_sum acumular livremente
        negativo -- se uma acao tomasse um "azar" grande de amostragem no
        comeco do treino, o placar dela podia ficar tao negativo que ela
        quase nunca mais era escolhida, e levava MUITAS iteracoes pra se
        recuperar (as vezes nem 5 milhoes bastavam). Travar em zero a
        cada passo faz a acao voltar a competir assim que tiver uma unica
        iteracao positiva, em vez de precisar "pagar a divida" acumulada
        primeiro. `regret` aqui ja vem pesado por opp_reach (ver
        _play_fold_or_jam/_resolve_responders) -- o piso e' aplicado
        DEPOIS de somar, nao antes."""
        for i in range(self.n_actions):
            self.regret_sum[i] = max(0.0, self.regret_sum[i] + regret[i])

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


class MultiwayRfiSolver:
    def __init__(self, seat_names, seat_idx_in_table, seat_posts, table_stacks, payouts,
                 equity_matrix, classes, open_size=2.2, effective_stack=None,
                 equity_cache=None, ante_pool=0.0, use_icm: bool = True,
                 use_cfr_plus: bool = True):
        """
        seat_names: ['opener','MP','CO','BTN','SB','BB'] -- ordem de acao.
        seat_idx_in_table: indice de cada seat dentro de table_stacks/payouts.
        seat_posts: quanto cada seat ja tem investido antes de decidir
                    (0 pra nao-blind, 0.5 SB, 1.0 BB) -- seat_posts[0]
                    (abridor) normalmente 0, exceto se o abridor for SB.
        ante_pool: soma de todos os antes da mesa (morta desde t=0,
                   independente de quem folda depois) -- vai pro vencedor
                   de qualquer terminal real da mao (nao entra em
                   _icm_fold_root, que nao e um terminal de verdade: o
                   abridor so decidiu nao abrir, a mao continua sem ser
                   modelada, entao o ante ainda vai ser ganho por
                   alguem fora do escopo deste solver).
        use_cfr_plus: liga o CFR+ (piso de regret em zero a cada update +
                    media da estrategia ponderada por iteracao -- ver
                    InfoSet.update_regret e o comentario de `t` em
                    _play_open_or_fold). Default True (converge mais
                    rapido e evita maos "travadas" numa decisao ruim por
                    azar de amostragem cedo no treino). Existe a opcao de
                    desligar (False = CFR classico, identico ao motor
                    heads-up rfi_jam.py) especificamente pra comparacoes
                    tipo tests/multiway_rfi.py::test_lockstep -- os dois
                    motores so' reproduzem EXATAMENTE o mesmo resultado
                    se usarem o MESMO algoritmo de regret matching.
        """
        self.seat_names = seat_names
        self.n_seats = len(seat_names)
        self.seat_idx_in_table = seat_idx_in_table
        self.seat_posts = seat_posts
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.use_icm = use_icm
        self.use_cfr_plus = use_cfr_plus
        if use_icm and not payouts:
            raise ValueError("payouts vazio/None -- sem payouts nao ha ICM pra calcular (use_icm=False pra chipEV puro)")
        self.equity_matrix = equity_matrix  # pairwise, usado só pra referência/compat
        self.classes = classes
        self.weights = {c: combo_count(c) for c in classes}
        total_w = sum(self.weights.values())
        self.weights_norm = {c: w / total_w for c, w in self.weights.items()}
        self._weights_list = [self.weights_norm[c] for c in classes]

        self.R = open_size
        self.T = effective_stack or min(table_stacks[i] for i in seat_idx_in_table)

        # infosets: um por seat por fase (fold/jam pre-jam; fold/call pos-jam).
        # phase2 tem uma dimensao a mais que phase1: quem deu o jam e
        # informacao PUBLICA (todo mundo na mesa ve quem foi all-in), entao
        # a decisao de fold/call de um seat depois de um jam precisa ser uma
        # ficha (infoset) SEPARADA pra cada jammer possivel -- responder a um
        # jam do BB (que entrou mais barato) nao e a mesma decisao que
        # responder a um jam do BTN. Compartilhar uma unica ficha pras duas
        # situacoes (como era antes) faz o seat aprender uma frequencia
        # media que nao e otima pra nenhuma das duas -- e o motivo do CO
        # (que sempre responde, seja qual for o jammer) ficar com
        # exploitability muito maior que os outros seats.
        self.phase1 = [{c: InfoSet(2) for c in classes} for _ in range(self.n_seats)]
        self.phase2 = [
            {j: {c: InfoSet(2) for c in classes} for j in self._possible_jammers(seat_i)}
            for seat_i in range(self.n_seats)
        ]

        self.ante_pool = ante_pool

        self._icm_cache = {}
        self._equity_cache = equity_cache if equity_cache is not None else {}

    def _possible_jammers(self, seat_i):
        """Quais seats podem ser o jammer que faz `seat_i` responder em
        fase 2. So' seats 1..n-1 podem dar jam (seat 0 e' o abridor, que so
        decide fold/open). O abridor (seat 0) responde a QUALQUER jammer
        (ele sempre abriu antes). Qualquer outro seat so' responde a um
        jammer que agiu ANTES dele na ordem (jammer < seat_i) -- depois
        disso, se `seat_i` ainda nao tiver agido, e' ele quem decide
        fold/jam em fase 1, nao um responder de fase 2."""
        if seat_i == 0:
            return list(range(1, self.n_seats))
        return list(range(1, seat_i))

    def _icm(self, stack_deltas: dict):
        """stack_deltas: {seat_idx: delta}. Retorna a UTILIDADE de cada
        seat nesse terminal -- em $ICM (padrao) ou em fichas cruas
        (use_icm=False, "chipEV puro" -- mesmo espirito de
        RfiJamSolver._icm_pair, unico ponto de acesso a ICM no motor
        multiway). Nome do metodo mantido (nao "_utility") pra nao
        quebrar nenhum chamador existente.

        No modo ICM, a entrada devolvida cobre TODOS os n_seats, nao so'
        os presentes em stack_deltas -- quem nao aparece ali (stack nao
        mudou, ex: fold sem blind pago) tem ICM equity normal (nao-zero),
        e todo consumidor usa `.get(seat, 0.0)`. Devolver so' os seats de
        stack_deltas fazia esse equity real virar SILENCIOSAMENTE zero em
        qualquer regret/best-response calculado a partir dali -- inflava
        a frequencia de jam de seats sem blind (fold parecia inutil).
        No modo chipEV (use_icm=False) isso nao se aplica: delta ausente
        e' corretamente 0 fichas (omissao = 0 e' o valor certo ali)."""
        if not self.use_icm:
            return dict(stack_deltas)
        key = tuple(sorted(stack_deltas.items()))
        if key in self._icm_cache:
            return self._icm_cache[key]
        stacks = list(self.table_stacks)
        for seat, delta in stack_deltas.items():
            table_i = self.seat_idx_in_table[seat]
            stacks[table_i] = max(0.0, stacks[table_i] + delta)
        eq = icm_equity(stacks, self.payouts)
        result = {seat: eq[self.seat_idx_in_table[seat]] for seat in range(self.n_seats)}
        self._icm_cache[key] = result
        return result

    # Tamanho de cada lote de simulacao (novo ou de refinamento) e teto de
    # amostras acumuladas por combinacao -- ver docstring de _multiway_eq.
    EQUITY_BATCH = 150
    EQUITY_MAX_SAMPLES = 2000

    def _multiway_eq(self, seat_hand_pairs):
        """seat_hand_pairs: lista de (seat_idx, hand_class). Retorna dict
        seat_idx -> equity.

        Refinamento progressivo com teto: o resultado de cada combinacao
        de maos era calculado UMA VEZ (150 simulacoes Monte Carlo) e
        ficava congelado pra sempre em self._equity_cache, mesmo que
        aquela MESMA combinacao aparecesse de novo centenas de vezes
        durante o treino (e' exatamente pra aproveitar essas repeticoes
        que o cache existe). Com 150 simulacoes, o desvio-padrao medido
        empiricamente pra uma equity de 3-way ficou em ~0.04 (4 pontos
        percentuais) -- um erro FIXO desse tamanho, congelado pra sempre,
        e' o suficiente pra fazer o CFR aprender a decisao errada pra
        maos especificas mesmo depois de milhoes de iteracoes (nao e'
        ruido que se cancela com mais treino, ja que e' sempre o mesmo
        numero errado reusado). Simplesmente multiplicar `iterations` de
        uma vez (testado com 1000) resolve a precisao mas custa caro
        demais (~7x mais lento no treino todo), inclusive em combinacoes
        raras que quase nao importam.

        Fix: a cada vez que uma combinacao (nova ou ja' vista) aparece,
        roda mais um lote de EQUITY_BATCH simulacoes e funde com a media
        acumulada (media ponderada pelo numero de amostras de cada lado)
        -- ate' acumular EQUITY_MAX_SAMPLES no total, depois disso so'
        reaproveita sem gastar mais (desvio-padrao cai pra ~0.012-0.015
        nesse ponto). Combinacoes raras ficam baratas por natureza (nunca
        chegam perto do teto); combinacoes frequentes (que mais pesam no
        resultado final) ficam cada vez mais precisas conforme sao
        revisitadas.

        Cache chaveado pelo MULTISET de classes (ignorando qual seat
        tem qual mão) -- a equity de cada classe so depende de QUAIS
        classes estao competindo, nao de qual seat especifico as tem.
        Isso reaproveita o cache entre diferentes atribuicoes de seat
        pras mesmas 3 maos (ate 6x mais reaproveitamento pra 3-way sem
        classes repetidas), essencial pra tornar multiway viavel."""
        seats = [s for s, h in seat_hand_pairs]
        hands = [h for s, h in seat_hand_pairs]

        order = sorted(range(len(hands)), key=lambda i: hands[i])
        sorted_hands = tuple(hands[i] for i in order)

        cached = self._equity_cache.get(sorted_hands)
        cached_eqs, cached_n = cached if cached is not None else (None, 0)

        if cached_n >= self.EQUITY_MAX_SAMPLES:
            sorted_eqs = cached_eqs
        else:
            fresh_eqs = multiway_equity(list(sorted_hands), iterations=self.EQUITY_BATCH)
            if cached_eqs is None:
                sorted_eqs = fresh_eqs
                new_n = self.EQUITY_BATCH
            else:
                new_n = cached_n + self.EQUITY_BATCH
                sorted_eqs = [
                    (cached_eqs[i] * cached_n + fresh_eqs[i] * self.EQUITY_BATCH) / new_n
                    for i in range(len(fresh_eqs))
                ]
            self._equity_cache[sorted_hands] = (sorted_eqs, new_n)

        # remonta na ordem original dos seats (desfaz o sort)
        eqs = [0.0] * len(hands)
        for pos, orig_i in enumerate(order):
            eqs[orig_i] = sorted_eqs[pos]
        return dict(zip(seats, eqs))

    def train(self, iterations=500_000, seed=42, start_t=1):
        """start_t: numero da primeira iteracao deste lote, pra continuar
        corretamente a media ponderada por iteracao entre lotes/
        checkpoints (CFR+ "linear averaging" -- ver comentario em
        _play_open_or_fold sobre por que strategy_sum e' pesado por t)."""
        random.seed(seed)
        classes_list = self.classes
        weights_list = [self.weights_norm[c] for c in classes_list]
        for t in range(start_t, start_t + iterations):
            hands = {i: random.choices(classes_list, weights=weights_list, k=1)[0]
                      for i in range(self.n_seats)}
            self._play_open_or_fold(hands, t)

    # ---- reach probability (correcao 2026-09) ------------------------
    #
    # BUG encontrado: as funcoes de fase 1/2 abaixo atualizavam
    # regret_sum SEM pesar pela probabilidade dos OUTROS jogadores terem
    # realmente tomado as acoes que levam ate aquele infoset (chamada de
    # "opponent reach"/"counterfactual reach" na literatura de CFR) --
    # so' o motor heads-up (rfi_jam.py) fazia isso certo (p_sb/p_bb
    # threading em _node_bb_facing_raise/_node_sb_facing_jam). Sem esse
    # peso, o regret acumulado superestima decisoes raramente
    # alcancadas e o equilibrio aprendido diverge do correto -- e' o que
    # explicava spots de 2 seats (caso degenerado) NAO baterem com o
    # motor heads-up ja validado, mesmo usando a MESMA tabela de equity
    # (confirmado isolando a variavel: com equity identica, a
    # divergencia continuou grande -- so' podia ser bug de logica, nao
    # ruido de amostragem).
    #
    # Fix (v2 -- a v1 tinha um bug sutil, ver abaixo): `own_reach` e' um
    # dict {seat: probabilidade} que acompanha, PRA CADA JOGADOR
    # separadamente, a chance de ELE MESMO ter escolhido o caminho
    # percorrido ate aqui. O regret_sum de quem esta decidindo AGORA e'
    # pesado pelo produto da reach de TODOS OS OUTROS (excluindo a
    # propria) -- e' isso que rfi_jam.py faz com p_sb/p_bb.
    #
    # BUG da v1: eu tinha um unico escalar `opp_reach` acumulando a
    # reach de TODOS que agiram antes, sem excluir o proprio jogador
    # quando ele age DUAS VEZES na mesma mao (o abridor: abre na fase 1,
    # responde ao jam na fase 2). Isso fazia a propria reach do abridor
    # (de ter aberto) entrar de novo no peso do regret dele mesmo na
    # fase 2 -- contava a mesma probabilidade duas vezes. Confirmado
    # isolando 1 iteracao (sem ruido nenhum): o regret_sum da decisao
    # "SB responde ao jam" saia exatamente pela METADE do valor do
    # motor heads-up (0.5x, porque a reach do abridor entrava um fator
    # 0.5 a mais que devia). strategy_sum nunca teve esse problema (ja
    # usava a reach do PROPRIO jogador de proposito, que e' o correto).


    def _icm_fold_root(self, hands):
        """Abridor folda antes de abrir (nunca chega a investir R):
        perde so o post que ja tinha (0 pra posicoes sem blind). Sem
        outros jogadores tendo agido ainda, nao ha vencedor especifico
        -- convencao: se houver algo a ganhar, vai pro seat seguinte
        (proximo a agir), igual o caso heads-up ja validado."""
        op = self.seat_posts[0]
        if op <= 0 or self.n_seats < 2:
            return self._icm({0: 0.0})
        return self._icm({0: -op, 1: op})

    def _opp_reach(self, own_reach, seat_i):
        """Produto da reach de TODOS OS OUTROS jogadores (exclui a
        propria) -- o peso certo pro regret_sum de quem esta decidindo
        agora, em qualquer fase."""
        p = 1.0
        for s, r in own_reach.items():
            if s != seat_i:
                p *= r
        return p

    def _update_regret(self, infoset, regret):
        """Aplica o update de regret no InfoSet, com ou sem o piso do
        CFR+ dependendo de self.use_cfr_plus (ver __init__)."""
        if self.use_cfr_plus:
            infoset.update_regret(regret)
        else:
            infoset.regret_sum[0] += regret[0]
            infoset.regret_sum[1] += regret[1]

    def _t_weight(self, t):
        """Peso de iteracao pra media da estrategia (CFR+ linear
        averaging) -- so' se aplica quando use_cfr_plus esta ligado,
        senao a media classica (peso igual pra todas as iteracoes)."""
        return t if self.use_cfr_plus else 1

    def _play_open_or_fold(self, hands, t=1):
        """Decisao do ABRIDOR (seat 0): fold ou abrir (nao e jam --
        e um raise pequeno, R, igual o motor heads-up). So depois de
        abrir e que os demais seats entram na sequencia fold-ou-jam.

        E' o unico infoset onde ninguem mais agiu antes -- ninguem tem
        reach reduzida ainda, entao o regret_sum de seat 0 aqui nao
        precisa de peso nenhum (equivalente a opp_reach=1.0, mesma
        convencao de rfi_jam.py: p_bb comeca em 1.0 no _node_root).

        t: numero da iteracao atual (1-based) -- CFR+ "linear averaging"
        (ver comentario detalhado no update de strategy_sum abaixo)."""
        infoset = self.phase1[0][hands[0]]
        strat = infoset.current_strategy()

        icm_fold = self._icm_fold_root(hands)
        # own_reach[0] = strat[1] (chance do proprio abridor ter aberto)
        # -- entra no dict pra ser excluida do peso do regret DELE MESMO
        # mais adiante (fase 2), e conta normalmente como "reach de um
        # jogador anterior" pro regret de qualquer outro seat.
        own_reach = {0: strat[1]}
        icm_open = self._play_fold_or_jam(1, hands, own_reach, t)

        node_val = {}
        all_seats = set(icm_fold.keys()) | set(icm_open.keys())
        for s in all_seats:
            node_val[s] = strat[0] * icm_fold.get(s, 0.0) + strat[1] * icm_open.get(s, 0.0)

        regret = [icm_fold.get(0, 0.0) - node_val.get(0, 0.0),
                  icm_open.get(0, 0.0) - node_val.get(0, 0.0)]
        self._update_regret(infoset, regret)
        # CFR+ "linear averaging": multiplica a contribuicao de cada
        # iteracao pelo numero dela (t), em vez de dar peso igual pra
        # todas. Sem isso, uma mao que jogou mal nas primeiras iteracoes
        # (antes do regret ainda ter convergido) carrega esse "estrago"
        # com peso IGUAL ao das iteracoes finais (ja bem mais precisas)
        # na media final -- e' o comportamento que CFR+ pressupoe pra
        # convergir rapido (o piso de regret sozinho nao basta se a
        # media continuar arrastando o comeco ruim do treino).
        tw = self._t_weight(t)
        infoset.strategy_sum[0] += tw * strat[0]
        infoset.strategy_sum[1] += tw * strat[1]

        return node_val

    def _terminal_all_fold(self, hands):
        """Todo mundo depois do abridor foldou -- abridor ganha os posts
        de quem tinha blind + o ante morto da mesa (os outros nao perdem
        nada alem do que ja haviam postado, que ja esta contado)."""
        deltas = {}
        total_won = self.ante_pool
        for i in range(1, self.n_seats):
            p = self.seat_posts[i]
            if p > 0:
                deltas[i] = -p
                total_won += p
        deltas[0] = total_won
        return self._icm(deltas)

    def _play_fold_or_jam(self, seat_i, hands, own_reach, t=1):
        """Decisao de cada seat DEPOIS do abridor (seat_i >= 1): fold
        ou jam (all-in), quando a acao chega nele (todos antes dele
        ja foldaram, por construcao -- essa funcao so e chamada na
        sequencia, nunca fora de ordem).

        own_reach: dict {seat: reach}, uma entrada por jogador que ja
        tomou alguma decisao no caminho ate aqui. O regret_sum de
        seat_i e' pesado por _opp_reach(own_reach, seat_i) -- produto
        de todos OS OUTROS, nunca a propria (mesmo esquema de p_sb em
        rfi_jam.py::_node_bb_facing_raise)."""
        if seat_i >= self.n_seats:
            return self._terminal_all_fold(hands)

        infoset = self.phase1[seat_i][hands[seat_i]]
        strat = infoset.current_strategy()
        opp_reach = self._opp_reach(own_reach, seat_i)

        # Cada ramo recebe seu PROPRIO dict (nunca muta o do chamador --
        # os dois ramos sao caminhos DIFERENTES, nao podem compartilhar
        # estado) com a reach de seat_i atualizada pra essa escolha.
        reach_fold = {**own_reach, seat_i: own_reach.get(seat_i, 1.0) * strat[0]}
        reach_jam = {**own_reach, seat_i: own_reach.get(seat_i, 1.0) * strat[1]}

        icm_fold = self._play_fold_or_jam(seat_i + 1, hands, reach_fold, t)
        icm_jam = self._play_phase2(jammer=seat_i, hands=hands, own_reach=reach_jam, t=t)

        node_val = {}
        all_seats = set(icm_fold.keys()) | set(icm_jam.keys())
        for s in all_seats:
            node_val[s] = strat[0] * icm_fold.get(s, 0.0) + strat[1] * icm_jam.get(s, 0.0)

        regret = [icm_fold.get(seat_i, 0.0) - node_val.get(seat_i, 0.0),
                  icm_jam.get(seat_i, 0.0) - node_val.get(seat_i, 0.0)]
        self._update_regret(infoset, [opp_reach * regret[0], opp_reach * regret[1]])
        tw = self._t_weight(t)
        infoset.strategy_sum[0] += tw * strat[0]
        infoset.strategy_sum[1] += tw * strat[1]

        return node_val

    def _play_phase2(self, jammer, hands, own_reach, t=1):
        """Todos os seats DEPOIS do jammer que ainda nao agiram, em
        ordem, decidem fold/call; no final o abridor (seat 0, que
        sempre abriu -- nunca chega aqui tendo foldado, isso ja e
        outro ramo da arvore) tambem decide fold/call."""
        responders = [i for i in range(self.n_seats) if i > jammer]
        responders.append(0)  # abridor sempre responde (sempre abriu antes)

        return self._resolve_responders(jammer, responders, 0, {jammer}, hands, own_reach, t)

    def _resolve_responders(self, jammer, responders, idx, live_set, hands, own_reach, t=1):
        if idx >= len(responders):
            return self._showdown(live_set, hands)

        seat_i = responders[idx]
        infoset = self.phase2[seat_i][jammer][hands[seat_i]]
        strat = infoset.current_strategy()
        opp_reach = self._opp_reach(own_reach, seat_i)
        # peso da propria strategy_sum (ver comentario abaixo) -- pra
        # todo mundo aqui e' 1.0 (primeira decisao), EXCETO o abridor
        # (seat 0), que ja' carrega a reach de ter aberto na fase 1.
        own_weight = own_reach.get(seat_i, 1.0)

        reach_fold = {**own_reach, seat_i: own_weight * strat[0]}
        reach_call = {**own_reach, seat_i: own_weight * strat[1]}

        icm_fold = self._resolve_responders(jammer, responders, idx + 1, live_set, hands, reach_fold, t)
        icm_call = self._resolve_responders(jammer, responders, idx + 1, live_set | {seat_i}, hands, reach_call, t)

        node_val = {}
        all_seats = set(icm_fold.keys()) | set(icm_call.keys())
        for s in all_seats:
            node_val[s] = strat[0] * icm_fold.get(s, 0.0) + strat[1] * icm_call.get(s, 0.0)

        regret = [icm_fold.get(seat_i, 0.0) - node_val.get(seat_i, 0.0),
                  icm_call.get(seat_i, 0.0) - node_val.get(seat_i, 0.0)]
        self._update_regret(infoset, [opp_reach * regret[0], opp_reach * regret[1]])
        # A media de estrategia (strategy_sum) do CFR precisa ser pesada
        # pela probabilidade do PROPRIO jogador ter chegado ate essa ficha
        # (formula padrao de "average strategy" do CFR: soma de
        # pi_i(I) * sigma(I,a), nao soma direta de sigma(I,a)). Pra todo
        # mundo aqui isso e' sempre 1 (cada seat so' toma UMA decisao
        # propria por mao jogada) -- EXCETO o abridor (seat 0), que toma
        # duas decisoes em sequencia na mesma mao: abre/folda na fase 1 e,
        # se alguem der jam depois, paga/folda na fase 2. Sem esse peso,
        # a fase 2 do abridor conta com peso total mesmo em maos que ele
        # dificilmente abriria -- e' o que estava inflando a
        # exploitability do CO bem acima dos outros seats, mesmo depois
        # de separar a decisao por jammer.
        # t: CFR+ "linear averaging" (ver _play_open_or_fold), combinado
        # com own_weight (peso de reach do proprio jogador, ja existente).
        tw = self._t_weight(t)
        infoset.strategy_sum[0] += tw * own_weight * strat[0]
        infoset.strategy_sum[1] += tw * own_weight * strat[1]

        return node_val

    def _showdown(self, live_set, hands):
        live = sorted(live_set)
        # todo seat que nao esta vivo ja teve sua decisao resolvida como
        # fold -- seja no PRE-jam (folda antes de alguem dar jam: perde
        # o blind que tinha postado, se algum) ou no POS-jam (recebe o
        # jam e folda: perde o post, ou o open R se for o abridor). Os
        # dois casos tem que ser contados igual -- ANTES esse dinheiro
        # so era contado quando o fold acontecia depois do jam; blind
        # morto foldado antes do jam simplesmente sumia do pote.
        not_live = [i for i in range(self.n_seats) if i not in live_set]

        def cost(i):
            return self.R if i == 0 else self.seat_posts[i]

        dead = self.ante_pool + sum(cost(i) for i in not_live)

        if len(live) == 1:
            # todo mundo foldou pro jam (ou ja tinha foldado antes) --
            # o unico vivo (o jammer) ganha tudo que ficou morto na mesa
            deltas = {i: -cost(i) for i in not_live}
            deltas[live[0]] = dead
            return self._icm(deltas)

        # multiway showdown entre os "live"
        seat_hand_pairs = [(i, hands[i]) for i in live]
        eqs = self._multiway_eq(seat_hand_pairs)

        # ICM esperado: para cada resultado possivel de vencedor, calcula
        # o ICM e pondera pela equity -- aproximacao razoavel (nao
        # enumeramos boards, usamos a equity agregada por jogador)
        icm_by_winner = {}
        for winner in live:
            deltas = {i: -cost(i) for i in not_live}
            total_won = dead
            for i in live:
                if i != winner:
                    deltas[i] = -self.T
                    total_won += self.T
            deltas[winner] = total_won
            icm_by_winner[winner] = self._icm(deltas)

        result = {}
        for s in range(self.n_seats):
            val = 0.0
            for winner in live:
                val += eqs.get(winner, 0.0) * icm_by_winner[winner].get(s, 0.0)
            if val > 0 or s in live:
                result[s] = val
        return result

    def average_strategy(self):
        return {
            "phase1": [
                {c: self.phase1[i][c].average_strategy()[1] for c in self.classes}
                for i in range(self.n_seats)
            ],
            # phase2 agora tem uma camada extra: pra cada seat, uma
            # estrategia de fold/call DIFERENTE por jammer (ver comentario
            # em __init__ sobre por que "quem deu o jam" precisa ser parte
            # da ficha de decisao).
            "phase2": [
                {
                    j: {c: self.phase2[i][j][c].average_strategy()[1] for c in self.classes}
                    for j in self.phase2[i]
                }
                for i in range(self.n_seats)
            ],
        }

    @staticmethod
    def _blend(icm_a, icm_b, weight_a, weight_b):
        all_seats = set(icm_a.keys()) | set(icm_b.keys())
        return {s: weight_a * icm_a.get(s, 0.0) + weight_b * icm_b.get(s, 0.0) for s in all_seats}

    # ---- best response SEM vazamento de informação (correção 2026-09) ----
    #
    # BUG anterior (ver tests/multiway_exploitability_2seat.py e o
    # histórico do commit que documentou isso): a versão antiga de
    # best_response_value decidia a melhor ação de `br_seat` olhando pra
    # mão ESPECÍFICA sorteada do adversário NESSA amostra, em vez de
    # calcular o valor esperado médio sobre a distribuição de mãos do
    # adversário antes de fixar a decisão -- inflava o resultado em ~4%,
    # de forma sistemática (vazamento estrutural, não ruído).
    #
    # Correção: pra cada decisão que pertence a `br_seat`, a ação é
    # FIXADA por classe de mão de `br_seat` ANTES de qualquer avaliação
    # final -- calculando a média de cada ação possível sobre MUITAS
    # amostras dos OUTROS seats (a mão de `br_seat` fica fixa, os outros
    # são resorteados a cada amostra), igual ao cuidado que
    # rfi_jam.py::best_response_value já fazia (lá por enumeração exata,
    # aqui por amostragem -- com 4+ seats, enumerar exatamente todas as
    # combinações de mão dos adversários é inviável, mas ainda dá pra
    # fazer a média SEM deixar `br_seat` espiar a amostra específica).
    #
    # Só o abridor (seat 0) decide duas vezes na mesma mão (abre/folda
    # na raiz; se alguém jamma depois, responde call/fold em fase 2) --
    # por isso a decisão mais profunda dele (fase 2) precisa ser fixada
    # ANTES da raiz, senão a raiz "enxergaria" a fase 2 por baixo dos
    # panos. Qualquer outro seat tem no máximo UMA decisão própria por
    # mão (fase 1 OU responder em fase 2 -- nunca as duas, são ramos
    # mutuamente exclusivos), então não tem essa dependência.

    def _eval_fold_or_jam(self, seat_i, hands, avg):
        """Como _play_fold_or_jam, mas sem efeito colateral (não mexe em
        regret_sum/strategy_sum) e usando avg_strategy fixo em vez de
        current_strategy() do CFR -- pura avaliação, todo mundo por
        média (nenhum seat tratado como best-responder aqui)."""
        if seat_i >= self.n_seats:
            return self._terminal_all_fold(hands)
        p_jam = avg["phase1"][seat_i][hands[seat_i]]
        icm_fold = self._eval_fold_or_jam(seat_i + 1, hands, avg)
        icm_jam = self._eval_phase2(seat_i, hands, avg)
        return self._blend(icm_fold, icm_jam, 1 - p_jam, p_jam)

    def _eval_phase2(self, jammer, hands, avg):
        responders = [i for i in range(self.n_seats) if i > jammer]
        responders.append(0)
        return self._eval_resolve_responders(jammer, responders, 0, {jammer}, hands, avg)

    def _eval_resolve_responders(self, jammer, responders, idx, live_set, hands, avg):
        if idx >= len(responders):
            return self._showdown(live_set, hands)
        seat_i = responders[idx]
        p_call = avg["phase2"][seat_i][jammer][hands[seat_i]]
        icm_fold = self._eval_resolve_responders(jammer, responders, idx + 1, live_set, hands, avg)
        icm_call = self._eval_resolve_responders(jammer, responders, idx + 1, live_set | {seat_i}, hands, avg)
        return self._blend(icm_fold, icm_call, 1 - p_call, p_call)

    def _eval_resolve_responders_forced(self, jammer, responders, idx, live_set, hands, avg,
                                         forced_seat, forced_action):
        """Como _eval_resolve_responders, mas a decisão de `forced_seat`
        (quando aparece como responder) é FORÇADA pra `forced_action`
        (0=fold, 1=call) em vez de usar avg_strategy -- usado tanto pra
        FIXAR a política de forced_seat (chamado com forced_action=0 e
        =1 pra comparar) quanto na avaliação final (chamado com a ação
        já fixada, olhando só a própria mão de forced_seat)."""
        if idx >= len(responders):
            return self._showdown(live_set, hands)
        seat_i = responders[idx]
        if seat_i == forced_seat:
            next_live = live_set | {seat_i} if forced_action == 1 else live_set
            return self._eval_resolve_responders_forced(
                jammer, responders, idx + 1, next_live, hands, avg, forced_seat, forced_action
            )
        p_call = avg["phase2"][seat_i][jammer][hands[seat_i]]
        icm_fold = self._eval_resolve_responders_forced(
            jammer, responders, idx + 1, live_set, hands, avg, forced_seat, forced_action
        )
        icm_call = self._eval_resolve_responders_forced(
            jammer, responders, idx + 1, live_set | {seat_i}, hands, avg, forced_seat, forced_action
        )
        return self._blend(icm_fold, icm_call, 1 - p_call, p_call)

    def _sample_other_hands(self, fixed_seat, fixed_hand, rng):
        hands = {fixed_seat: fixed_hand}
        for i in range(self.n_seats):
            if i != fixed_seat:
                hands[i] = rng.choices(self.classes, weights=self._weights_list, k=1)[0]
        return hands

    def _fix_policy_phase1(self, br_seat, avg, samples, rng):
        """Fixa fold-vs-jam de `br_seat` (br_seat >= 1) pra cada classe de
        mão dele, SEM espiar a amostra dos adversários -- média sobre
        `samples` sorteios independentes deles antes de decidir."""
        policy = {}
        for h in self.classes:
            val_fold = 0.0
            val_jam = 0.0
            for _ in range(samples):
                hands = self._sample_other_hands(br_seat, h, rng)
                val_fold += self._eval_fold_or_jam(br_seat + 1, hands, avg).get(br_seat, 0.0)
                val_jam += self._eval_phase2(br_seat, hands, avg).get(br_seat, 0.0)
            policy[h] = 1 if val_jam > val_fold else 0
        return policy

    def _fix_policy_phase2(self, br_seat, jammer, avg, samples, rng):
        """Fixa fold-vs-call de `br_seat` respondendo ao jam de `jammer`
        (br_seat == 0, ou br_seat > jammer), por classe de mão. A mão do
        jammer é ponderada pela probabilidade dele TER REALMENTE jammado
        com ela (posterior condicionado em "jammer jammou", igual
        rfi_jam.py faz por enumeração exata -- aqui via peso de
        importância, já que enumerar exatamente todas as mãos dos
        adversários explode com muitos seats)."""
        policy = {}
        for h in self.classes:
            w_fold, w_call, w_total = 0.0, 0.0, 0.0
            for _ in range(samples):
                hands = self._sample_other_hands(br_seat, h, rng)
                w = avg["phase1"][jammer][hands[jammer]]
                if w <= 0:
                    continue
                responders = [i for i in range(self.n_seats) if i > jammer]
                responders.append(0)
                icm_fold = self._eval_resolve_responders_forced(
                    jammer, responders, 0, {jammer}, hands, avg, br_seat, 0
                )
                icm_call = self._eval_resolve_responders_forced(
                    jammer, responders, 0, {jammer}, hands, avg, br_seat, 1
                )
                w_fold += w * icm_fold.get(br_seat, 0.0)
                w_call += w * icm_call.get(br_seat, 0.0)
                w_total += w
            policy[h] = 1 if (w_total > 0 and w_call > w_fold) else 0
        return policy

    def _fix_policy_root_seat0(self, avg, phase2_policy, samples, rng):
        """Fixa abrir-vs-foldar do abridor (seat 0) na raiz, USANDO a
        política de fase 2 dele já fixada antes (ver docstring da seção)
        -- sem isso, a raiz reaproveitaria a versão com vazamento pra
        avaliar o que acontece quando alguém jamma depois de abrir."""
        val_fold_const = self._icm_fold_root({}).get(0, 0.0)
        policy = {}
        for h in self.classes:
            val_open = 0.0
            for _ in range(samples):
                hands = self._sample_other_hands(0, h, rng)
                val_open += self._eval_fold_or_jam_seat0_fixed(1, hands, avg, phase2_policy).get(0, 0.0)
            policy[h] = 1 if (val_open / samples) > val_fold_const else 0
        return policy

    def _eval_fold_or_jam_seat0_fixed(self, seat_i, hands, avg, phase2_policy):
        """Como _eval_fold_or_jam, mas quando a ação chega em fase 2, o
        abridor (seat 0) usa a política JÁ FIXADA (`phase2_policy`) em
        vez de avg_strategy -- os demais seats continuam por média."""
        if seat_i >= self.n_seats:
            return self._terminal_all_fold(hands)
        p_jam = avg["phase1"][seat_i][hands[seat_i]]
        icm_fold = self._eval_fold_or_jam_seat0_fixed(seat_i + 1, hands, avg, phase2_policy)
        responders = [i for i in range(self.n_seats) if i > seat_i]
        responders.append(0)
        action0 = phase2_policy[seat_i][hands[0]]
        icm_jam = self._eval_resolve_responders_forced(seat_i, responders, 0, {seat_i}, hands, avg, 0, action0)
        return self._blend(icm_fold, icm_jam, 1 - p_jam, p_jam)

    def _fix_br_policy(self, br_seat, avg, samples, rng):
        if br_seat == 0:
            phase2_policy = {
                jammer: self._fix_policy_phase2(0, jammer, avg, samples, rng)
                for jammer in range(1, self.n_seats)
            }
            root_policy = self._fix_policy_root_seat0(avg, phase2_policy, samples, rng)
            return {"root": root_policy, "phase2": phase2_policy}
        phase1_policy = self._fix_policy_phase1(br_seat, avg, samples, rng)
        phase2_policy = {
            jammer: self._fix_policy_phase2(br_seat, jammer, avg, samples, rng)
            for jammer in range(1, br_seat)
        }
        return {"phase1": phase1_policy, "phase2": phase2_policy}

    def _eval_root_full(self, hands, avg, br_seat, policy):
        if br_seat == 0:
            if policy["root"][hands[0]] == 0:
                return self._icm_fold_root(hands)
            return self._eval_fold_or_jam_full(1, hands, avg, br_seat, policy)
        p_open = avg["phase1"][0][hands[0]]
        icm_fold = self._icm_fold_root(hands)
        icm_open = self._eval_fold_or_jam_full(1, hands, avg, br_seat, policy)
        return self._blend(icm_fold, icm_open, 1 - p_open, p_open)

    def _eval_fold_or_jam_full(self, seat_i, hands, avg, br_seat, policy):
        if seat_i >= self.n_seats:
            return self._terminal_all_fold(hands)
        if seat_i == br_seat:
            if policy["phase1"][hands[seat_i]] == 0:
                return self._eval_fold_or_jam_full(seat_i + 1, hands, avg, br_seat, policy)
            return self._eval_phase2_full(seat_i, hands, avg, br_seat, policy)
        p_jam = avg["phase1"][seat_i][hands[seat_i]]
        icm_fold = self._eval_fold_or_jam_full(seat_i + 1, hands, avg, br_seat, policy)
        icm_jam = self._eval_phase2_full(seat_i, hands, avg, br_seat, policy)
        return self._blend(icm_fold, icm_jam, 1 - p_jam, p_jam)

    def _eval_phase2_full(self, jammer, hands, avg, br_seat, policy):
        responders = [i for i in range(self.n_seats) if i > jammer]
        responders.append(0)
        if br_seat in responders and (br_seat == 0 or br_seat > jammer):
            action = policy["phase2"][jammer][hands[br_seat]]
            return self._eval_resolve_responders_forced(jammer, responders, 0, {jammer}, hands, avg, br_seat, action)
        return self._eval_resolve_responders(jammer, responders, 0, {jammer}, hands, avg)

    def best_response_value(self, br_seat, avg_strategy=None, iterations=1000, seed=123, policy_samples=50):
        """Quanto `br_seat` ganharia jogando a MELHOR ação em cada decisão
        própria (fixada sem vazamento -- ver `_fix_br_policy` e a seção
        acima), enquanto todos os outros seats seguem `avg_strategy`.

        Duas amostragens diferentes, de propósito:
          - `policy_samples`: quantas vezes resorteamos os ADVERSÁRIOS
            (mão de br_seat fixa) pra decidir a política de br_seat por
            classe -- roda uma vez POR CLASSE de mão de br_seat (até
            169 vezes) e por decisão própria dele (fase 1 + até N-1
            respostas de fase 2), então o custo total escala com
            N_classes × N_decisões × policy_samples.
          - `iterations`: quantas mãos completas (todos os seats,
            incluindo br_seat) sorteamos pra avaliar o valor médio final,
            já com a política de br_seat fixada e sem risco de vazamento
            (a política não muda mais por amostra) -- bem mais barato,
            não escala com N_classes.

        CUSTO (2026-09, medido): com 2 seats, o showdown usa a tabela
        de equity pré-computada (`equity_matrix`) — rápido, `policy_samples`
        alto (100s) não pesa. Com 3+ seats, cada showdown chama
        `multiway_equity()` (simulação de carta real via `treys`) — bem
        mais caro, e NÃO é cacheável aqui (cada amostra sorteia mãos
        novas dos adversários de propósito, pra não vazar informação).
        Medido: 3 seats, `policy_samples=10` (bem menor que o default)
        levou ~90s pra `compute_exploitability()` inteiro (soma dos 3
        seats). Escala com o número de seats (mais responders em fase
        2, mais jammers possíveis) — pra 8 seats (UTG), espere minutos
        a dezenas de minutos. Não é bug, é o custo real de medir isso
        sem vazar informação com muitos jogadores — ajuste
        `policy_samples`/`iterations` pra baixo se só precisar de um
        termômetro grosseiro (ver tests/multiway_exploitability_2seat.py
        pra exemplos calibrados)."""
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        rng = random.Random(seed)
        policy = self._fix_br_policy(br_seat, avg_strategy, policy_samples, rng)
        total = 0.0
        for _ in range(iterations):
            hands = {i: rng.choices(self.classes, weights=self._weights_list, k=1)[0]
                      for i in range(self.n_seats)}
            icm = self._eval_root_full(hands, avg_strategy, br_seat, policy)
            total += icm.get(br_seat, 0.0)
        return total / iterations

    def compute_exploitability(self, avg_strategy=None, iterations=1000, seed=123, policy_samples=50):
        """Best response de cada seat, um de cada vez (mesma convenção do
        motor heads-up: soma das best responses, não uma diferença contra
        o valor sob a média -- serve como termômetro de convergência
        comparável entre runs, não como exploitability literal em $).
        Ver aviso de custo em `best_response_value` -- com 3+ seats,
        rode isso separado do treino (não em loop apertado)."""
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        return {
            i: self.best_response_value(i, avg_strategy, iterations=iterations, seed=seed, policy_samples=policy_samples)
            for i in range(self.n_seats)
        }

    def check_opener_convergence(self, avg_strategy=None, sample_hands=None,
                                  iterations=25, gap_threshold=0.3, seed=99):
        """Checagem de sanidade OBRIGATORIA antes de considerar um resultado
        pronto pra uso (ver CLAUDE.md) -- vai alem de conferir maos extremas
        e estrutura: para cada mao da amostra, calcula o valor REAL de abrir
        vs desistir (media sobre reamostragens independentes dos
        adversarios, via os mesmos helpers `_eval_fold_or_jam`/
        `_sample_other_hands` usados pelo best-response sem vazamento) e
        compara com a frequencia que o abridor (seat 0) realmente aprendeu.

        Isso pega o problema de "mao travada" do CFR classico -- uma mao
        que teve azar de amostragem cedo no treino e nunca mais se
        recuperou, mesmo com milhoes de iteracoes (jah visto em producao:
        A5s, A2s, KQs, QJs apareceram quase sempre foldando quando abrir
        claramente valia mais). O CFR+ (regret com piso em zero + media
        ponderada por iteracao, ver InfoSet.update_regret e o comentario
        de t em _play_open_or_fold) deixa isso bem mais raro, mas essa
        checagem continua sendo o jeito de CONFIRMAR que nao aconteceu de
        novo num resultado especifico -- nao e' opcional.

        Retorna lista de dicts {hand, gap, trained_freq} para as maos onde
        a direcao do treino diverge do valor real (gap > gap_threshold e
        o treino faz o oposto)."""
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        if sample_hands is None:
            sample_hands = self.classes  # todas as 169 por padrao

        rng = random.Random(seed)
        val_fold_const = self._icm_fold_root({}).get(0, 0.0)

        flags = []
        for hand in sample_hands:
            val_open = 0.0
            for _ in range(iterations):
                hands = self._sample_other_hands(0, hand, rng)
                val_open += self._eval_fold_or_jam(1, hands, avg_strategy).get(0, 0.0)
            val_open /= iterations
            gap = val_open - val_fold_const
            trained = avg_strategy["phase1"][0][hand]
            wrong = (gap > gap_threshold and trained < 0.5) or (gap < -gap_threshold and trained > 0.5)
            if wrong:
                flags.append({"hand": hand, "gap": gap, "trained_freq": trained})
        return flags
