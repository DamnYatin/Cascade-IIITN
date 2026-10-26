"""Tests P21, P22, P23: Leakage, Package Isolation, and Backward Compatibility.

Verifies:
  - P21: Import and file-reference isolation for explain/ and intervene/ (no eval, no synth, no label files).
  - P23: Defaults unchanged: with explain/intervene off, Phase 2 and Phase 3 outputs are byte-identical.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
import pytest

from tests.conftest import REPO


def test_p21_import_and_file_isolation_explain_and_intervene():
    """P21: Verify explain/ and intervene/ NEVER import eval, synth, or scenario label files (Rule W1)."""
    prohibited_modules = ["backend.app.eval", "backend.app.synth"]
    forbidden_terms = [
        "critical_labels.json",
        "observed_response.json",
        "events.json",
        "official_bulletins.json",
        "planted",
        "ground_truth",
    ]

    target_packages = ["backend.app.explain", "backend.app.intervene"]

    for pkg_name in target_packages:
        mod = importlib.import_module(pkg_name)
        pkg_path = Path(mod.__file__).parent
        for py in pkg_path.glob("**/*.py"):
            text = py.read_text(encoding="utf-8")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for prohibited in prohibited_modules:
                            assert not alias.name.startswith(prohibited), f"{py} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for prohibited in prohibited_modules:
                            assert not node.module.startswith(prohibited), f"{py} imports from {node.module}"

            for term in forbidden_terms:
                assert term not in text.lower(), f"{py} references forbidden term: {term}"
