"""
testgen/merge.py
================
AST-based merger for test modules generated across multiple batches.

When a large user story is split into batches, each batch produces an
independent PyTest module.  This module merges them into one coherent
file with:
- The module docstring from the **first** batch only.
- De-duplicated import statements (preserving first-seen order).
- De-duplicated top-level assignment statements (by assigned name).
- All function definitions, with automatic name-collision resolution
  (a suffix like ``__b2`` is appended to the duplicate, not dropped).

Public API
----------
merge_batches(batch_codes) -> str
"""

import ast
from typing import List, Set


def merge_batches(batch_codes: List[str]) -> str:
    """
    Merge multiple syntactically valid Python test modules into one file.

    The merge strategy preserves correctness:
    - The **module docstring** from batch 1 is kept; subsequent batch
      docstrings are discarded (they are identical by design).
    - **Import statements** are de-duplicated by their ``ast.unparse()``
      representation, preserving the order of first occurrence.
    - **Top-level assignments** (e.g. parametrize data tables, constants)
      are de-duplicated by the names being assigned.
    - **Function definitions** are all retained.  If two batches define a
      function with the same name (which should not happen with well-behaved
      prompts but can occur), the later one is renamed to ``<name>__b<n>``
      so neither is silently lost.

    Args:
        batch_codes: List of Python source strings, one per batch, in order.
                     Every string must be parseable by ``ast.parse``.

    Returns:
        A single merged Python source string ending with a newline.

    Raises:
        SyntaxError: Propagated from ``ast.parse`` if any batch code is
                     syntactically invalid (callers should pre-validate).
    """
    docstring: str = ""
    import_texts: List[str] = []
    seen_imports: Set[str] = set()
    body_parts: List[str] = []
    seen_assign_names: Set[tuple] = set()
    func_nodes: List[ast.FunctionDef] = []
    seen_func_names: Set[str] = set()

    for bi, code in enumerate(batch_codes):
        tree = ast.parse(code)
        body = list(tree.body)

        # Strip a leading string-literal expression (the module docstring)
        if (body
                and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc_node = body.pop(0)
            if bi == 0:
                docstring = doc_node.value.value  # keep only the first batch's docstring

        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                text = ast.unparse(node)
                if text not in seen_imports:
                    seen_imports.add(text)
                    import_texts.append(text)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name in seen_func_names:
                    # Rename the collision instead of dropping it
                    new_name = f"{name}__b{bi + 1}"
                    suffix = 2
                    while new_name in seen_func_names:
                        new_name = f"{name}__b{bi + 1}_{suffix}"
                        suffix += 1
                    node.name = new_name
                    name = new_name
                seen_func_names.add(name)
                func_nodes.append(node)

            elif isinstance(node, ast.Assign) and all(
                    isinstance(t, ast.Name) for t in node.targets):
                target_names = tuple(t.id for t in node.targets)
                if target_names not in seen_assign_names:
                    seen_assign_names.add(target_names)
                    body_parts.append(ast.unparse(node))

            else:
                body_parts.append(ast.unparse(node))

    # Assemble sections separated by blank lines
    sections: List[str] = []
    if docstring:
        sections.append('"""' + docstring.replace('"""', '\\"\\"\\"') + '"""')
    if import_texts:
        sections.append("\n".join(import_texts))
    if body_parts:
        sections.append("\n\n".join(body_parts))
    if func_nodes:
        sections.append("\n\n\n".join(ast.unparse(fn) for fn in func_nodes))

    return "\n\n\n".join(s for s in sections if s.strip()) + "\n"
