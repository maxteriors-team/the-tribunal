"""Multi-armed bandit arm selection using Thompson Sampling."""

import random
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bandit_decision import BanditDecision, DecisionType
from app.models.prompt_version import PromptVersion

logger = structlog.get_logger()


class BanditArmSelector:
    """Selects prompt versions (arms) using multi-armed bandit strategies.

    Supports Thompson Sampling as the primary strategy, with UCB and
    epsilon-greedy as alternatives.
    """

    async def select_arm(
        self,
        db: AsyncSession,
        agent_id: uuid.UUID,
        *,
        strategy: str = "thompson_sampling",
        context: dict[str, Any] | None = None,
        message_id: uuid.UUID | None = None,
        epsilon: float = 0.1,
    ) -> tuple[PromptVersion, BanditDecision]:
        """Select a prompt version arm for the given agent.

        Args:
            db: Database session
            agent_id: Agent ID to select arm for
            strategy: Selection strategy ("thompson_sampling", "ucb", "epsilon_greedy")
            context: Decision-time context snapshot
            message_id: Optional message ID to link decision to call
            epsilon: Exploration rate for epsilon-greedy strategy

        Returns:
            Tuple of (selected PromptVersion, BanditDecision record)

        Raises:
            ValueError: If no active prompt versions exist for the agent
        """
        log = logger.bind(
            service="bandit_arm_selector",
            agent_id=str(agent_id),
            strategy=strategy,
        )

        # Get all prompt versions for this agent
        result = await db.execute(
            select(PromptVersion)
            .where(PromptVersion.agent_id == agent_id)
            .where(PromptVersion.is_active.is_(True))
        )
        versions = list(result.scalars().all())

        if not versions:
            raise ValueError(f"No active prompt versions found for agent {agent_id}")

        # If only one version, select it directly
        if len(versions) == 1:
            selected = versions[0]
            decision_type = DecisionType.EXPLOIT
            arm_stats = self._build_arm_stats(selected, sampled_value=None)
        elif strategy == "thompson_sampling":
            selected, arm_stats, decision_type = self._thompson_sampling(versions)
        elif strategy == "ucb":
            selected, arm_stats, decision_type = self._ucb_selection(versions)
        elif strategy == "epsilon_greedy":
            selected, arm_stats, decision_type = self._epsilon_greedy(versions, epsilon)
        else:
            # Default to Thompson Sampling
            selected, arm_stats, decision_type = self._thompson_sampling(versions)

        log.info(
            "arm_selected",
            version_id=str(selected.id),
            version_number=selected.version_number,
            decision_type=decision_type.value,
        )

        # Create decision record
        decision = BanditDecision(
            agent_id=agent_id,
            arm_id=selected.id,
            message_id=message_id,
            decision_type=decision_type.value,
            exploration_rate=epsilon if strategy == "epsilon_greedy" else None,
            arm_statistics=arm_stats,
            context_snapshot=context or {},
        )

        db.add(decision)
        await db.commit()
        await db.refresh(decision)

        return selected, decision

    def _thompson_sampling(
        self, versions: list[PromptVersion]
    ) -> tuple[PromptVersion, dict[str, Any], DecisionType]:
        """Select arm using Thompson Sampling with Beta distributions.

        Each arm samples from Beta(alpha, beta) and the highest sample wins.
        """
        samples: list[tuple[PromptVersion, float]] = []

        for v in versions:
            # Sample from Beta distribution
            sampled = random.betavariate(v.bandit_alpha, v.bandit_beta)
            samples.append((v, sampled))

        # Select arm with highest sampled value
        samples.sort(key=lambda x: x[1], reverse=True)
        selected, sampled_value = samples[0]

        arm_stats = self._build_arm_stats(selected, sampled_value=sampled_value)

        return selected, arm_stats, DecisionType.THOMPSON_SAMPLING

    def _ucb_selection(
        self, versions: list[PromptVersion], c: float = 2.0
    ) -> tuple[PromptVersion, dict[str, Any], DecisionType]:
        """Select arm using Upper Confidence Bound (UCB1).

        UCB1 = mean_reward + c * sqrt(ln(total_pulls) / arm_pulls)
        """
        import math

        total_pulls = sum(v.reward_count for v in versions) + 1  # +1 to avoid log(0)

        ucb_values: list[tuple[PromptVersion, float, float]] = []

        for v in versions:
            if v.reward_count == 0:
                # Unexplored arms get infinite UCB (explore first)
                ucb = float("inf")
                mean_reward = 0.0
            else:
                mean_reward = v.total_reward / v.reward_count
                exploration_bonus = c * math.sqrt(math.log(total_pulls) / v.reward_count)
                ucb = mean_reward + exploration_bonus

            ucb_values.append((v, ucb, mean_reward))

        # Select arm with highest UCB
        ucb_values.sort(key=lambda x: x[1], reverse=True)
        selected, ucb_value, mean_reward = ucb_values[0]

        arm_stats = self._build_arm_stats(
            selected, sampled_value=ucb_value, extra={"ucb_value": ucb_value}
        )

        return selected, arm_stats, DecisionType.UCB

    def _epsilon_greedy(
        self, versions: list[PromptVersion], epsilon: float
    ) -> tuple[PromptVersion, dict[str, Any], DecisionType]:
        """Select arm using epsilon-greedy strategy.

        With probability epsilon, explore (random selection).
        With probability 1-epsilon, exploit (best mean reward).
        """
        if random.random() < epsilon:
            # Explore: random selection
            selected = random.choice(versions)
            arm_stats = self._build_arm_stats(selected, sampled_value=None)
            return selected, arm_stats, DecisionType.EXPLORE
        else:
            # Exploit: select best mean reward
            best_version = max(
                versions,
                key=lambda v: (v.total_reward / v.reward_count) if v.reward_count > 0 else 0.0,
            )
            arm_stats = self._build_arm_stats(best_version, sampled_value=None)
            return best_version, arm_stats, DecisionType.EXPLOIT

    def _build_arm_stats(
        self,
        version: PromptVersion,
        sampled_value: float | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build arm statistics snapshot."""
        mean_reward = (
            version.total_reward / version.reward_count if version.reward_count > 0 else 0.0
        )

        stats: dict[str, Any] = {
            "alpha": version.bandit_alpha,
            "beta": version.bandit_beta,
            "total_reward": version.total_reward,
            "reward_count": version.reward_count,
            "mean_reward": mean_reward,
        }

        if sampled_value is not None:
            stats["sampled_value"] = sampled_value

        if extra:
            stats.update(extra)

        return stats

    async def get_arm_by_message(
        self, db: AsyncSession, message_id: uuid.UUID
    ) -> BanditDecision | None:
        """Get the bandit decision for a specific message/call.

        Args:
            db: Database session
            message_id: Message ID to look up

        Returns:
            BanditDecision if found, None otherwise
        """
        result = await db.execute(
            select(BanditDecision).where(BanditDecision.message_id == message_id)
        )
        return result.scalar_one_or_none()
