"""The measured ink and similarity of the chart symbols (`cross_stitch.export.glyphs`)."""

import numpy as np
import pytest

from cross_stitch.export import SYMBOLS, glyphs
from cross_stitch.export.glyphs import ALIKE, glyph_table, measure

# Filled and outlined versions of one shape: plain to tell apart, so not alike.
FILLED_AND_OUTLINED = [
    ("■", "□"),  # ■ □
    ("▲", "△"),  # ▲ △
    ("◆", "◇"),  # ◆ ◇
    ("▼", "▽"),  # ▼ ▽
    ("●", "○"),  # ● ○
]

# Near-identical silhouettes: alike. ◇ ▽ is the pair the shark chart put side by side.
NEAR_IDENTICAL = [
    ("◇", "▽"),  # ◇ ▽
    ("◇", "△"),  # ◇ △
    ("⊕", "⊗"),  # ⊕ ⊗
    ("▤", "▥"),  # ▤ ▥
]


def _similarity(a: str, b: str) -> float:
    table = glyph_table()
    return float(table.similarity[table.index(a), table.index(b)])


def _ink(symbol: str) -> float:
    table = glyph_table()
    return float(table.ink[table.index(symbol)])


def test_the_table_measures_exactly_the_symbol_list_in_order() -> None:
    table = glyph_table()

    assert table.symbols == SYMBOLS
    assert table.ink.shape == (len(SYMBOLS),)
    assert table.similarity.shape == (len(SYMBOLS), len(SYMBOLS))
    assert all(0 < ink < 1 for ink in table.ink)


def test_similarity_is_one_with_itself_symmetric_and_between_zero_and_one() -> None:
    similarity = glyph_table().similarity

    assert np.all(np.diag(similarity) == 1)
    assert np.array_equal(similarity, similarity.T)
    assert np.all((similarity >= 0) & (similarity <= 1))


def test_the_committed_table_matches_a_fresh_measurement_of_the_font() -> None:
    fresh = measure(SYMBOLS)
    committed = glyph_table()
    overridden = np.zeros_like(committed.similarity, dtype=bool)
    for a, b in glyphs.OVERRIDES:
        i, j = committed.index(a), committed.index(b)
        overridden[i, j] = overridden[j, i] = True

    assert fresh.symbols == committed.symbols
    assert np.max(np.abs(fresh.ink - committed.ink)) <= 0.005
    drift = np.abs(fresh.similarity - committed.similarity)
    assert np.max(drift[~overridden]) <= 0.02


def test_filled_shapes_carry_more_ink_than_their_outlines() -> None:
    assert _ink("■") > _ink("□")
    assert _ink("●") > _ink("○")


def test_the_three_dots_are_among_the_lightest_symbols() -> None:
    table = glyph_table()
    lightest = [table.symbols[i] for i in np.argsort(table.ink)[:5]]

    assert "∴" in lightest  # ∴


@pytest.mark.parametrize(("a", "b"), FILLED_AND_OUTLINED)
def test_a_filled_and_an_outlined_shape_are_not_alike(a: str, b: str) -> None:
    assert _similarity(a, b) < ALIKE


@pytest.mark.parametrize(("a", "b"), NEAR_IDENTICAL)
def test_near_identical_silhouettes_are_alike(a: str, b: str) -> None:
    assert _similarity(a, b) >= ALIKE


def test_an_override_replaces_the_measured_score_in_both_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = "■", "●"  # ■ ●
    monkeypatch.setattr(glyphs, "OVERRIDES", {(a, b): (0.95, "test")})
    glyph_table.cache_clear()
    try:
        first, second = b, a
        assert _similarity(a, b) == 0.95
        assert _similarity(first, second) == 0.95
    finally:
        monkeypatch.undo()
        glyph_table.cache_clear()


def test_every_override_names_measured_symbols_and_gives_a_reason() -> None:
    for (a, b), (score, reason) in glyphs.OVERRIDES.items():
        assert a in SYMBOLS
        assert b in SYMBOLS
        assert 0 <= score <= 1
        assert reason
