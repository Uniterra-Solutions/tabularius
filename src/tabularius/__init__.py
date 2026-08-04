"""Tabularius — Hermes MemoryProvider plugin: extract, index, and recall
conversation memory as markdown.

``register(ctx)`` is the Hermes plugin entry point: it hands a
:class:`TabulariusMemoryProvider` to ``ctx.register_memory_provider`` so the
provider becomes the active ``memory.provider`` backend.
"""

from __future__ import annotations

from typing import Any

from tabularius.provider import (
    PROVIDER_NAME,
    TabulariusMemoryProvider,
    create_provider,
)

__version__ = "0.1.1"


def register(ctx: Any) -> None:
    """Register the tabularius memory provider with Hermes.

    Called by the Hermes memory-plugin discovery (``plugins.memory``) with a
    context exposing ``register_memory_provider``; any other context is
    ignored so the module stays importable standalone.
    """
    register_memory_provider = getattr(ctx, "register_memory_provider", None)
    if callable(register_memory_provider):
        register_memory_provider(create_provider())


__all__ = ["PROVIDER_NAME", "TabulariusMemoryProvider", "create_provider", "register"]
