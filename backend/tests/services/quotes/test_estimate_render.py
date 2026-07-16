"""Unit tests for the estimator's photorealistic night-render service.

The OpenAI image client is always mocked — these prove credential resolution,
image decoding, prompt selection, response handling, and error mapping without
any network call or spend.
"""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.exceptions import ServiceUnavailableError, ValidationError
from app.services.quotes import estimate_render
from app.services.quotes.estimate_render import (
    default_render_prompt,
    render_design,
)

# A 1x1 transparent PNG — the smallest valid image payload.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode()
_PNG_DATA_URL = f"data:image/png;base64,{_PNG_B64}"


def _fake_client(b64: str | None) -> AsyncMock:
    """A stand-in AsyncOpenAI whose images.edit returns one b64 image."""
    client = AsyncMock()
    data = [SimpleNamespace(b64_json=b64)] if b64 is not None else []
    client.images.edit = AsyncMock(return_value=SimpleNamespace(data=data))
    return client


# --------------------------------------------------------------------------- #
# Prompt selection
# --------------------------------------------------------------------------- #


def test_default_prompt_varies_by_mode_and_stays_under_cap() -> None:
    seasonal = default_render_prompt("seasonal")
    permanent = default_render_prompt("permanent")
    assert "C9 Christmas lights" in seasonal
    assert "permanent LED track lighting" in permanent
    # OpenAI caps the image-edit prompt at 1000 characters.
    assert len(seasonal) <= 1000
    assert len(permanent) <= 1000


def test_unknown_mode_falls_back_to_seasonal_prompt() -> None:
    assert default_render_prompt("weird") == default_render_prompt("seasonal")


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_render_returns_jpeg_data_url_from_workspace_client() -> None:
    client = _fake_client("RESULTB64==")
    workspace_id = uuid.uuid4()
    with patch.object(
        estimate_render, "create_workspace_openai_client", AsyncMock(return_value=client)
    ) as resolve:
        out = await render_design(AsyncMock(), workspace_id, image=_PNG_DATA_URL, mode="seasonal")

    assert out == "data:image/jpeg;base64,RESULTB64=="
    # Uses the per-tenant credential resolver, not a global client.
    resolve.assert_awaited_once()
    kwargs = client.images.edit.await_args.kwargs
    assert kwargs["model"] == "gpt-image-2"
    assert kwargs["output_format"] == "jpeg"
    assert kwargs["n"] == 1
    # The decoded PNG bytes are forwarded as the edit base image, with a real
    # image content type (never application/octet-stream, which OpenAI rejects).
    filename, blob, content_type = kwargs["image"]
    assert blob == _PNG_BYTES
    assert filename == "design.png"
    assert content_type == "image/png"


@pytest.mark.asyncio
async def test_raw_base64_without_data_prefix_is_accepted() -> None:
    client = _fake_client("OK==")
    with patch.object(
        estimate_render, "create_workspace_openai_client", AsyncMock(return_value=client)
    ):
        out = await render_design(AsyncMock(), uuid.uuid4(), image=_PNG_B64)
    assert out.startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_custom_prompt_overrides_default() -> None:
    client = _fake_client("OK==")
    with patch.object(
        estimate_render, "create_workspace_openai_client", AsyncMock(return_value=client)
    ):
        await render_design(
            AsyncMock(), uuid.uuid4(), image=_PNG_DATA_URL, prompt="  make it pop  "
        )
    assert client.images.edit.await_args.kwargs["prompt"] == "make it pop"


# --------------------------------------------------------------------------- #
# Input validation (clean 400s, no OpenAI call)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_invalid_base64_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        await render_design(AsyncMock(), uuid.uuid4(), image="data:image/png;base64,@@notb64@@")


@pytest.mark.asyncio
async def test_empty_data_url_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        await render_design(AsyncMock(), uuid.uuid4(), image="data:image/png;base64,")


@pytest.mark.asyncio
async def test_oversize_image_raises_validation_error() -> None:
    big = base64.b64encode(b"\x00" * (9 * 1024 * 1024)).decode()
    with pytest.raises(ValidationError):
        await render_design(AsyncMock(), uuid.uuid4(), image=big)


# --------------------------------------------------------------------------- #
# External-failure mapping (503, never a raw provider error)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_missing_credentials_maps_to_service_unavailable() -> None:
    with (
        patch.object(
            estimate_render,
            "create_workspace_openai_client",
            AsyncMock(side_effect=estimate_render.OpenAICredentialError("nope")),
        ),
        pytest.raises(ServiceUnavailableError),
    ):
        await render_design(AsyncMock(), uuid.uuid4(), image=_PNG_DATA_URL)


@pytest.mark.asyncio
async def test_openai_error_maps_to_service_unavailable() -> None:
    client = AsyncMock()
    client.images.edit = AsyncMock(side_effect=estimate_render.OpenAIError("boom"))
    with (
        patch.object(
            estimate_render, "create_workspace_openai_client", AsyncMock(return_value=client)
        ),
        pytest.raises(ServiceUnavailableError),
    ):
        await render_design(AsyncMock(), uuid.uuid4(), image=_PNG_DATA_URL)


@pytest.mark.asyncio
async def test_empty_openai_response_maps_to_service_unavailable() -> None:
    client = _fake_client(None)
    with (
        patch.object(
            estimate_render, "create_workspace_openai_client", AsyncMock(return_value=client)
        ),
        pytest.raises(ServiceUnavailableError),
    ):
        await render_design(AsyncMock(), uuid.uuid4(), image=_PNG_DATA_URL)
