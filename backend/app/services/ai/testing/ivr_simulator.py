"""IVR Simulator for testing AI agents' phone menu navigation.

Adapted from pipecat-ai/pipecat (BSD-2-Clause License).

This module provides a simulator that mimics IVR (Interactive Voice Response)
phone systems for testing purposes. It allows:
- Defining IVR menus with multiple options
- Navigating through menus using DTMF digits
- Testing loop detection and timeout behavior
- Validating expected navigation paths

Example usage:
    scenario = IVRScenario(
        name="simple_menu",
        initial_state="main_menu",
        states={
            "main_menu": IVRState(
                id="main_menu",
                transcript="Press 1 for sales, press 2 for support.",
                options=[
                    IVRMenuOption(digit="1", description="Sales", next_state="sales"),
                    IVRMenuOption(digit="2", description="Support", next_state="support"),
                ],
            ),
            "sales": IVRState(
                id="sales",
                transcript="Connecting to sales.",
                is_terminal=True,
                state_type="operator",
            ),
        }
    )

    simulator = IVRSimulator(scenario)
    print(simulator.get_current_transcript())  # "Press 1 for sales..."
    simulator.send_dtmf("1")  # Navigate to sales
    print(simulator.is_terminal())  # True
"""

from dataclasses import dataclass, field
from enum import Enum

import structlog

logger = structlog.get_logger()


class IVRStateType(Enum):
    """Type of IVR state."""

    MENU = "menu"  # Interactive menu with options
    VOICEMAIL = "voicemail"  # Voicemail recording state
    OPERATOR = "operator"  # Connected to human operator
    QUEUE = "queue"  # Hold queue waiting for operator
    INFO = "info"  # Information playback (no interaction)


@dataclass
class IVRMenuOption:
    """A single option in an IVR menu.

    Attributes:
        digit: The DTMF digit that selects this option (0-9, *, #)
        description: Human-readable description of the option
        next_state: The state ID to transition to when selected
    """

    digit: str
    description: str
    next_state: str


@dataclass
class IVRState:
    """A state in the IVR state machine.

    Attributes:
        id: Unique identifier for this state
        transcript: The text that the IVR speaks in this state
        options: List of menu options (empty for terminal states)
        is_terminal: Whether this state ends the IVR navigation
        state_type: Type of state (menu, voicemail, operator, etc.)
        timeout_action: State to transition to on timeout (default: repeat)
        invalid_action: State to transition to on invalid input (default: repeat)
        max_repeats: Maximum times to repeat before escalating (0 = unlimited)
    """

    id: str
    transcript: str
    options: list[IVRMenuOption] = field(default_factory=list)
    is_terminal: bool = False
    state_type: str = "menu"
    timeout_action: str | None = None
    invalid_action: str | None = None
    max_repeats: int = 0


@dataclass
class IVRScenario:
    """A complete IVR scenario with multiple states.

    Attributes:
        name: Human-readable name for the scenario
        initial_state: ID of the starting state
        states: Dictionary mapping state IDs to IVRState objects
        expected_path: Optional expected navigation path for testing
        description: Optional description of the scenario
    """

    name: str
    initial_state: str
    states: dict[str, IVRState]
    expected_path: list[str] | None = None
    description: str | None = None


class IVRSimulator:
    """Simulates an IVR phone system for testing.

    The simulator maintains state and allows navigation through
    DTMF digit input. It tracks the navigation path and can
    detect loops and timeout conditions.

    Attributes:
        scenario: The IVR scenario being simulated
        current_state_id: ID of the current state
        navigation_path: List of state IDs visited
        repeat_count: Number of times current state has repeated
    """

    def __init__(self, scenario: IVRScenario) -> None:
        """Initialize the simulator with a scenario.

        Args:
            scenario: The IVR scenario to simulate

        Raises:
            ValueError: If initial state doesn't exist in scenario
        """
        if scenario.initial_state not in scenario.states:
            msg = f"Initial state '{scenario.initial_state}' not found in scenario"
            raise ValueError(msg)

        self.scenario = scenario
        self.current_state_id = scenario.initial_state
        self.navigation_path: list[str] = [scenario.initial_state]
        self.repeat_count = 0
        self.logger = logger.bind(
            service="ivr_simulator",
            scenario=scenario.name,
        )
        self.logger.info("ivr_simulator_initialized", initial_state=scenario.initial_state)

    @property
    def current_state(self) -> IVRState:
        """Get the current IVR state."""
        return self.scenario.states[self.current_state_id]

    def get_current_transcript(self) -> str:
        """Get the transcript for the current state.

        Returns:
            The text that the IVR would speak
        """
        return self.current_state.transcript

    def get_available_options(self) -> list[IVRMenuOption]:
        """Get the menu options for the current state.

        Returns:
            List of available menu options (empty for terminal states)
        """
        return self.current_state.options

    def send_dtmf(self, digits: str) -> tuple[bool, str]:
        """Send DTMF digits to navigate the IVR.

        Args:
            digits: The DTMF digit(s) to send (e.g., "1", "2", "*")

        Returns:
            Tuple of (success, response_transcript)
            - success: True if navigation occurred, False if invalid
            - response_transcript: The transcript of the new state
        """
        state = self.current_state

        # Check if terminal state
        if state.is_terminal:
            self.logger.warning(
                "dtmf_in_terminal_state",
                state=self.current_state_id,
                digits=digits,
            )
            return False, state.transcript

        # Find matching option
        for option in state.options:
            if option.digit == digits:
                return self._transition_to(option.next_state, digits)

        # Invalid input - handle based on configuration
        self.logger.info(
            "invalid_dtmf_input",
            state=self.current_state_id,
            digits=digits,
            valid_options=[o.digit for o in state.options],
        )

        if state.invalid_action and state.invalid_action in self.scenario.states:
            return self._transition_to(state.invalid_action, digits)

        # Default: stay in current state
        self.repeat_count += 1
        return False, state.transcript

    def _transition_to(self, state_id: str, reason: str) -> tuple[bool, str]:
        """Transition to a new state.

        Args:
            state_id: The state ID to transition to
            reason: The reason for transition (digit pressed, timeout, etc.)

        Returns:
            Tuple of (success, new_transcript)
        """
        if state_id not in self.scenario.states:
            self.logger.error(
                "invalid_state_transition",
                from_state=self.current_state_id,
                to_state=state_id,
                reason=reason,
            )
            return False, self.current_state.transcript

        old_state = self.current_state_id
        self.current_state_id = state_id
        self.navigation_path.append(state_id)
        self.repeat_count = 0

        self.logger.info(
            "state_transition",
            from_state=old_state,
            to_state=state_id,
            reason=reason,
        )

        return True, self.current_state.transcript

    def simulate_timeout(self) -> str:
        """Simulate a timeout (no input received).

        Returns:
            The transcript after timeout handling
        """
        state = self.current_state

        # Check if terminal state
        if state.is_terminal:
            return state.transcript

        self.repeat_count += 1

        # Check max repeats - escalate if timeout_action defined
        timeout_action = state.timeout_action
        max_reached = state.max_repeats > 0 and self.repeat_count >= state.max_repeats
        has_timeout = timeout_action is not None and timeout_action in self.scenario.states
        if max_reached and has_timeout and timeout_action:
            self._transition_to(timeout_action, "max_repeats_exceeded")
            return self.current_state.transcript

        # Handle timeout action - transition if different from current
        if has_timeout and timeout_action and timeout_action != self.current_state_id:
            self._transition_to(timeout_action, "timeout")
            return self.current_state.transcript

        self.logger.info(
            "timeout_repeat",
            state=self.current_state_id,
            repeat_count=self.repeat_count,
        )

        # Default: repeat current state
        return state.transcript

    def is_terminal(self) -> bool:
        """Check if current state is terminal.

        Returns:
            True if in a terminal state (voicemail, operator, etc.)
        """
        return self.current_state.is_terminal

    def get_state_type(self) -> str:
        """Get the type of the current state.

        Returns:
            State type string (menu, voicemail, operator, queue, info)
        """
        return self.current_state.state_type

    def get_navigation_path(self) -> list[str]:
        """Get the path of states visited.

        Returns:
            List of state IDs in order of visitation
        """
        return self.navigation_path.copy()

    def is_in_loop(self, threshold: int = 2) -> bool:
        """Check if navigation is stuck in a loop.

        Args:
            threshold: Number of repeats to consider a loop

        Returns:
            True if the same state has repeated threshold times
        """
        if len(self.navigation_path) < threshold + 1:
            return False

        # Check if last N states are the same
        recent = self.navigation_path[-threshold:]
        return len(set(recent)) == 1 and self.repeat_count >= threshold - 1

    def validate_expected_path(self) -> bool:
        """Check if navigation followed the expected path.

        Returns:
            True if navigation matches expected path, False otherwise.
            Returns True if no expected path was defined.
        """
        if self.scenario.expected_path is None:
            return True

        return self.navigation_path == self.scenario.expected_path

    def reset(self) -> None:
        """Reset the simulator to initial state."""
        self.current_state_id = self.scenario.initial_state
        self.navigation_path = [self.scenario.initial_state]
        self.repeat_count = 0
        self.logger.info("simulator_reset")
