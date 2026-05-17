"""IVR mode controller for Grok voice agent.

This module handles IVR mode switching with Grok-specific behavior,
including turn detection adjustments for IVR menus, voicemail systems,
and normal conversation mode.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from app.services.ai.grok.constants import (
    IVR_TURN_DETECTION,
    VOICEMAIL_TURN_DETECTION,
)

if TYPE_CHECKING:
    from app.services.ai.ivr_detector import IVRDetector, IVRMode

logger = structlog.get_logger()


@dataclass
class IVRModeConfig:
    """Configuration for IVR mode behavior.

    Attributes:
        default_silence_ms: Default silence duration for conversation mode
        default_threshold: Default VAD threshold for conversation mode
        ivr_silence_duration_ms: Silence duration for IVR mode (wait for complete menus)
        post_dtmf_cooldown_ms: Cooldown after DTMF before responding
        menu_buffer_silence_ms: Buffer silence to accumulate transcript
    """

    default_silence_ms: int = 700
    default_threshold: float = 0.5
    # IVR-specific timing (can be overridden by agent config)
    ivr_silence_duration_ms: int = 3000
    post_dtmf_cooldown_ms: int = 3000
    menu_buffer_silence_ms: int = 2000


class IVRModeController:
    """Controls IVR mode switching with Grok-specific behavior.

    This controller manages transitions between:
    - CONVERSATION mode (normal human conversation)
    - IVR mode (automated phone menu navigation)
    - VOICEMAIL mode (voicemail handling)

    Each mode has different turn detection settings optimized for that context.

    Usage:
        controller = IVRModeController(
            configure_session=session.configure_session,
            inject_ivr_context=session._inject_ivr_context,
            config=IVRModeConfig(),
        )

        # Handle mode switch
        await controller.handle_mode_switch(old_mode, new_mode)
    """

    def __init__(
        self,
        configure_session: Callable[..., Any],
        inject_ivr_context: Callable[[str], Any] | None = None,
        config: IVRModeConfig | None = None,
        agent_silence_ms: int | None = None,
        agent_threshold: float | None = None,
        ivr_detector: "IVRDetector | None" = None,
        navigation_goal: str | None = None,
    ) -> None:
        """Initialize the IVR mode controller.

        Args:
            configure_session: Async callback to configure session settings
            inject_ivr_context: Optional callback to inject IVR navigation context
            config: Configuration for mode behavior
            agent_silence_ms: Agent's configured silence duration
            agent_threshold: Agent's configured VAD threshold
            ivr_detector: IVR detector instance for navigation prompts
            navigation_goal: Goal for IVR navigation
        """
        self._configure_session = configure_session
        self._inject_ivr_context = inject_ivr_context
        self._config = config or IVRModeConfig()
        self._ivr_detector = ivr_detector
        self._navigation_goal = navigation_goal
        self._logger = logger.bind(service="ivr_mode_controller")

        # Use agent settings if provided, otherwise use defaults
        self._default_silence_ms = agent_silence_ms or self._config.default_silence_ms
        self._default_threshold = agent_threshold or self._config.default_threshold

    def set_ivr_detector(
        self,
        detector: "IVRDetector | None",
        navigation_goal: str | None = None,
    ) -> None:
        """Update the IVR detector reference.

        Args:
            detector: IVR detector instance
            navigation_goal: Goal for IVR navigation
        """
        self._ivr_detector = detector
        self._navigation_goal = navigation_goal

    async def handle_mode_switch(
        self,
        old_mode: "IVRMode",
        new_mode: "IVRMode",
    ) -> None:
        """Handle IVR mode switching with Grok-specific behavior.

        Args:
            old_mode: Previous IVR mode
            new_mode: New IVR mode
        """
        from app.services.ai.ivr_detector import IVRMode

        self._logger.info(
            "ivr_mode_switch",
            old_mode=old_mode.value,
            new_mode=new_mode.value,
        )

        if new_mode == IVRMode.IVR:
            await self._switch_to_ivr_mode()
        elif new_mode == IVRMode.CONVERSATION:
            await self._switch_to_conversation_mode()
        elif new_mode == IVRMode.VOICEMAIL:
            await self._switch_to_voicemail_mode()

    async def _switch_to_ivr_mode(self) -> None:
        """Switch to IVR navigation mode.

        Adjusts turn detection for IVR menus which often have longer pauses.
        Uses agent-configured silence duration if available.
        """
        self._logger.info("switching_to_ivr_mode")

        # Use agent-configured silence duration, falling back to constants
        silence_ms = self._config.ivr_silence_duration_ms
        threshold = IVR_TURN_DETECTION["turn_detection_threshold"]

        self._logger.info(
            "ivr_mode_timing",
            silence_duration_ms=silence_ms,
            turn_detection_threshold=threshold,
        )

        # Increase silence duration for IVR menus
        # IVR systems have longer pauses between options
        await self._configure_session(
            silence_duration_ms=silence_ms,
            turn_detection_threshold=threshold,
        )

        # Update prompt to include IVR navigation guidance
        if self._ivr_detector and self._navigation_goal and self._inject_ivr_context:
            ivr_prompt = self._ivr_detector.get_ivr_navigation_prompt(self._navigation_goal)
            await self._inject_ivr_context(ivr_prompt)

    async def _switch_to_conversation_mode(self) -> None:
        """Switch back to normal conversation mode.

        Restores normal turn detection settings.
        """
        self._logger.info("switching_to_conversation_mode")

        await self._configure_session(
            silence_duration_ms=self._default_silence_ms,
            turn_detection_threshold=self._default_threshold,
        )

    async def _switch_to_voicemail_mode(self) -> None:
        """Switch to voicemail handling mode.

        Similar to IVR mode but with voicemail-specific settings.
        Voicemail systems often have beeps and long pauses.
        """
        self._logger.info("switching_to_voicemail_mode")

        await self._configure_session(
            silence_duration_ms=VOICEMAIL_TURN_DETECTION["silence_duration_ms"],
            turn_detection_threshold=VOICEMAIL_TURN_DETECTION["turn_detection_threshold"],
        )

    async def restore_defaults(self) -> None:
        """Restore default turn detection settings.

        Convenience method to reset to conversation mode settings.
        """
        await self._switch_to_conversation_mode()
