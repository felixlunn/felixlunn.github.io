"""Every source module attribute build.py uses must exist.

The demo build doesn't run the real source steps, so a misnamed attribute (e.g. a module's SOURCE_URL) would
only fail in the scheduled data refresh. This checks them statically.
"""

import ast
import importlib
from pathlib import Path

import whips


import pytest


@pytest.mark.parametrize("module", ["build.py", "registry.py"])
def test_build_only_uses_attributes_that_exist(module):
    # Attributes used inside loader lambdas are only looked up when the source runs: check them statically.
    tree = ast.parse((Path(whips.__file__).parent / module).read_text())
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("sources", ".sources") or (
                isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "sources"):
            for a in node.names:
                aliases[a.asname or a.name] = a.name
    missing = sorted({
        f"{node.value.id}.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases
        and not hasattr(importlib.import_module(f"whips.sources.{aliases[node.value.id]}"), node.attr)
    })
    assert missing == []
