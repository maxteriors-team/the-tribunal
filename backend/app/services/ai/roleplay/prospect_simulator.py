"""Synthetic prospect simulator.

Given a persona's in-character system prompt and the conversation so far, asks an
LLM to produce the prospect's next reply. The agent's turns are presented to the
prospect as the *user* role and the prospect's own turns as *assistant*, so the
model continues its own character.
"""

from __future__ import annotations

import asyncio
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

# Match the model family used by the production text agent so rehearsals are
# representative without pulling in a heavier reasoning model.
_MODEL = "gpt-5.4-nano"
_TIMEOUT_SECONDS = 60.0
_MAX_TOKENS = 220


def _build_messages(
    persona_prompt: str,
    transcript: list[dict[str, Any]],
) -> list[ChatCompletionMessageParam]:
    """Map a roleplay transcript into prospect-perspective chat messages.

    ``transcript`` entries are ``{"role": "prospect"|"agent", "content": str}``.
    From the prospect's point of view, its own lines are ``assistant`` and the
    agent's lines are ``user``.
    """
    messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": persona_prompt}]
    for turn in transcript:
        content = str(turn.get("content", ""))
        if content:
            if turn.get("role") == "prospect":
                messages.append({"role": "assistant", "content": content})
            else:
                messages.append({"role": "user", "content": content})
    return messages


async def generate_prospect_reply(
    *,
    client: AsyncOpenAI,
    persona_prompt: str,
    transcript: list[dict[str, Any]],
    temperature: float = 0.8,
) -> str:
    """Generate the synthetic prospect's next message.

    Args:
        client: An OpenAI client bound to a resolved workspace credential.
        persona_prompt: The persona's in-character system prompt.
        transcript: Conversation so far (prospect + agent turns).
        temperature: Sampling temperature; prospects are a bit unpredictable.

    Returns:
        A genuine provider utterance. Errors propagate; no dialogue is fabricated.
    """
    messages = _build_messages(persona_prompt, transcript)
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=_MAX_TOKENS,
        ),
        timeout=_TIMEOUT_SECONDS,
    )
    text = (response.choices[0].message.content or "").strip() if response.choices else ""
    if not text:
        raise ValueError("Prospect provider returned an empty reply")
    return text
