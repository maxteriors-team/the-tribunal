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
