"""Rehearsal agent responder.

Produces the agent's next turn during a rehearsal using the agent's *real*
production prompt construction so the rehearsal reflects how the agent actually
behaves with leads. We deliberately reuse ``build_text_instructions`` and the
knowledge preamble from the live text pipeline.

Side-effect free: unlike the production text path, this never creates
conversations/messages, never sends SMS, and never executes booking tools (no
real Google Calendar calls). "Did it attempt a booking?" is judged from the transcript
by the report scorer instead.
"""

from __future__ import annotations

import asyncio
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.services.ai.text_prompt_builder import build_text_instructions
from app.services.knowledge.knowledge_context_service import knowledge_context_service

_MODEL = "gpt-5.4-nano"
_TIMEOUT_SECONDS = 60.0
_MAX_TOKENS = 500


async def build_agent_system_prompt(
    db: AsyncSession,
    agent: Agent,
    *,
    timezone: str = "America/New_York",
) -> str:
    """Assemble the agent's system prompt exactly like the live text pipeline.

    Mirrors ``generate_text_response``: the agent's own ``system_prompt`` wrapped
    in ``build_text_instructions`` with the high-priority knowledge preamble. We
    omit booking-tool function calling on purpose (rehearsal is side-effect free)
    but instruct the agent to behave as if it can book.
    """
    knowledge_context = await knowledge_context_service.get_preamble_for_agent(db, agent.id)
    return build_text_instructions(
        system_prompt=agent.system_prompt,
        language=agent.language,
        timezone=timezone,
        contact_phone=None,
        offer_context=None,
        booking_url=None,
        knowledge_context=knowledge_context,
    )


def _build_messages(
    system_prompt: str,
    transcript: list[dict[str, Any]],
) -> list[ChatCompletionMessageParam]:
    """Map the transcript into agent-perspective chat messages.

    From the agent's point of view its own lines are ``assistant`` and the
    prospect's lines are ``user``.
    """
    messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": system_prompt}]
    for turn in transcript:
        content = str(turn.get("content", ""))
        if content:
            if turn.get("role") == "agent":
                messages.append({"role": "assistant", "content": content})
            else:
                messages.append({"role": "user", "content": content})
    return messages


async def generate_agent_reply(
    *,
    client: AsyncOpenAI,
    system_prompt: str,
    transcript: list[dict[str, Any]],
    temperature: float = 0.7,
) -> str:
    """Generate the agent's next message for a rehearsal.

    Args:
        client: OpenAI client bound to a resolved workspace credential.
        system_prompt: Prompt from :func:`build_agent_system_prompt`.
        transcript: Conversation so far (prospect + agent turns).
        temperature: Sampling temperature (defaults to the agent's setting).

    Returns:
        A genuine provider utterance. Errors propagate; no dialogue is fabricated.
    """
    messages = _build_messages(system_prompt, transcript)
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
        raise ValueError("Agent provider returned an empty reply")
    return text
