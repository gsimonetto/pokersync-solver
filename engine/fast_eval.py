"""
Avaliador de mão de 7 cartas (hold'em) rápido, 100% Python -- sem
dependência nova. Existe por performance: o treino multiway passava
praticamente 100% do tempo calculando equity de showdown (medido com
cProfile, CO vs BB), e mais da metade disso era desperdício:

  - `treys.Deck()` cria um gerador aleatório NOVO a cada chamada
    (semente via os.urandom) e embaralha as 52 cartas -- e o código
    ainda embaralhava de novo logo depois, só pra tirar 5 cartas da mesa;
  - `treys.Evaluator` avalia 7 cartas testando as 21 combinações de 5
    cartas uma a uma (~29 microssegundos por mão).

Aqui a mão é avaliada por tabela (contagem de cartas por valor + por
naipe), sem testar combinações: ~1 microssegundo por mão.

GARANTIA DE EQUIVALÊNCIA (ver tests/fast_eval.py): a ordem das mãos é
EXATAMENTE a mesma do `treys` -- conferido em TODAS as 2.598.960 mãos de
5 cartas possíveis (as 7.462 classes de força batem 1 a 1) e em milhões
de mãos aleatórias de 7 cartas. Só a escala do número muda: aqui MAIOR =
mão melhor (no treys, menor = melhor).

Representação das cartas: inteiro 0..51 = valor*4 + naipe, valor 0..12
(2..A) e naipe 0..3 (s, h, d, c). `card_index("Ah")` converte.
"""

import itertools

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "shdc"

# chave de contagem por valor (base 5: no máximo 4 cartas de cada valor)
# e por naipe (base 8: no máximo 7 cartas do mesmo naipe)
RANK_KEY = [5 ** (c >> 2) for c in range(52)]
SUIT_KEY = [8 ** (c & 3) for c in range(52)]
RANK_BIT = [1 << (c >> 2) for c in range(52)]


def card_index(card: str) -> int:
    """'Ah' -> índice 0..51. Levanta ValueError pra carta inválida."""
    if len(card) != 2 or card[0] not in RANK_CHARS or card[1] not in SUIT_CHARS:
        raise ValueError(f"carta invalida: {card!r} (formato esperado: valor 23456789TJQKA + naipe shdc, ex 'Ah')")
    return RANK_CHARS.index(card[0]) * 4 + SUIT_CHARS.index(card[1])


def _encode(category, ranks):
    """categoria (0=carta alta ... 8=straight flush) + até 5 valores de
    desempate, em ordem de importância -- um único inteiro comparável."""
    value = category
    for i in range(5):
        value = (value << 4) | (ranks[i] if i < len(ranks) else 0)
    return value


_WHEEL = (1 << 12) | 0b1111  # A-2-3-4-5


def _straight_high(mask):
    """Maior carta da melhor sequência dentro de `mask` (bits = valores),
    3 pra roda (A-5), -1 se não tem sequência."""
    for high in range(12, 3, -1):
        need = 0b11111 << (high - 4)
        if mask & need == need:
            return high
    if mask & _WHEEL == _WHEEL:
        return 3
    return -1


def _flush_value(mask):
    sf = _straight_high(mask)
    if sf >= 0:
        return _encode(8, [sf])
    top5 = [r for r in range(12, -1, -1) if mask >> r & 1][:5]
    return _encode(5, top5)


def _nonflush_value(counts):
    """Melhor mão de 5 cartas SEM flush, dada a contagem por valor
    (counts[r] = quantas cartas de valor r)."""
    ranks_desc = [r for r in range(12, -1, -1) if counts[r] > 0]
    quads = [r for r in ranks_desc if counts[r] == 4]
    trips = [r for r in ranks_desc if counts[r] == 3]
    pairs = [r for r in ranks_desc if counts[r] == 2]
    if quads:
        q = quads[0]
        return _encode(7, [q, next(r for r in ranks_desc if r != q)])
    if trips:
        others = trips[1:] + pairs
        if others:
            return _encode(6, [trips[0], max(others)])
    straight = _straight_high(sum(1 << r for r in ranks_desc))
    if straight >= 0:
        return _encode(4, [straight])
    if trips:
        t = trips[0]
        return _encode(3, [t] + [r for r in ranks_desc if r != t][:2])
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        return _encode(2, [p1, p2] + [r for r in ranks_desc if r != p1 and r != p2][:1])
    if pairs:
        p = pairs[0]
        return _encode(1, [p] + [r for r in ranks_desc if r != p][:3])
    return _encode(0, ranks_desc[:5])


# Tabelas montadas uma vez (preguiçosamente, ~0,3s no primeiro uso):
#   _FLUSH_SUIT[chave_de_naipe] -> naipe com 5+ cartas, ou -1
#   _FLUSH_VALUE[máscara_de_valores] -> melhor flush/straight flush
#   _NONFLUSH[chave_de_valores] -> melhor mão sem flush
# Com 7 cartas, flush e quadra/full house nunca coexistem (faltam
# cartas), então havendo flush a melhor mão é o próprio flush (ou
# straight flush) -- por isso as duas tabelas separadas bastam.
_FLUSH_SUIT = None
_FLUSH_VALUE = None
_NONFLUSH = None


def _build_tables():
    global _FLUSH_SUIT, _FLUSH_VALUE, _NONFLUSH
    flush_suit = [-1] * (8 ** 4)
    for key in range(8 ** 4):
        for s in range(4):
            if (key // 8 ** s) % 8 >= 5:
                flush_suit[key] = s
    flush_value = [0] * (1 << 13)
    for mask in range(1 << 13):
        if bin(mask).count("1") >= 5:
            flush_value[mask] = _flush_value(mask)
    nonflush = {}
    for combo in itertools.combinations_with_replacement(range(13), 7):
        counts = [0] * 13
        for r in combo:
            counts[r] += 1
        if max(counts) > 4:
            continue
        nonflush[sum(5 ** r * counts[r] for r in range(13))] = _nonflush_value(counts)
    _FLUSH_SUIT, _FLUSH_VALUE, _NONFLUSH = flush_suit, flush_value, nonflush


def tables():
    """(FLUSH_SUIT, FLUSH_VALUE, NONFLUSH) -- pra laços quentes que
    querem fazer a avaliação inline (ver engine/multiway_equity.py)."""
    if _NONFLUSH is None:
        _build_tables()
    return _FLUSH_SUIT, _FLUSH_VALUE, _NONFLUSH


def eval7(cards) -> int:
    """Força de uma mão de exatamente 7 cartas distintas (índices
    0..51). MAIOR = melhor; empate = mesmo valor."""
    flush_suit, flush_value, nonflush = tables()
    rk = 0
    sk = 0
    for c in cards:
        rk += RANK_KEY[c]
        sk += SUIT_KEY[c]
    fs = flush_suit[sk]
    if fs < 0:
        return nonflush[rk]
    m = 0
    for c in cards:
        if c & 3 == fs:
            m |= RANK_BIT[c]
    return flush_value[m]


def value_any(cards) -> int:
    """Versão lenta e direta (5 a 7 cartas) -- só pra validação
    independente em tests/fast_eval.py, não usar em laço quente."""
    counts = [0] * 13
    suits = [0] * 4
    for c in cards:
        counts[c >> 2] += 1
        suits[c & 3] |= 1 << (c >> 2)
    for mask in suits:
        if bin(mask).count("1") >= 5:
            return _flush_value(mask)
    return _nonflush_value(counts)
