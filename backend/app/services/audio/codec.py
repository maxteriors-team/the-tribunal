"""Audio codec service for voice communications.

This module provides audio format conversion functions for the voice bridge,
handling conversion between Telnyx (PSTN) and AI voice provider formats.

Audio Formats:
    - Telnyx: mu-law (G.711) at 8kHz sample rate
    - OpenAI Realtime: g711_ulaw at 8kHz (same as Telnyx - no conversion!)
    - Grok Realtime: PCM16 at 24kHz
    - ElevenLabs TTS: ulaw_8000 (same as Telnyx - no conversion!)

Conversion Pipelines:
    Telnyx -> Grok: mulaw 8kHz -> PCM16 8kHz -> PCM16 24kHz
    Grok -> Telnyx: PCM16 24kHz -> PCM16 8kHz -> mulaw 8kHz
"""

from collections.abc import Callable
from enum import Enum
from typing import Any

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop  # type: ignore[no-redef]

import numpy as np
import soxr
import structlog

from app.services.ai.exceptions import AudioConversionError

logger = structlog.get_logger()

# Audio format constants
TELNYX_SAMPLE_RATE = 8000  # 8kHz for PSTN/Telnyx (mu-law/G.711)
OPENAI_SAMPLE_RATE = 24000  # 24kHz for Grok Realtime API

# Telnyx requires audio chunks to be 20ms-30s in duration
# At 8kHz with 1 byte per sample (mu-law), 20ms = 160 bytes
TELNYX_MIN_CHUNK_BYTES = 160  # 20ms at 8kHz mu-law


class AudioFormat(Enum):
    """Audio format enumeration for voice communications.

    Each format specifies the encoding and sample rate used by
    different voice providers.
    """

    MULAW_8K = "mulaw_8k"  # Telnyx PSTN, OpenAI g711_ulaw
    PCM16_8K = "pcm16_8k"  # Intermediate format
    PCM16_24K = "pcm16_24k"  # Grok Realtime API
    G711_ULAW = "g711_ulaw"  # OpenAI Realtime native (same as MULAW_8K)

    @property
    def sample_rate(self) -> int:
        """Get the sample rate for this format."""
        if self in (AudioFormat.MULAW_8K, AudioFormat.PCM16_8K, AudioFormat.G711_ULAW):
            return 8000
        return 24000

    @property
    def is_mulaw(self) -> bool:
        """Check if this format uses mu-law encoding."""
        return self in (AudioFormat.MULAW_8K, AudioFormat.G711_ULAW)


def mulaw_to_pcm(data: bytes) -> bytes:
    """Convert mu-law audio to PCM16.

    Uses Python's audioop module for conversion.

    Args:
        data: mu-law encoded audio bytes (8kHz)

    Returns:
        PCM16 audio bytes (little-endian, 8kHz)

    Raises:
        AudioConversionError: If conversion fails
    """
    if not data:
        return b""

    try:
        # audioop.ulaw2lin converts mu-law to linear PCM
        # 2 = sample width in bytes (16-bit)
        return audioop.ulaw2lin(data, 2)
    except audioop.error as e:
        raise AudioConversionError(
            f"Failed to convert mu-law to PCM: {e}",
            source_format="mulaw_8k",
            target_format="pcm16_8k",
        ) from e


def pcm_to_mulaw(data: bytes) -> bytes:
    """Convert PCM16 audio to mu-law.

    Uses Python's audioop module for conversion.

    Args:
        data: PCM16 audio bytes (little-endian)

    Returns:
        mu-law encoded audio bytes

    Raises:
        AudioConversionError: If conversion fails
    """
    if not data:
        return b""

    try:
        # audioop.lin2ulaw converts linear PCM to mu-law
        # 2 = sample width in bytes (16-bit)
        return audioop.lin2ulaw(data, 2)
    except audioop.error as e:
        raise AudioConversionError(
            f"Failed to convert PCM to mu-law: {e}",
            source_format="pcm16_8k",
            target_format="mulaw_8k",
        ) from e


def upsample_8k_to_24k(data: bytes) -> bytes:
    """Upsample PCM16 audio from 8kHz to 24kHz.

    Uses soxr (libsoxr) for high-quality polyphase anti-aliased resampling.

    Args:
        data: PCM16 audio bytes at 8kHz

    Returns:
        PCM16 audio bytes at 24kHz (3x samples)

    Raises:
        AudioConversionError: If resampling fails
    """
    if len(data) < 2:
        return data

    try:
        samples = np.frombuffer(data, dtype=np.int16)
        resampled: np.ndarray[Any, np.dtype[np.int16]] = soxr.resample(
            samples, TELNYX_SAMPLE_RATE, OPENAI_SAMPLE_RATE, quality="HQ"
        )
        result: bytes = resampled.astype(np.int16).tobytes()
        return result
    except (ValueError, TypeError) as e:
        raise AudioConversionError(
            f"Failed to upsample 8kHz to 24kHz: {e}",
            source_format="pcm16_8k",
            target_format="pcm16_24k",
        ) from e


def downsample_24k_to_8k(data: bytes) -> bytes:
    """Downsample PCM16 audio from 24kHz to 8kHz.

    Uses soxr (libsoxr) for high-quality polyphase anti-aliased resampling.

    Args:
        data: PCM16 audio bytes at 24kHz

    Returns:
        PCM16 audio bytes at 8kHz (1/3x samples)

    Raises:
        AudioConversionError: If resampling fails
    """
    if len(data) < 2:
        return data

    try:
        samples = np.frombuffer(data, dtype=np.int16)
        resampled: np.ndarray[Any, np.dtype[np.int16]] = soxr.resample(
            samples, OPENAI_SAMPLE_RATE, TELNYX_SAMPLE_RATE, quality="HQ"
        )
        result: bytes = resampled.astype(np.int16).tobytes()
        return result
    except (ValueError, TypeError) as e:
        raise AudioConversionError(
            f"Failed to downsample 24kHz to 8kHz: {e}",
            source_format="pcm16_24k",
            target_format="pcm16_8k",
        ) from e


def convert_telnyx_to_openai(mulaw_8k: bytes, log: Any = None) -> bytes:
    """Convert Telnyx mu-law 8kHz audio to Grok PCM16 24kHz.

    Pipeline: mu-law 8kHz -> PCM16 8kHz -> PCM16 24kHz

    Note: This is only needed for Grok. OpenAI uses g711_ulaw which
    matches Telnyx format directly (no conversion needed).

    Args:
        mulaw_8k: mu-law encoded audio at 8kHz from Telnyx
        log: Optional logger instance (for compatibility)

    Returns:
        PCM16 audio at 24kHz for Grok Realtime API

    Raises:
        AudioConversionError: If any conversion step fails
    """
    # Step 1: mu-law to PCM16 (still at 8kHz)
    pcm_8k = mulaw_to_pcm(mulaw_8k)

    # Step 2: Upsample 8kHz to 24kHz (3x)
    pcm_24k = upsample_8k_to_24k(pcm_8k)

    return pcm_24k


def convert_openai_to_telnyx(pcm_24k: bytes, log: Any = None) -> bytes:
    """Convert Grok PCM16 24kHz audio to Telnyx mu-law 8kHz.

    Pipeline: PCM16 24kHz -> PCM16 8kHz -> mu-law 8kHz

    Note: This is only needed for Grok. OpenAI and ElevenLabs
    output formats that match Telnyx directly (no conversion).

    Args:
        pcm_24k: PCM16 audio at 24kHz from Grok Realtime API
        log: Optional logger instance (for compatibility)

    Returns:
        mu-law encoded audio at 8kHz for Telnyx

    Raises:
        AudioConversionError: If any conversion step fails
    """
    # Step 1: Downsample 24kHz to 8kHz (3x)
    pcm_8k = downsample_24k_to_8k(pcm_24k)

    # Step 2: PCM16 to mu-law
    mulaw_8k = pcm_to_mulaw(pcm_8k)

    return mulaw_8k


class AudioCodecService:
    """Service for audio format conversion between voice providers.

    This class provides a unified interface for audio conversion,
    handling the complexity of different provider formats internally.

    Attributes:
        logger: Structured logger for debugging audio conversion
    """

    def __init__(self) -> None:
        """Initialize audio codec service."""
        self.logger = logger.bind(service="audio_codec")

    # Conversion dispatch table: (source, target) -> converter function
    _CONVERTERS: dict[tuple[AudioFormat, AudioFormat], Callable[[bytes], bytes]] = {
        (AudioFormat.MULAW_8K, AudioFormat.PCM16_24K): convert_telnyx_to_openai,
        (AudioFormat.PCM16_24K, AudioFormat.MULAW_8K): convert_openai_to_telnyx,
        (AudioFormat.MULAW_8K, AudioFormat.PCM16_8K): mulaw_to_pcm,
        (AudioFormat.PCM16_8K, AudioFormat.MULAW_8K): pcm_to_mulaw,
        (AudioFormat.PCM16_8K, AudioFormat.PCM16_24K): upsample_8k_to_24k,
        (AudioFormat.PCM16_24K, AudioFormat.PCM16_8K): downsample_24k_to_8k,
    }

    def convert_for_provider(
        self,
        audio_data: bytes,
        source_format: AudioFormat,
        target_format: AudioFormat,
    ) -> bytes:
        """Convert audio between formats.

        Args:
            audio_data: Input audio bytes
            source_format: Source audio format
            target_format: Target audio format

        Returns:
            Converted audio bytes

        Raises:
            AudioConversionError: If conversion fails or path not supported
        """
        if source_format == target_format:
            return audio_data

        converter = self._CONVERTERS.get((source_format, target_format))
        if converter:
            return converter(audio_data)

        raise AudioConversionError(
            f"Unsupported conversion path: {source_format.value} -> {target_format.value}",
            source_format=source_format.value,
            target_format=target_format.value,
        )

    def needs_conversion(
        self,
        provider: str,
        direction: str,
    ) -> bool:
        """Check if audio conversion is needed for a provider.

        Args:
            provider: Voice provider name (openai, grok, elevenlabs)
            direction: Audio direction (inbound, outbound)

        Returns:
            True if conversion is needed, False if formats match
        """
        # OpenAI uses g711_ulaw which matches Telnyx - no conversion
        if provider == "openai":
            return False

        # ElevenLabs outputs ulaw_8000 which matches Telnyx - no conversion
        if provider == "elevenlabs" and direction == "outbound":
            return False

        # Grok uses PCM16 24kHz - conversion always needed
        if provider == "grok":
            return True

        # ElevenLabs inbound goes to Grok STT - conversion needed
        return provider == "elevenlabs" and direction == "inbound"
