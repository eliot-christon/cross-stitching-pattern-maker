"""Image -> cross-stitch pattern: the stitch grid, its DMC key, counts and sizes."""

from cross_stitch.pattern.cleanup import (
    CleanedPattern,
    clean_pattern,
    merge_similar_threads,
    prune_rare_threads,
)
from cross_stitch.pattern.confetti import isolated_stitches, remove_confetti
from cross_stitch.pattern.convert import OPAQUE_THRESHOLD, convert_image, stitch_height
from cross_stitch.pattern.model import (
    EMPTY,
    KeyEntry,
    Pattern,
    build_pattern,
    skeins_needed,
    stitches_per_skein,
)

__all__ = [
    "EMPTY",
    "OPAQUE_THRESHOLD",
    "CleanedPattern",
    "KeyEntry",
    "Pattern",
    "build_pattern",
    "clean_pattern",
    "convert_image",
    "isolated_stitches",
    "merge_similar_threads",
    "prune_rare_threads",
    "remove_confetti",
    "skeins_needed",
    "stitch_height",
    "stitches_per_skein",
]
