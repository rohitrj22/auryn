# Contract: the model provider boundary

One protocol, two implementations. The engine cannot tell which one answered
(FR-025b).

```python
class Provider(Protocol):
    name: str
    def respond(self, messages: list[Msg], tools: list[ToolSpec]) -> Reply: ...

@dataclass
class Reply:
    text: str
    memory_ops: list[MemoryOp]   # what the model decided to remember
```

`MemoryOp` carries a kind, a text, and its subjects. Nothing else.

## `mock` — the default

- Selected whenever `GEMINI_API_KEY` is absent.
- Deterministic. The same input gives the same output, every run (FR-038).
- Returns scripted `memory_ops` that stand in for a model's choices (FR-025a).
- Needs no network, so every proof runs on a clean clone (FR-026).

## `gemini` — selected when a key is present

| Setting | Value | Why |
|---|---|---|
| Model | `gemini-3.8-flash` | Verified HTTP 200. `gemini-2.5-flash` is retired and returns 404. |
| `maxOutputTokens` | generous, not tight | The model spends output budget on thinking. A low cap returns empty text. Observed `thoughtsTokenCount: 97` on a two-word reply. |
| Retries | one | An early probe 404'd then succeeded on a clean retry. |
| Key source | `.env`, never logged | Principle V |

The model chooses what to remember through tool calling, and those choices
become `memory_ops` (FR-025).

## Switching

Automatic, by key presence. No code change and no behaviour change beyond the
wording of generated text (FR-027). Overridable with `AURYN_PROVIDER=mock` so a
judge with a key can still see the deterministic path.
