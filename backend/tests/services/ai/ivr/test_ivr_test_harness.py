"""Tests for IVR test harness.

Tests the IVRTestHarness using MockLLMClient for deterministic testing
without actual LLM API calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ai.testing import (
    IVRTestConfig,
    IVRTestHarness,
    MockLLMClient,
    ScenarioLoader,
)
from app.services.ai.testing.ivr_test_models import (
    IVRTestReport,
    IVRTestResult,
    IVRTestTurn,
)

# Path to scenario files
SCENARIOS_DIR = Path(__file__).parent / "scenarios"


class MockAgent:
    """Mock agent for testing without database."""

    def __init__(
        self,
        name: str = "Test Agent",
        system_prompt: str = "You are a test agent.",
        enable_ivr_navigation: bool = True,
        ivr_navigation_goal: str | None = "Reach a human operator",
        ivr_loop_threshold: int = 2,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.enable_ivr_navigation = enable_ivr_navigation
        self.ivr_navigation_goal = ivr_navigation_goal
        self.ivr_loop_threshold = ivr_loop_threshold


@pytest.fixture
def mock_agent() -> MockAgent:
    """Create a mock agent for testing."""
    return MockAgent()


@pytest.fixture
def simple_scenario():
    """Load the simple menu scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "simple_menu.yaml")


@pytest.fixture
def nested_scenario():
    """Load the nested menu scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "nested_menu.yaml")


@pytest.fixture
def stuck_loop_scenario():
    """Load the stuck loop scenario."""
    return ScenarioLoader.load(SCENARIOS_DIR / "stuck_loop.yaml")


class TestIVRTestTurn:
    """Tests for IVRTestTurn dataclass."""

    def test_to_dict(self) -> None:
        """Test turn serialization."""
        turn = IVRTestTurn(
            turn_number=1,
            ivr_transcript="Press 1 for sales.",
            agent_response="I'll press 1. <dtmf>1</dtmf>",
            dtmf_sent="1",
            state_before="main_menu",
            state_after="sales",
            dtmf_success=True,
        )

        data = turn.to_dict()

        assert data["turn_number"] == 1
        assert data["dtmf_sent"] == "1"
        assert data["state_before"] == "main_menu"
        assert data["state_after"] == "sales"
        assert data["dtmf_success"] is True
        assert "timestamp" in data


class TestIVRTestResult:
    """Tests for IVRTestResult dataclass."""

    def test_to_dict(self) -> None:
        """Test result serialization."""
        result = IVRTestResult(
            scenario_name="test_scenario",
            agent_name="Test Agent",
            workspace_name="Test Workspace",
            status="success",
            outcome_reason="reached_terminal",
            reached_goal=True,
            final_state="operator",
            final_state_type="operator",
            navigation_path=["main_menu", "sales", "operator"],
            duration_seconds=5.5,
        )

        data = result.to_dict()

        assert data["scenario_name"] == "test_scenario"
        assert data["status"] == "success"
        assert data["reached_goal"] is True
        assert data["navigation_path"] == ["main_menu", "sales", "operator"]

    def test_to_markdown(self) -> None:
        """Test markdown generation."""
        result = IVRTestResult(
            scenario_name="test_scenario",
            agent_name="Test Agent",
            workspace_name="Test Workspace",
            status="success",
            outcome_reason="reached_terminal",
            reached_goal=True,
            final_state="operator",
            final_state_type="operator",
            navigation_path=["main_menu", "operator"],
            duration_seconds=3.2,
        )

        md = result.to_markdown()

        assert "### ✅ test_scenario" in md
        assert "reached_terminal" in md
        assert "main_menu → operator" in md


class TestIVRTestReport:
    """Tests for IVRTestReport dataclass."""

    def test_add_result(self) -> None:
        """Test adding results updates counts."""
        report = IVRTestReport(
            agent_name="Test Agent",
            workspace_name="Test Workspace",
        )

        success = IVRTestResult(
            scenario_name="success_test",
            agent_name="Test Agent",
            workspace_name="Test Workspace",
            status="success",
            outcome_reason="reached_terminal",
            reached_goal=True,
            final_state="operator",
            final_state_type="operator",
        )
        failure = IVRTestResult(
            scenario_name="failure_test",
            agent_name="Test Agent",
            workspace_name="Test Workspace",
            status="failure",
            outcome_reason="loop_detected",
            reached_goal=False,
            final_state="main_menu",
            final_state_type="menu",
        )

        report.add_result(success)
        report.add_result(failure)

        assert report.total_scenarios == 2
        assert report.passed == 1
        assert report.failed == 1
        assert report.errors == 0

    def test_to_dict(self) -> None:
        """Test report serialization."""
        report = IVRTestReport(
            agent_name="Test Agent",
            workspace_name="Test Workspace",
        )

        data = report.to_dict()

        assert data["agent_name"] == "Test Agent"
        assert "summary" in data
        assert data["summary"]["total_scenarios"] == 0

    def test_to_markdown(self) -> None:
        """Test markdown report generation."""
        report = IVRTestReport(
            agent_name="Test Agent",
            workspace_name="Test Workspace",
        )

        md = report.to_markdown()

        assert "# IVR Test Report: Test Agent" in md
        assert "Test Workspace" in md


class TestMockLLMClient:
    """Tests for MockLLMClient."""

    async def test_returns_responses_in_order(self) -> None:
        """Test mock returns responses sequentially."""
        client = MockLLMClient(
            responses=[
                "First response",
                "Second response",
            ]
        )

        r1 = await client.generate_response("prompt", "transcript", [])
        r2 = await client.generate_response("prompt", "transcript", [])

        assert r1 == "First response"
        assert r2 == "Second response"
        assert client.call_count == 2

    async def test_raises_when_exhausted(self) -> None:
        """Test mock raises IndexError when responses exhausted."""
        client = MockLLMClient(responses=["Only one"])

        await client.generate_response("prompt", "transcript", [])

        with pytest.raises(IndexError):
            await client.generate_response("prompt", "transcript", [])

    async def test_records_calls(self) -> None:
        """Test mock records call parameters."""
        client = MockLLMClient(responses=["response"])

        await client.generate_response(
            "system prompt",
            "ivr transcript",
            [{"role": "user", "content": "hello"}],
        )

        assert len(client.calls) == 1
        assert client.calls[0]["system_prompt"] == "system prompt"
        assert client.calls[0]["ivr_transcript"] == "ivr transcript"


class TestIVRTestHarness:
    """Tests for IVRTestHarness."""

    async def test_successful_navigation(
        self,
        mock_agent: MockAgent,
        simple_scenario,
    ) -> None:
        """Test successful navigation to terminal state."""
        # Mock responses that press 1 to reach sales
        client = MockLLMClient(
            responses=[
                "I'll press 1 for sales. <dtmf>1</dtmf>",
            ]
        )
        harness = IVRTestHarness(llm_client=client)

        result = await harness.run_scenario(mock_agent, simple_scenario, "Test Workspace")

        assert result.status == "success"
        assert result.outcome_reason == "reached_terminal"
        assert result.final_state == "sales"
        assert result.final_state_type == "operator"
        assert len(result.turns) == 2  # Initial + terminal
        assert result.reached_goal is True

    async def test_nested_navigation(
        self,
        mock_agent: MockAgent,
        nested_scenario,
    ) -> None:
        """Test navigation through nested menus."""
        # Navigate: main_menu -> support_menu -> operator
        client = MockLLMClient(
            responses=[
                "I'll try technical support. <dtmf>2</dtmf>",  # main -> support
                "Let me speak to an operator. <dtmf>0</dtmf>",  # support -> operator
            ]
        )
        harness = IVRTestHarness(llm_client=client)

        result = await harness.run_scenario(mock_agent, nested_scenario, "Test Workspace")

        assert result.status == "success"
        assert result.outcome_reason == "reached_terminal"
        assert result.final_state == "operator"
        assert "main_menu" in result.navigation_path
        assert "support_menu" in result.navigation_path
        assert "operator" in result.navigation_path

    async def test_loop_detection(
        self,
        mock_agent: MockAgent,
        stuck_loop_scenario,
    ) -> None:
        """Test that loops are detected and reported."""
        # Mock responses that always press 1 (which loops back in stuck_loop scenario)
        client = MockLLMClient(
            responses=[
                "Pressing 1 <dtmf>1</dtmf>",
                "Pressing 1 again <dtmf>1</dtmf>",
                "Pressing 1 again <dtmf>1</dtmf>",
                "Pressing 1 again <dtmf>1</dtmf>",
            ]
        )
        config = IVRTestConfig(loop_threshold=3)
        harness = IVRTestHarness(llm_client=client, config=config)

        result = await harness.run_scenario(mock_agent, stuck_loop_scenario, "Test Workspace")

        assert result.status == "failure"
        assert result.outcome_reason == "loop_detected"
        assert result.reached_goal is False

    async def test_max_turns_exceeded(
        self,
        mock_agent: MockAgent,
        nested_scenario,
    ) -> None:
        """Test that max turns limit is enforced."""
        # Mock responses that never send DTMF
        client = MockLLMClient(
            responses=[
                "I'm not sure what to press.",
                "Still thinking...",
                "Hmm...",
            ]
        )
        config = IVRTestConfig(max_turns=3, loop_threshold=10)
        harness = IVRTestHarness(llm_client=client, config=config)

        result = await harness.run_scenario(mock_agent, nested_scenario, "Test Workspace")

        assert result.status == "failure"
        assert result.outcome_reason == "max_turns"
        assert len(result.turns) == 3

    async def test_llm_error_handling(
        self,
        mock_agent: MockAgent,
        simple_scenario,
    ) -> None:
        """Test that LLM errors are caught and reported."""
        # Mock client that raises an exception
        client = MockLLMClient(responses=[])  # Will raise IndexError
        harness = IVRTestHarness(llm_client=client)

        result = await harness.run_scenario(mock_agent, simple_scenario, "Test Workspace")

        assert result.status == "error"
        assert "llm_error" in result.outcome_reason

    async def test_run_scenarios(
        self,
        mock_agent: MockAgent,
        simple_scenario,
        nested_scenario,
    ) -> None:
        """Test running multiple scenarios generates report."""
        # Set up responses for both scenarios
        client = MockLLMClient(
            responses=[
                # Simple scenario - press 1
                "Press 1 <dtmf>1</dtmf>",
                # Nested scenario - press 2 then 0
                "Press 2 <dtmf>2</dtmf>",
                "Press 0 <dtmf>0</dtmf>",
            ]
        )
        harness = IVRTestHarness(llm_client=client)

        report = await harness.run_scenarios(
            mock_agent,
            [simple_scenario, nested_scenario],
            "Test Workspace",
        )

        assert report.total_scenarios == 2
        assert report.passed == 2
        assert report.failed == 0
        assert len(report.results) == 2

    async def test_no_dtmf_in_response(
        self,
        mock_agent: MockAgent,
        simple_scenario,
    ) -> None:
        """Test handling of responses without DTMF tags."""
        client = MockLLMClient(
            responses=[
                "I'm listening to the options...",  # No DTMF
                "Let me press 1 for sales. <dtmf>1</dtmf>",  # Has DTMF
            ]
        )
        harness = IVRTestHarness(llm_client=client)

        result = await harness.run_scenario(mock_agent, simple_scenario, "Test Workspace")

        assert result.status == "success"
        # First turn should have no DTMF sent
        assert result.turns[0].dtmf_sent is None
        # Second turn should have DTMF
        assert result.turns[1].dtmf_sent == "1"

    async def test_invalid_dtmf(
        self,
        mock_agent: MockAgent,
        simple_scenario,
    ) -> None:
        """Test handling of invalid DTMF input."""
        client = MockLLMClient(
            responses=[
                "Press 9 <dtmf>9</dtmf>",  # Invalid option
                "Press 1 <dtmf>1</dtmf>",  # Valid option
            ]
        )
        harness = IVRTestHarness(llm_client=client)

        result = await harness.run_scenario(mock_agent, simple_scenario, "Test Workspace")

        assert result.status == "success"
        # First DTMF should fail (invalid)
        assert result.turns[0].dtmf_success is False
        assert result.turns[0].state_before == result.turns[0].state_after

    def test_build_system_prompt(self, mock_agent: MockAgent) -> None:
        """Test system prompt construction."""
        client = MockLLMClient(responses=[])
        harness = IVRTestHarness(llm_client=client)

        prompt = harness._build_system_prompt(mock_agent)

        assert mock_agent.system_prompt in prompt
        assert "IVR NAVIGATION MODE" in prompt
        assert "dtmf" in prompt.lower()

    def test_build_system_prompt_ivr_disabled(self) -> None:
        """Test prompt when IVR navigation is disabled."""
        agent = MockAgent(enable_ivr_navigation=False)
        client = MockLLMClient(responses=[])
        harness = IVRTestHarness(llm_client=client)

        prompt = harness._build_system_prompt(agent)

        assert agent.system_prompt in prompt
        assert "IVR NAVIGATION MODE" not in prompt


class TestIVRTestConfig:
    """Tests for IVRTestConfig."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = IVRTestConfig()

        assert config.max_turns == 20
        assert config.loop_threshold == 3
        assert config.timeout_per_turn_seconds == 30.0
        assert config.verbose is False

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = IVRTestConfig(
            max_turns=10,
            loop_threshold=2,
            verbose=True,
        )

        assert config.max_turns == 10
        assert config.loop_threshold == 2
        assert config.verbose is True
