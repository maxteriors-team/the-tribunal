"""LLM client abstraction for IVR test harness.

This module provides protocol-based LLM clients for generating agent responses
during IVR test simulations. Supports multiple providers:
- OpenAITestClient: Uses OpenAI GPT models
- GrokTestClient: Uses xAI Grok models

Example usage:
    client = OpenAITestClient(api_key="sk-...", model="gpt-5.4-nano")
    response = await client.generate_response(
        system_prompt="You are an AI voice agent...",
        ivr_transcript="Press 1 for sales, press 2 for support.",
        conversation_history=[
            {"role": "assistant", "content": "Hi, I'm calling about..."},
            {"role": "user", "content": "Thank you for calling Acme Corp."},
        ],
    )
"""

from typing import Protocol

import httpx
import structlog

logger = structlog.get_logger()


class IVRTestLLMClient(Protocol):
    """Protocol for LLM clients used in IVR testing.

    Implementations must provide async generate_response method.
    """

    async def generate_response(
        self,
        system_prompt: str,
        ivr_transcript: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        """Generate an agent response to an IVR prompt.

        Args:
            system_prompt: The agent's system prompt including IVR navigation instructions
            ivr_transcript: The current IVR transcript to respond to
            conversation_history: Previous turns as list of role/content dicts

        Returns:
            The agent's response text, potentially containing <dtmf>X</dtmf> tags
        """
        ...


class OpenAITestClient:
    """OpenAI-based LLM client for IVR testing.

    Uses the OpenAI Chat Completions API with low temperature
    for more deterministic IVR navigation decisions.

    Attributes:
        api_key: OpenAI API key
        model: Model to use (default: gpt-5.4-nano)
        temperature: Sampling temperature (default: 0.3)
        timeout: Request timeout in seconds (default: 30)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4-nano",
        temperature: float = 0.3,
        timeout: float = 30.0,
    ) -> None:
        """Initialize OpenAI test client.

        Args:
            api_key: OpenAI API key
            model: Model ID to use
            temperature: Sampling temperature (0.0-2.0)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.logger = logger.bind(service="openai_test_client", model=model)

    async def generate_response(
        self,
        system_prompt: str,
        ivr_transcript: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        """Generate agent response using OpenAI API.

        Args:
            system_prompt: Agent system prompt with IVR instructions
            ivr_transcript: Current IVR transcript
            conversation_history: Previous conversation turns

        Returns:
            Agent response text

        Raises:
            httpx.HTTPError: On API request failure
        """
        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Add conversation history
        for turn in conversation_history:
            messages.append(turn)

        # Add current IVR transcript as user message
        messages.append({"role": "user", "content": ivr_transcript})

        self.logger.debug(
            "openai_request",
            model=self.model,
            message_count=len(messages),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_completion_tokens": 500,
                },
            )
            response.raise_for_status()
            data = response.json()

        content: str = data["choices"][0]["message"]["content"]

        self.logger.debug(
            "openai_response",
            response_preview=content[:100] if content else "",
        )

        return content


class GrokTestClient:
    """xAI Grok-based LLM client for IVR testing.

    Uses the xAI API with low temperature for deterministic IVR navigation.

    Attributes:
        api_key: xAI API key
        model: Model to use (default: grok-3-mini)
        temperature: Sampling temperature (default: 0.3)
        timeout: Request timeout in seconds (default: 30)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "grok-3-mini",
        temperature: float = 0.3,
        timeout: float = 30.0,
    ) -> None:
        """Initialize Grok test client.

        Args:
            api_key: xAI API key
            model: Model ID to use
            temperature: Sampling temperature
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.logger = logger.bind(service="grok_test_client", model=model)

    async def generate_response(
        self,
        system_prompt: str,
        ivr_transcript: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        """Generate agent response using xAI Grok API.

        Args:
            system_prompt: Agent system prompt with IVR instructions
            ivr_transcript: Current IVR transcript
            conversation_history: Previous conversation turns

        Returns:
            Agent response text

        Raises:
            httpx.HTTPError: On API request failure
        """
        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Add conversation history
        for turn in conversation_history:
            messages.append(turn)

        # Add current IVR transcript as user message
        messages.append({"role": "user", "content": ivr_transcript})

        self.logger.debug(
            "grok_request",
            model=self.model,
            message_count=len(messages),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": 500,
                },
            )
            response.raise_for_status()
            data = response.json()

        content: str = data["choices"][0]["message"]["content"]

        self.logger.debug(
            "grok_response",
            response_preview=content[:100] if content else "",
        )

        return content


class MockLLMClient:
    """Mock LLM client for deterministic testing.

    Returns predetermined responses in sequence, useful for unit tests.

    Attributes:
        responses: List of responses to return in order
        call_count: Number of calls made
    """

    def __init__(self, responses: list[str]) -> None:
        """Initialize mock client with predetermined responses.

        Args:
            responses: Ordered list of responses to return
        """
        self.responses = responses
        self.call_count = 0
        self.calls: list[dict[str, object]] = []
        self.logger = logger.bind(service="mock_llm_client")

    async def generate_response(
        self,
        system_prompt: str,
        ivr_transcript: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        """Return next predetermined response.

        Args:
            system_prompt: Ignored in mock
            ivr_transcript: Logged for verification
            conversation_history: Ignored in mock

        Returns:
            Next response from the responses list

        Raises:
            IndexError: If more calls made than responses provided
        """
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "ivr_transcript": ivr_transcript,
                "conversation_history": conversation_history,
            }
        )

        if self.call_count >= len(self.responses):
            self.logger.warning("mock_responses_exhausted", call_count=self.call_count)
            raise IndexError(f"MockLLMClient exhausted responses after {self.call_count} calls")

        response = self.responses[self.call_count]
        self.call_count += 1

        self.logger.debug(
            "mock_response",
            call_count=self.call_count,
            response_preview=response[:50] if response else "",
        )

        return response
