"""Tests for shared image-input validation and content-part builders."""

import base64

import pytest

from app.services.ai.image_input import (
    MAX_IMAGE_BYTES,
    ImageValidationError,
    build_chat_image_content_part,
    build_chat_user_message_with_image,
    validate_image_data_url,
)
from app.services.ai.openai_realtime_config import build_realtime_image_input_item

# 1x1 transparent PNG.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode()
_PNG_DATA_URL = f"data:image/png;base64,{_PNG_B64}"


def test_validate_image_data_url_accepts_supported_png() -> None:
    assert validate_image_data_url(_PNG_DATA_URL) == _PNG_DATA_URL


def test_validate_image_data_url_normalizes_mime_case() -> None:
    assert (
        validate_image_data_url(f"data:IMAGE/PNG;base64,{_PNG_B64}") == _PNG_DATA_URL
    )


def test_validate_image_data_url_rejects_non_data_url() -> None:
    with pytest.raises(ImageValidationError):
        validate_image_data_url("https://example.com/roof.png")


def test_validate_image_data_url_rejects_disallowed_mime() -> None:
    with pytest.raises(ImageValidationError):
        validate_image_data_url(f"data:application/pdf;base64,{_PNG_B64}")


def test_validate_image_data_url_rejects_non_base64_payload() -> None:
    with pytest.raises(ImageValidationError):
        validate_image_data_url("data:image/png;base64,not valid base64!!")


def test_validate_image_data_url_rejects_oversized_image() -> None:
    oversized = base64.b64encode(b"\x00" * (MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(ImageValidationError):
        validate_image_data_url(f"data:image/png;base64,{oversized}")


def test_build_chat_image_content_part_shape() -> None:
    assert build_chat_image_content_part(_PNG_DATA_URL) == {
        "type": "image_url",
        "image_url": {"url": _PNG_DATA_URL},
    }


def test_build_chat_user_message_without_image_stays_plain_string() -> None:
    assert build_chat_user_message_with_image("hello", None) == {
        "role": "user",
        "content": "hello",
    }


def test_build_chat_user_message_with_image_is_multimodal() -> None:
    message = build_chat_user_message_with_image("What is this?", _PNG_DATA_URL)
    assert message["role"] == "user"
    assert message["content"] == [
        {"type": "text", "text": "What is this?"},
        {"type": "image_url", "image_url": {"url": _PNG_DATA_URL}},
    ]


def test_build_realtime_image_input_item_matches_ga_shape() -> None:
    event = build_realtime_image_input_item(image_url=_PNG_DATA_URL, text="see this")
    assert event == {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "see this"},
                {"type": "input_image", "image_url": _PNG_DATA_URL},
            ],
        },
    }


def test_build_realtime_image_input_item_without_text_omits_input_text() -> None:
    event = build_realtime_image_input_item(image_url=_PNG_DATA_URL)
    assert event["item"]["content"] == [
        {"type": "input_image", "image_url": _PNG_DATA_URL},
    ]
