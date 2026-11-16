"""background_as_fabric: the border's thread, where it joins the border, made bare fabric.

Patterns are drawn with `cleanup_helpers.drawn` and read back with `drawing`.
"""

from cleanup_helpers import counted, drawing, drawn

from cross_stitch.pattern import EMPTY, Pattern, background_as_fabric, skeins_needed

LEGEND = {"W": "Blanc", "R": "321", "B": "820"}


def _assert_counts_add_up(pattern: Pattern) -> None:
    stitched = int((pattern.grid != EMPTY).sum())
    assert pattern.total_stitches == stitched
    for index, entry in enumerate(pattern.key):
        assert entry.stitches == int((pattern.grid == index).sum()) > 0
        assert entry.skeins == skeins_needed(entry.stitches, pattern.fabric_count)


def _square_with_eye() -> list[str]:
    """20 x 20 white, a 10 x 10 red square in the middle holding a 2 x 2 white eye."""
    rows = [["W"] * 20 for _ in range(20)]
    for row in range(5, 15):
        for col in range(5, 15):
            rows[row][col] = "R"
    for row in (8, 9):
        for col in (8, 9):
            rows[row][col] = "W"
    return ["".join(row) for row in rows]


def test_the_surround_goes_bare_and_an_eye_of_the_same_thread_stays() -> None:
    rows = _square_with_eye()

    result = background_as_fabric(drawn(rows, LEGEND))

    expected = [
        "".join(
            "." if (char == "W" and not _in_square(r, c)) else char for c, char in enumerate(row)
        )
        for r, row in enumerate(rows)
    ]
    assert drawing(result, LEGEND) == expected
    assert counted(result) == [("321", 96), ("Blanc", 4)]
    _assert_counts_add_up(result)


def _in_square(row: int, col: int) -> bool:
    return 5 <= row < 15 and 5 <= col < 15


def test_the_background_does_not_leak_through_a_diagonal_outline() -> None:
    size, centre, reach = 11, 5, 4
    rows = [
        "".join("R" if abs(r - centre) + abs(c - centre) == reach else "W" for c in range(size))
        for r in range(size)
    ]

    cleared = background_as_fabric(drawn(rows, LEGEND))
    result = drawing(cleared, LEGEND)

    _assert_counts_add_up(cleared)
    for r in range(size):
        for c in range(size):
            inside = abs(r - centre) + abs(c - centre)
            expected = "." if inside > reach else rows[r][c]
            assert result[r][c] == expected, (r, c)


def test_the_most_frequent_border_thread_is_the_background() -> None:
    rows = ["BBRRBB", "BBBBBB", "BBRRBB", "BBRRBB", "BBBBBB", "BRBBBB"]

    result = background_as_fabric(drawn(rows, LEGEND))

    assert drawing(result, LEGEND) == [row.replace("B", ".") for row in rows]
    _assert_counts_add_up(result)


def test_a_bare_border_changes_nothing() -> None:
    pattern = drawn(["....", ".WW.", ".WW.", "...."], LEGEND)

    assert background_as_fabric(pattern) is pattern


def test_a_border_half_bare_half_thread_changes_nothing() -> None:
    pattern = drawn(["..WW", "..WW", "WW..", "WW.."], LEGEND)

    assert background_as_fabric(pattern) is pattern


def test_one_thread_everywhere_leaves_bare_fabric_and_an_empty_key() -> None:
    result = background_as_fabric(drawn(["RRR", "RRR"], LEGEND))

    assert drawing(result, LEGEND) == ["...", "..."]
    assert not result.key
    assert result.total_stitches == 0


def test_a_tie_between_threads_goes_to_the_earlier_key_entry() -> None:
    rows = ["WWWW", "W..R", "RRRR"]
    pattern = drawn(rows, LEGEND)
    first = next(letter for letter, code in LEGEND.items() if code == pattern.key[0].thread.code)

    result = background_as_fabric(pattern)

    assert drawing(result, LEGEND) == [row.replace(first, ".") for row in rows]
    _assert_counts_add_up(result)
