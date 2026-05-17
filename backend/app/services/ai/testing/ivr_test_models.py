"""Data models for IVR test harness results.

This module provides dataclasses for capturing test execution results:
- IVRTestTurn: A single turn in the IVR navigation
- IVRTestResult: Complete result of a single scenario test
- IVRTestReport: Aggregated results from multiple scenarios

Example usage:
    result = IVRTestResult(
        scenario_name="nested_menu",
        agent_name="Dawn Gatekeeper Destroyer",
        workspace_name="Maxteriors",
        status="success",
        outcome_reason="reached_terminal",
        reached_goal=True,
        final_state="operator",
        final_state_type="operator",
        turns=[...],
        navigation_path=["main_menu", "support_menu", "operator"],
        duration_seconds=12.5,
    )
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class IVRTestTurn:
    """A single turn in the IVR navigation test.

    Attributes:
        turn_number: Sequential turn number (1-indexed)
        ivr_transcript: The transcript from the IVR system
        agent_response: The LLM agent's full response
        dtmf_sent: DTMF digit(s) extracted and sent, or None if none
        state_before: IVR state ID before this turn
        state_after: IVR state ID after this turn
        dtmf_success: Whether the DTMF navigation succeeded
        timestamp: When this turn occurred
    """

    turn_number: int
    ivr_transcript: str
    agent_response: str
    dtmf_sent: str | None
    state_before: str
    state_after: str
    dtmf_success: bool
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "turn_number": self.turn_number,
            "ivr_transcript": self.ivr_transcript,
            "agent_response": self.agent_response,
            "dtmf_sent": self.dtmf_sent,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "dtmf_success": self.dtmf_success,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class IVRTestResult:
    """Complete result of running a single IVR scenario test.

    Attributes:
        scenario_name: Name of the IVR scenario
        agent_name: Name of the agent being tested
        workspace_name: Name of the agent's workspace
        status: Overall test status (success, failure, error)
        outcome_reason: Why the test ended (reached_terminal, loop_detected, max_turns, llm_error)
        reached_goal: Whether the agent reached its navigation goal
        final_state: The final IVR state ID
        final_state_type: Type of final state (menu, operator, voicemail, etc.)
        turns: List of all turns in the test
        navigation_path: Ordered list of state IDs visited
        duration_seconds: Total test duration
    """

    scenario_name: str
    agent_name: str
    workspace_name: str
    status: Literal["success", "failure", "error"]
    outcome_reason: str
    reached_goal: bool
    final_state: str
    final_state_type: str
    turns: list[IVRTestTurn] = field(default_factory=list)
    navigation_path: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "scenario_name": self.scenario_name,
            "agent_name": self.agent_name,
            "workspace_name": self.workspace_name,
            "status": self.status,
            "outcome_reason": self.outcome_reason,
            "reached_goal": self.reached_goal,
            "final_state": self.final_state,
            "final_state_type": self.final_state_type,
            "turns": [t.to_dict() for t in self.turns],
            "navigation_path": self.navigation_path,
            "duration_seconds": self.duration_seconds,
        }

    def to_markdown(self) -> str:
        """Generate markdown summary of this result."""
        status_icon = {"success": "✅", "failure": "❌", "error": "⚠️"}.get(self.status, "❓")

        lines = [
            f"### {status_icon} {self.scenario_name}",
            "",
            f"- **Status:** {self.status}",
            f"- **Outcome:** {self.outcome_reason}",
            f"- **Reached Goal:** {'Yes' if self.reached_goal else 'No'}",
            f"- **Final State:** {self.final_state} ({self.final_state_type})",
            f"- **Turns:** {len(self.turns)}",
            f"- **Duration:** {self.duration_seconds:.2f}s",
            "",
            f"**Navigation Path:** {' → '.join(self.navigation_path)}",
        ]

        return "\n".join(lines)


@dataclass
class IVRTestReport:
    """Aggregated results from testing an agent against multiple scenarios.

    Attributes:
        agent_name: Name of the agent tested
        workspace_name: Workspace the agent belongs to
        results: List of individual test results
        total_scenarios: Total number of scenarios tested
        passed: Number of scenarios that passed
        failed: Number of scenarios that failed
        errors: Number of scenarios with errors
    """

    agent_name: str
    workspace_name: str
    results: list[IVRTestResult] = field(default_factory=list)
    total_scenarios: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0

    def add_result(self, result: IVRTestResult) -> None:
        """Add a result and update counts."""
        self.results.append(result)
        self.total_scenarios += 1

        if result.status == "success":
            self.passed += 1
        elif result.status == "failure":
            self.failed += 1
        else:
            self.errors += 1

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent_name": self.agent_name,
            "workspace_name": self.workspace_name,
            "summary": {
                "total_scenarios": self.total_scenarios,
                "passed": self.passed,
                "failed": self.failed,
                "errors": self.errors,
                "pass_rate": (
                    f"{(self.passed / self.total_scenarios * 100):.1f}%"
                    if self.total_scenarios > 0
                    else "N/A"
                ),
            },
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Generate markdown report."""
        pass_rate = (
            f"{(self.passed / self.total_scenarios * 100):.1f}%"
            if self.total_scenarios > 0
            else "N/A"
        )

        lines = [
            f"# IVR Test Report: {self.agent_name}",
            "",
            f"**Workspace:** {self.workspace_name}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Scenarios | {self.total_scenarios} |",
            f"| Passed | {self.passed} |",
            f"| Failed | {self.failed} |",
            f"| Errors | {self.errors} |",
            f"| Pass Rate | {pass_rate} |",
            "",
            "## Results",
            "",
        ]

        for result in self.results:
            lines.append(result.to_markdown())
            lines.append("")

        return "\n".join(lines)
