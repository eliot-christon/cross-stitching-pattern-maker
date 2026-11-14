"""Chart symbols: one fixed ordered list, one symbol per key entry, by position."""

import pytest

from cross_stitch.export import SYMBOLS, key_symbols
from cross_stitch.pattern import KeyEntry
from cross_stitch.threads import dmc_threads

LIMIT = 100

# Look-alike groups, written with code point escapes so each member is unambiguous. At most
# one member of a group may be in SYMBOLS: two of them are hard to tell apart on paper.
LOOK_ALIKES: list[tuple[str, ...]] = [
    ("O", "0", "o", "\U000025cb"),
    ("I", "l", "1", "|", "i"),
    ("S", "5", "s"),
    ("Z", "2", "z"),
    ("B", "8"),
    ("C", "c"),
    ("X", "x", "\U000000d7", "\U00002715"),
    ("V", "v"),
    ("W", "w"),
    ("P", "p"),
    ("U", "u"),
    ("K", "k"),
    ("Y", "y"),
    ("-", "\U00002013", "\U00002212"),
    ("'", "`", "\U000000b4"),
    ('"', "\U00002033"),
    ("\U000000b7", ".", "\U00002219", "\U000022c5"),
    ("\U000000b0", "\U000000ba", "\U000002da"),
    ("\U000000a6", "|"),
    ("\U000000ac", "\U00002310"),
    ("\U000025a0", "\U000025aa"),
    ("\U000025a1", "\U000025ab"),
    ("\U000025cf", "\U000026ab"),
    ("\U000025c6", "\U00002666"),
    (",", "\U000000b8"),
    (";", "\U0000037e"),
    (":", "\U00002236"),
    ("~", "\U0000223c"),
    ("^", "\U000002c6"),
    ("\U000000af", "\U0000203e"),
    ("*", "\U00002217"),
    ("/", "\U00002215"),
    ("\\", "\U00002216"),
    ("<", "\U00002039"),
    (">", "\U0000203a"),
    ("C", "G"),
    ("G", "6"),
    ("E", "\U000000c6"),
    ("\U00002234", "\U00002235"),
    ("\U000025cb", "\U00002299", "\U000000a9"),
    ("S", "\U000000a7", "$"),
    ("\U000000a3", "f"),
    ("\U000025a0", "\U000025a3"),
    ("Y", "\U000000a5"),
    ("\U00002205", "\U000000d8"),
]

# Blocks the chart font (DejaVu Sans) is relied on for, as inclusive code point ranges.
ALLOWED_RANGES = [
    (0x0021, 0x007E),  # Basic Latin, printable, no space
    (0x00A1, 0x00FF),  # Latin-1 Supplement, from the inverted exclamation mark
    (0x2190, 0x21FF),  # Arrows
    (0x2200, 0x22FF),  # Mathematical Operators
    (0x25A0, 0x25FF),  # Geometric Shapes
]
EXCLUDED = {0x00A0, 0x00AD}  # no-break space, soft hyphen


def _key(length: int) -> list[KeyEntry]:
    """A key of `length` entries, each a different real DMC thread."""
    threads = dmc_threads()
    assert length <= len(threads)
    return [KeyEntry(thread=threads[i], stitches=1000 - i, skeins=1) for i in range(length)]


def _label(group: tuple[str, ...]) -> str:
    return " ".join(f"U+{ord(c):04X}" for c in group)


def test_the_list_has_exactly_100_symbols() -> None:
    assert len(SYMBOLS) == LIMIT


def test_the_list_has_no_duplicates() -> None:
    assert len(set(SYMBOLS)) == len(SYMBOLS)


def test_an_empty_key_has_no_symbols() -> None:
    assert not key_symbols([])


def test_a_one_entry_key_gets_the_first_symbol() -> None:
    assert key_symbols(_key(1)) == [SYMBOLS[0]]


def test_a_100_entry_key_gets_100_different_symbols() -> None:
    symbols = key_symbols(_key(LIMIT))
    assert len(symbols) == LIMIT
    assert len(set(symbols)) == LIMIT
    assert symbols == list(SYMBOLS)


def test_a_101_entry_key_is_refused_naming_the_limit() -> None:
    with pytest.raises(ValueError, match="100"):
        key_symbols(_key(LIMIT + 1))


def test_the_same_key_twice_gives_identical_symbols() -> None:
    key = _key(37)
    assert key_symbols(key) == key_symbols(key)


@pytest.mark.parametrize("length", [1, 2, 3, 17, 99])
def test_position_decides_the_symbols_not_the_thread(length: int) -> None:
    assert key_symbols(_key(length)) == key_symbols(_key(LIMIT))[:length]


def test_the_threads_do_not_change_the_symbols() -> None:
    threads = dmc_threads()
    first = [KeyEntry(thread=threads[i], stitches=10, skeins=1) for i in range(5)]
    other = [KeyEntry(thread=threads[-1 - i], stitches=99, skeins=3) for i in range(5)]
    assert key_symbols(first) == key_symbols(other)


@pytest.mark.parametrize("index", range(LIMIT))
def test_every_symbol_is_one_visible_character(index: int) -> None:
    symbol = SYMBOLS[index]
    assert isinstance(symbol, str)
    assert len(symbol) == 1
    assert not symbol.isspace()
    assert symbol.isprintable()


@pytest.mark.parametrize("group", LOOK_ALIKES, ids=_label)
def test_at_most_one_member_of_a_look_alike_group_is_in_the_list(group: tuple[str, ...]) -> None:
    present = [c for c in group if c in SYMBOLS]
    assert len(present) <= 1, f"look-alikes together in SYMBOLS: {present}"


@pytest.mark.parametrize("index", range(LIMIT))
def test_every_symbol_is_in_a_block_the_font_covers(index: int) -> None:
    code_point = ord(SYMBOLS[index])
    assert code_point not in EXCLUDED
    assert any(low <= code_point <= high for low, high in ALLOWED_RANGES), hex(code_point)
