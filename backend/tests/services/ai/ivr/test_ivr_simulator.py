"""Tests for IVRSimulator.

Integration tests that verify:
- Basic navigation through IVR menus
- Nested menu navigation
- Voicemail option handling
- Loop detection in stuck scenarios
"""

import pytest

from app.services.ai.ivr_detector import IVRClassifier, IVRMode
from app.services.ai.testing import IVRSimulator, ScenarioLoader
from app.services.ai.testing.scenario_loader import ScenarioLoadError


class TestIVRSimulatorBasics:
    """Basic simulator functionality tests."""

    def test_initial_state(self, ivr_simulator_simple: IVRSimulator):
        """Simulator should start at initial state."""
        assert ivr_simulator_simple.current_state_id == "main_menu"
        assert not ivr_simulator_simple.is_terminal()

    def test_get_current_transcript(self, ivr_simulator_simple: IVRSimulator):
        """Should return transcript for current state."""
        transcript = ivr_simulator_simple.get_current_transcript()
        assert "Press 1 for sales" in transcript
        assert "Press 2 for support" in transcript

    def test_get_available_options(self, ivr_simulator_simple: IVRSimulator):
        """Should return list of available menu options."""
        options = ivr_simulator_simple.get_available_options()
        assert len(options) == 2
        assert options[0].digit == "1"
        assert options[1].digit == "2"


class TestIVRSimulatorNavigation:
    """Navigation tests."""

    def test_simple_navigation_to_sales(self, ivr_simulator_simple: IVRSimulator):
        """Navigate to sales by pressing 1."""
        success, transcript = ivr_simulator_simple.send_dtmf("1")

        assert success
        assert ivr_simulator_simple.current_state_id == "sales"
        assert ivr_simulator_simple.is_terminal()
        assert "sales" in transcript.lower()

    def test_simple_navigation_to_support(self, ivr_simulator_simple: IVRSimulator):
        """Navigate to support by pressing 2."""
        success, transcript = ivr_simulator_simple.send_dtmf("2")

        assert success
        assert ivr_simulator_simple.current_state_id == "support"
        assert ivr_simulator_simple.is_terminal()
        assert "support" in transcript.lower()

    def test_invalid_digit_stays_in_state(self, ivr_simulator_simple: IVRSimulator):
        """Invalid digit should keep simulator in current state."""
        success, transcript = ivr_simulator_simple.send_dtmf("9")

        assert not success
        assert ivr_simulator_simple.current_state_id == "main_menu"
        # Should return current menu transcript
        assert "Press 1" in transcript

    def test_navigation_path_tracking(self, ivr_simulator_simple: IVRSimulator):
        """Navigation path should be tracked."""
        path_before = ivr_simulator_simple.get_navigation_path()
        assert path_before == ["main_menu"]

        ivr_simulator_simple.send_dtmf("1")

        path_after = ivr_simulator_simple.get_navigation_path()
        assert path_after == ["main_menu", "sales"]


class TestIVRSimulatorNestedMenus:
    """Tests for nested menu navigation."""

    def test_navigate_to_submenu(self, ivr_simulator_nested: IVRSimulator):
        """Should navigate to sales submenu."""
        success, transcript = ivr_simulator_nested.send_dtmf("1")

        assert success
        assert ivr_simulator_nested.current_state_id == "sales_menu"
        assert "new customers" in transcript.lower()

    def test_navigate_through_nested_menu(self, ivr_simulator_nested: IVRSimulator):
        """Should navigate through nested menus to terminal state."""
        # Main menu → Sales menu
        ivr_simulator_nested.send_dtmf("1")
        assert ivr_simulator_nested.current_state_id == "sales_menu"

        # Sales menu → New customer
        ivr_simulator_nested.send_dtmf("1")
        assert ivr_simulator_nested.current_state_id == "new_customer"
        assert ivr_simulator_nested.is_terminal()

    def test_return_to_main_menu(self, ivr_simulator_nested: IVRSimulator):
        """Should return to main menu using 9."""
        # Navigate to sales menu
        ivr_simulator_nested.send_dtmf("1")
        assert ivr_simulator_nested.current_state_id == "sales_menu"

        # Press 9 to return
        ivr_simulator_nested.send_dtmf("9")
        assert ivr_simulator_nested.current_state_id == "main_menu"

    def test_operator_from_support_menu(self, ivr_simulator_nested: IVRSimulator):
        """Should reach operator from support submenu."""
        # Navigate to support menu
        ivr_simulator_nested.send_dtmf("2")
        assert ivr_simulator_nested.current_state_id == "support_menu"

        # Press 0 for operator
        ivr_simulator_nested.send_dtmf("0")
        assert ivr_simulator_nested.current_state_id == "operator"
        assert ivr_simulator_nested.is_terminal()


class TestIVRSimulatorVoicemailOption:
    """Tests for the critical voicemail option edge case."""

    def test_voicemail_option_transcript_is_ivr(
        self,
        ivr_simulator_voicemail: IVRSimulator,
        ivr_classifier: IVRClassifier,
    ):
        """CRITICAL: Menu with voicemail option should classify as IVR."""
        transcript = ivr_simulator_voicemail.get_current_transcript()

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR, (
            f"Menu with voicemail OPTION should be IVR, not {mode.value}. Transcript: {transcript}"
        )

    def test_navigate_to_voicemail(self, ivr_simulator_voicemail: IVRSimulator):
        """Should be able to navigate to voicemail by pressing 1."""
        success, transcript = ivr_simulator_voicemail.send_dtmf("1")

        assert success
        assert ivr_simulator_voicemail.current_state_id == "voicemail"
        assert ivr_simulator_voicemail.is_terminal()
        assert ivr_simulator_voicemail.get_state_type() == "voicemail"

    def test_navigate_to_sales_instead(self, ivr_simulator_voicemail: IVRSimulator):
        """Should be able to navigate to sales by pressing 2."""
        success, transcript = ivr_simulator_voicemail.send_dtmf("2")

        assert success
        assert ivr_simulator_voicemail.current_state_id == "sales_queue"
        assert ivr_simulator_voicemail.is_terminal()

    def test_voicemail_state_transcript_is_voicemail(
        self,
        ivr_simulator_voicemail: IVRSimulator,
        ivr_classifier: IVRClassifier,
    ):
        """After navigating to voicemail, that state should classify as VOICEMAIL."""
        # Navigate to voicemail
        ivr_simulator_voicemail.send_dtmf("1")

        transcript = ivr_simulator_voicemail.get_current_transcript()
        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL, (
            f"Actual voicemail state should be VOICEMAIL, not {mode.value}. "
            f"Transcript: {transcript}"
        )


class TestIVRSimulatorPureVoicemail:
    """Tests for pure voicemail (no menu options)."""

    def test_pure_voicemail_is_terminal(self, ivr_simulator_pure_voicemail: IVRSimulator):
        """Pure voicemail should start as terminal state."""
        assert ivr_simulator_pure_voicemail.is_terminal()
        assert ivr_simulator_pure_voicemail.get_state_type() == "voicemail"

    def test_pure_voicemail_classified_correctly(
        self,
        ivr_simulator_pure_voicemail: IVRSimulator,
        ivr_classifier: IVRClassifier,
    ):
        """Pure voicemail transcript should classify as VOICEMAIL."""
        transcript = ivr_simulator_pure_voicemail.get_current_transcript()

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL, (
            f"Pure voicemail should be VOICEMAIL, not {mode.value}. Transcript: {transcript}"
        )


class TestIVRSimulatorLoopDetection:
    """Tests for loop detection in stuck scenarios."""

    def test_loop_detected_after_repeats(self, ivr_simulator_loop: IVRSimulator):
        """Should detect loop after multiple repeats."""
        # Press 1 which loops back to main menu (stays at main_menu)
        ivr_simulator_loop.send_dtmf("1")
        assert ivr_simulator_loop.current_state_id == "main_menu"

        # Press 1 again - still at main_menu
        ivr_simulator_loop.send_dtmf("1")
        assert ivr_simulator_loop.current_state_id == "main_menu"

        # Path is now [main_menu, main_menu, main_menu] - 3 same states
        path = ivr_simulator_loop.get_navigation_path()
        assert path.count("main_menu") >= 3

        # Simulate timeout to increment repeat_count for is_in_loop check
        ivr_simulator_loop.simulate_timeout()

        # Now loop should be detected with threshold 2
        assert ivr_simulator_loop.is_in_loop(threshold=2)

    def test_escape_loop_with_different_option(self, ivr_simulator_loop: IVRSimulator):
        """Should escape loop by pressing different option."""
        # Get stuck in loop
        ivr_simulator_loop.send_dtmf("1")
        ivr_simulator_loop.send_dtmf("2")

        # Try option 3 to escape
        success, transcript = ivr_simulator_loop.send_dtmf("3")

        assert success
        assert ivr_simulator_loop.current_state_id == "more_options"
        assert not ivr_simulator_loop.is_in_loop()

    def test_operator_escape_from_loop(self, ivr_simulator_loop: IVRSimulator):
        """Should be able to reach operator by pressing 0."""
        # Get stuck first
        ivr_simulator_loop.send_dtmf("1")
        ivr_simulator_loop.send_dtmf("2")

        # Press 0 for operator
        success, transcript = ivr_simulator_loop.send_dtmf("0")

        assert success
        assert ivr_simulator_loop.current_state_id == "operator"
        assert ivr_simulator_loop.is_terminal()


class TestIVRSimulatorTimeout:
    """Tests for timeout behavior."""

    def test_timeout_repeats_menu(self, ivr_simulator_simple: IVRSimulator):
        """Timeout should repeat current menu."""
        transcript1 = ivr_simulator_simple.get_current_transcript()
        transcript2 = ivr_simulator_simple.simulate_timeout()

        # Should get same transcript
        assert transcript1 == transcript2

    def test_timeout_increments_repeat_count(self, ivr_simulator_simple: IVRSimulator):
        """Timeout should increment repeat count."""
        assert ivr_simulator_simple.repeat_count == 0

        ivr_simulator_simple.simulate_timeout()
        assert ivr_simulator_simple.repeat_count == 1

        ivr_simulator_simple.simulate_timeout()
        assert ivr_simulator_simple.repeat_count == 2


class TestIVRSimulatorReset:
    """Tests for reset functionality."""

    def test_reset_returns_to_initial_state(self, ivr_simulator_simple: IVRSimulator):
        """Reset should return to initial state."""
        # Navigate somewhere
        ivr_simulator_simple.send_dtmf("1")
        assert ivr_simulator_simple.current_state_id == "sales"

        # Reset
        ivr_simulator_simple.reset()

        assert ivr_simulator_simple.current_state_id == "main_menu"
        assert ivr_simulator_simple.navigation_path == ["main_menu"]
        assert ivr_simulator_simple.repeat_count == 0


class TestScenarioLoader:
    """Tests for YAML scenario loader."""

    def test_load_simple_menu(self, simple_menu_scenario):
        """Should load simple menu scenario."""
        assert simple_menu_scenario.name == "simple_menu"
        assert simple_menu_scenario.initial_state == "main_menu"
        assert "main_menu" in simple_menu_scenario.states
        assert "sales" in simple_menu_scenario.states

    def test_load_nested_menu(self, nested_menu_scenario):
        """Should load nested menu scenario."""
        assert nested_menu_scenario.name == "nested_menu"
        assert len(nested_menu_scenario.states) > 5

    def test_load_invalid_file_raises_error(self):
        """Should raise error for non-existent file."""
        with pytest.raises(ScenarioLoadError):
            ScenarioLoader.load("/nonexistent/path.yaml")

    def test_load_from_string(self):
        """Should load scenario from YAML string."""
        yaml_content = """
name: inline_test
initial_state: start
states:
  start:
    transcript: Press 1 to continue.
    options:
      - digit: "1"
        next_state: end
  end:
    transcript: Goodbye.
    is_terminal: true
"""
        scenario = ScenarioLoader.load_from_string(yaml_content)

        assert scenario.name == "inline_test"
        assert len(scenario.states) == 2


class TestIVRSimulatorWithClassifier:
    """Integration tests combining simulator with classifier."""

    def test_all_scenarios_classify_correctly(
        self,
        ivr_simulator_simple: IVRSimulator,
        ivr_simulator_nested: IVRSimulator,
        ivr_simulator_voicemail: IVRSimulator,
        ivr_simulator_pure_voicemail: IVRSimulator,
        ivr_classifier: IVRClassifier,
    ):
        """All IVR menu states should classify as IVR (not voicemail)."""
        ivr_menus = [
            ("simple_menu", ivr_simulator_simple),
            ("nested_menu", ivr_simulator_nested),
            ("voicemail_option", ivr_simulator_voicemail),
        ]

        for name, simulator in ivr_menus:
            transcript = simulator.get_current_transcript()
            mode, confidence = ivr_classifier.classify(transcript)

            assert mode == IVRMode.IVR, (
                f"Scenario '{name}' initial menu should classify as IVR, "
                f"got {mode.value}. Transcript: {transcript[:100]}..."
            )

        # Pure voicemail should be VOICEMAIL
        voicemail_transcript = ivr_simulator_pure_voicemail.get_current_transcript()
        mode, confidence = ivr_classifier.classify(voicemail_transcript)

        assert mode == IVRMode.VOICEMAIL, (
            f"Pure voicemail should classify as VOICEMAIL, "
            f"got {mode.value}. Transcript: {voicemail_transcript[:100]}..."
        )
