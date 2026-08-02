"""Shared pytest fixtures for tabularius tests."""

import sys
from pathlib import Path

import pytest

# Ensure local src/ takes priority over any PYTHONPATH entries.
_SRC = Path(__file__).absolute().parent.parent / "src"
sys.path.insert(0, str(_SRC))
_tabularius_keys = [k for k in sys.modules if k == "tabularius" or k.startswith("tabularius.")]
for _k in _tabularius_keys:
    del sys.modules[_k]
del _SRC


@pytest.fixture
def memory_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the memory directory at a real tmp dir via HERMES_HOME."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    root = tmp_path / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root
