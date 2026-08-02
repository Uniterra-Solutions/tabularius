"""Tabularius agent roles (memory / recall / index / reader).

Each role is a versioned system prompt (``prompts/*.md``) + tool set +
output schema running on the shared ``run_agent`` loop.
"""

from tabularius.agents.index import run_index_agent
from tabularius.agents.memory import run_memory_agent
from tabularius.agents.reader import run_reader
from tabularius.agents.recall import RecallSession, run_recall_agent

__all__ = [
    "RecallSession",
    "run_index_agent",
    "run_memory_agent",
    "run_reader",
    "run_recall_agent",
]
