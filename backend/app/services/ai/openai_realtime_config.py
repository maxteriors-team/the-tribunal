"""OpenAI GA Realtime session configuration helpers.

This module is the single place where the app translates existing voice-agent
settings into the GA Realtime API shape. Keep provider-specific compatibility
payloads out of browser code and route handlers by using these builders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict, cast

from app.core.config import settings

type OpenAIRealtimeVoice = Literal[
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
]

OPENAI_REALTIME_VOICES: frozenset[OpenAIRealtimeVoice] = frozenset(
    {
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    }
)
DEFAULT_OPENAI_REALTIME_VOICE: OpenAIRealtimeVoice = "ash"
DEFAULT_INPUT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_AUDIO_FORMAT = "g711_ulaw"

OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE_CODES = frozenset(
    {
        "af",
        "ar",
        "az",
        "be",
        "bg",
        "bs",
        "ca",
        "cs",
        "cy",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fa",
        "fi",
        "fr",
        "gl",
        "he",
        "hi",
        "hr",
        "hu",
        "hy",
        "id",
        "is",
        "it",
        "iw",
        "ja",
        "kk",
        "kn",
        "ko",
        "lt",
        "lv",
        "mi",
        "mk",
        "mr",
        "ms",
        "ne",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sr",
        "sv",
        "sw",
        "ta",
        "th",
        "tl",
        "tr",
        "uk",
        "ur",
        "vi",
        "zh",
    }
)

GA_AUDIO_FORMAT_BY_LEGACY_NAME: dict[str, str] = {
    "g711_ulaw": "audio/pcmu",
    "g711-ulaw": "audio/pcmu",
    "ulaw": "audio/pcmu",
    "pcmu": "audio/pcmu",
    "audio/pcmu": "audio/pcmu",
    "g711_alaw": "audio/pcma",
    "g711-alaw": "audio/pcma",
    "alaw": "audio/pcma",
    "pcma": "audio/pcma",
    "audio/pcma": "audio/pcma",
    "pcm16": "audio/pcm",
    "pcm": "audio/pcm",
    "audio/pcm": "audio/pcm",
}
REASONING_REALTIME_MODELS = frozenset(
    {
        "gpt-realtime-2",
        "gpt-realtime-2-2025-12-15",
    }
)


def extract_realtime_client_secret_value(payload: object) -> str | None:
    """Return a Realtime client secret value from current or legacy response shapes."""
    if not isinstance(payload, dict):
        return None

    value = payload.get("value")
    if isinstance(value, str) and value.strip():
        return value.strip()

    nested = payload.get("client_secret")
    if isinstance(nested, dict):
        nested_value = nested.get("value")
        if isinstance(nested_value, str) and nested_value.strip():
            return nested_value.strip()

    return None


class AudioFormatConfig(TypedDict, total=False):
    """GA Realtime audio format object."""

    type: Literal["audio/pcm", "audio/pcmu", "audio/pcma"]
    rate: Literal[24000]


class ServerVADConfig(TypedDict, total=False):
    """Server VAD configuration for GA Realtime audio input."""

    type: Literal["server_vad"]
    threshold: float
    prefix_padding_ms: int
    silence_duration_ms: int
    idle_timeout_ms: int | None
    create_response: bool
    interrupt_response: bool


class SemanticVADConfig(TypedDict, total=False):
    """Semantic VAD configuration for GA Realtime audio input."""

    type: Literal["semantic_vad"]
    eagerness: Literal["low", "medium", "high", "auto"]
    create_response: bool
    interrupt_response: bool


type TurnDetectionConfig = ServerVADConfig | SemanticVADConfig


class AudioInputConfig(TypedDict, total=False):
    """GA Realtime audio input config."""

    format: AudioFormatConfig
    transcription: dict[str, str]
    turn_detection: TurnDetectionConfig | None
    noise_reduction: dict[str, str] | None


class AudioOutputConfig(TypedDict, total=False):
    """GA Realtime audio output config."""

    format: AudioFormatConfig
    voice: str
    speed: float


class AudioConfig(TypedDict, total=False):
    """GA Realtime audio config."""

    input: AudioInputConfig
    output: AudioOutputConfig


class RealtimeSessionConfig(TypedDict, total=False):
    """Subset of GA Realtime session config used by this app."""

    type: Literal["realtime"]
    model: str
    instructions: str
    output_modalities: list[Literal["audio", "text"]]
    audio: AudioConfig
    tools: list[dict[str, Any]]
    tool_choice: str
    truncation: dict[str, float | str]
    reasoning: dict[str, str]
    parallel_tool_calls: bool


class ResponseCreatePayload(TypedDict):
    """response.create Realtime event."""

    type: Literal["response.create"]
    response: dict[str, list[str] | str]


class RealtimeInputTextPart(TypedDict):
    """GA Realtime ``input_text`` user content part."""

    type: Literal["input_text"]
    text: str


class RealtimeInputImagePart(TypedDict):
    """GA Realtime ``input_image`` user content part.

    ``image_url`` is the base64 ``data:`` URL string itself (not a nested
    object), per the GA ``gpt-realtime``/``gpt-realtime-2`` image-input shape.
    """

    type: Literal["input_image"]
    image_url: str


type RealtimeUserContentPart = RealtimeInputTextPart | RealtimeInputImagePart


def normalize_openai_voice(
    voice: str | None,
    *,
    default: OpenAIRealtimeVoice = DEFAULT_OPENAI_REALTIME_VOICE,
) -> OpenAIRealtimeVoice:
    """Normalize an arbitrary voice string to a supported OpenAI Realtime voice."""
    if not voice:
        return default
    normalized = voice.strip().lower()
    if normalized in OPENAI_REALTIME_VOICES:
        return normalized
    return default


def normalize_realtime_audio_format(format_name: str | None = None) -> AudioFormatConfig:
    """Map legacy audio format names to GA Realtime audio format objects."""
    key = (format_name or DEFAULT_AUDIO_FORMAT).strip().lower()
    audio_type = GA_AUDIO_FORMAT_BY_LEGACY_NAME.get(
        key,
        GA_AUDIO_FORMAT_BY_LEGACY_NAME[DEFAULT_AUDIO_FORMAT],
    )
    audio_format: AudioFormatConfig = {
        "type": cast(Literal["audio/pcm", "audio/pcmu", "audio/pcma"], audio_type)
    }
    if audio_type == "audio/pcm":
        audio_format["rate"] = 24000
    return audio_format


def normalize_transcription_language(language: str | None) -> str | None:
    """Normalize app locale values to OpenAI Realtime transcription language codes."""
    if not language:
        return None

    normalized = language.strip().lower().replace("_", "-")
    if not normalized:
        return None

    if normalized in OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE_CODES:
        return normalized

    primary_subtag = normalized.split("-", maxsplit=1)[0]
    if primary_subtag in OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE_CODES:
        return primary_subtag

    return None


def build_server_vad_turn_detection(
    *,
    threshold: float | None = None,
    prefix_padding_ms: int = 800,
    silence_duration_ms: int | None = None,
    idle_timeout_ms: int | None = None,
    create_response: bool = True,
    interrupt_response: bool = True,
) -> ServerVADConfig:
    """Build GA server_vad turn detection with app defaults."""
    config: ServerVADConfig = {
        "type": "server_vad",
        "threshold": threshold if threshold is not None else 0.5,
        "prefix_padding_ms": prefix_padding_ms,
        "silence_duration_ms": silence_duration_ms if silence_duration_ms is not None else 700,
        "create_response": create_response,
        "interrupt_response": interrupt_response,
    }
    if idle_timeout_ms is not None:
        config["idle_timeout_ms"] = idle_timeout_ms
    return config


def build_turn_detection_config(
    *,
    mode: str | None = "server_vad",
    threshold: float | None = None,
    silence_duration_ms: int | None = None,
    idle_timeout_ms: int | None = None,
    prefix_padding_ms: int = 800,
) -> TurnDetectionConfig | None:
    """Build a GA turn-detection object from current agent fields."""
    normalized_mode = (mode or "server_vad").strip().lower()
    if normalized_mode in {"none", "disabled", "off", "manual"}:
        return None
    if normalized_mode == "semantic_vad":
        return {
            "type": "semantic_vad",
            "eagerness": "auto",
            "create_response": True,
            "interrupt_response": True,
        }
    return build_server_vad_turn_detection(
        threshold=threshold,
        prefix_padding_ms=prefix_padding_ms,
        silence_duration_ms=silence_duration_ms,
        idle_timeout_ms=idle_timeout_ms,
    )


def build_realtime_audio_config(
    *,
    voice: str | None = None,
    input_audio_format: str | None = DEFAULT_AUDIO_FORMAT,
    output_audio_format: str | None = DEFAULT_AUDIO_FORMAT,
    turn_detection_mode: str | None = "server_vad",
    turn_detection_threshold: float | None = None,
    silence_duration_ms: int | None = None,
    idle_timeout_ms: int | None = None,
    transcription_model: str = DEFAULT_INPUT_TRANSCRIPTION_MODEL,
    language: str | None = None,
    noise_reduction_type: str | None = "near_field",
) -> AudioConfig:
    """Build nested GA Realtime audio config."""
    transcription: dict[str, str] = {"model": transcription_model}
    normalized_language = normalize_transcription_language(language)
    if normalized_language:
        transcription["language"] = normalized_language

    audio_input: AudioInputConfig = {
        "format": normalize_realtime_audio_format(input_audio_format),
        "transcription": transcription,
        "turn_detection": build_turn_detection_config(
            mode=turn_detection_mode,
            threshold=turn_detection_threshold,
            silence_duration_ms=silence_duration_ms,
            idle_timeout_ms=idle_timeout_ms,
        ),
    }
    if noise_reduction_type:
        audio_input["noise_reduction"] = {"type": noise_reduction_type}

    return {
        "input": audio_input,
        "output": {
            "format": normalize_realtime_audio_format(output_audio_format),
            "voice": normalize_openai_voice(voice),
        },
    }


def model_supports_realtime_reasoning(model: str) -> bool:
    """Return whether the model accepts GA Realtime reasoning config."""
    return model in REASONING_REALTIME_MODELS or model.startswith("gpt-realtime-2-")


def _filter_openai_tools(tools: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Return tools compatible with OpenAI Realtime.

    Existing tool builders also expose Grok provider-native tools such as
    ``web_search`` and ``x_search``. OpenAI Realtime should receive only function
    tools from that list until MCP/native web-search support is explicitly wired.
    """
    if not tools:
        return []
    return [dict(tool) for tool in tools if tool.get("type") == "function"]


def build_realtime_session_config(
    *,
    instructions: str,
    voice: str | None = None,
    model: str | None = None,
    input_audio_format: str | None = DEFAULT_AUDIO_FORMAT,
    output_audio_format: str | None = DEFAULT_AUDIO_FORMAT,
    turn_detection_mode: str | None = "server_vad",
    turn_detection_threshold: float | None = None,
    silence_duration_ms: int | None = None,
    idle_timeout_ms: int | None = None,
    language: str | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    tool_choice: str = "auto",
    truncation_retention_ratio: float = 0.8,
    reasoning_effort: str = "low",
) -> RealtimeSessionConfig:
    """Build a GA Realtime session config for OpenAI voice sessions."""
    selected_model = model or settings.openai_realtime_model
    session: RealtimeSessionConfig = {
        "type": "realtime",
        "model": selected_model,
        "instructions": instructions,
        "output_modalities": ["audio"],
        "audio": build_realtime_audio_config(
            voice=voice,
            input_audio_format=input_audio_format,
            output_audio_format=output_audio_format,
            turn_detection_mode=turn_detection_mode,
            turn_detection_threshold=turn_detection_threshold,
            silence_duration_ms=silence_duration_ms,
            idle_timeout_ms=idle_timeout_ms,
            language=language,
        ),
        "truncation": {
            "type": "retention_ratio",
            "retention_ratio": truncation_retention_ratio,
        },
    }

    openai_tools = _filter_openai_tools(tools)
    if openai_tools:
        session["tools"] = openai_tools
        session["tool_choice"] = tool_choice
        if model_supports_realtime_reasoning(selected_model):
            session["parallel_tool_calls"] = True

    if model_supports_realtime_reasoning(selected_model):
        session["reasoning"] = {"effort": reasoning_effort}

    return session


def build_realtime_image_input_item(
    *,
    image_url: str,
    text: str | None = None,
) -> dict[str, Any]:
    """Build a ``conversation.item.create`` event carrying a user image.

    ``gpt-realtime`` and ``gpt-realtime-2`` accept images as ``input_image``
    content parts on a user message, where ``image_url`` is a base64 ``data:``
    URL string. An optional ``text`` is added as a leading ``input_text`` part
    so the model has a caption/question alongside the photo. Validate the data
    URL with ``image_input.validate_image_data_url`` before passing it here.
    """
    content: list[RealtimeUserContentPart] = []
    if text:
        content.append({"type": "input_text", "text": text})
    content.append({"type": "input_image", "image_url": image_url})
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": content,
        },
    }


def build_session_update_event(session: RealtimeSessionConfig) -> dict[str, Any]:
    """Wrap a GA session config in a session.update Realtime event."""
    return {"type": "session.update", "session": session}


def build_response_create_event(
    *,
    instructions: str | None = None,
    output_modalities: Sequence[Literal["audio", "text"]] = ("audio",),
) -> dict[str, Any]:
    """Build a GA response.create event."""
    response: dict[str, Any] = {"output_modalities": list(output_modalities)}
    if instructions:
        response["instructions"] = instructions
    return {"type": "response.create", "response": response}


def build_client_secret_request(
    *,
    session: RealtimeSessionConfig,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Build the body for POST /v1/realtime/client_secrets."""
    seconds = (
        ttl_seconds
        if ttl_seconds is not None
        else settings.openai_realtime_client_secret_ttl_seconds
    )
    return {
        "session": session,
        "expires_after": {
            "anchor": "created_at",
            "seconds": seconds,
        },
    }


def build_legacy_realtime_session_config(
    *,
    instructions: str,
    voice: str | None = None,
    input_audio_format: str = DEFAULT_AUDIO_FORMAT,
    output_audio_format: str = DEFAULT_AUDIO_FORMAT,
    turn_detection_mode: str | None = "server_vad",
    turn_detection_threshold: float | None = None,
    silence_duration_ms: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Build the older flat Realtime shape for legacy-compatible providers only."""
    session: dict[str, Any] = {
        "modalities": ["text", "audio"],
        "instructions": instructions,
        "voice": normalize_openai_voice(voice),
        "input_audio_format": input_audio_format,
        "output_audio_format": output_audio_format,
    }
    turn_detection = build_turn_detection_config(
        mode=turn_detection_mode,
        threshold=turn_detection_threshold,
        silence_duration_ms=silence_duration_ms,
    )
    if turn_detection is not None:
        session["turn_detection"] = turn_detection
    if temperature is not None:
        session["temperature"] = temperature
    return session
