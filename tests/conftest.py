"""pytest configuration shared by every test module."""

import pytest

# Helper modules whose asserts should report values like the tests' own do.
pytest.register_assert_rewrite("cleanup_helpers", "pdf_helpers", "stitch_helpers")
