from __future__ import annotations

import os
from typing import List, Optional, TypedDict

from openai import OpenAI


class InputMessage(TypedDict):
    role: str
    content: str


def _client() -> OpenAI:
    # OPENAI_API_KEY is picked up automatically by the SDK if set in env.
    base_url = os.getenv("OPENAI_BASE_URL") or None
    if base_url:
        return OpenAI(base_url=base_url)
    return OpenAI()


def generate_text(
    *,
    messages: List[InputMessage],
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = _client()

    # Using Responses API with role-based message input.
    resp = client.responses.create(
        model=model,
        input=messages,
        temperature=temperature,
    )
    # `output_text` is a convenience property in the SDK for text outputs.
    return getattr(resp, "output_text", "").strip() or str(resp)
