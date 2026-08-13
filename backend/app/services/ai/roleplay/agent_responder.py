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

import structlog
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.services.ai.text_prompt_builder import build_text_instructions
from app.services.knowledge.knowledge_context_service import knowledge_context_service

logger = structlog.get_logger()

_MODEL = "gpt-5.4-nano"
_TIMEOUT_SECONDS = 30.0
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
) -> list[dict[str, str]]:
    """Map the transcript into agent-perspective chat messages.

    From the agent's point of view its own lines are ``assistant`` and the
    prospect's lines are ``user``.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for turn in transcript:
        role = "assistant" if turn.get("role") == "agent" else "user"
        content = str(turn.get("content", ""))
        if content:
            messages.append({"role": role, "content": content})
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
        The agent's next utterance, or a short fallback on failure.
    """
    messages = _build_messages(system_prompt, transcript)
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=_MODEL,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_completion_tokens=_MAX_TOKENS,
            ),
            timeout=_TIMEOUT_SECONDS,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
        logger.warning("agent_reply_empty")
    except TimeoutError:
        logger.error("agent_reply_timeout")
    except Exception:
        logger.exception("agent_reply_failed")
    return "Thanks for reaching out — happy to help with any questions you have."
