"""Image -> cross-stitch pattern: the stitch grid, its DMC key, counts and sizes."""

from cross_stitch.pattern.cleanup import (
    CLEANUP_HEADROOM,
    CleanedPattern,
    clean_pattern,
    colours_with_headroom,
    limit_threads,
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
from cross_stitch.pattern.pixelart import (
    PixelGrid,
    find_pixel_grid,
    pixel_art_colours,
    unscale_pixel_art,
)
from cross_stitch.pattern.replace import Replaced, replace_threads

__all__ = [
    "CLEANUP_HEADROOM",
    "EMPTY",
    "OPAQUE_THRESHOLD",
    "CleanedPattern",
    "KeyEntry",
    "Pattern",
    "PixelGrid",
    "Replaced",
    "build_pattern",
    "clean_pattern",
    "colours_with_headroom",
    "convert_image",
    "find_pixel_grid",
    "isolated_stitches",
    "limit_threads",
    "merge_similar_threads",
    "pixel_art_colours",
    "prune_rare_threads",
    "remove_confetti",
    "replace_threads",
    "skeins_needed",
    "stitch_height",
    "stitches_per_skein",
    "unscale_pixel_art",
]
