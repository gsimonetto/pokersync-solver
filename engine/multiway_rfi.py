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

import itertools
import random
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.fast_eval import RANK_BIT, RANK_KEY, SUIT_KEY, tables  # noqa: E402
from engine.hand_classes import all_hand_classes, combo_count  # noqa: E402
from engine.icm import icm_equity  # noqa: E402
from engine.multiway_equity import class_combo_indices, multiway_equity_counts  # noqa: E402

# Versão da LÓGICA do motor (não do arquivo): muda sempre que uma correção
# altera o que o treino aprende. Checkpoints gravados com outra versão não
# podem ser retomados (misturariam dois algoritmos diferentes na mesma
# média) -- ver run_offline_all_positions.py::load_checkpoint.
#   v3 (2026-09-24): ICM sem divisão por zero com vários eliminados,
#       cartas dadas de verdade (sem mãos impossíveis, e as cartas de
#       quem foldou saem do baralho -- ver _BoardOracle), showdown chipEV
#       mantendo a perda de quem foldou com blind.
#   v4 (2026-09-24): fase 2 separada por quem ja pagou o jam (overcall).
ENGINE_VERSION = "multiway-rfi-v4-2026-09-24"


from engine.card_removal import CLASS_OF as _CLASS_OF  # noqa: E402  (tabela carta+carta -> classe)



class _Table(dict):
    """Mãos de uma mesa sorteada: {seat: classe} (igual antes, é um dict)
    + `holes`, as cartas DE VERDADE de cada seat (quando card_removal), e
    `oracle`, criado na primeira vez que a mesa chega num showdown."""
    __slots__ = ("holes", "oracle")

    def __init__(self, classes_by_seat, holes):
        super().__init__(classes_by_seat)
        self.holes = holes
        self.oracle = None


class _BoardOracle:
    """Equity de QUALQUER grupo de jogadores da mesa a partir de um único
    lote de mesas (5 cartas) sorteadas uma vez só (2026-09-24).

    Antes cada showdown da árvore sorteava suas próprias combinações de
    cartas e suas próprias mesas do zero -- com 8 seats são 247 showdowns
    por iteração (~250 ms só disso). Aqui: como o treino dá cartas de
    verdade a cada seat, sorteia `n_boards` mesas das cartas que SOBRARAM
    (as de quem foldou também saem do baralho, como na vida real), avalia
    a mão de cada seat em cada mesa uma vez, e a equity de um grupo é só
    ver quem tem o maior valor dentro do grupo em cada mesa (empate
    divide) -- ~13x mais rápido em 8 seats, e sem cache (memória ~zero).

    Estatisticamente: cada equity continua sendo uma estimativa SEM viés
    do valor verdadeiro pra essas cartas (mesmas mesas pra todos os
    grupos da iteração só deixam as estimativas correlacionadas entre
    si, o que ajuda a comparar fold vs call, não atrapalha)."""

    __slots__ = ("values", "memo")

    def __init__(self, holes, n_boards, rng):
        flush_suit, flush_value, nonflush = tables()
        rk_key, sk_key, rbit = RANK_KEY, SUIT_KEY, RANK_BIT
        used = 0
        for c1, c2 in holes:
            used |= (1 << c1) | (1 << c2)
        rand = rng.random
        values = []
        for _ in range(n_boards):
            board = []
            mask = used
            while len(board) < 5:
                c = int(rand() * 52)
                if mask >> c & 1:
                    continue
                mask |= 1 << c
                board.append(c)
            b0, b1, b2, b3, b4 = board
            brk = rk_key[b0] + rk_key[b1] + rk_key[b2] + rk_key[b3] + rk_key[b4]
            bsk = sk_key[b0] + sk_key[b1] + sk_key[b2] + sk_key[b3] + sk_key[b4]
            row = []
            for c1, c2 in holes:
                fs = flush_suit[bsk + sk_key[c1] + sk_key[c2]]
                if fs < 0:
                    row.append(nonflush[brk + rk_key[c1] + rk_key[c2]])
                else:
                    m = 0
                    for c in (b0, b1, b2, b3, b4, c1, c2):
                        if c & 3 == fs:
                            m |= rbit[c]
                    row.append(flush_value[m])
            values.append(row)
        self.values = values
        self.memo = {}

    def equities(self, live):
        """{seat: fração média do pote} pro grupo `live` (lista ordenada)."""
        key = tuple(live)
        cached = self.memo.get(key)
        if cached is not None:
            return cached
        shares = dict.fromkeys(live, 0.0)
        for row in self.values:
            best = -1
            winners = None
            for i in live:
                v = row[i]
                if v > best:
                    best = v
                    winners = [i]
                elif v == best:
                    winners.append(i)
            if len(winners) == 1:
                shares[winners[0]] += 1.0
            else:
                share = 1.0 / len(winners)
                for i in winners:
                    shares[i] += share
        n = len(self.values)
        result = {i: shares[i] / n for i in live}
        self.memo[key] = result
        return result


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
                 use_cfr_plus: bool = True, card_removal: bool = True):
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
        card_removal: True (padrao, 2026-09) = as maos de cada iteracao
                    saem de um baralho de verdade (52 cartas, sem
                    repetir) e so' depois viram classe. Antes cada seat
                    sorteava sua CLASSE de forma independente -- isso
                    gerava mesas impossiveis (ex: 3 jogadores com AA, ou
                    AA + AA + AKs = 5 ases) que chegavam ao showdown com
                    uma equity inventada (divisao igual), e ignorava o
                    efeito de bloqueio (quem tem AA deixa os outros com
                    menos chance de ter um As). Com 8 seats, cerca de 8%
                    das maos do treino caiam nesse caso. False = sorteio
                    antigo, mantido so' pra comparacao exata com o motor
                    heads-up (rfi_jam.py, que sorteia classes
                    independentes) nos testes do caso degenerado de 2
                    jogadores.
        """
        self.seat_names = seat_names
        self.n_seats = len(seat_names)
        self.seat_idx_in_table = seat_idx_in_table
        self.seat_posts = seat_posts
        self.table_stacks = list(table_stacks)
        self.payouts = payouts
        self.use_icm = use_icm
        self.use_cfr_plus = use_cfr_plus
        self.card_removal = card_removal
        if len(seat_idx_in_table) != self.n_seats or len(seat_posts) != self.n_seats:
            raise ValueError("seat_names, seat_idx_in_table e seat_posts precisam ter o mesmo tamanho")
        if self.n_seats < 2:
            raise ValueError("precisa de pelo menos 2 seats (abridor + 1 defensor)")
        if 2 * self.n_seats > 52:
            raise ValueError("seats demais pra um baralho de 52 cartas")
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
        # v4 (2026-09-24, overcall): alem do jammer, a ficha de fase 2 tambem
        # depende de QUEM JA PAGOU o jam antes deste seat (informacao
        # publica). Pagar um jam sozinho e pagar depois de alguem ja ter
        # pago (overcall, pote de 3+ jogadores) sao decisoes diferentes --
        # a segunda precisa de mao mais forte. Antes as duas situacoes
        # dividiam a mesma ficha e o seat aprendia uma media errada pras
        # duas. Chave: phase2[seat][jammer][callers][classe], com callers =
        # tupla ordenada dos seats que pagaram antes (() = ninguem pagou).
        self.phase1 = [{c: InfoSet(2) for c in classes} for _ in range(self.n_seats)]
        self.phase2 = [
            {
                j: {callers: {c: InfoSet(2) for c in classes} for callers in self._possible_callers(seat_i, j)}
                for j in self._possible_jammers(seat_i)
            }
            for seat_i in range(self.n_seats)
        ]

        self.ante_pool = ante_pool

        self._icm_cache = {}
        self._equity_cache = equity_cache if equity_cache is not None else {}
        # Gerador usado no Monte Carlo de equity. None = `random` global
        # (o treino semeia o global em train(), entao fica reproduzivel);
        # as checagens trocam por um gerador proprio durante a execucao.
        self._eq_rng = None

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

    def _responders(self, jammer):
        """Ordem de resposta ao jam de `jammer`: quem vem depois dele, e o
        abridor por ultimo (ja tinha aberto)."""
        return [i for i in range(self.n_seats) if i > jammer] + [0]

    def _possible_callers(self, seat_i, jammer):
        """Todos os grupos possiveis de quem pagou o jam ANTES de `seat_i`
        (subconjuntos de quem responde antes dele), como tuplas ordenadas."""
        responders = self._responders(jammer)
        before = responders[:responders.index(seat_i)]
        return [tuple(sorted(c)) for k in range(len(before) + 1) for c in itertools.combinations(before, k)]

    @staticmethod
    def _callers_key(live_set, jammer):
        return tuple(sorted(s for s in live_set if s != jammer))

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
        # bust_tiebreak: stack no COMECO da mao -- regra de torneio pra
        # quem quebra na mesma mao (comum aqui: all-in de 3+ jogadores,
        # 1 ganha e os outros zeram). Ver engine/icm.py.
        eq = icm_equity(stacks, self.payouts, bust_tiebreak=self.table_stacks)
        result = {seat: eq[self.seat_idx_in_table[seat]] for seat in range(self.n_seats)}
        self._icm_cache[key] = result
        return result

    # Tamanho de cada lote de simulacao (novo ou de refinamento) e teto de
    # amostras acumuladas por combinacao -- ver docstring de _multiway_eq.
    EQUITY_BATCH = 150
    EQUITY_MAX_SAMPLES = 2000
    # Showdowns com MAIS jogadores que isso nao entram no cache (2026-09):
    # o numero de combinacoes possiveis explode (4 jogadores: ~35 milhoes
    # de combinacoes de classes; 8 jogadores: trilhoes), entao quase toda
    # combinacao aparece UMA vez so' no treino inteiro -- guardar isso nao
    # reaproveitava nada e so' enchia a memoria (medido: ~226 entradas
    # novas por iteracao em UTG vs BB -> dezenas de GB em 1M iteracoes,
    # MemoryError garantido no PC, e checkpoints gigantes). Sem cache,
    # cada visita usa uma estimativa NOVA e independente (sem vies -- o
    # ruido se cancela ao longo das iteracoes do CFR, igual o ruido de
    # sorteio de maos). Pares (~14 mil combinacoes) e trincas (~820 mil)
    # continuam no cache, com memoria limitada.
    EQUITY_CACHE_MAX_PLAYERS = 3
    # False = mesmo com cartas de verdade, a equity sai por classe
    # (_multiway_eq) -- so' pra teste cruzado com o motor heads-up exato,
    # que usa a matriz de equity por classe.
    USE_BOARD_ORACLE = True

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

        cacheable = len(sorted_hands) <= self.EQUITY_CACHE_MAX_PLAYERS
        cached = self._equity_cache.get(sorted_hands) if cacheable else None

        if cached is not None and cached[1] >= self.EQUITY_MAX_SAMPLES:
            sorted_eqs = cached[0]
        else:
            # n_validas pode ser MENOR que EQUITY_BATCH quando as classes
            # disputam as mesmas cartas (ex: AA vs AA vs KK vs KK) -- a media
            # acumulada usa o numero REAL de simulacoes de cada lado (antes
            # assumia sempre EQUITY_BATCH, superestimando o peso do lote).
            wins, valid = multiway_equity_counts(list(sorted_hands), self.EQUITY_BATCH, self._eq_rng)
            if cached is not None:
                cached_eqs, cached_n = cached
                new_n = cached_n + valid
                sorted_eqs = [(cached_eqs[i] * cached_n + wins[i]) / new_n for i in range(len(wins))]
            elif valid > 0:
                new_n = valid
                sorted_eqs = [w / valid for w in wins]
            else:
                # Combinacao impossivel de cartas (ex: 3x AA). Com
                # card_removal=True (padrao) o treino nunca gera isso; so'
                # acontece no modo de comparacao com o motor heads-up.
                new_n = 0
                sorted_eqs = [1.0 / len(hands)] * len(hands)
            if cacheable and new_n > 0:
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
        for t in range(start_t, start_t + iterations):
            self._play_open_or_fold(self._deal_hands(random), t)

    @contextmanager
    def _equity_rng(self, seed):
        """Durante best-response/checagens, o Monte Carlo de equity usa um
        gerador PROPRIO semeado por `seed` (antes usava o `random` global
        + o gerador interno do treys.Deck, semeado pelo sistema -- rodar a
        MESMA checagem duas vezes dava numeros diferentes)."""
        previous = self._eq_rng
        self._eq_rng = random.Random(f"equity-{seed}")
        try:
            yield
        finally:
            self._eq_rng = previous

    def _deal_hands(self, rng):
        """Uma mao pra cada seat. card_removal=True: baralho de verdade
        (cartas sem repeticao, depois convertidas em classe); False:
        classe sorteada independente por seat (modo antigo, ver __init__)."""
        if not self.card_removal:
            return {i: rng.choices(self.classes, weights=self._weights_list, k=1)[0]
                    for i in range(self.n_seats)}
        cards = rng.sample(range(52), 2 * self.n_seats)
        holes = [(cards[2 * i], cards[2 * i + 1]) for i in range(self.n_seats)]
        return _Table({i: _CLASS_OF[c1][c2] for i, (c1, c2) in enumerate(holes)}, holes)

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
        infoset = self.phase2[seat_i][jammer][self._callers_key(live_set, jammer)][hands[seat_i]]
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

        # multiway showdown entre os "live". Mesa com cartas de verdade
        # (card_removal, o padrão): equity do oráculo de mesas da própria
        # mesa, criado no primeiro showdown dela (ver _BoardOracle). Sem
        # cartas (modo de comparação com o motor heads-up): equity por
        # classe, como antes (_multiway_eq).
        holes = getattr(hands, "holes", None) if self.USE_BOARD_ORACLE else None
        if holes is not None:
            oracle = hands.oracle
            if oracle is None:
                oracle = hands.oracle = _BoardOracle(holes, self.EQUITY_BATCH, self._eq_rng or random)
            eqs = oracle.equities(live)
        else:
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

        # Correcao (2026-09): devolve TODOS os seats. Antes so' entravam os
        # vivos e quem tinha valor > 0 -- no modo ICM isso nao mudava nada
        # (todo mundo com fichas tem $ICM > 0), mas em chipEV o valor de
        # quem foldou com dinheiro no pote e' NEGATIVO (ex: SB perde 0.5,
        # abridor perde o open) e sumia do dict; quem le com
        # .get(seat, 0.0) passava a enxergar 0 em vez da perda real, e o
        # fold desses seats parecia mais barato do que e' (vies pra foldar,
        # so' nos showdowns com 2+ jogadores -- no ramo "todo mundo foldou
        # pro jam" o valor ja' vinha certo).
        result = {}
        for s in range(self.n_seats):
            val = 0.0
            for winner in live:
                val += eqs.get(winner, 0.0) * icm_by_winner[winner].get(s, 0.0)
            result[s] = val
        return result

    # ---- checkpoint (estado de treino como dados simples) ----------------
    #
    # Os scripts offline gravavam o OBJETO inteiro (pickle da classe). Isso
    # quebra de jeitos confusos quando o codigo muda entre uma rodada e
    # outra (ex: checkpoint gravado antes do CFR+ existir -> AttributeError
    # 'use_cfr_plus' ao retomar). Agora o checkpoint guarda so' numeros
    # (regret_sum/strategy_sum de cada ficha + cache de equity) e a versao
    # da logica (ENGINE_VERSION); quem carrega recria o solver pela config
    # e confere a versao antes de importar.

    def export_state(self):
        def pack(infoset):
            return (list(infoset.regret_sum), list(infoset.strategy_sum))
        return {
            "engine_version": ENGINE_VERSION,
            "phase1": [{c: pack(inf) for c, inf in seat.items()} for seat in self.phase1],
            "phase2": [
                {j: {callers: {c: pack(inf) for c, inf in by_class.items()} for callers, by_class in by_callers.items()}
                 for j, by_callers in seat.items()}
                for seat in self.phase2
            ],
            "equity_cache": dict(self._equity_cache),
        }

    def import_state(self, state):
        if state.get("engine_version") != ENGINE_VERSION:
            raise ValueError(
                f"estado gravado com outra versao do motor ({state.get('engine_version')!r}), "
                f"atual e' {ENGINE_VERSION!r} -- nao da pra continuar esse treino"
            )
        if len(state["phase1"]) != self.n_seats:
            raise ValueError("estado gravado com outro numero de seats")

        def unpack(infoset, packed):
            regret, strat = packed
            infoset.regret_sum = list(regret)
            infoset.strategy_sum = list(strat)

        for seat_i, seat in enumerate(state["phase1"]):
            for c, packed in seat.items():
                unpack(self.phase1[seat_i][c], packed)
        for seat_i, seat in enumerate(state["phase2"]):
            for j, by_callers in seat.items():
                for callers, by_class in by_callers.items():
                    for c, packed in by_class.items():
                        unpack(self.phase2[seat_i][j][callers][c], packed)
        self._equity_cache = dict(state.get("equity_cache", {}))

    def average_strategy(self):
        return {
            "phase1": [
                {c: self.phase1[i][c].average_strategy()[1] for c in self.classes}
                for i in range(self.n_seats)
            ],
            # phase2[seat][jammer][callers][classe] = prob de PAGAR -- uma
            # estrategia por jammer E por grupo de quem ja pagou antes (ver
            # __init__: quem deu o jam e quem ja pagou sao informacao publica).
            "phase2": [
                {
                    j: {
                        callers: {c: by_class[c].average_strategy()[1] for c in self.classes}
                        for callers, by_class in by_callers.items()
                    }
                    for j, by_callers in self.phase2[i].items()
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
        return self._mix(
            p_jam,
            lambda: self._eval_fold_or_jam(seat_i + 1, hands, avg),
            lambda: self._eval_phase2(seat_i, hands, avg),
        )

    # Poda na AVALIACAO (best-response/checagens, nunca no treino): galho
    # com peso menor que isso na estrategia media nao e' calculado -- ele
    # mudaria o resultado em no maximo ~1e-6 x (maior variacao de $ICM da
    # mao), bem abaixo de qualquer limite de checagem. Sem isso, cada
    # mesa sorteada percorria a arvore inteira (2^n galhos) mesmo quando
    # quase todo mundo sempre folda aquela mao -- em 7-8 seats a avaliacao
    # final levava mais que o proprio treino. 0 desliga a poda.
    EVAL_PRUNE_BELOW = 1e-6

    def _mix(self, p_act, fold_fn, act_fn):
        """Valor esperado de (1-p) * fold + p * agir, calculando so' o(s)
        galho(s) com peso relevante (ver EVAL_PRUNE_BELOW)."""
        eps = self.EVAL_PRUNE_BELOW
        if p_act <= eps:
            return fold_fn()
        if p_act >= 1.0 - eps:
            return act_fn()
        return self._blend(fold_fn(), act_fn(), 1 - p_act, p_act)

    def _eval_phase2(self, jammer, hands, avg):
        responders = [i for i in range(self.n_seats) if i > jammer]
        responders.append(0)
        return self._eval_resolve_responders(jammer, responders, 0, {jammer}, hands, avg)

    def _p_call(self, avg, seat_i, jammer, live_set, hands):
        return avg["phase2"][seat_i][jammer][self._callers_key(live_set, jammer)][hands[seat_i]]

    def _eval_resolve_responders(self, jammer, responders, idx, live_set, hands, avg):
        if idx >= len(responders):
            return self._showdown(live_set, hands)
        seat_i = responders[idx]
        p_call = self._p_call(avg, seat_i, jammer, live_set, hands)
        return self._mix(
            p_call,
            lambda: self._eval_resolve_responders(jammer, responders, idx + 1, live_set, hands, avg),
            lambda: self._eval_resolve_responders(jammer, responders, idx + 1, live_set | {seat_i}, hands, avg),
        )

    def _eval_resolve_responders_forced(self, jammer, responders, idx, live_set, hands, avg,
                                         forced_seat, forced_action):
        """Como _eval_resolve_responders, mas a decisão de `forced_seat`
        (quando aparece como responder) é FORÇADA em vez de usar
        avg_strategy -- usado tanto pra FIXAR a política de forced_seat
        (chamado com forced_action=0 e =1 pra comparar) quanto na avaliação
        final (com a política já fixada, olhando só a própria mão de
        forced_seat).

        forced_action: 0 (fold), 1 (call), ou um dict {callers: 0/1/None}
        -- a ação pode depender de QUEM JÁ PAGOU antes (ver __init__); None
        (ou grupo ausente do dict) = usa a frequência treinada naquele
        ponto (política não fixada por falta de amostra, grupo raríssimo)."""
        if idx >= len(responders):
            return self._showdown(live_set, hands)
        seat_i = responders[idx]
        if seat_i == forced_seat:
            action = forced_action
            if isinstance(forced_action, dict):
                action = forced_action.get(self._callers_key(live_set, jammer))
            if action is not None:
                next_live = live_set | {seat_i} if action == 1 else live_set
                return self._eval_resolve_responders_forced(
                    jammer, responders, idx + 1, next_live, hands, avg, forced_seat, forced_action
                )
        p_call = self._p_call(avg, seat_i, jammer, live_set, hands)
        return self._mix(
            p_call,
            lambda: self._eval_resolve_responders_forced(
                jammer, responders, idx + 1, live_set, hands, avg, forced_seat, forced_action
            ),
            lambda: self._eval_resolve_responders_forced(
                jammer, responders, idx + 1, live_set | {seat_i}, hands, avg, forced_seat, forced_action
            ),
        )

    def _sample_other_hands(self, fixed_seat, fixed_hand, rng):
        """Maos dos OUTROS seats dada a classe de `fixed_seat` -- com
        card_removal, um combo concreto da classe fixa sai do baralho
        antes de dar as cartas dos outros (quem tem AA bloqueia ases)."""
        if not self.card_removal:
            hands = {fixed_seat: fixed_hand}
            for i in range(self.n_seats):
                if i != fixed_seat:
                    hands[i] = rng.choices(self.classes, weights=self._weights_list, k=1)[0]
            return hands
        combos = class_combo_indices(fixed_hand)
        c1, c2 = combos[int(rng.random() * len(combos))]
        cards = rng.sample([c for c in range(52) if c != c1 and c != c2], 2 * (self.n_seats - 1))
        holes = []
        k = 0
        for i in range(self.n_seats):
            if i == fixed_seat:
                holes.append((c1, c2))
            else:
                holes.append((cards[k], cards[k + 1]))
                k += 2
        classes = {i: (fixed_hand if i == fixed_seat else _CLASS_OF[a][b]) for i, (a, b) in enumerate(holes)}
        return _Table(classes, holes)

    def _history_weight(self, hands, avg, seat, jammer=None, callers=None):
        """Chance (dadas as maos) de a acao publica ter chegado ate a
        decisao de `seat` do jeito que chegou -- abridor ABRIU (se `seat`
        nao for o proprio abridor), todo mundo entre o abridor e o jammer
        (ou `seat`, em fase 1) FOLDOU, e o `jammer` JAMMOU (fase 2). E' o
        peso certo pra sortear as maos dos adversarios "como elas
        realmente sao" naquele ponto da arvore (ver _sample_posterior)."""
        w = 1.0
        if seat != 0:
            w *= avg["phase1"][0][hands[0]]
        last_folder = (jammer if jammer is not None else seat) - 1
        for k in range(1, last_folder + 1):
            w *= 1.0 - avg["phase1"][k][hands[k]]
        if jammer is not None:
            w *= avg["phase1"][jammer][hands[jammer]]
            if callers is not None and w > 0.0:
                # quem respondeu ANTES de `seat`: pagou (se esta em callers)
                # ou foldou -- tambem e' historico publico (v4, overcall)
                live = {jammer}
                for r in self._responders(jammer):
                    if r == seat:
                        break
                    p = self._p_call(avg, r, jammer, live, hands)
                    if r in callers:
                        w *= p
                        live.add(r)
                    else:
                        w *= 1.0 - p
        return w

    def _sample_posterior(self, seat, hand, avg, rng, samples, jammer=None, max_draws_per_sample=400,
                          callers=None):
        """Sorteia `samples` mesas (maos dos OUTROS seats) CONDICIONADAS ao
        historico publico que leva ate a decisao de `seat` com `hand`
        (rejeicao: aceita cada sorteio com probabilidade _history_weight).

        Correcao (2026-09): as checagens/best-response sorteavam os
        adversarios SEM esse condicionamento -- ex: ao avaliar o jam do
        BTN depois do open do CO, a mao do CO saia de QUALQUER lugar do
        baralho (inclusive 72o, que o CO nunca abre), e a resposta dele ao
        jam usava a frequencia de call "aprendida" pra uma mao que nunca
        chega ali (ruido puro). So' a decisao do proprio abridor na raiz
        (ninguem agiu antes) estava certa. Devolve a lista de maos aceitas
        (pode ter menos que `samples` se o historico for rarissimo com
        essa mao -- quem chama decide o que fazer)."""
        accepted = []
        budget = samples * max_draws_per_sample
        while len(accepted) < samples and budget > 0:
            budget -= 1
            hands = self._sample_other_hands(seat, hand, rng)
            w = self._history_weight(hands, avg, seat, jammer, callers)
            if w >= 1.0 or (w > 0.0 and rng.random() < w):
                accepted.append(hands)
        return accepted

    def _phase1_values(self, seat, hands, avg):
        """(valor de foldar, valor de jammar) pra `seat` (>= 1) numa mesa
        especifica, com todo mundo mais seguindo `avg`."""
        val_fold = self._eval_fold_or_jam(seat + 1, hands, avg).get(seat, 0.0)
        val_jam = self._eval_phase2(seat, hands, avg).get(seat, 0.0)
        return val_fold, val_jam

    def _phase2_values(self, seat, jammer, hands, avg, callers=()):
        """(valor de foldar, valor de pagar) pra `seat` respondendo ao jam
        de `jammer` depois de `callers` terem pagado (e o resto de quem
        agiu antes ter foldado), numa mesa especifica."""
        responders = self._responders(jammer)
        idx = responders.index(seat)
        live = {jammer, *callers}
        icm_fold = self._eval_resolve_responders_forced(jammer, responders, idx, live, hands, avg, seat, 0)
        icm_call = self._eval_resolve_responders_forced(jammer, responders, idx, live, hands, avg, seat, 1)
        return icm_fold.get(seat, 0.0), icm_call.get(seat, 0.0)

    # Grupo de "quem ja pagou" alcancado menos que isso por mao jogada nao
    # e' avaliado no best-response/checagem (v4): com 8 seats existem
    # dezenas de grupos por jammer, e os raros (ex: 4 jogadores ja pagaram)
    # quase nunca acontecem -- o sorteio condicionado nao acha mesas
    # suficientes e so' gastaria tempo. No best-response esses pontos usam
    # a frequencia treinada; na checagem entram no resumo como "raros".
    MIN_NODE_FREQ = 1e-4

    def _phase2_node_freq(self, avg, rng, deals=20_000):
        """Frequencia estimada (por mao jogada) de cada ponto de decisao de
        fase 2: {(seat, jammer, callers): prob}. Monte Carlo barato: da as
        cartas, pesa o caminho ate o jam de cada jammer possivel pela
        estrategia media e sorteia as respostas dos responders."""
        freq = {}
        n = self.n_seats
        for _ in range(deals):
            hands = self._deal_hands(rng)
            reach = avg["phase1"][0][hands[0]]
            for j in range(1, n):
                if reach <= 0.0:
                    break
                p_jam = avg["phase1"][j][hands[j]]
                w = reach * p_jam
                reach *= 1.0 - p_jam
                if w <= 0.0:
                    continue
                live = {j}
                for r in self._responders(j):
                    key = (r, j, self._callers_key(live, j))
                    freq[key] = freq.get(key, 0.0) + w
                    if rng.random() < self._p_call(avg, r, j, live, hands):
                        live.add(r)
        return {k: v / deals for k, v in freq.items()}

    def _frequent_callers(self, seat, jammer, node_freq):
        return [c for c in self._possible_callers(seat, jammer)
                if node_freq.get((seat, jammer, c), 0.0) >= self.MIN_NODE_FREQ]

    def _fix_policy_phase1(self, br_seat, avg, samples, rng):
        """Fixa fold-vs-jam de `br_seat` (br_seat >= 1) pra cada classe de
        mão dele, SEM espiar a amostra dos adversários -- média sobre
        `samples` mesas sorteadas JÁ condicionadas ao que aconteceu antes
        (abridor abriu, quem estava no meio foldou -- ver
        _sample_posterior) antes de decidir."""
        policy = {}
        for h in self.classes:
            val_fold = 0.0
            val_jam = 0.0
            for hands in self._sample_posterior(br_seat, h, avg, rng, samples):
                vf, vj = self._phase1_values(br_seat, hands, avg)
                val_fold += vf
                val_jam += vj
            policy[h] = 1 if val_jam > val_fold else 0
        return policy

    def _fix_policy_phase2(self, br_seat, jammer, avg, samples, rng, node_freq):
        """Fixa fold-vs-call de `br_seat` respondendo ao jam de `jammer`
        (br_seat == 0, ou br_seat > jammer), por GRUPO de quem ja pagou e
        por classe de mão: {callers: {classe: 0/1/None}}. As mãos dos
        adversários vêm condicionadas ao histórico inteiro (abridor abriu,
        quem estava antes do jammer foldou, jammer JAMMOU, quem respondeu
        antes pagou/foldou) -- igual rfi_jam.py faz por enumeração exata,
        aqui por amostragem com rejeição (ver _sample_posterior). None =
        amostra insuficiente (mão que quase nunca chega ali): a avaliação
        usa a frequência treinada nesse ponto. Grupos raros (abaixo de
        MIN_NODE_FREQ) ficam de fora pelo mesmo motivo."""
        policy = {}
        for callers in self._frequent_callers(br_seat, jammer, node_freq):
            by_hand = {}
            for h in self.classes:
                tables = self._sample_posterior(br_seat, h, avg, rng, samples, jammer=jammer, callers=callers)
                if len(tables) < max(2, samples // 4):
                    by_hand[h] = None
                    continue
                val_fold, val_call = 0.0, 0.0
                for hands in tables:
                    vf, vc = self._phase2_values(br_seat, jammer, hands, avg, callers)
                    val_fold += vf
                    val_call += vc
                by_hand[h] = 1 if val_call > val_fold else 0
            policy[callers] = by_hand
        return policy

    @staticmethod
    def _policy_for_hand(policy_by_callers, hand):
        """{callers: {classe: acao}} -> {callers: acao} pra uma mão (o
        formato que _eval_resolve_responders_forced aceita)."""
        return {callers: by_hand.get(hand) for callers, by_hand in policy_by_callers.items()}

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
        responders = [i for i in range(self.n_seats) if i > seat_i]
        responders.append(0)
        action0 = self._policy_for_hand(phase2_policy[seat_i], hands[0])
        return self._mix(
            p_jam,
            lambda: self._eval_fold_or_jam_seat0_fixed(seat_i + 1, hands, avg, phase2_policy),
            lambda: self._eval_resolve_responders_forced(seat_i, responders, 0, {seat_i}, hands, avg, 0, action0),
        )

    def _fix_br_policy(self, br_seat, avg, samples, rng):
        node_freq = self._phase2_node_freq(avg, rng)
        if br_seat == 0:
            phase2_policy = {
                jammer: self._fix_policy_phase2(0, jammer, avg, samples, rng, node_freq)
                for jammer in range(1, self.n_seats)
            }
            root_policy = self._fix_policy_root_seat0(avg, phase2_policy, samples, rng)
            return {"root": root_policy, "phase2": phase2_policy}
        phase1_policy = self._fix_policy_phase1(br_seat, avg, samples, rng)
        phase2_policy = {
            jammer: self._fix_policy_phase2(br_seat, jammer, avg, samples, rng, node_freq)
            for jammer in range(1, br_seat)
        }
        return {"phase1": phase1_policy, "phase2": phase2_policy}

    def _eval_root_full(self, hands, avg, br_seat, policy):
        if br_seat == 0:
            if policy["root"][hands[0]] == 0:
                return self._icm_fold_root(hands)
            return self._eval_fold_or_jam_full(1, hands, avg, br_seat, policy)
        p_open = avg["phase1"][0][hands[0]]
        return self._mix(
            p_open,
            lambda: self._icm_fold_root(hands),
            lambda: self._eval_fold_or_jam_full(1, hands, avg, br_seat, policy),
        )

    def _eval_fold_or_jam_full(self, seat_i, hands, avg, br_seat, policy):
        if seat_i >= self.n_seats:
            return self._terminal_all_fold(hands)
        if seat_i == br_seat:
            if policy["phase1"][hands[seat_i]] == 0:
                return self._eval_fold_or_jam_full(seat_i + 1, hands, avg, br_seat, policy)
            return self._eval_phase2_full(seat_i, hands, avg, br_seat, policy)
        p_jam = avg["phase1"][seat_i][hands[seat_i]]
        return self._mix(
            p_jam,
            lambda: self._eval_fold_or_jam_full(seat_i + 1, hands, avg, br_seat, policy),
            lambda: self._eval_phase2_full(seat_i, hands, avg, br_seat, policy),
        )

    def _eval_phase2_full(self, jammer, hands, avg, br_seat, policy):
        responders = [i for i in range(self.n_seats) if i > jammer]
        responders.append(0)
        if br_seat in responders and (br_seat == 0 or br_seat > jammer):
            action = self._policy_for_hand(policy["phase2"][jammer], hands[br_seat])
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
        with self._equity_rng(seed):
            policy = self._fix_br_policy(br_seat, avg_strategy, policy_samples, rng)
            total = 0.0
            for _ in range(iterations):
                hands = self._deal_hands(rng)
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
                                  iterations=25, gap_threshold=0.3, seed=99,
                                  phase2_fix_samples=40, equity_precision_batch=600,
                                  z=3.0, max_iterations_factor=8):
        """Checagem de sanidade OBRIGATORIA antes de considerar um resultado
        pronto pra uso (ver CLAUDE.md) -- vai alem de conferir maos extremas
        e estrutura: para cada mao da amostra, calcula o valor REAL de abrir
        vs desistir e compara com a frequencia que o abridor (seat 0)
        realmente aprendeu.

        Isso pega o problema de "mao travada" do CFR classico -- uma mao
        que teve azar de amostragem cedo no treino e nunca mais se
        recuperou, mesmo com milhoes de iteracoes (jah visto em producao:
        A5s, A2s, KQs, QJs apareceram quase sempre foldando quando abrir
        claramente valia mais). O CFR+ (regret com piso em zero + media
        ponderada por iteracao, ver InfoSet.update_regret e o comentario
        de t em _play_open_or_fold) deixa isso bem mais raro, mas essa
        checagem continua sendo o jeito de CONFIRMAR que nao aconteceu de
        novo num resultado especifico -- nao e' opcional.

        v2 (2026-09, achado auditando um resultado de 4 seats com 40% das
        maos flagadas -- desproporcional demais pra ser so' convergencia
        lenta): a v1 tinha DOIS problemas que infestavam o "gap" de ruido/
        vies, sem relacao com a qualidade real do treino --
          1. VAZAMENTO: usava `_eval_fold_or_jam` puro, que decide a
             resposta do proprio abridor em fase 2 (call/fold contra um
             jam) pela media que ELE MESMO aprendeu -- se essa media
             ainda nao convergiu bem (fase 2 nunca teve checagem
             equivalente, ver nota no CLAUDE.md), isso contamina o
             julgamento da decisao de fase 1 que estamos tentando medir.
             Fix: fixa a resposta OTIMA de fase 2 do abridor primeiro
             (via `_fix_policy_phase2`, mesma tecnica sem vazamento de
             `compute_exploitability`/`_fix_policy_root_seat0`), e usa
             `_eval_fold_or_jam_seat0_fixed` daqui pra frente.
          2. RUIDO: cada reamostragem de maos dos adversarios caia quase
             sempre numa combinacao NOVA (com 3+ adversarios o espaco de
             combinacoes e' grande demais pra repetir dentro de poucas
             iteracoes), entao o cache incremental de equity (pensado pra
             CFR, que revisita a MESMA combinacao milhoes de vezes) nunca
             tinha chance de acumular precisao -- cada amostra usava so'
             EQUITY_BATCH=150 simulacoes brutas, sozinha, sem refinamento.
             Confirmado empiricamente: rodando a MESMA mao duas vezes
             (mesma avg_strategy) o gap trocava de sinal. Fix: em vez de
             pedir mais reamostragens (caro), pede uma equity mais precisa
             POR amostra (equity_precision_batch, default 600 -- 4x mais
             preciso que o normal do treino) so' durante esta checagem.

        v3 (2026-09-24): confirmacao estatistica (ver _confirm_gap) --
        mao so' e' apontada se a diferenca for maior que `gap_threshold`
        E maior que `z` erros-padrao do proprio sorteio (com mais amostras
        automaticas pras candidatas, ate' `max_iterations_factor` vezes
        `iterations`). Com 25 amostras o ruido tipico do gap fica bem
        acima de 0.3, entao sem isso qualquer mao marginal podia ser
        apontada por azar do sorteio.

        Retorna lista de dicts {hand, gap, trained_freq, se, n} para as
        maos onde a direcao do treino diverge do valor real (gap alem do
        limite e do ruido, e o treino faz o oposto)."""
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        if sample_hands is None:
            sample_hands = self.classes  # todas as 169 por padrao

        rng = random.Random(seed)
        val_fold_const = self._icm_fold_root({}).get(0, 0.0)

        with self._equity_rng(seed):
            # fixa a resposta de fase 2 do abridor (seat 0) pra cada jammer
            # possivel, sem vazamento -- feito UMA VEZ so', reaproveitado
            # pra todas as maos de sample_hands.
            phase2_policy = {}
            node_freq = self._phase2_node_freq(avg_strategy, rng)
            for jammer in range(1, self.n_seats):
                phase2_policy[jammer] = self._fix_policy_phase2(
                    0, jammer, avg_strategy, phase2_fix_samples, rng, node_freq
                )

            original_equity_batch = self.EQUITY_BATCH
            self.EQUITY_BATCH = equity_precision_batch
            try:
                flags = []
                for hand in sample_hands:
                    def draw_gaps(k, hand=hand):
                        return [
                            self._eval_fold_or_jam_seat0_fixed(1, hands, avg_strategy, phase2_policy).get(0, 0.0)
                            - val_fold_const
                            for hands in self._sample_posterior(0, hand, avg_strategy, rng, k)
                        ]
                    trained = avg_strategy["phase1"][0][hand]
                    stats = self._confirm_gap(draw_gaps, iterations, max_iterations_factor, gap_threshold, trained, z)
                    self._tally_check(stats)
                    if stats is not None and stats["flag"]:
                        flags.append({"hand": hand, "gap": stats["gap"], "trained_freq": trained,
                                      "se": stats["se"], "n": stats["n"]})
            finally:
                self.EQUITY_BATCH = original_equity_batch
        return flags

    # Resumo da ultima checagem (preenchido por _tally_check): quantas
    # decisoes foram checadas, quantas pareciam na direcao errada mas
    # ficaram DENTRO do ruido mesmo com mais amostras (inconclusivas, nao
    # apontadas), e quantas nao tinham amostra suficiente (historico
    # rarissimo com aquela mao -- ex: jam que quase nunca acontece).
    last_check_summary = None

    def _tally_check(self, stats):
        if self.last_check_summary is None:
            self.last_check_summary = {"checked": 0, "flagged": 0, "inconclusive": 0, "insufficient_data": 0}
        s = self.last_check_summary
        if stats is None:
            s["insufficient_data"] += 1
            return
        s["checked"] += 1
        if stats["flag"]:
            s["flagged"] += 1
        elif stats["inconclusive"]:
            s["inconclusive"] += 1

    @staticmethod
    def _confirm_gap(draw_gaps, n_initial, max_factor, gap_threshold, trained, z):
        """Estatistica de uma decisao: `draw_gaps(k)` devolve ate' k
        valores de (EV da acao agressiva - EV de foldar), um por mesa
        sorteada. Se a media discorda do treino (passa do limite pro lado
        oposto da frequencia treinada), sorteia MAIS mesas (dobrando, SEMPRE
        ate' n_initial*max_factor) antes de concluir -- mesmo espirito da
        regra do CLAUDE.md de reconferir com mais amostras antes de
        acusar um bug. So' marca `flag` se a diferenca passar de
        `gap_threshold` E de `z` erros-padrao. None = amostras
        insuficientes (menos de 2 mesas validas)."""
        gaps = draw_gaps(n_initial)
        n_max = n_initial * max_factor
        while True:
            n = len(gaps)
            if n < 2:
                return None
            mean = sum(gaps) / n
            var = sum((g - mean) ** 2 for g in gaps) / (n - 1)
            se = (var / n) ** 0.5
            disagrees = (mean > gap_threshold and trained < 0.5) or (mean < -gap_threshold and trained > 0.5)
            result = {"gap": mean, "se": se, "n": n, "flag": False, "inconclusive": False}
            if not disagrees:
                return result
            # So' conclui com TODAS as amostras (n_max), nunca no primeiro
            # lote (2026-09-25): o valor de um jam tem cauda pesada -- quase
            # sempre todo mundo folda (ganho pequeno e igual em toda mesa),
            # raramente alguem paga com mao forte (perda grande). Com 25
            # mesas era comum nenhuma ter quem pagasse: todas davam o MESMO
            # valor, o erro-padrao saia ~0 e a mao era apontada na hora
            # (CO 40bb: 17 apontadas, 0 confirmadas com 200 mesas).
            if n >= n_max:
                if abs(mean) > z * se:
                    result["flag"] = True
                else:
                    result["inconclusive"] = True
                return result
            more = draw_gaps(min(n, n_max - n))
            if not more:
                result["inconclusive"] = True
                return result
            gaps += more

    def check_seat_phase1_convergence(self, seat_i, avg_strategy=None, sample_hands=None,
                                       iterations=25, gap_threshold=0.3, seed=99,
                                       equity_precision_batch=600, z=3.0, max_iterations_factor=8):
        """Como check_opener_convergence, mas pra decisao de fold-vs-jam de
        QUALQUER seat >= 1 quando a acao chega nele em fase 1 (todo mundo
        antes ja tendo foldado -- por construcao, ver _play_fold_or_jam).

        Diferente do abridor (seat 0), esses seats tem NO MAXIMO uma
        decisao propria por mao inteira (fold/jam em fase 1 OU responder
        em fase 2 -- ramos mutuamente exclusivos, nunca os dois na mesma
        mao). Por isso NAO ha o problema de vazamento que check_opener_
        convergence precisa corrigir (fixar a resposta de fase 2 antes de
        julgar fase 1): aqui dá pra usar avg_strategy direto em todo
        mundo, inclusive no proprio seat_i, porque a decisao sendo
        avaliada e' a UNICA que ele toma nesse ramo da arvore.

        v3 (2026-09-24): as mesas sorteadas agora respeitam o que
        aconteceu antes (abridor ABRIU, quem estava no meio FOLDOU -- ver
        _sample_posterior); antes a mao do abridor saia de qualquer lugar
        do baralho, e a resposta dele ao jam (que pesa muito no valor do
        jam) vinha de maos que ele nunca abriria. Mais a confirmacao
        estatistica de check_opener_convergence (ver _confirm_gap).

        Retorna lista de dicts {seat, hand, gap, trained_freq, se, n}."""
        if seat_i == 0:
            raise ValueError("seat 0 (abridor) usa check_opener_convergence(), nao este metodo")
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        if sample_hands is None:
            sample_hands = self.classes

        rng = random.Random(seed)
        original_equity_batch = self.EQUITY_BATCH
        self.EQUITY_BATCH = equity_precision_batch
        try:
            with self._equity_rng(seed):
                flags = []
                for hand in sample_hands:
                    def draw_gaps(k, hand=hand):
                        out = []
                        for hands in self._sample_posterior(seat_i, hand, avg_strategy, rng, k):
                            vf, vj = self._phase1_values(seat_i, hands, avg_strategy)
                            out.append(vj - vf)
                        return out
                    trained = avg_strategy["phase1"][seat_i][hand]
                    stats = self._confirm_gap(draw_gaps, iterations, max_iterations_factor, gap_threshold, trained, z)
                    self._tally_check(stats)
                    if stats is not None and stats["flag"]:
                        flags.append({"seat": seat_i, "hand": hand, "gap": stats["gap"], "trained_freq": trained,
                                      "se": stats["se"], "n": stats["n"]})
        finally:
            self.EQUITY_BATCH = original_equity_batch
        return flags

    def check_phase2_convergence(self, seat_i, jammer, avg_strategy=None, sample_hands=None,
                                  iterations=40, gap_threshold=0.3, seed=99,
                                  equity_precision_batch=600, z=3.0, max_iterations_factor=8,
                                  callers=()):
        """Checa a decisao de call-vs-fold de `seat_i` respondendo a um
        jam de `jammer` (seat_i deve ser 0, ou > jammer -- os unicos
        responders validos nessa ordem de acao, ver _eval_phase2).

        Mesmo espirito de check_opener_convergence, mas pra fase 2: gap
        e' o valor esperado de pagar menos o de desistir, ponderado pela
        probabilidade de `jammer` TER REALMENTE jammado com cada mao
        amostrada dele (peso de importancia condicionado em "jammer
        jammou" -- mesmo esquema usado por _fix_policy_phase2 pra fixar
        a melhor resposta num best-response de verdade). Sem vazamento:
        seat_i so' tem essa unica decisao nesse ramo (responder a UM
        jam especifico), entao os demais podem usar avg_strategy direto.

        v3 (2026-09-24): o condicionamento agora cobre o historico
        INTEIRO (abridor abriu -- se seat_i nao for ele --, quem estava
        antes do jammer foldou, jammer jammou), via _sample_posterior; a
        v2 so' pesava pelo jam do jammer e deixava a mao do abridor
        (que responde depois, em fase 2) sair de qualquer lugar do
        baralho. Mais a confirmacao estatistica (ver _confirm_gap).

        v4 (overcall): checa UM grupo de quem ja pagou antes (`callers`,
        tupla de seats; () = ninguem pagou) -- cada grupo e' uma ficha
        propria no treino.

        Retorna lista de dicts {seat, jammer, callers, hand, gap, trained_freq, se, n}."""
        if not (seat_i == 0 or seat_i > jammer):
            raise ValueError(f"seat {seat_i} nunca responde ao jam de {jammer} nesta ordem de acao")
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        if sample_hands is None:
            sample_hands = self.classes

        rng = random.Random(seed)
        original_equity_batch = self.EQUITY_BATCH
        self.EQUITY_BATCH = equity_precision_batch
        try:
            with self._equity_rng(seed):
                flags = []
                for hand in sample_hands:
                    def draw_gaps(k, hand=hand):
                        out = []
                        for hands in self._sample_posterior(seat_i, hand, avg_strategy, rng, k, jammer=jammer,
                                                            callers=callers):
                            vf, vc = self._phase2_values(seat_i, jammer, hands, avg_strategy, callers)
                            out.append(vc - vf)
                        return out
                    trained = avg_strategy["phase2"][seat_i][jammer][callers][hand]
                    # sem mesa suficiente com esse historico (jam rarissimo
                    # com essa mao) -> None, contado como "sem dados" e nao
                    # apontado (nao da pra confundir com gap zero).
                    stats = self._confirm_gap(draw_gaps, iterations, max_iterations_factor, gap_threshold, trained, z)
                    self._tally_check(stats)
                    if stats is not None and stats["flag"]:
                        flags.append({"seat": seat_i, "jammer": jammer, "callers": callers, "hand": hand,
                                      "gap": stats["gap"],
                                      "trained_freq": trained, "se": stats["se"], "n": stats["n"]})
        finally:
            self.EQUITY_BATCH = original_equity_batch
        return flags

    def check_full_convergence(self, avg_strategy=None, sample_hands=None,
                                iterations=25, phase2_iterations=40, gap_threshold=0.3,
                                seed=99, equity_precision_batch=600, z=3.0,
                                max_iterations_factor=8, progress=None):
        """Roda a checagem OBRIGATORIA de convergencia (ver CLAUDE.md) pra
        TODAS as decisoes do motor, nao so' a do abridor:
          - "opener_phase1": abrir vs desistir do abridor (seat 0) --
            check_opener_convergence().
          - "other_phase1": fold vs jam de cada seat >= 1, quando a acao
            chega nele em fase 1 -- check_seat_phase1_convergence().
          - "phase2": call vs fold de cada seat respondendo a cada jammer
            possivel -- check_phase2_convergence(), incluindo as
            respostas do proprio abridor (que antes so' eram usadas
            internamente pra corrigir o vazamento de opener_phase1, sem
            nunca ter sido checadas por si so').

        Antes desta versao (2026-09), so' opener_phase1 tinha checagem
        automatica -- as outras duas categorias usam o MESMO mecanismo
        de CFR, entao podem sofrer do mesmo problema de "mao travada"
        (documentado como lacuna conhecida no CLAUDE.md ate aqui).

        Retorna um dict {"opener_phase1": [...], "other_phase1": [...],
        "phase2": [...]} -- cada lista no mesmo formato de
        check_opener_convergence/check_seat_phase1_convergence/
        check_phase2_convergence. O resumo (decisoes checadas, apontadas,
        inconclusivas, sem dados) fica em `self.last_check_summary`.

        `progress`: funcao opcional chamada com uma mensagem curta antes de
        cada bloco (a checagem inteira leva de minutos a horas conforme o
        numero de seats -- sem isso o terminal parece travado)."""
        if avg_strategy is None:
            avg_strategy = self.average_strategy()
        self.last_check_summary = None
        say = progress or (lambda msg: None)
        common = dict(equity_precision_batch=equity_precision_batch, z=z,
                      max_iterations_factor=max_iterations_factor)

        say("abridor (abrir vs desistir)")
        flags = {
            "opener_phase1": self.check_opener_convergence(
                avg_strategy, sample_hands, iterations, gap_threshold, seed, **common,
            ),
            "other_phase1": [],
            "phase2": [],
        }
        for seat_i in range(1, self.n_seats):
            say(f"seat {seat_i} ({self.seat_names[seat_i]}): fold vs jam")
            flags["other_phase1"].extend(
                self.check_seat_phase1_convergence(
                    seat_i, avg_strategy, sample_hands, iterations, gap_threshold, seed, **common,
                )
            )
        # v4 (overcall): cada grupo de "quem ja pagou antes" e' uma decisao
        # separada; so' os que acontecem com alguma frequencia sao checados
        # (MIN_NODE_FREQ), os raros entram no resumo.
        node_freq = self._phase2_node_freq(avg_strategy, random.Random(f"nodes-{seed}"))
        rare = 0
        rare_mass = 0.0
        for jammer in range(1, self.n_seats):
            for seat_i in self._responders(jammer):
                frequent = self._frequent_callers(seat_i, jammer, node_freq)
                for callers in self._possible_callers(seat_i, jammer):
                    if callers not in frequent:
                        rare += 1
                        rare_mass += node_freq.get((seat_i, jammer, callers), 0.0)
                for callers in frequent:
                    who = "+".join(self.seat_names[c] for c in callers) or "ninguem"
                    say(f"seat {seat_i} ({self.seat_names[seat_i]}): call vs fold contra jam de "
                        f"{self.seat_names[jammer]} (ja pagaram: {who})")
                    flags["phase2"].extend(
                        self.check_phase2_convergence(
                            seat_i, jammer, avg_strategy, sample_hands, phase2_iterations, gap_threshold, seed,
                            callers=callers, **common,
                        )
                    )
        if self.last_check_summary is None:
            self.last_check_summary = {"checked": 0, "flagged": 0, "inconclusive": 0, "insufficient_data": 0}
        self.last_check_summary["rare_nodes_skipped"] = rare
        self.last_check_summary["rare_nodes_freq"] = rare_mass
        return flags
