"""Voice prompt builder for consistent prompt engineering.

This module consolidates all prompt construction logic that was previously
duplicated across voice agent implementations. It provides a single source
of truth for:
- Date context injection
- Identity prefix
- Realism cues (Grok)
- Search guidance
- Telephony guidance
- Booking instructions

Usage:
    builder = VoicePromptBuilder(agent, timezone="America/New_York")
    prompt = builder.build_full_prompt(
        base_prompt=agent.system_prompt,
        include_realism=True,
        include_booking=True,
        is_outbound=False,
    )
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.agent import Agent

if TYPE_CHECKING:
    from app.services.ai.ivr_detector import IVRStatus


class VoicePromptBuilder:
    """Builder for voice agent system prompts.

    Consolidates all prompt engineering patterns used across voice agents
    to eliminate duplication and ensure consistency.

    Features:
    - Date context injection for appointment booking accuracy
    - Agent identity prefix for consistent identification
    - Realism cues for Grok voice expressiveness
    - Search tools guidance for web/X search
    - Telephony behavior guidance
    - Cal.com booking instructions

    Attributes:
        agent: Optional Agent model for configuration
        timezone: Timezone for date context (IANA format)
    """

    def __init__(
        self,
        agent: Agent | None = None,
        timezone: str = "America/New_York",
    ) -> None:
        """Initialize prompt builder.

        Args:
            agent: Optional Agent model for configuration
            timezone: Timezone for date context (IANA format)
        """
        self.agent = agent
        self.timezone = timezone
        self._tz = self._get_timezone()

    def _get_timezone(self) -> ZoneInfo:
        """Get ZoneInfo for configured timezone.

        Returns:
            ZoneInfo object, defaulting to America/New_York on error
        """
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("America/New_York")

    def get_date_context(self) -> str:
        """Get date context string for system prompt.

        Critical for appointment booking accuracy - LLMs often have
        outdated training data dates.

        Returns:
            Date context string to prepend to prompts
        """
        now = datetime.now(self._tz)
        today_str = now.strftime("%A, %B %d, %Y")
        today_iso = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%I:%M %p")

        return (
            f"CRITICAL DATE CONTEXT: Today is {today_str} ({today_iso}). "
            f"The current time is {current_time}. "
            f"Your training data may be outdated - ALWAYS use {today_iso} as today's date.\n\n"
        )

    def get_identity_prefix(self) -> str:
        """Get identity prefix for agent name enforcement.

        Returns:
            Identity instruction string, or empty if no agent name
        """
        if not self.agent or not self.agent.name:
            return ""

        agent_name = self.agent.name
        return (
            f"CRITICAL IDENTITY INSTRUCTION: Your name is {agent_name}. "
            f"You MUST always identify yourself as {agent_name}. "
            f"When greeting or introducing yourself, say your name is {agent_name}. "
            "This is non-negotiable.\n\n"
        )

    def get_realism_cues(self) -> str:
        """Get Grok realism enhancement instructions.

        These cues allow the voice to use auditory expressions
        for more natural conversation.

        Returns:
            Realism instructions string
        """
        return """
# Voice Realism Enhancements
You can use these auditory cues naturally in your responses to sound more human:
- [sigh] - Express mild frustration, relief, or thoughtfulness
- [laugh] - React to humor or express friendliness
- [whisper] - For confidential or emphasis moments
- Use these sparingly and naturally - don't overuse them.
"""

    def get_search_guidance(self) -> str:
        """Get search tools guidance based on agent configuration.

        Returns:
            Search tools instructions if any are enabled, empty otherwise
        """
        if not self.agent or not self.agent.enabled_tools:
            return ""

        enabled = self.agent.enabled_tools
        has_web_search = "web_search" in enabled
        has_x_search = "x_search" in enabled

        if not has_web_search and not has_x_search:
            return ""

        parts = ["\n\n# Search Capabilities"]

        if has_web_search:
            parts.append(
                "You have access to real-time web search. "
                "Use it when users ask about current events, prices, news, weather, "
                "facts you're unsure about, or anything that requires up-to-date information. "
                "Search results are integrated automatically - respond naturally."
            )

        if has_x_search:
            parts.append(
                "You have access to X (Twitter) search. "
                "Use it when users ask about trending topics, public opinions, "
                "what people are saying about something, or recent posts. "
                "The search results will help you provide current social context."
            )

        if has_web_search or has_x_search:
            parts.append(
                "Use these search tools proactively when the conversation would benefit "
                "from current information - don't wait to be asked explicitly."
            )

        return "\n".join(parts)

    def get_ivr_navigation_guidance(
        self,
        ivr_status: "IVRStatus | None" = None,
        is_outbound: bool = False,
    ) -> str:
        """Get IVR/automated menu navigation guidance.

        Args:
            ivr_status: Optional IVR status for enhanced guidance
            is_outbound: If True, always return guidance for outbound calls

        Returns:
            IVR navigation instructions string
        """
        # For outbound calls, always include IVR guidance since they commonly hit IVRs
        if not is_outbound:
            if not self.agent or not self.agent.enabled_tools:
                return ""

            enabled = self.agent.enabled_tools
            tool_settings = self.agent.tool_settings or {}
            call_control_tools = tool_settings.get("call_control", []) or []

            # Check if DTMF is enabled
            dtmf_enabled = "send_dtmf" in enabled or (
                "call_control" in enabled and "send_dtmf" in call_control_tools
            )

            if not dtmf_enabled:
                return ""

        # Import DTMFContext for context detection
        from app.services.ai.ivr_detector import DTMFContext

        # Get current context
        context = DTMFContext.MENU
        if ivr_status and hasattr(ivr_status, "menu_state") and ivr_status.menu_state:
            context = ivr_status.menu_state.context

        # Context-specific guidance
        if context == DTMFContext.EXTENSION:
            context_guidance = """EXTENSION entry mode:
- Enter ALL digits together: <dtmf>1234</dtmf>
- System will add # terminator automatically"""
        elif context == DTMFContext.MENU:
            context_guidance = """MENU selection mode:
- Send ONE digit at a time: <dtmf>1</dtmf>
- Do NOT send multiple selections together"""
        elif context == DTMFContext.VOICEMAIL:
            context_guidance = """VOICEMAIL detected:
- Do NOT use <dtmf> tags
- Wait for beep, then speak your message"""
        else:
            context_guidance = ""

        # Add attempt history
        attempt_info = ""
        if ivr_status and hasattr(ivr_status, "menu_state") and ivr_status.menu_state:
            if ivr_status.menu_state.attempted_dtmf:
                tried = ", ".join(sorted(ivr_status.menu_state.attempted_dtmf))
                attempt_info += f"\n✓ Already tried: {tried}"
            if ivr_status.menu_state.failed_dtmf:
                failed = ", ".join(sorted(ivr_status.menu_state.failed_dtmf))
                attempt_info += f"\n✗ These didn't work: {failed}"

        # Tag-based DTMF is the PRIMARY mechanism - works regardless of function calling
        base_guidance = f"""

# IVR/AUTOMATED MENU NAVIGATION - CRITICAL

When you hear an automated phone menu (IVR):

1. RECOGNIZE: "Press 1 for...", "dial extension" = automated machine, NOT human
2. DO NOT SPEAK to machines - they only understand touch-tones
3. TO PRESS A BUTTON: Include <dtmf>X</dtmf> in your response
   - Example: "Selecting sales. <dtmf>2</dtmf>"
   - Example: "Trying option 1. <dtmf>1</dtmf>"
   - Example: "Entering extension. <dtmf>123</dtmf>"
4. WAIT SILENTLY after sending - don't speak until human responds
5. If menu repeats, try a DIFFERENT numbered option (1-9) you haven't tried yet

Format: <dtmf>X</dtmf> where X is digit(s) (0-9, *, #)

WRONG: Hearing "Press 1 for sales" and saying "I'd like to speak to sales please"
RIGHT: Hearing "Press 1 for sales" and responding "Selecting sales. <dtmf>1</dtmf>"

{context_guidance}
{attempt_info}

IMPORTANT: Try numbered options (1-9) systematically before resorting to "0" or "#".
You can also use the send_dtmf tool if available, but <dtmf> tags are preferred."""

        # Add loop warning if applicable
        if ivr_status and ivr_status.loop_detected:
            base_guidance += """

WARNING: IVR LOOP DETECTED - The menu is repeating itself.
ACTION REQUIRED: Try a DIFFERENT numbered option (1-9) that you haven't tried yet.
Only use "0" for operator or "#" to skip as a LAST RESORT after trying other options."""

        return base_guidance

    def get_telephony_guidance(self, is_outbound: bool = False) -> str:
        """Get telephony-specific behavior guidance.

        Args:
            is_outbound: True if this is an outbound call

        Returns:
            Telephony guidance string
        """
        if is_outbound:
            return """

IMPORTANT: You are on a phone call that YOU initiated.
- You called THEM - introduce yourself and explain why you're calling
- Do NOT ask "what would you like to talk about" - YOU know why you called
- Be direct and professional about the purpose of your call
- If you reach an automated menu (IVR), use send_dtmf to navigate - do NOT speak to machines"""
        else:
            return """

IMPORTANT: You are on a phone call. When the call connects:
- Wait briefly for the caller to speak first, OR
- If instructed to greet first, deliver your greeting naturally and wait for response
- Do NOT generate random content, fun facts, or filler - stay focused on your purpose
- Speak clearly and conversationally as if on a real phone call"""

    def get_booking_instructions(self) -> str:
        """Get Cal.com booking instructions with current date context.

        Returns:
            Booking instructions string with embedded date context
        """
        now = datetime.now(self._tz)
        today_str = now.strftime("%A, %B %d, %Y")
        today_iso = now.strftime("%Y-%m-%d")

        return f"""

[APPOINTMENT BOOKING - CRITICAL DATE AND RULES]
TODAY IS {today_str} ({today_iso}).
Your training data may be outdated - IGNORE IT. The ACTUAL current date is {today_iso}.

When converting relative dates to YYYY-MM-DD format:
- "today" = {today_iso}
- "tomorrow" = the day after {today_iso}
- "Friday" = the NEXT Friday from {today_iso} (calculate it)
- "next week" = the week starting after {today_iso}
- "Monday" = the NEXT Monday from {today_iso}

You have tools to check calendar availability and book appointments. Follow these rules:

1. NEVER say "one moment", "let me check", "checking", or "I'll get back to you"
2. NEVER promise to do something without IMMEDIATELY calling the function
3. When the customer asks about times, call check_availability RIGHT NOW
4. When the customer picks a time, call book_appointment RIGHT NOW
5. EMAIL IS REQUIRED for booking - ask for it when offering time slots

WHEN TO CALL check_availability:
- Customer asks about availability ("when are you free", "what times work")
- Customer mentions a day ("Monday", "tomorrow", "next week", "Friday")
- Customer wants to schedule or book something
- ALWAYS use dates relative to {today_iso}, NOT your training data dates

WHEN TO CALL book_appointment:
- Customer confirms a specific time AND you have their email

RESPONSE PATTERN:
- If they ask about times: Call check_availability, then offer 2 specific options
- If they pick a time and you have email: Call book_appointment immediately
- If they pick a time but no email: Ask for email, then book once provided

DO NOT say things like "I'll check and get back to you" - you can check instantly!

TIME FORMAT RULES:
- ALWAYS speak times in 12-hour AM/PM format (e.g., "2 PM", "10:30 AM")
- NEVER say times in military/24-hour format (do NOT say "fourteen hundred" or "1500")
- The tool results include display_time in 12-hour format - use those when speaking
- The book_appointment tool still accepts HH:MM 24-hour format for the time parameter

AVAILABILITY ACCURACY RULES:
- ONLY offer times from check_availability. NEVER make up or guess times.
- If booking fails, use alternative_slots from the error. Do NOT re-state failed time.
- When booking fails, say "That time is no longer available" and offer alternatives.
- If no alternatives are provided, ask the customer to check a different day.
- NEVER offer a time that was not explicitly returned by a tool."""

    def build_context_section(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> str:
        """Build call context section for system prompt.

        Args:
            contact_info: Contact information dict
            offer_info: Offer/product information dict
            is_outbound: True if this is an outbound call

        Returns:
            Context section string
        """
        if not contact_info and not offer_info:
            return ""

        parts = []
        parts.extend(self._build_call_direction_header(is_outbound))

        if contact_info:
            parts.extend(self._build_contact_section(contact_info, is_outbound))

        if offer_info:
            parts.extend(self._build_offer_section(offer_info, is_outbound))

        return "\n".join(parts)

    def _build_call_direction_header(self, is_outbound: bool) -> list[str]:
        """Build header section based on call direction."""
        if is_outbound:
            return [
                "\n\n# CURRENT CALL CONTEXT - THIS IS AN OUTBOUND CALL YOU ARE MAKING",
                "You initiated this call. You know exactly why you're calling. "
                "Do NOT ask the customer what they want to talk about.",
            ]
        return [
            "\n\n# CURRENT CALL CONTEXT - THIS IS AN INBOUND CALL",
            "The customer called you. Listen to what they need and assist them.",
        ]

    def _build_contact_section(self, contact_info: dict[str, Any], is_outbound: bool) -> list[str]:
        """Build contact information section."""
        header = "\n## Customer You Are Calling:" if is_outbound else "\n## Customer Information:"
        parts = [header]
        if contact_info.get("name"):
            parts.append(f"- Name: {contact_info['name']}")
        if contact_info.get("company"):
            parts.append(f"- Company: {contact_info['company']}")
        if contact_info.get("notes"):
            notes = contact_info["notes"]
            parts.append(
                f"\n### Lead Intake Notes (use this to personalize the conversation):\n{notes}"
            )
        return parts

    def _build_offer_section(self, offer_info: dict[str, Any], is_outbound: bool) -> list[str]:
        """Build offer information section."""
        header = "\n## What You Are Calling About:" if is_outbound else "\n## Offer Information:"
        parts = [header]
        if offer_info.get("name"):
            parts.append(f"- Offer: {offer_info['name']}")
        if offer_info.get("description"):
            parts.append(f"- Details: {offer_info['description']}")
        if offer_info.get("terms"):
            parts.append(f"- Terms: {offer_info['terms']}")
        return parts

    def build_full_prompt(
        self,
        base_prompt: str | None = None,
        *,
        include_date_context: bool = True,
        include_identity: bool = True,
        include_realism: bool = False,
        include_search: bool = True,
        include_telephony: bool = True,
        include_booking: bool = False,
        include_ivr_guidance: bool = True,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> str:
        """Build complete system prompt with all enhancements.

        Args:
            base_prompt: Base system prompt (defaults to agent.system_prompt)
            include_date_context: Include date context section
            include_identity: Include identity prefix
            include_realism: Include realism cues (Grok only)
            include_search: Include search guidance
            include_telephony: Include telephony guidance
            include_booking: Include booking instructions
            include_ivr_guidance: Include IVR/DTMF navigation guidance
            contact_info: Contact information for context
            offer_info: Offer information for context
            is_outbound: True if outbound call

        Returns:
            Complete enhanced system prompt
        """
        # Get base prompt
        if base_prompt is None:
            base_prompt = (
                self.agent.system_prompt if self.agent else "You are a helpful AI voice assistant."
            )

        parts = []

        # 1. Date context (FIRST - critical for booking)
        if include_date_context:
            parts.append(self.get_date_context())

        # 2. Identity prefix
        if include_identity:
            parts.append(self.get_identity_prefix())

        # 3. Base prompt
        parts.append(base_prompt)

        # 4. Call context
        context = self.build_context_section(contact_info, offer_info, is_outbound)
        if context:
            parts.append(context)

        # 5. Realism cues (Grok)
        if include_realism:
            parts.append(self.get_realism_cues())

        # 6. Search guidance
        if include_search:
            parts.append(self.get_search_guidance())

        # 7. IVR/DTMF navigation guidance (before booking, critical for outbound)
        if include_ivr_guidance:
            parts.append(self.get_ivr_navigation_guidance(is_outbound=is_outbound))

        # 8. Booking instructions
        if include_booking:
            parts.append(self.get_booking_instructions())

        # 9. Telephony guidance (last)
        if include_telephony:
            parts.append(self.get_telephony_guidance(is_outbound))

        return "".join(parts)

    def get_outbound_opener_prompt(self) -> str:
        """Get the opener prompt for outbound calls.

        If the agent's system prompt contains an 'Opening the Call' section,
        the AI is instructed to follow those custom opener instructions.
        Otherwise, falls back to a generic pattern interrupt opener.

        Returns:
            Prompt text for triggering outbound call opener
        """
        # Extract just the first name
        full_name = self.agent.name if self.agent else "Alex"
        agent_name = full_name.split("|")[0].split("-")[0].strip().split()[0]

        # Check if system prompt has custom opener instructions
        system_prompt = (self.agent.system_prompt if self.agent else "") or ""
        if "Opening the Call" in system_prompt:
            return (
                "You just called someone and they answered. "
                "Follow your 'Opening the Call' instructions from your system prompt. "
                "Reference the lead intake notes to personalize your opener. "
                "Keep it natural and conversational. Wait for their response."
            )

        return (
            f"You just called someone. Open with a pattern interrupt. "
            f"Say: 'Hey! It's {agent_name}. This is a sales call. "
            f"Do you wanna hang up... or can I tell you why I'm calling?!' "
            f"Start friendly and upbeat. Sound a bit disappointed on 'hang up'. "
            f"Then get excited on 'or can I tell you why I'm calling?!' "
            f"Wait for their response."
        )

    def get_inbound_greeting_prompt(self, greeting: str | None = None) -> str:
        """Get the greeting prompt for inbound calls.

        Args:
            greeting: Optional specific greeting text

        Returns:
            Prompt text for triggering inbound greeting
        """
        if greeting:
            return f"Greet the caller by saying: {greeting}"

        # Build default greeting prompt
        parts = []

        if self.agent and self.agent.name:
            parts.append(f"You are {self.agent.name}.")

        parts.append(
            "Greet the caller and introduce yourself. Follow your "
            "system instructions for the purpose of this call."
        )

        return " ".join(parts)

    def get_ivr_mode_prompt(
        self,
        goal: str | None = None,
        loop_detected: bool = False,
    ) -> str:
        """Get full IVR navigation mode prompt.

        This prompt is used when the agent detects it's navigating an IVR
        system and needs specialized navigation instructions.

        Args:
            goal: Navigation goal (e.g., "reach sales department")
            loop_detected: Whether an IVR loop has been detected

        Returns:
            Complete IVR navigation prompt
        """
        parts = []

        parts.append("# IVR NAVIGATION MODE ACTIVE")
        parts.append("")
        parts.append(
            "You are navigating an automated phone menu (IVR system). Follow these critical rules:"
        )
        parts.append("")

        # Rules section
        parts.append("## RULES")
        parts.append(
            "1. DO NOT speak conversationally - IVR systems only understand button presses"
        )
        parts.append("2. Listen to ALL menu options before selecting")
        parts.append("3. Select the option that best matches your goal")
        parts.append("4. Use <dtmf>X</dtmf> tags OR the send_dtmf tool to press buttons")
        parts.append("")

        # How to respond
        parts.append("## HOW TO RESPOND")
        parts.append("When you hear menu options, respond with:")
        parts.append("1. A brief acknowledgment of what you heard")
        parts.append("2. Your selection using DTMF")
        parts.append("")
        parts.append(
            'Example: "I heard the menu. Pressing 1 for sales." then call send_dtmf(digits="1")'
        )
        parts.append("")

        # Navigation tips
        parts.append("## NAVIGATION TIPS")
        parts.append("- Try each numbered menu option (1-9) that might match your goal")
        parts.append('- If options 1-9 don\'t work, then try "0" (operator) or "#" (skip)')
        parts.append('- "9" sometimes repeats the menu')
        parts.append('- "*" sometimes goes back to the previous menu')
        parts.append("")

        # Goal
        goal_text = goal or "Navigate to the appropriate department or reach a human operator"
        parts.append("## YOUR GOAL")
        parts.append(goal_text)
        parts.append("")

        # Loop warning
        if loop_detected:
            parts.append("## WARNING: LOOP DETECTED")
            parts.append("The menu is repeating. The system may not have received your input.")
            parts.append(
                "ACTION: Try a DIFFERENT numbered option (1-9) that you haven't tried yet."
            )
            parts.append("Only use '0' for operator or '#' to skip as a LAST RESORT.")
            parts.append("")

        parts.append(
            "Remember: IVR systems CANNOT understand speech - "
            "you MUST use DTMF tones via send_dtmf or <dtmf></dtmf> tags."
        )

        return "\n".join(parts)
