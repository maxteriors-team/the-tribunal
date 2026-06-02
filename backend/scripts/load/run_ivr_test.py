#!/usr/bin/env python
"""Run IVR test harness against a specific agent.

This script loads an agent from the database and runs it through IVR
simulation scenarios to test its navigation capabilities.

Usage:
    # Run all scenarios
    cd backend && uv run python scripts/run_ivr_test.py \\
        --agent "Dawn Gatekeeper Destroyer" \\
        --workspace "Maxteriors" \\
        --scenarios all

    # Run specific scenario
    cd backend && uv run python scripts/run_ivr_test.py \\
        --agent "Dawn Gatekeeper Destroyer" \\
        --workspace "Maxteriors" \\
        --scenario-file tests/services/ai/ivr/scenarios/nested_menu.yaml

    # Save report to file
    cd backend && uv run python scripts/run_ivr_test.py \\
        --agent "Dawn Gatekeeper Destroyer" \\
        --workspace "Maxteriors" \\
        --scenarios all \\
        --output report.json \\
        --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.ai.testing import (
    AgentNotFoundError,
    IVRScenario,
    IVRTestConfig,
    IVRTestHarness,
    IVRTestReport,
    ScenarioLoader,
    WorkspaceNotFoundError,
)
from app.services.ai.testing.ivr_test_llm import GrokTestClient, OpenAITestClient

if TYPE_CHECKING:
    from app.models.agent import Agent

# Default scenarios directory
DEFAULT_SCENARIOS_DIR = Path(__file__).parent.parent / "tests/services/ai/ivr/scenarios"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run IVR test harness against a specific agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run all scenarios with default settings
    uv run python scripts/run_ivr_test.py \\
        --agent "Dawn Gatekeeper Destroyer" \\
        --workspace "Maxteriors"

    # Run specific scenario file
    uv run python scripts/run_ivr_test.py \\
        --agent "My Agent" \\
        --workspace "My Workspace" \\
        --scenario-file tests/services/ai/ivr/scenarios/nested_menu.yaml

    # Run with verbose output and save JSON report
    uv run python scripts/run_ivr_test.py \\
        --agent "My Agent" \\
        --workspace "My Workspace" \\
        --verbose \\
        --output report.json
        """,
    )

    parser.add_argument(
        "--agent",
        required=True,
        help="Name of the agent to test",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Name of the workspace containing the agent",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=["all"],
        help="Scenario names to run, or 'all' for all scenarios (default: all)",
    )
    parser.add_argument(
        "--scenario-file",
        type=Path,
        help="Path to a specific scenario YAML file to run",
    )
    parser.add_argument(
        "--scenario-dir",
        type=Path,
        default=DEFAULT_SCENARIOS_DIR,
        help=f"Directory containing scenario YAML files (default: {DEFAULT_SCENARIOS_DIR})",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Maximum turns per scenario before stopping (default: 20)",
    )
    parser.add_argument(
        "--loop-threshold",
        type=int,
        default=3,
        help="State repeats to consider a loop (default: 3)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save JSON report to this file",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Output markdown format instead of summary",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed turn-by-turn output",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["openai", "grok"],
        default="openai",
        help="LLM provider to use (default: openai)",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4o-mini",
        help="Model to use (default: gpt-4o-mini for OpenAI, grok-3-mini for Grok)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="LLM temperature for more/less deterministic responses (default: 0.3)",
    )

    return parser.parse_args()


def create_llm_client(
    provider: str,
    model: str,
    temperature: float,
) -> OpenAITestClient | GrokTestClient:
    """Create LLM client based on provider."""
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return OpenAITestClient(api_key=api_key, model=model, temperature=temperature)

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY environment variable not set")
    # Use grok-3-mini as default if user didn't specify
    actual_model = "grok-3-mini" if model == "gpt-4o-mini" else model
    return GrokTestClient(api_key=api_key, model=actual_model, temperature=temperature)


def print_header(args: argparse.Namespace) -> None:
    """Print the header with configuration info."""
    print("=" * 60)
    print("IVR Test Harness")
    print("=" * 60)
    print()
    print(f"Agent:     {args.agent}")
    print(f"Workspace: {args.workspace}")
    print(f"Provider:  {args.llm_provider}")
    print(f"Model:     {args.llm_model}")
    print()


def print_agent_info(agent: Agent) -> None:
    """Print agent details."""
    print(f"Agent ID: {agent.id}")
    ivr_status = "Enabled" if agent.enable_ivr_navigation else "Disabled"
    print(f"IVR Navigation: {ivr_status}")
    if agent.ivr_navigation_goal:
        print(f"IVR Goal: {agent.ivr_navigation_goal}")
    print()


def load_scenarios(args: argparse.Namespace) -> list[IVRScenario]:
    """Load scenarios based on arguments."""
    if args.scenario_file:
        print(f"Loading scenario from: {args.scenario_file}")
        return [ScenarioLoader.load(args.scenario_file)]

    print(f"Loading scenarios from: {args.scenario_dir}")
    all_scenarios = ScenarioLoader.load_directory(args.scenario_dir)

    if "all" in args.scenarios:
        return list(all_scenarios.values())

    return [all_scenarios[name] for name in args.scenarios if name in all_scenarios]


def print_scenarios(scenarios: list[IVRScenario]) -> None:
    """Print scenario list."""
    print(f"Scenarios: {len(scenarios)}")
    for s in scenarios:
        print(f"  - {s.name}")
    print()
    print("-" * 60)
    print("Running tests...")
    print("-" * 60)
    print()


def print_results(report: IVRTestReport, markdown: bool) -> None:
    """Print test results."""
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print()

    if markdown:
        print(report.to_markdown())
        return

    print(f"Total:  {report.total_scenarios}")
    print(f"Passed: {report.passed} ✅")
    print(f"Failed: {report.failed} ❌")
    print(f"Errors: {report.errors} ⚠️")
    print()

    status_icons = {"success": "✅", "failure": "❌", "error": "⚠️"}
    for result in report.results:
        icon = status_icons.get(result.status, "❓")
        print(f"{icon} {result.scenario_name}")
        print(f"   Status: {result.status} ({result.outcome_reason})")
        print(f"   Turns:  {len(result.turns)}")
        print(f"   Path:   {' → '.join(result.navigation_path)}")
        print()


async def run_tests(args: argparse.Namespace) -> int:
    """Run the IVR tests and return exit code."""
    print_header(args)

    # Create LLM client
    try:
        llm_client = create_llm_client(args.llm_provider, args.llm_model, args.temperature)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    # Create test harness
    config = IVRTestConfig(
        max_turns=args.max_turns,
        loop_threshold=args.loop_threshold,
        verbose=args.verbose,
    )
    harness = IVRTestHarness(llm_client=llm_client, config=config)

    # Create database session
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as db:
            # Load agent
            try:
                agent = await harness.load_agent(db, args.agent, args.workspace)
            except WorkspaceNotFoundError:
                print(f"ERROR: Workspace '{args.workspace}' not found")
                return 1
            except AgentNotFoundError:
                print(f"ERROR: Agent '{args.agent}' not found in workspace")
                return 1

            print_agent_info(agent)

            # Load and run scenarios
            scenarios = load_scenarios(args)
            if not scenarios:
                print("ERROR: No scenarios found")
                return 1

            print_scenarios(scenarios)
            report = await harness.run_scenarios(agent, scenarios, args.workspace)

    finally:
        await engine.dispose()

    # Output results
    print_results(report, args.markdown)

    if args.output:
        args.output.write_text(report.to_json(indent=2))
        print(f"Report saved to: {args.output}")

    return 1 if (report.failed > 0 or report.errors > 0) else 0


def main() -> int:
    """Main entry point."""
    args = parse_args()
    return asyncio.run(run_tests(args))


if __name__ == "__main__":
    sys.exit(main())
