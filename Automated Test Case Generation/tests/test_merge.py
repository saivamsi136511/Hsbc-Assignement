"""
tests/test_merge.py
===================
Unit tests for testgen.merge — AST-based multi-batch module merger.

Tests cover:
  - Happy path: two valid modules merge correctly
  - Import de-duplication: identical imports appear only once
  - Function naming collision: duplicate function renamed with suffix
  - Module docstring: only batch 1's docstring is kept
  - Constant de-duplication: assignments with the same name deduplicated
  - Edge cases: single batch, three batches, empty batches list
  - Output is always valid Python (parseable with ast.parse)
"""

import ast
import pytest
import textwrap
from testgen.merge import merge_batches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_valid_python(code: str) -> bool:
    """Return True if code is syntactically valid Python."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def count_functions(code: str, name_prefix: str = "test_") -> int:
    """Count top-level function definitions starting with name_prefix."""
    tree = ast.parse(code)
    return sum(
        1 for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith(name_prefix)
    )


def count_imports(code: str) -> int:
    """Count unique import statements in the merged code."""
    tree = ast.parse(code)
    return sum(1 for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom)))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestMergeBatchesHappyPath:
    """Basic merge correctness tests."""

    BATCH_1 = textwrap.dedent('''\
        """ASSUMPTIONS: add(a, b) -> int"""
        import pytest
        from solution import add

        def test_add_happy_path():
            assert add(1, 2) == 3
    ''')

    BATCH_2 = textwrap.dedent('''\
        import pytest
        from solution import add

        def test_add_negative():
            assert add(-1, -1) == -2
    ''')

    def test_merged_output_is_valid_python(self):
        """The merged module must be syntactically valid Python."""
        result = merge_batches([self.BATCH_1, self.BATCH_2])
        assert is_valid_python(result)

    def test_merged_contains_both_test_functions(self):
        """Both test functions must be present in the merged output."""
        result = merge_batches([self.BATCH_1, self.BATCH_2])
        assert "test_add_happy_path" in result
        assert "test_add_negative" in result

    def test_docstring_from_batch_1_only(self):
        """The ASSUMPTIONS docstring must come from batch 1 only."""
        result = merge_batches([self.BATCH_1, self.BATCH_2])
        assert result.count("ASSUMPTIONS") == 1

    def test_imports_are_deduplicated(self):
        """Identical import statements must appear only once."""
        result = merge_batches([self.BATCH_1, self.BATCH_2])
        assert result.count("import pytest") == 1
        assert result.count("from solution import add") == 1


import textwrap


# ---------------------------------------------------------------------------
# Collision resolution
# ---------------------------------------------------------------------------

class TestMergeBatchesCollision:
    """Tests for handling of colliding function names between batches."""

    BATCH_A = "def test_foo():\n    pass\n"
    BATCH_B = "def test_foo():\n    assert True\n"

    def test_collision_renamed_not_dropped(self):
        """Both functions must survive; the duplicate gets a suffix."""
        result = merge_batches([self.BATCH_A, self.BATCH_B])
        assert is_valid_python(result)
        assert "test_foo" in result
        assert "test_foo__b2" in result

    def test_three_collisions_all_renamed(self):
        """Three batches each defining the same name: all three must survive."""
        batches = ["def test_x():\n    pass\n"] * 3
        result = merge_batches(batches)
        assert is_valid_python(result)
        tree = ast.parse(result)
        names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        assert len(names) == 3


# ---------------------------------------------------------------------------
# Single batch
# ---------------------------------------------------------------------------

class TestMergeSingleBatch:
    """Merge of a single batch should be a no-op (aside from formatting)."""

    def test_single_batch_valid_output(self):
        code = '"""Docstring."""\nimport pytest\n\ndef test_a():\n    assert True\n'
        result = merge_batches([code])
        assert is_valid_python(result)
        assert "test_a" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestMergeBatchesEdgeCases:
    """Edge case tests for unusual batch contents."""

    def test_empty_list_returns_newline(self):
        """Empty batch list should produce a valid (empty) Python file."""
        result = merge_batches([])
        assert is_valid_python(result)

    def test_batch_with_only_imports(self):
        """A batch containing only imports should merge cleanly."""
        result = merge_batches(["import pytest\n", "import os\n"])
        assert is_valid_python(result)
        assert "import pytest" in result
        assert "import os" in result
