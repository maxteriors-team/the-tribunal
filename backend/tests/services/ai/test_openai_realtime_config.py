"""Tests for OpenAI Realtime session configuration helpers."""

from app.services.ai.openai_realtime_config import (
    build_realtime_audio_config,
    normalize_transcription_language,
)


def test_normalize_transcription_language_maps_locale_to_primary_subtag() -> None:
    """OpenAI Realtime transcription accepts language codes, not app locales."""
    assert normalize_transcription_language("en-US") == "en"
    assert normalize_transcription_language("es_MX") == "es"


def test_normalize_transcription_language_preserves_supported_code() -> None:
    assert normalize_transcription_language("pt") == "pt"


def test_normalize_transcription_language_omits_unsupported_locale() -> None:
    assert normalize_transcription_language("x-klingon") is None
    assert normalize_transcription_language("") is None


def test_build_realtime_audio_config_uses_normalized_transcription_language() -> None:
    audio_config = build_realtime_audio_config(language="en-US")

    assert audio_config["input"]["transcription"] == {
        "model": "gpt-4o-mini-transcribe",
        "language": "en",
    }


def test_build_realtime_audio_config_omits_unsupported_transcription_language() -> None:
    audio_config = build_realtime_audio_config(language="x-klingon")

    assert audio_config["input"]["transcription"] == {"model": "gpt-4o-mini-transcribe"}
