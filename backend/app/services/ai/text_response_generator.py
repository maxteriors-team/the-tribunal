"""Text response generation for AI-powered SMS conversations.

Handles:
- LLM response generation with OpenAI function calling
- Booking tool requirement detection
- Follow-up message generation for re-engagement
"""

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.services.ai.message_context_builder import (
    build_message_context,
    extract_email_from_messages,
    get_offer_context,
    get_workspace_timezone,
)
from app.services.ai.openai_credentials import (
    OpenAICredentialContext,
    build_async_openai_client,
)
from app.services.ai.text_prompt_builder import (
    FOLLOWUP_SYSTEM_PROMPT,
    build_booking_instructions,
    build_text_instructions,
)
from app.services.ai.text_tool_executor import TextToolExecutor
from app.services.ai.voice_tools import get_text_booking_tools, get_text_search_knowledge_tool
from app.services.knowledge.knowledge_context_service import knowledge_context_service

logger = structlog.get_logger()


def should_require_booking_tools(message: str) -> bool:  # noqa: PLR0911
    """Determine if booking tools should be required based on message content.

    Uses smarter matching to avoid false positives like "weather today".

    Args:
        message: The lowercased message to analyze

    Returns:
        True if booking tools should be required
    """
    # Direct booking intent phrases - always trigger
    direct_booking_phrases = [
        "book a",
        "book an",
        "schedule a",
        "schedule an",
        "set up a",
        "setup a",
        "arrange a",
        "want to meet",
        "want to call",
        "want to schedule",
        "like to meet",
        "like to call",
        "like to schedule",
        "can we meet",
        "can we call",
        "can we schedule",
        "let's meet",
        "lets meet",
        "let's schedule",
        "lets schedule",
        "interested in scheduling",
        "interested in meeting",
        "ready to book",
        "ready to schedule",
    ]
    if any(phrase in message for phrase in direct_booking_phrases):
        return True

    # Buying signals - general positive responses indicating readiness to proceed
    # These trigger booking tools so the AI offers to schedule instead of more questions
    buying_signal_phrases = [
        "sounds good",
        "that sounds great",
        "that sounds good",
        "ok sounds good",
        "okay sounds good",
        "i'm in",
        "im in",
        "count me in",
        "sign me up",
        "i'm interested",
        "im interested",
        "i'm ready",
        "im ready",
        "let's move forward",
        "lets move forward",
        "let's get started",
        "lets get started",
        "let's go",
        "lets go",
        "how do we get started",
        "how do i get started",
        "what's the next step",
        "whats the next step",
        "what do i need to do",
        "what do we do next",
        "i want that",
        "i need that",
        "i want this",
        "i need this",
        "yes please",
        "yeah that works",
        "yes that works",
    ]
    if any(phrase in message for phrase in buying_signal_phrases):
        return True

    # Availability questions - trigger tools
    availability_phrases = [
        "when are you",
        "when is he",
        "when is she",
        "when is nolan",
        "what times",
        "what time do",
        "what days",
        "any availability",
        "your availability",
        "his availability",
        "are you available",
        "is he available",
        "is she available",
        "when can we",
        "when can i",
        "when could we",
        "what's available",
        "whats available",
        "free time",
        "open slots",
        "available slots",
    ]
    if any(phrase in message for phrase in availability_phrases):
        return True

    # Time selection responses - user picking a slot
    # Must be in scheduling context (short message with time reference)
    time_selection_patterns = [
        r"\b(tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b.*\b(works|good|perfect|great|fine)\b",
        r"\b(works|good|perfect|great|fine)\b.*\b(tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"^(tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(at\s*)?\d",
        r"^\d{1,2}(:\d{2})?\s*(am|pm|AM|PM)?\s*(works|good|perfect|sounds|great)?",
        r"^(let's do|lets do|i'll take|ill take|how about)\s",
    ]
    for pattern in time_selection_patterns:
        if re.search(pattern, message, re.IGNORECASE):
            return True

    # Specific time mentions with booking context
    # Only trigger if message is SHORT and contains time (likely a time selection)
    if len(message) < 50:
        time_patterns = [
            r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b",  # "2pm", "2:30 pm"
            r"\bat\s+\d{1,2}\b",  # "at 2", "at 3"
            r"\b(morning|afternoon|evening)\s+(works|is good|sounds good)\b",
        ]
        for pattern in time_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True

    # Email provided - likely confirming booking
    # Check for actual email pattern, not just "@" or ".com"
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    if re.search(email_pattern, message):
        return True

    # Email mention in booking context
    email_context_phrases = [
        "my email is",
        "email is",
        "send it to",
        "send confirmation to",
        "here's my email",
        "heres my email",
        "my email:",
    ]
    return any(phrase in message for phrase in email_context_phrases)


async def generate_text_response(  # noqa: PLR0915, PLR0912
    agent: Agent,
    conversation: Conversation,
    db: AsyncSession,
    openai_api_key: str,
    *,
    credential: OpenAICredentialContext | None = None,
) -> str | None:
    """Generate AI response for a text conversation.

    Supports OpenAI function calling for booking appointments via Cal.com.

    Args:
        agent: The text agent to use
        conversation: The conversation
        db: Database session
        openai_api_key: OpenAI API key (used when ``credential`` is not supplied)
        credential: Resolved OpenAI credential context. When provided, the SDK
            client is built with :func:`build_async_openai_client` so OAuth
            tokens carry the required OAuth headers; a bare ``openai_api_key``
            omits them and OAuth-backed workspaces get 401s that surface as an
            empty reply.

    Returns:
        Generated response text, or None if failed
    """
    log = logger.bind(
        agent_id=str(agent.id),
        conversation_id=str(conversation.id),
    )
    log.info("generating_text_response")

    # Get timezone from workspace settings
    timezone = await get_workspace_timezone(conversation.workspace_id, db)

    # Build message context
    messages = await build_message_context(
        conversation, db, max_messages=agent.text_max_context_messages
    )

    if not messages:
        log.warning("no_messages_in_context")
        return None

    # Get offer context if conversation was from a campaign
    offer_context = await get_offer_context(conversation, db)

    # Build system instructions - include booking tools info if configured
    has_booking_tools = bool(
        agent.calcom_event_type_id
        and settings.calcom_api_key
        and "book_appointment" in (agent.enabled_tools or [])
    )

    booking_instructions = ""
    extracted_email = None
    if has_booking_tools:
        # Extract email from conversation history
        extracted_email = extract_email_from_messages(messages)

        # Build booking instructions using extracted module
        booking_instructions = build_booking_instructions(
            timezone=timezone,
            extracted_email=extracted_email,
        )

        # Log extracted email for debugging
        if extracted_email:
            log.info("email_extracted_from_history", email=extracted_email)

    # Build a small high-priority knowledge preamble (must-know facts only).
    # Bulk knowledge is reached on demand via the search_knowledge tool instead
    # of statically prompt-stuffing the whole base into every request.
    knowledge_context = await knowledge_context_service.get_preamble_for_agent(db, agent.id)

    # Expose the on-demand knowledge tool when the operator enabled it or the
    # agent has an ingested knowledge base to search.
    knowledge_tool_enabled = "search_knowledge" in (agent.enabled_tools or []) or (
        await knowledge_context_service.has_active_documents(db, agent.id)
    )

    system_prompt = build_text_instructions(
        system_prompt=agent.system_prompt + booking_instructions,
        language=agent.language,
        timezone=timezone,
        contact_phone=conversation.contact_phone,
        offer_context=offer_context,
        booking_url=None,  # Don't include URL when using function calling
        knowledge_context=knowledge_context,
    )

    # Create OpenAI client. Prefer the resolved credential so OAuth-backed
    # workspaces get the required OAuth headers; fall back to the bare key.
    client = (
        build_async_openai_client(credential)
        if credential is not None
        else AsyncOpenAI(api_key=openai_api_key)
    )

    try:
        # Build messages for API call
        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        # Prepare API call parameters
        api_params: dict[str, Any] = {
            "model": "gpt-5.4-nano",
            "messages": api_messages,
            "temperature": agent.temperature,
            "max_completion_tokens": 500,
        }

        # Assemble the tool list: booking tools (if configured) plus the
        # on-demand knowledge retrieval tool (if enabled). Both can coexist.
        active_tools: list[dict[str, Any]] = []
        if has_booking_tools:
            active_tools.extend(get_text_booking_tools(timezone))
        if knowledge_tool_enabled:
            active_tools.append(get_text_search_knowledge_tool())
        if active_tools:
            api_params["tools"] = active_tools

        # Include tools if booking is configured
        if has_booking_tools:
            # Check if last message mentions booking-related keywords
            last_msg = messages[-1]["content"].lower() if messages else ""

            # OPT-OUT DETECTION: Never force booking tools on negative intent
            # These phrases indicate user wants to stop communication
            opt_out_phrases = [
                "stop",
                "unsubscribe",
                "opt out",
                "optout",
                "cancel",
                "remove me",
                "take me off",
                "don't text",
                "dont text",
                "don't contact",
                "dont contact",
                "leave me alone",
                "not interested",
                "no thanks",
                "no thank you",
                "spam",
                "harassment",
                "harassing",
                "reported",
                "wrong number",
                "wrong person",
            ]
            is_opt_out = any(phrase in last_msg for phrase in opt_out_phrases)

            if is_opt_out:
                # Don't force tools on opt-out messages - let AI respond naturally
                api_params["tool_choice"] = "auto"
                log.info("opt_out_detected_tools_auto")
            else:
                # Check for booking intent using smarter matching
                require_tools = should_require_booking_tools(last_msg)

                if require_tools:
                    api_params["tool_choice"] = "required"
                    log.info("booking_tools_required")
                else:
                    api_params["tool_choice"] = "auto"
                    log.info("booking_tools_enabled")
        elif knowledge_tool_enabled:
            # Knowledge-only tool set: let the model decide when to look things up.
            api_params["tool_choice"] = "auto"
            log.info("knowledge_tool_enabled")

        # Make initial LLM call
        response = await asyncio.wait_for(
            client.chat.completions.create(**api_params),
            timeout=30.0,
        )

        assistant_message = response.choices[0].message

        # Handle tool calls if present
        if assistant_message.tool_calls:
            log.info(
                "tool_calls_received",
                count=len(assistant_message.tool_calls),
            )

            # Execute the tool calls using TextToolExecutor
            tool_executor = TextToolExecutor(
                agent=agent,
                conversation=conversation,
                db=db,
                timezone=timezone,
            )
            tool_results = await tool_executor.handle_tool_calls(
                tool_calls=assistant_message.tool_calls,
            )

            # Add assistant message and tool results to conversation
            api_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_message.tool_calls
                    ],
                }
            )
            api_messages.extend(tool_results)

            # Make follow-up call to get final response
            follow_up_response = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-5.4-nano",
                    messages=api_messages,  # type: ignore[arg-type]
                    temperature=agent.temperature,
                    max_completion_tokens=500,
                ),
                timeout=30.0,
            )

            final_message = follow_up_response.choices[0].message
            final_text: str | None = final_message.content

            if final_text:
                log.info(
                    "response_generated_with_tools",
                    length=len(final_text),
                )
                return final_text
        else:
            # No tool calls, use direct response
            response_text: str | None = assistant_message.content
            if response_text:
                log.info("response_generated", length=len(response_text))
                return response_text

        return None

    except TimeoutError:
        log.error("openai_timeout")
        return None
    except Exception:
        log.exception("openai_error")
        return None


async def generate_followup_message(
    conversation: Conversation,
    db: AsyncSession,
    openai_api_key: str,
    custom_instructions: str | None = None,
) -> str | None:
    """Generate an AI follow-up message for a conversation.

    Creates a contextual re-engagement message based on conversation history,
    time since last interaction, and optional custom instructions.

    Args:
        conversation: The conversation to generate a follow-up for
        db: Database session
        openai_api_key: OpenAI API key
        custom_instructions: Optional custom instructions to guide the message

    Returns:
        Generated follow-up message text, or None if generation failed
    """
    log = logger.bind(conversation_id=str(conversation.id))
    log.info("generating_followup_message")

    # Build message context
    messages = await build_message_context(conversation, db, max_messages=10)

    if not messages:
        log.warning("no_messages_in_context_for_followup")
        return None

    # Get contact name for personalization
    contact_name = "there"
    if conversation.contact_id:
        result = await db.execute(select(Contact).where(Contact.id == conversation.contact_id))
        contact = result.scalar_one_or_none()
        if contact and contact.first_name:
            contact_name = contact.first_name

    # Calculate time since last message
    time_context = ""
    if conversation.last_message_at:
        time_diff = datetime.now(UTC) - conversation.last_message_at.replace(tzinfo=UTC)
        days = time_diff.days
        hours = time_diff.seconds // 3600

        if days > 0:
            time_context = f"\nTime since last message: {days} day{'s' if days != 1 else ''}"
        elif hours > 0:
            time_context = f"\nTime since last message: {hours} hour{'s' if hours != 1 else ''}"

    # Build the system prompt with context
    system_prompt = FOLLOWUP_SYSTEM_PROMPT
    if custom_instructions:
        system_prompt += f"\n\nADDITIONAL INSTRUCTIONS:\n{custom_instructions}"

    # Build user prompt with context
    user_prompt = f"""Generate a follow-up message for this conversation.

Contact name: {contact_name}
Previous follow-ups sent: {conversation.followup_count_sent}{time_context}

Recent conversation:
"""
    for msg in messages[-6:]:  # Last 6 messages for context
        role = "Customer" if msg["role"] == "user" else "You"
        user_prompt += f"\n{role}: {msg['content']}"

    user_prompt += "\n\nWrite a short, friendly follow-up message:"

    # Create OpenAI client
    client = AsyncOpenAI(api_key=openai_api_key)

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-5.4-nano",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_completion_tokens=200,
            ),
            timeout=30.0,
        )

        followup_text: str | None = response.choices[0].message.content
        if followup_text:
            followup_text = followup_text.strip()
            log.info("followup_message_generated", length=len(followup_text))
            return followup_text

        return None

    except TimeoutError:
        log.error("followup_generation_timeout")
        return None
    except Exception:
        log.exception("followup_generation_error")
        return None
