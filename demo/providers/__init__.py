"""The model provider boundary.

One protocol, two implementations. The engine cannot tell which one answered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderFailure(Exception):
    """A text generator failed. The engine never raises this."""


@dataclass(frozen=True)
class MemoryOp:
    """A memory the generator decided is worth keeping."""

    kind: str
    text: str
    subjects: tuple[str, ...] = ()
    trigger: str | None = None


@dataclass(frozen=True)
class Reply:
    text: str
    memory_ops: list[MemoryOp] = field(default_factory=list)


@runtime_checkable
class Provider(Protocol):
    name: str

    def respond(self, messages: list[dict[str, str]], *, recalled: list[Any] = ...) -> Reply: ...


def get_provider(name: str | None = None) -> Provider:
    """Pick a provider. `mock` unless a key is present. Overridable."""
    choice = (name or os.environ.get("AURYN_PROVIDER") or "").strip().lower()
    if not choice:
        choice = "gemini" if os.environ.get("GEMINI_API_KEY") else "mock"
    if choice == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider()
    from .mock import MockProvider

    return MockProvider()
