"""The symbol each key entry gets from its thread's tone and its borders (`pattern_symbols`).

Patterns are built in code with `build_pattern` and real DMC threads. Borders and strong
pairs are counted here, independently of the code under test: a border is the edge between
two orthogonally adjacent stitched cells of different entries, counted once; a strong pair
shares at least 1% of all such borders, and at least one. Lightness is CIELAB L* from
`srgb_to_lab`; ink and similarity come from the committed glyph table.
"""

import functools
import itertools
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pytest

from cross_stitch.colour import srgb_to_lab
from cross_stitch.export import SYMBOLS, pattern_symbols
from cross_stitch.export.glyphs import ALIKE, glyph_table
from cross_stitch.pattern import EMPTY, Pattern, build_pattern
from cross_stitch.threads import Thread, dmc_thread, dmc_threads

type Cells = npt.NDArray[np.intp]
type Pair = tuple[int, int]

LIMIT = 100
FABRIC_COUNT = 14.0
STRONG_SHARE = 0.01

BLACK = dmc_thread("310")  # (0, 0, 0)
WHITE = dmc_thread("Blanc")  # (252, 251, 248)


# ------------------------------------------------------------------------------ helpers


def _lightness(thread: Thread) -> float:
    return float(srgb_to_lab(thread.rgb)[0])


def _ink(symbol: str) -> float:
    table = glyph_table()
    return float(table.ink[table.index(symbol)])


def _similarity(first: str, second: str) -> float:
    table = glyph_table()
    return float(table.similarity[table.index(first), table.index(second)])


@functools.cache
def _by_lightness() -> tuple[Thread, ...]:
    """Every DMC thread, darkest first; equal L* keeps the source order."""
    threads = dmc_threads()
    lightness = srgb_to_lab([thread.rgb for thread in threads])[:, 0]
    return tuple(threads[int(i)] for i in np.argsort(lightness, kind="stable"))


def _spread(count: int, pool: Sequence[Thread] | None = None) -> list[Thread]:
    """`count` different threads evenly spaced through `pool` (by default all DMC threads,
    darkest first), so their L* spreads from near black to near white."""
    threads = _by_lightness() if pool is None else tuple(pool)
    positions = np.round(np.linspace(0, len(threads) - 1, count)).astype(int)
    assert len(set(positions.tolist())) == count
    return [threads[int(i)] for i in positions]


def _apart(count: int) -> Cells:
    """Entry k as a block 2 rows high and 1 + k % 3 columns wide, the blocks in one row with
    a bare column between two of them: no entry borders another. The widths differ, so the
    key order (by stitches) is not the order of `threads`."""
    parts: list[Cells] = []
    for k in range(count):
        if k:
            parts.append(np.full((2, 1), EMPTY, dtype=np.intp))
        parts.append(np.full((2, 1 + k % 3), k, dtype=np.intp))
    return np.hstack(parts).astype(np.intp)


def _bands(count: int, rows: int = 4) -> Cells:
    """Entry k as a vertical band 2 + k % 3 columns wide, `rows` high, each band against the
    next: band k borders band k + 1 along `rows` edges and no other band."""
    row = np.repeat(np.arange(count, dtype=np.intp), [2 + k % 3 for k in range(count)])
    return np.tile(row, (rows, 1)).astype(np.intp)


def _random_blocks(seed: int, threads: int = 20, blocks: tuple[int, int] = (10, 14)) -> Cells:
    """A seeded grid of 4 x 4 cell blocks, each block one of `threads` entries, every entry
    used at least once. Not square, so its transpose has another shape."""
    rng = np.random.default_rng(seed)
    total = blocks[0] * blocks[1]
    draw = np.concatenate([np.arange(threads), rng.integers(0, threads, total - threads)])
    layout = rng.permutation(draw).reshape(blocks)
    return layout.repeat(4, axis=0).repeat(4, axis=1).astype(np.intp)


def _build(cells: Cells, threads: Sequence[Thread]) -> Pattern:
    return build_pattern(cells, list(threads), FABRIC_COUNT)


def _borders(pattern: Pattern) -> dict[Pair, int]:
    """Borders per unordered pair of key entries (lower index first)."""
    grid = pattern.grid
    found: list[npt.NDArray[np.intp]] = []
    for first, second in ((grid[:, :-1], grid[:, 1:]), (grid[:-1, :], grid[1:, :])):
        mask = (first != EMPTY) & (second != EMPTY) & (first != second)
        low = np.minimum(first[mask], second[mask])
        high = np.maximum(first[mask], second[mask])
        found.append(np.stack([low, high], axis=1))
    edges = np.concatenate(found)
    if edges.shape[0] == 0:
        return {}
    pairs, counts = np.unique(edges, axis=0, return_counts=True)
    return {(int(p[0]), int(p[1])): int(n) for p, n in zip(pairs, counts, strict=True)}


def _strong_pairs(pattern: Pattern) -> dict[Pair, int]:
    borders = _borders(pattern)
    threshold = max(1.0, STRONG_SHARE * sum(borders.values()))
    return {pair: count for pair, count in borders.items() if count >= threshold}


def _clashes(symbols: Sequence[str], pairs: dict[Pair, int]) -> list[tuple[str, str]]:
    """The strong pairs whose two symbols look alike."""
    return [
        (symbols[i], symbols[j]) for i, j in pairs if _similarity(symbols[i], symbols[j]) >= ALIKE
    ]


def _thread_pairs(pattern: Pattern, pairs: dict[Pair, int]) -> set[frozenset[Thread]]:
    return {frozenset((pattern.key[i].thread, pattern.key[j].thread)) for i, j in pairs}


def _by_code(pattern: Pattern, symbols: Sequence[str]) -> dict[str, str]:
    return {entry.thread.code: symbol for entry, symbol in zip(pattern.key, symbols, strict=True)}


def _ranks(values: Sequence[float]) -> npt.NDArray[np.float64]:
    """Ranks from 0, tied values sharing their average rank."""
    array = np.asarray(values, dtype=np.float64)
    ranks = np.empty(len(array), dtype=np.float64)
    ranks[np.argsort(array, kind="stable")] = np.arange(len(array), dtype=np.float64)
    for value in np.unique(array):
        tied = array == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def _spearman(first: Sequence[float], second: Sequence[float]) -> float:
    return float(np.corrcoef(_ranks(first), _ranks(second))[0, 1])


def _heavier_symbols(symbol: str) -> int:
    """How many symbols of the whole list carry strictly more ink than `symbol`."""
    return int(np.count_nonzero(glyph_table().ink > _ink(symbol)))


def _lighter_symbols(symbol: str) -> int:
    """How many symbols of the whole list carry strictly less ink than `symbol`."""
    return int(np.count_nonzero(glyph_table().ink < _ink(symbol)))


def _assert_valid(pattern: Pattern, symbols: Sequence[str]) -> None:
    assert len(symbols) == len(pattern.key)
    assert len(set(symbols)) == len(symbols)
    assert all(symbol in SYMBOLS for symbol in symbols)


# ------------------------------------------------------------------------------ validity


def test_an_all_bare_pattern_has_no_symbols() -> None:
    pattern = _build(np.full((2, 3), EMPTY, dtype=np.intp), [BLACK])
    assert not pattern.key

    assert pattern_symbols(pattern) == []


def test_one_entry_gets_one_symbol_from_the_list() -> None:
    pattern = _build(np.zeros((2, 2), dtype=np.intp), [dmc_thread("797")])

    symbols = pattern_symbols(pattern)

    assert len(symbols) == 1
    assert symbols[0] in SYMBOLS


def test_100_bands_get_100_distinct_symbols_from_the_list() -> None:
    pattern = _build(_bands(LIMIT), _spread(LIMIT))
    assert len(pattern.key) == LIMIT

    symbols = pattern_symbols(pattern)

    _assert_valid(pattern, symbols)


def test_101_entries_are_refused_naming_the_limit() -> None:
    pattern = _build(_bands(LIMIT + 1), _spread(LIMIT + 1))
    assert len(pattern.key) == LIMIT + 1

    with pytest.raises(ValueError, match="100"):
        pattern_symbols(pattern)


# ------------------------------------------------------------------------------ determinism


def test_the_same_pattern_twice_gives_identical_symbols() -> None:
    cells, threads = _random_blocks(seed=7), _spread(20)
    first, second = _build(cells, threads), _build(cells, threads)

    symbols = pattern_symbols(first)

    assert pattern_symbols(first) == symbols
    assert pattern_symbols(second) == symbols


def test_the_transposed_grid_gives_the_same_symbols() -> None:
    cells, threads = _random_blocks(seed=7), _spread(20)
    pattern = _build(cells, threads)
    transposed = _build(np.ascontiguousarray(cells.T), threads)
    assert transposed.key == pattern.key
    assert transposed.grid.shape != pattern.grid.shape

    assert pattern_symbols(transposed) == pattern_symbols(pattern)


# ------------------------------------------------------------------------------ tone


@pytest.mark.parametrize("count", [2, 5, 15])
def test_entries_kept_apart_get_symbols_in_tone_order(count: int) -> None:
    pattern = _build(_apart(count), _spread(count))
    assert len(pattern.key) == count
    assert _borders(pattern) == {}

    symbols = pattern_symbols(pattern)

    _assert_valid(pattern, symbols)
    lightness = [_lightness(entry.thread) for entry in pattern.key]
    for i, j in itertools.permutations(range(count), 2):
        if lightness[i] < lightness[j]:
            assert _ink(symbols[i]) >= _ink(symbols[j]), (
                pattern.key[i].thread.code,
                symbols[i],
                pattern.key[j].thread.code,
                symbols[j],
            )
    darkest = int(np.argmin(lightness))
    lightest = int(np.argmax(lightness))
    assert _heavier_symbols(symbols[darkest]) < 10, symbols[darkest]
    assert _lighter_symbols(symbols[lightest]) < 10, symbols[lightest]


def test_black_apart_from_white_gets_the_symbol_with_more_ink() -> None:
    cells = np.array([[0, 0, EMPTY, 1, 1]], dtype=np.intp)
    pattern = _build(cells, [BLACK, WHITE])
    assert _borders(pattern) == {}

    by_code = _by_code(pattern, pattern_symbols(pattern))

    assert _ink(by_code["310"]) > _ink(by_code["Blanc"])


# ------------------------------------------------------------------------------ neighbours


@pytest.mark.parametrize("count", [5, 15, 30, 50])
def test_bands_in_tone_order_have_no_alike_strong_pair_and_follow_tone(count: int) -> None:
    threads = _spread(count)
    pattern = _build(_bands(count), threads)
    strong = _strong_pairs(pattern)
    neighbours = {frozenset(pair) for pair in itertools.pairwise(threads)}
    assert strong
    assert _thread_pairs(pattern, strong) == neighbours

    symbols = pattern_symbols(pattern)

    _assert_valid(pattern, symbols)
    assert _clashes(symbols, strong) == []
    lightness = [_lightness(entry.thread) for entry in pattern.key]
    assert _spearman(lightness, [-_ink(symbol) for symbol in symbols]) >= 0.9


def test_100_bands_keep_at_most_a_tenth_of_strong_pairs_alike() -> None:
    pattern = _build(_bands(LIMIT), _spread(LIMIT))
    strong = _strong_pairs(pattern)
    assert len(strong) == LIMIT - 1

    symbols = pattern_symbols(pattern)

    _assert_valid(pattern, symbols)
    clashes = _clashes(symbols, strong)
    assert len(clashes) <= 0.1 * len(strong), clashes


def _near_equal_pair(start: int) -> tuple[Thread, Thread]:
    """Two threads next to each other in L* order, the closest such pair among the 40
    positions from `start`: nothing in the DMC table lies strictly between them."""
    ordered = _by_lightness()
    window = range(start, start + 40)
    best = min(window, key=lambda i: _lightness(ordered[i + 1]) - _lightness(ordered[i]))
    return ordered[best], ordered[best + 1]


@pytest.mark.parametrize("start", [60, 240, 420], ids=["dark", "mid", "light"])
def test_a_checkerboard_of_two_near_equal_tones_gets_symbols_that_do_not_look_alike(
    start: int,
) -> None:
    # 98 threads apart from everything and the near-equal pair in a 4 x 4 checkerboard
    # below them: a full key, so the pair would take neighbouring ranks by tone alone.
    pair = _near_equal_pair(start)
    assert abs(_lightness(pair[0]) - _lightness(pair[1])) < 1.0
    others = _spread(LIMIT - 2, [t for t in _by_lightness() if t not in pair])
    top = _apart(LIMIT - 2)
    cells = np.full((top.shape[0] + 5, top.shape[1]), EMPTY, dtype=np.intp)
    cells[: top.shape[0]] = top
    cells[top.shape[0] + 1 :, :4] = np.indices((4, 4)).sum(axis=0) % 2 + LIMIT - 2
    pattern = _build(cells, [*others, *pair])
    assert len(pattern.key) == LIMIT
    strong = _strong_pairs(pattern)
    assert list(strong.values()) == [24]
    assert _thread_pairs(pattern, strong) == {frozenset(pair)}

    symbols = pattern_symbols(pattern)

    _assert_valid(pattern, symbols)
    assert _clashes(symbols, strong) == []


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_random_block_pattern_of_20_entries_has_no_alike_strong_pair(seed: int) -> None:
    pattern = _build(_random_blocks(seed), _spread(20))
    assert len(pattern.key) == 20
    strong = _strong_pairs(pattern)
    assert strong

    symbols = pattern_symbols(pattern)

    _assert_valid(pattern, symbols)
    assert _clashes(symbols, strong) == []


# ------------------------------------------------------------------------------ position


def test_black_and_white_keep_their_symbols_when_the_key_order_flips() -> None:
    more_black = _build(np.array([[0, 0, 0, 1, 1]], dtype=np.intp), [BLACK, WHITE])
    more_white = _build(np.array([[0, 0, 1, 1, 1]], dtype=np.intp), [BLACK, WHITE])
    assert [entry.thread.code for entry in more_black.key] == ["310", "Blanc"]
    assert [entry.thread.code for entry in more_white.key] == ["Blanc", "310"]
    assert _borders(more_black) == _borders(more_white) == {(0, 1): 1}

    first = _by_code(more_black, pattern_symbols(more_black))
    second = _by_code(more_white, pattern_symbols(more_white))

    assert first == second
