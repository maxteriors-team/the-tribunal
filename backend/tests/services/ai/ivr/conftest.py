"""IVR-specific test fixtures.

Provides fixtures for testing IVR detection and simulation:
- IVRClassifier instances
- IVRDetector instances
- IVRSimulator with various scenarios
- Mock agent for harness testing
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.services.ai.ivr_detector import (
    IVRClassifier,
    IVRDetector,
    IVRDetectorConfig,
    LoopDetector,
)
from app.services.ai.testing import IVRSimulator, MockLLMClient, ScenarioLoader

# Path to scenario files
SCENARIOS_DIR = Path(__file__).parent / "scenarios"


@pytest.fixture
def ivr_classifier() -> IVRClassifier:
    """Create a fresh IVRClassifier instance."""
    return IVRClassifier()


@pytest.fixture
def ivr_detector() -> IVRDetector:
    """Create a fresh IVRDetector with default config."""
    return IVRDetector(config=IVRDetectorConfig())


@pytest.fixture
def ivr_detector_sensitive() -> IVRDetector:
    """Create an IVRDetector with lower thresholds for faster detection."""
    return IVRDetector(
        config=IVRDetectorConfig(
            loop_similarity_threshold=0.7,
            consecutive_classifications=1,
        )
    )


@pytest.fixture
def loop_detector() -> LoopDetector:
    """Create a fresh LoopDetector instance."""
    return LoopDetector(similarity_threshold=0.85, max_history=10)


@pytest.fixture
def loop_detector_sensitive() -> LoopDetector:
    """Create a LoopDetector with lower threshold."""
    return LoopDetector(similarity_threshold=0.7, max_history=5)


# Scenario-specific fixtures


@pytest.fixture
def simple_menu_scenario():
    """Load the simple menu scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "simple_menu.yaml")


@pytest.fixture
def nested_menu_scenario():
    """Load the nested menu scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "nested_menu.yaml")


@pytest.fixture
def voicemail_option_scenario():
    """Load the voicemail option scenario (critical edge case)."""
    return ScenarioLoader.load(SCENARIOS_DIR / "voicemail_option.yaml")


@pytest.fixture
def pure_voicemail_scenario():
    """Load the pure voicemail scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "pure_voicemail.yaml")


@pytest.fixture
def stuck_loop_scenario():
    """Load the stuck loop scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "stuck_loop.yaml")


# Simulator fixtures


@pytest.fixture
def ivr_simulator_simple(simple_menu_scenario) -> IVRSimulator:
    """Create a simulator with the simple menu scenario."""
    return IVRSimulator(simple_menu_scenario)


@pytest.fixture
def ivr_simulator_nested(nested_menu_scenario) -> IVRSimulator:
    """Create a simulator with the nested menu scenario."""
    return IVRSimulator(nested_menu_scenario)


@pytest.fixture
def ivr_simulator_voicemail(voicemail_option_scenario) -> IVRSimulator:
    """Create a simulator with the voicemail option scenario."""
    return IVRSimulator(voicemail_option_scenario)


@pytest.fixture
def ivr_simulator_pure_voicemail(pure_voicemail_scenario) -> IVRSimulator:
    """Create a simulator with the pure voicemail scenario."""
    return IVRSimulator(pure_voicemail_scenario)


@pytest.fixture
def ivr_simulator_loop(stuck_loop_scenario) -> IVRSimulator:
    """Create a simulator with the stuck loop scenario."""
    return IVRSimulator(stuck_loop_scenario)


# Test harness fixtures


@dataclass
class MockAgent:
    """Mock agent for testing without database access."""

    name: str = "Test Agent"
    system_prompt: str = "You are a test agent navigating phone menus."
    enable_ivr_navigation: bool = True
    ivr_navigation_goal: str | None = "Reach a human operator"
    ivr_loop_threshold: int = 2


@pytest.fixture
def mock_agent() -> MockAgent:
    """Create a mock agent for harness testing."""
    return MockAgent()


@pytest.fixture
def mock_agent_no_ivr() -> MockAgent:
    """Create a mock agent with IVR navigation disabled."""
    return MockAgent(enable_ivr_navigation=False)


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """Create a mock LLM client with default responses."""
    return MockLLMClient(
        responses=[
            "I'll press 1. <dtmf>1</dtmf>",
            "Let me try 2. <dtmf>2</dtmf>",
            "Pressing 0 for operator. <dtmf>0</dtmf>",
        ]
    )
