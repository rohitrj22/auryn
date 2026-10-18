"""Constitution Principle III, enforced rather than asserted.

The engine must carry no vocabulary from the demonstration's subject area, and
must depend on nothing outside itself.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / "auryn"

# Words from the demonstration's subject area. None may appear in the engine.
FORBIDDEN = ("ticket", "refund", "order", "customer", "support", "complaint", "invoice")

# "ORDER BY" and "ORDER" are Cypher keywords, not subject-area vocabulary.
# This is the only exemption, and it is removed before matching.
CYPHER_KEYWORDS = re.compile(r"\bORDER\s+BY\b")

# The engine must not import from any layer above it.
UPPER_LAYERS = ("demo", "proofs", "evals", "providers")


def engine_files() -> list[pathlib.Path]:
    return sorted(p for p in ENGINE.rglob("*.py"))


def test_engine_has_no_domain_vocabulary() -> None:
    hits: list[str] = []
    for path in engine_files():
        text = path.read_text()
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = CYPHER_KEYWORDS.sub("", raw)
            for word in FORBIDDEN:
                if re.search(rf"\b{word}s?\b", line, re.I):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {word!r} in {raw.strip()[:70]}")
    assert not hits, "engine contains demonstration vocabulary:\n" + "\n".join(hits)


def test_engine_imports_nothing_from_upper_layers() -> None:
    hits: list[str] = []
    for path in engine_files():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for layer in UPPER_LAYERS:
                if re.search(rf"^\s*(from|import)\s+{layer}\b", line):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not hits, "engine imports from an upper layer:\n" + "\n".join(hits)


def test_engine_is_importable_without_upper_layers() -> None:
    import auryn

    assert auryn.Memory is not None
    assert set(("EVENT", "FACT", "PROCEDURE")).issubset(set(auryn.__all__))


def test_engine_needs_no_text_generator() -> None:
    """Auryn is pure graph work. No model, no embeddings, no generation.

    Recall uses FalkorDB's full-text index plus traversal. Consolidation counts
    events. So the engine must contain no reference to a text generator at all.
    """
    banned = ("provider", "gemini", "openai", "anthropic", "embedding", "llm")
    hits: list[str] = []
    for path in engine_files():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for word in banned:
                if re.search(rf"\b{word}s?\b", line, re.I):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {word!r}")
    assert not hits, "engine references a text generator:\n" + "\n".join(hits)
