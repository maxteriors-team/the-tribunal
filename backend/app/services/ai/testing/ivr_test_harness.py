"""IVR Test Harness for running agents through IVR simulation scenarios.

This module provides the main orchestrator for testing AI agents' IVR navigation
capabilities. It loads agents from the database and runs them through simulated
IVR scenarios to verify they can navigate phone menus correctly.

Example usage:
    from app.services.ai.testing import IVRTestHarness, ScenarioLoader
    from app.services.ai.testing.ivr_test_llm import OpenAITestClient

    client = OpenAITestClient(api_key="sk-...", model="gpt-5.4-nano")
    harness = IVRTestHarness(llm_client=client)

    async with async_session() as db:
        agent = await harness.load_agent(db, "Dawn Gatekeeper Destroyer", "Maxteriors")
        scenarios = ScenarioLoader.load_directory("tests/services/ai/ivr/scenarios")
        report = await harness.run_scenarios(agent, list(scenarios.values()), "Maxteriors")
        print(report.to_markdown())
"""


import time
from dataclasses import dataclass, field
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.workspace import Workspace
from app.services.ai.ivr_detector import DTMFParser, IVRDetector, IVRDetectorConfig
from app.services.ai.testing.ivr_simulator import IVRScenario, IVRSimulator
from app.services.ai.testing.ivr_test_llm import IVRTestLLMClient
from app.services.ai.testing.ivr_test_models import (
    IVRTestReport,
    IVRTestResult,
    IVRTestTurn,
)

logger = structlog.get_logger()


class AgentNotFoundError(Exception):
    """Raised when agent cannot be found in database."""

    pass


class WorkspaceNotFoundError(Exception):
    """Raised when workspace cannot be found in database."""

    pass


@dataclass
class IVRTestConfig:
    """Configuration for IVR test execution.

    Attributes:
        max_turns: Maximum turns before stopping (prevents infinite loops)
        loop_threshold: Number of state repeats to consider a loop
        timeout_per_turn_seconds: Timeout for each LLM call
        verbose: Whether to log detailed turn information
    """

    max_turns: int = 20
    loop_threshold: int = 3
    timeout_per_turn_seconds: float = 30.0
    verbose: bool = False


@dataclass
class IVRTestHarness:
    """Main orchestrator for IVR agent testing.

    Coordinates the IVR simulator, LLM client, and DTMF parsing to run
    agents through IVR scenarios and capture results.

    Attributes:
        llm_client: LLM client for generating agent responses
        config: Test execution configuration
    """

    llm_client: IVRTestLLMClient
    config: IVRTestConfig = field(default_factory=IVRTestConfig)

    def __post_init__(self) -> None:
        """Initialize components after dataclass init."""
        self._dtmf_parser = DTMFParser()
        self.logger = logger.bind(service="ivr_test_harness")

    async def load_agent(
        self,
        db: AsyncSession,
        agent_name: str,
        workspace_name: str,
    ) -> Agent:
        """Load an agent from the database by name and workspace.

        Args:
            db: Async database session
            agent_name: Name of the agent to load
            workspace_name: Name of the workspace containing the agent

        Returns:
            The loaded Agent model

        Raises:
            WorkspaceNotFoundError: If workspace not found
            AgentNotFoundError: If agent not found in workspace
        """
        # First find the workspace
        workspace_stmt = select(Workspace).where(Workspace.name == workspace_name)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()

        if not workspace:
            raise WorkspaceNotFoundError(f"Workspace '{workspace_name}' not found")

        # Then find the agent in that workspace
        agent_stmt = select(Agent).where(
            Agent.workspace_id == workspace.id,
            Agent.name == agent_name,
        )
        agent_result = await db.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()

        if not agent:
            raise AgentNotFoundError(
                f"Agent '{agent_name}' not found in workspace '{workspace_name}'"
            )

        self.logger.info(
            "agent_loaded",
            agent_id=str(agent.id),
            agent_name=agent.name,
            workspace=workspace_name,
            ivr_enabled=agent.enable_ivr_navigation,
            ivr_goal=agent.ivr_navigation_goal,
        )

        return agent

    async def run_scenario(
        self,
        agent: Agent,
        scenario: IVRScenario,
        workspace_name: str,
    ) -> IVRTestResult:
        """Run a single IVR scenario with the given agent.

        Args:
            agent: The agent to test
            scenario: The IVR scenario to run
            workspace_name: Name of the workspace (for reporting)

        Returns:
            Test result with all turns and outcome
        """
        start_time = time.time()
        simulator = IVRSimulator(scenario)
        detector = IVRDetector(
            config=IVRDetectorConfig(
                loop_similarity_threshold=0.85,
            )
        )

        # Build the system prompt
        system_prompt = self._build_system_prompt(agent)

        turns: list[IVRTestTurn] = []
        conversation_history: list[dict[str, str]] = []
        loop_count: dict[str, int] = {}

        self.logger.info(
            "scenario_started",
            scenario=scenario.name,
            agent=agent.name,
            initial_state=scenario.initial_state,
        )

        try:
            for turn_number in range(1, self.config.max_turns + 1):
                # Get current IVR transcript
                ivr_transcript = simulator.get_current_transcript()
                state_before = simulator.current_state_id

                # Track state visits for loop detection
                loop_count[state_before] = loop_count.get(state_before, 0) + 1

                if self.config.verbose:
                    self.logger.info(
                        "turn_start",
                        turn=turn_number,
                        state=state_before,
                        transcript_preview=ivr_transcript[:80],
                    )

                # Check for terminal state
                if simulator.is_terminal():
                    turn = IVRTestTurn(
                        turn_number=turn_number,
                        ivr_transcript=ivr_transcript,
                        agent_response="[Terminal state reached]",
                        dtmf_sent=None,
                        state_before=state_before,
                        state_after=state_before,
                        dtmf_success=True,
                        timestamp=datetime.now(),
                    )
                    turns.append(turn)

                    duration = time.time() - start_time
                    return IVRTestResult(
                        scenario_name=scenario.name,
                        agent_name=agent.name,
                        workspace_name=workspace_name,
                        status="success",
                        outcome_reason="reached_terminal",
                        reached_goal=self._check_goal_reached(agent, simulator),
                        final_state=simulator.current_state_id,
                        final_state_type=simulator.get_state_type(),
                        turns=turns,
                        navigation_path=simulator.get_navigation_path(),
                        duration_seconds=duration,
                    )

                # Check for loop
                if loop_count[state_before] >= self.config.loop_threshold:
                    duration = time.time() - start_time
                    return IVRTestResult(
                        scenario_name=scenario.name,
                        agent_name=agent.name,
                        workspace_name=workspace_name,
                        status="failure",
                        outcome_reason="loop_detected",
                        reached_goal=False,
                        final_state=simulator.current_state_id,
                        final_state_type=simulator.get_state_type(),
                        turns=turns,
                        navigation_path=simulator.get_navigation_path(),
                        duration_seconds=duration,
                    )

                # Generate agent response
                agent_response = await self.llm_client.generate_response(
                    system_prompt=system_prompt,
                    ivr_transcript=ivr_transcript,
                    conversation_history=conversation_history,
                )

                # Parse DTMF from response
                dtmf_digits = self._dtmf_parser.parse(agent_response)
                dtmf_sent = dtmf_digits[0] if dtmf_digits else None

                # Send DTMF if present
                dtmf_success = False
                state_after = state_before

                if dtmf_sent:
                    dtmf_success, _ = simulator.send_dtmf(dtmf_sent)
                    state_after = simulator.current_state_id
                    detector.record_dtmf_attempt(dtmf_sent)

                    if self.config.verbose:
                        self.logger.info(
                            "dtmf_sent",
                            dtmf=dtmf_sent,
                            success=dtmf_success,
                            new_state=state_after,
                        )

                # Record turn
                turn = IVRTestTurn(
                    turn_number=turn_number,
                    ivr_transcript=ivr_transcript,
                    agent_response=agent_response,
                    dtmf_sent=dtmf_sent,
                    state_before=state_before,
                    state_after=state_after,
                    dtmf_success=dtmf_success,
                    timestamp=datetime.now(),
                )
                turns.append(turn)

                # Update conversation history
                conversation_history.append({"role": "user", "content": ivr_transcript})
                stripped_response = self._dtmf_parser.strip_dtmf_tags(agent_response)
                conversation_history.append(
                    {"role": "assistant", "content": stripped_response}
                )

            # Max turns exceeded
            duration = time.time() - start_time
            return IVRTestResult(
                scenario_name=scenario.name,
                agent_name=agent.name,
                workspace_name=workspace_name,
                status="failure",
                outcome_reason="max_turns",
                reached_goal=False,
                final_state=simulator.current_state_id,
                final_state_type=simulator.get_state_type(),
                turns=turns,
                navigation_path=simulator.get_navigation_path(),
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.exception(
                "scenario_error",
                scenario=scenario.name,
                error=str(e),
            )

            return IVRTestResult(
                scenario_name=scenario.name,
                agent_name=agent.name,
                workspace_name=workspace_name,
                status="error",
                outcome_reason=f"llm_error: {e!s}",
                reached_goal=False,
                final_state=simulator.current_state_id,
                final_state_type=simulator.get_state_type(),
                turns=turns,
                navigation_path=simulator.get_navigation_path(),
                duration_seconds=duration,
            )

    async def run_scenarios(
        self,
        agent: Agent,
        scenarios: list[IVRScenario],
        workspace_name: str,
    ) -> IVRTestReport:
        """Run multiple scenarios and generate a report.

        Args:
            agent: The agent to test
            scenarios: List of scenarios to run
            workspace_name: Name of the workspace (for reporting)

        Returns:
            Aggregated test report
        """
        report = IVRTestReport(
            agent_name=agent.name,
            workspace_name=workspace_name,
        )

        self.logger.info(
            "test_run_started",
            agent=agent.name,
            scenario_count=len(scenarios),
        )

        for scenario in scenarios:
            result = await self.run_scenario(agent, scenario, workspace_name)
            report.add_result(result)

            self.logger.info(
                "scenario_completed",
                scenario=scenario.name,
                status=result.status,
                outcome=result.outcome_reason,
            )

        self.logger.info(
            "test_run_completed",
            agent=agent.name,
            passed=report.passed,
            failed=report.failed,
            errors=report.errors,
        )

        return report

    def _build_system_prompt(self, agent: Agent) -> str:
        """Build the complete system prompt for IVR navigation.

        Combines the agent's base system prompt with IVR navigation instructions.

        Args:
            agent: The agent being tested

        Returns:
            Complete system prompt string
        """
        # Create a detector to get the navigation prompt
        detector = IVRDetector(config=IVRDetectorConfig())
        ivr_prompt = detector.get_ivr_navigation_prompt(goal=agent.ivr_navigation_goal)

        # Combine prompts
        parts = [agent.system_prompt]

        if agent.enable_ivr_navigation:
            parts.append("\n\n--- IVR NAVIGATION MODE ---\n")
            parts.append(ivr_prompt)

        return "\n".join(parts)

    def _check_goal_reached(self, agent: Agent, simulator: IVRSimulator) -> bool:
        """Check if the agent reached its navigation goal.

        This is a heuristic check based on the final state type.
        An operator state generally means successful navigation.

        Args:
            agent: The agent being tested
            simulator: The simulator at final state

        Returns:
            True if goal appears to be reached
        """
        state_type = simulator.get_state_type()

        # Common success states
        success_types = {"operator", "queue"}

        # If agent has a specific goal mentioning voicemail, that's also success
        if agent.ivr_navigation_goal:
            goal_lower = agent.ivr_navigation_goal.lower()
            if "voicemail" in goal_lower and state_type == "voicemail":
                return True

        return state_type in success_types
