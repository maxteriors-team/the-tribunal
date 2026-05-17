"""YAML scenario loader for IVR simulator.

This module provides utilities to load IVR scenarios from YAML files.

Example YAML format:
    name: simple_menu
    description: A simple IVR menu with sales and support options
    initial_state: main_menu
    states:
      main_menu:
        transcript: Press 1 for sales, press 2 for support.
        options:
          - digit: "1"
            description: Sales
            next_state: sales
          - digit: "2"
            description: Support
            next_state: support
        timeout_action: main_menu
      sales:
        transcript: Connecting to sales.
        state_type: operator
        is_terminal: true
"""

from pathlib import Path
from typing import Any

import structlog
import yaml  # type: ignore[import-untyped]

from app.services.ai.testing.ivr_simulator import (
    IVRMenuOption,
    IVRScenario,
    IVRState,
)

logger = structlog.get_logger()


class ScenarioLoadError(Exception):
    """Error loading IVR scenario from file."""

    pass


class ScenarioLoader:
    """Loads IVR scenarios from YAML files.

    Provides methods to load scenarios from files, directories,
    or built-in test scenarios.
    """

    # Built-in scenarios directory (relative to this file)
    _BUILTIN_DIR: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> IVRScenario:
        """Load a scenario from a YAML file.

        Args:
            path: Path to the YAML file

        Returns:
            Parsed IVRScenario object

        Raises:
            ScenarioLoadError: If file cannot be loaded or parsed
        """
        path = Path(path)

        if not path.exists():
            raise ScenarioLoadError(f"Scenario file not found: {path}")

        if path.suffix not in {".yaml", ".yml"}:
            raise ScenarioLoadError(f"Unsupported file format: {path.suffix}")

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ScenarioLoadError(f"Invalid YAML in {path}: {e}") from e

        return cls._parse_scenario(data, path.stem)

    @classmethod
    def load_from_string(cls, yaml_content: str, name: str = "unnamed") -> IVRScenario:
        """Load a scenario from a YAML string.

        Args:
            yaml_content: YAML content as string
            name: Name to use if not specified in YAML

        Returns:
            Parsed IVRScenario object

        Raises:
            ScenarioLoadError: If YAML cannot be parsed
        """
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ScenarioLoadError(f"Invalid YAML: {e}") from e

        return cls._parse_scenario(data, name)

    @classmethod
    def load_directory(cls, path: str | Path) -> dict[str, IVRScenario]:
        """Load all scenarios from a directory.

        Args:
            path: Path to directory containing YAML files

        Returns:
            Dictionary mapping scenario names to scenarios

        Raises:
            ScenarioLoadError: If directory doesn't exist
        """
        path = Path(path)

        if not path.exists():
            raise ScenarioLoadError(f"Scenario directory not found: {path}")

        if not path.is_dir():
            raise ScenarioLoadError(f"Path is not a directory: {path}")

        scenarios: dict[str, IVRScenario] = {}
        for file in path.glob("*.yaml"):
            try:
                scenario = cls.load(file)
                scenarios[scenario.name] = scenario
            except ScenarioLoadError as e:
                logger.warning(
                    "scenario_load_skipped",
                    file=str(file),
                    error=str(e),
                )

        for file in path.glob("*.yml"):
            try:
                scenario = cls.load(file)
                scenarios[scenario.name] = scenario
            except ScenarioLoadError as e:
                logger.warning(
                    "scenario_load_skipped",
                    file=str(file),
                    error=str(e),
                )

        return scenarios

    @classmethod
    def _parse_scenario(cls, data: dict[str, Any], default_name: str) -> IVRScenario:
        """Parse scenario data into IVRScenario object.

        Args:
            data: Parsed YAML data
            default_name: Name to use if not in data

        Returns:
            IVRScenario object

        Raises:
            ScenarioLoadError: If required fields are missing
        """
        if not isinstance(data, dict):
            raise ScenarioLoadError("Scenario must be a YAML object")

        # Required fields
        if "initial_state" not in data:
            raise ScenarioLoadError("Scenario missing 'initial_state'")

        if "states" not in data:
            raise ScenarioLoadError("Scenario missing 'states'")

        # Parse states
        states: dict[str, IVRState] = {}
        for state_id, state_data in data["states"].items():
            states[state_id] = cls._parse_state(state_id, state_data)

        # Validate initial state exists
        if data["initial_state"] not in states:
            raise ScenarioLoadError(f"Initial state '{data['initial_state']}' not found in states")

        return IVRScenario(
            name=data.get("name", default_name),
            initial_state=data["initial_state"],
            states=states,
            expected_path=data.get("expected_path"),
            description=data.get("description"),
        )

    @classmethod
    def _parse_state(cls, state_id: str, data: dict[str, Any]) -> IVRState:
        """Parse state data into IVRState object.

        Args:
            state_id: The state identifier
            data: State data from YAML

        Returns:
            IVRState object

        Raises:
            ScenarioLoadError: If required fields are missing
        """
        if not isinstance(data, dict):
            raise ScenarioLoadError(f"State '{state_id}' must be a YAML object")

        if "transcript" not in data:
            raise ScenarioLoadError(f"State '{state_id}' missing 'transcript'")

        # Parse options
        options: list[IVRMenuOption] = []
        for opt_data in data.get("options", []):
            options.append(cls._parse_option(state_id, opt_data))

        return IVRState(
            id=state_id,
            transcript=data["transcript"].strip(),
            options=options,
            is_terminal=data.get("is_terminal", False),
            state_type=data.get("state_type", "menu"),
            timeout_action=data.get("timeout_action"),
            invalid_action=data.get("invalid_action"),
            max_repeats=data.get("max_repeats", 0),
        )

    @classmethod
    def _parse_option(cls, state_id: str, data: dict[str, Any]) -> IVRMenuOption:
        """Parse option data into IVRMenuOption object.

        Args:
            state_id: Parent state ID (for error messages)
            data: Option data from YAML

        Returns:
            IVRMenuOption object

        Raises:
            ScenarioLoadError: If required fields are missing
        """
        if not isinstance(data, dict):
            raise ScenarioLoadError(f"Option in state '{state_id}' must be a YAML object")

        required = {"digit", "next_state"}
        missing = required - set(data.keys())
        if missing:
            raise ScenarioLoadError(f"Option in state '{state_id}' missing fields: {missing}")

        return IVRMenuOption(
            digit=str(data["digit"]),
            description=data.get("description", ""),
            next_state=data["next_state"],
        )
