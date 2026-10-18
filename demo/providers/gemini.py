"""gemini-3.8-flash, used only when GEMINI_API_KEY is present.

Three verified facts shaped this file:
  1. gemini-2.5-flash is retired for new keys and returns HTTP 404.
  2. The model spends output budget on thinking tokens. A tight output cap
     leaves nothing for visible text, so the reply comes back empty.
  3. A probe returned a transient 404 that succeeded on a clean retry.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from auryn.models import EVENT, PROCEDURE, FACT
from . import MemoryOp, ProviderFailure, Reply

MODEL = "gemini-3.8-flash"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
MAX_OUTPUT_TOKENS = 4096  # generous on purpose; thinking tokens draw from this
TIMEOUT_S = 45

_INSTRUCTION = """You are an agent with a persistent memory.

Reply to the user in at most three sentences.

Then decide what is worth remembering. Return JSON only, in this exact shape:
{"reply": "...", "memories": [{"kind": "Event|Fact|Procedure",
                               "text": "...", "subjects": ["..."]}]}

Use Event for something that happened, Fact for something that stays true, and
Procedure for how to carry out a task. Return an empty list if nothing is worth
keeping."""

_KINDS = {EVENT, FACT, PROCEDURE}


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ProviderFailure("GEMINI_API_KEY is not set")

    def _call(self, prompt: str) -> str:
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": MAX_OUTPUT_TOKENS,
                    "responseMimeType": "application/json",
                },
            }
        ).encode()
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"content-type": "application/json", "x-goog-api-key": self.api_key},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read())

        candidates = payload.get("candidates") or []
        if not candidates:
            raise ProviderFailure(f"{MODEL} returned no candidates")
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            finish = candidates[0].get("finishReason")
            raise ProviderFailure(
                f"{MODEL} returned empty text (finishReason={finish}). "
                "If this is MAX_TOKENS, thinking tokens consumed the output budget."
            )
        return text

    def respond(self, messages: list[dict[str, str]], *, recalled: list[Any] = ()) -> Reply:
        known = "\n".join(f"- [{m.kind}] {m.text}" for m in (recalled or [])[:10])
        convo = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages)
        prompt = (
            f"{_INSTRUCTION}\n\n"
            f"What you already remember about this user:\n{known or '(nothing yet)'}\n\n"
            f"Conversation so far:\n{convo}"
        )

        last_error: Exception | None = None
        for _attempt in range(2):  # one retry; a probe 404'd then succeeded
            try:
                raw = self._call(prompt)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
        else:
            raise ProviderFailure(f"{MODEL} failed after a retry: {last_error}")

        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> Reply:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return Reply(text=raw.strip(), memory_ops=[])
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return Reply(text=raw.strip(), memory_ops=[])

        ops: list[MemoryOp] = []
        for item in data.get("memories") or []:
            kind = item.get("kind")
            text = (item.get("text") or "").strip()
            if kind in _KINDS and text:
                subjects = tuple(str(s) for s in (item.get("subjects") or []) if s)
                ops.append(MemoryOp(kind=kind, text=text, subjects=subjects, trigger=item.get("trigger")))
        return Reply(text=(data.get("reply") or raw).strip(), memory_ops=ops)
