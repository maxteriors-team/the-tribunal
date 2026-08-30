"""End-to-end unit coverage for the SMS contact-evidence generation loop."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.message_context_builder import ContactGenerationContext
from app.services.ai.text_response_generator import generate_text_response


@pytest.mark.asyncio
async def test_quote_intent_forces_fresh_lookup_before_customer_claim() -> None:
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=agent_id,
        workspace_id=workspace_id,
        text_max_context_messages=20,
        enabled_tools=[],
        system_prompt="Help the customer.",
        language="en",
        temperature=0.2,
    )
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=42,
        contact_phone="+15125550100",
    )
    contact_result = MagicMock()
    contact_result.scalar_one_or_none.return_value = SimpleNamespace()
    db = AsyncMock()
    db.execute.return_value = contact_result

    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="lookup_contact_state",
            arguments=json.dumps({"subject": "quote", "reference": "Q-101"}),
        ),
    )
    first_completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tool_call]),
            )
        ]
    )
    final_completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Your quote Q-101 is approved at $900.",
                    tool_calls=None,
                )
            )
        ]
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[first_completion, final_completion])
    executor = MagicMock()
    executor.handle_tool_calls = AsyncMock(
        return_value=[
            {
                "tool_call_id": "call-1",
                "role": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "evidence_domains": ["quote"],
                        "evidence_status": "found",
                        "active_quotes": [
                            {
                                "number": "Q-101",
                                "status": "approved",
                                "total": "900.00",
                            }
                        ],
                    }
                ),
            }
        ]
    )
    training_loader = AsyncMock(return_value="")

    with (
        patch(
            "app.services.ai.text_response_generator.get_workspace_timezone",
            AsyncMock(return_value="America/New_York"),
        ),
        patch(
            "app.services.ai.text_response_generator.build_message_context",
            AsyncMock(return_value=[{"role": "user", "content": "Is quote Q-101 approved?"}]),
        ),
        patch(
            "app.services.ai.text_response_generator.get_offer_context",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai.text_response_generator.build_contact_generation_context",
            AsyncMock(
                return_value=ContactGenerationContext(
                    "<CONTACT_CONTEXT_SNAPSHOT>live CRM</CONTACT_CONTEXT_SNAPSHOT>",
                    "Is quote Q-101 approved?",
                )
            ),
        ),
        patch(
            "app.services.ai.text_response_generator.get_website_lead_qualification_policy",
            return_value=None,
        ),
        patch(
            "app.services.ai.text_response_generator.get_training_examples_prompt",
            training_loader,
        ),
        patch(
            "app.services.ai.text_response_generator.knowledge_context_service.get_preamble_for_agent",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai.text_response_generator.knowledge_context_service.has_active_documents",
            AsyncMock(return_value=False),
        ),
        patch(
            "app.services.ai.text_response_generator.AsyncOpenAI",
            return_value=client,
        ),
        patch(
            "app.services.ai.text_response_generator.TextToolExecutor",
            return_value=executor,
        ),
    ):
        response = await generate_text_response(
            agent,
            conversation,
            db,
            openai_api_key="test-key",
        )

    assert response == "Your quote Q-101 is approved at $900."
    assert client.chat.completions.create.await_count == 2
    first_request = client.chat.completions.create.await_args_list[0].kwargs
    assert first_request["tool_choice"] == {
        "type": "function",
        "function": {"name": "lookup_contact_state"},
    }
    assert "<CONTACT_CONTEXT_SNAPSHOT>live CRM" in first_request["messages"][0]["content"]
    executor.handle_tool_calls.assert_awaited_once_with(tool_calls=[tool_call])
    training_loader.assert_awaited_once_with(
        db,
        workspace_id=workspace_id,
        agent_id=agent_id,
        latest_inbound_intent="Is quote Q-101 approved?",
    )


@pytest.mark.asyncio
async def test_prepare_booking_returns_canonical_summary_without_second_model_turn() -> None:
    workspace_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        text_max_context_messages=20,
        enabled_tools=["book_appointment"],
        system_prompt="Help the customer book.",
        language="en",
        temperature=0.2,
    )
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=None,
        contact_phone="+15125550100",
    )
    latest_message = "Monday at 10, phone, use lead@example.com."
    confirmation = (
        "Please confirm: 30-minute phone call on Tuesday, September 1, 2099 at "
        "10:00 AM America/New_York, invitation to lead@example.com. Is that correct?"
    )
    tool_call = SimpleNamespace(
        id="call-prepare",
        function=SimpleNamespace(
            name="prepare_booking",
            arguments=json.dumps(
                {
                    "date": "2099-09-01",
                    "time": "10:00",
                    "email": "lead@example.com",
                    "duration_minutes": 30,
                    "call_type": "phone_call",
                }
            ),
        ),
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))]
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[completion, RuntimeError("unexpected second model turn")]
    )
    executor = MagicMock()
    executor.handle_tool_calls = AsyncMock(
        return_value=[
            {
                "tool_call_id": "call-prepare",
                "role": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "booking_draft_prepared": True,
                        "direct_response": confirmation,
                    }
                ),
            }
        ]
    )

    with (
        patch(
            "app.services.ai.text_response_generator.get_workspace_timezone",
            AsyncMock(return_value="America/New_York"),
        ),
        patch(
            "app.services.ai.text_response_generator.build_message_context",
            AsyncMock(return_value=[{"role": "user", "content": latest_message}]),
        ),
        patch(
            "app.services.ai.text_response_generator.get_offer_context",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai.text_response_generator.build_contact_generation_context",
            AsyncMock(return_value=ContactGenerationContext(None, latest_message)),
        ),
        patch(
            "app.services.ai.text_response_generator.get_website_lead_qualification_policy",
            return_value=None,
        ),
        patch(
            "app.services.ai.text_response_generator.get_training_examples_prompt",
            AsyncMock(return_value=""),
        ),
        patch(
            "app.services.ai.text_response_generator.knowledge_context_service.get_preamble_for_agent",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai.text_response_generator.knowledge_context_service.has_active_documents",
            AsyncMock(return_value=False),
        ),
        patch(
            "app.services.ai.text_response_generator.AsyncOpenAI",
            return_value=client,
        ),
        patch(
            "app.services.ai.text_response_generator.TextToolExecutor",
            return_value=executor,
        ),
    ):
        response = await generate_text_response(
            agent,
            conversation,
            AsyncMock(),
            openai_api_key="test-key",
        )

    assert response == confirmation
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_tool_error_without_domains_hands_off_instead_of_repeating_forced_tool() -> None:
    """An unlabeled evidence failure must end the turn, not re-force the same tool."""
    workspace_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        text_max_context_messages=20,
        enabled_tools=[],
        system_prompt="Help the customer.",
        language="en",
        temperature=0.2,
    )
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=42,
        contact_phone="+15125550100",
    )
    contact_result = MagicMock()
    contact_result.scalar_one_or_none.return_value = SimpleNamespace()
    db = AsyncMock()
    db.execute.return_value = contact_result

    def _tool_call() -> SimpleNamespace:
        return SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(
                name="lookup_contact_state",
                arguments=json.dumps({"subject": "balance"}),
            ),
        )

    def _completion() -> SimpleNamespace:
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[_tool_call()]))
            ]
        )

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[_completion() for _ in range(6)])
    executor = MagicMock()
    executor.handle_tool_calls = AsyncMock(
        return_value=[
            {
                "tool_call_id": "call-1",
                "role": "tool",
                # Mirrors the real executor's invalid-subject and workspace-scope
                # errors: a status with no ``evidence_domains`` to attach it to.
                "content": json.dumps(
                    {
                        "success": False,
                        "error": "subject must be quote, invoice, or appointment",
                        "evidence_status": "error",
                    }
                ),
            }
        ]
    )

    with (
        patch(
            "app.services.ai.text_response_generator.get_workspace_timezone",
            AsyncMock(return_value="America/New_York"),
        ),
        patch(
            "app.services.ai.text_response_generator.build_message_context",
            AsyncMock(return_value=[{"role": "user", "content": "Is my quote still pending?"}]),
        ),
        patch(
            "app.services.ai.text_response_generator.get_offer_context",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai.text_response_generator.build_contact_generation_context",
            AsyncMock(return_value=ContactGenerationContext(None, "Is my quote still pending?")),
        ),
        patch(
            "app.services.ai.text_response_generator.get_website_lead_qualification_policy",
            return_value=None,
        ),
        patch(
            "app.services.ai.text_response_generator.get_training_examples_prompt",
            AsyncMock(return_value=""),
        ),
        patch(
            "app.services.ai.text_response_generator.knowledge_context_service.get_preamble_for_agent",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai.text_response_generator.knowledge_context_service.has_active_documents",
            AsyncMock(return_value=False),
        ),
        patch(
            "app.services.ai.text_response_generator.AsyncOpenAI",
            return_value=client,
        ),
        patch(
            "app.services.ai.text_response_generator.TextToolExecutor",
            return_value=executor,
        ),
    ):
        response = await generate_text_response(
            agent,
            conversation,
            db,
            openai_api_key="test-key",
        )

    assert response == "I can't verify that quote in the CRM, so I'll have the team follow up."
    assert client.chat.completions.create.await_count == 1
    assert executor.handle_tool_calls.await_count == 1
