"""Bayesian statistics service for multi-armed bandit analysis.

Provides statistical analysis for A/B testing including:
- Monte Carlo simulation for probability best
- Credible interval computation
- Winner detection
- Arm elimination recommendations
"""

import uuid
from dataclasses import dataclass

import numpy as np
import structlog

from app.models.prompt_version import PromptVersion

logger = structlog.get_logger()

# Minimum samples before statistical analysis is meaningful
MIN_SAMPLES_FOR_ANALYSIS = 30

# Default confidence threshold for declaring winners
DEFAULT_WINNER_THRESHOLD = 0.95

# Threshold for eliminating underperforming arms
DEFAULT_ELIMINATION_THRESHOLD = 0.99


@dataclass
class VersionStats:
    """Statistical summary for a prompt version."""

    version_id: uuid.UUID
    version_number: int
    is_active: bool
    is_baseline: bool
    arm_status: str
    alpha: float
    beta: float
    sample_size: int
    mean_estimate: float
    probability_best: float
    credible_interval: tuple[float, float]
    booking_rate: float | None


@dataclass
class ComparisonResult:
    """Result of comparing multiple versions."""

    versions: list[VersionStats]
    winner_id: uuid.UUID | None
    winner_probability: float | None
    recommended_action: str
    min_samples_needed: int


@dataclass
class WinnerResult:
    """Result of winner detection."""

    winner_id: uuid.UUID | None
    winner_probability: float | None
    confidence_threshold: float
    is_conclusive: bool
    message: str


class BanditStatisticsService:
    """Bayesian statistics for multi-armed bandit A/B testing.

    Uses Beta distributions to model conversion rates and Monte Carlo
    simulation to compute probabilities.
    """

    def __init__(self, random_seed: int | None = None) -> None:
        """Initialize the service.

        Args:
            random_seed: Optional seed for reproducible results in testing
        """
        self._rng = np.random.default_rng(random_seed)

    def compute_probability_best(
        self,
        versions: list[PromptVersion],
        num_samples: int = 10000,
    ) -> dict[uuid.UUID, float]:
        """Compute probability each version is the best using Monte Carlo.

        Samples from each version's Beta distribution and counts how often
        each version has the highest sampled value.

        Args:
            versions: List of prompt versions to compare
            num_samples: Number of Monte Carlo samples

        Returns:
            Dict mapping version_id to probability of being best
        """
        if not versions:
            return {}

        if len(versions) == 1:
            return {versions[0].id: 1.0}

        # Sample from each Beta distribution
        samples = np.zeros((len(versions), num_samples))
        for i, version in enumerate(versions):
            samples[i] = self._rng.beta(
                version.bandit_alpha,
                version.bandit_beta,
                size=num_samples,
            )

        # Find which version wins each sample
        winners = np.argmax(samples, axis=0)

        # Count wins for each version
        probabilities: dict[uuid.UUID, float] = {}
        for i, version in enumerate(versions):
            win_count = np.sum(winners == i)
            probabilities[version.id] = float(win_count / num_samples)

        return probabilities

    def compute_credible_interval(
        self,
        version: PromptVersion,
        confidence: float = 0.95,
    ) -> tuple[float, float]:
        """Compute Bayesian credible interval for conversion rate.

        Uses the Beta distribution's quantile function.

        Args:
            version: Prompt version to analyze
            confidence: Confidence level (e.g., 0.95 for 95%)

        Returns:
            Tuple of (lower_bound, upper_bound)
        """
        from scipy import stats

        alpha = version.bandit_alpha
        beta = version.bandit_beta

        # Calculate quantiles
        lower_quantile = (1 - confidence) / 2
        upper_quantile = 1 - lower_quantile

        lower = float(stats.beta.ppf(lower_quantile, alpha, beta))
        upper = float(stats.beta.ppf(upper_quantile, alpha, beta))

        return (lower, upper)

    def detect_winner(
        self,
        versions: list[PromptVersion],
        threshold: float = DEFAULT_WINNER_THRESHOLD,
        num_samples: int = 10000,
    ) -> WinnerResult:
        """Detect if a statistical winner can be declared.

        A winner is declared when one version has probability > threshold
        of being the best.

        Args:
            versions: List of prompt versions to compare
            threshold: Minimum probability to declare winner
            num_samples: Number of Monte Carlo samples

        Returns:
            WinnerResult with winner info or None
        """
        if not versions:
            return WinnerResult(
                winner_id=None,
                winner_probability=None,
                confidence_threshold=threshold,
                is_conclusive=False,
                message="No versions to compare",
            )

        if len(versions) == 1:
            return WinnerResult(
                winner_id=versions[0].id,
                winner_probability=1.0,
                confidence_threshold=threshold,
                is_conclusive=True,
                message="Only one version active",
            )

        # Check if we have enough samples
        total_samples = sum(v.reward_count for v in versions)
        min_needed = MIN_SAMPLES_FOR_ANALYSIS * len(versions)

        if total_samples < min_needed:
            return WinnerResult(
                winner_id=None,
                winner_probability=None,
                confidence_threshold=threshold,
                is_conclusive=False,
                message=f"Need {min_needed - total_samples} more samples for reliable analysis",
            )

        # Compute probabilities
        probabilities = self.compute_probability_best(versions, num_samples)

        # Find the best
        best_id = max(probabilities, key=lambda k: probabilities[k])
        best_prob = probabilities[best_id]

        if best_prob >= threshold:
            return WinnerResult(
                winner_id=best_id,
                winner_probability=best_prob,
                confidence_threshold=threshold,
                is_conclusive=True,
                message=f"Version has {best_prob:.1%} probability of being best",
            )

        return WinnerResult(
            winner_id=best_id,
            winner_probability=best_prob,
            confidence_threshold=threshold,
            is_conclusive=False,
            message=f"Leading version has {best_prob:.1%} probability (need {threshold:.0%})",
        )

    def should_eliminate(
        self,
        version: PromptVersion,
        best_version: PromptVersion,
        threshold: float = DEFAULT_ELIMINATION_THRESHOLD,
        num_samples: int = 10000,
    ) -> bool:
        """Check if a version should be eliminated from testing.

        A version should be eliminated if there's > threshold probability
        that it's worse than the best version.

        Args:
            version: Version to potentially eliminate
            best_version: Current best version
            threshold: Probability threshold for elimination
            num_samples: Number of Monte Carlo samples

        Returns:
            True if version should be eliminated
        """
        if version.id == best_version.id:
            return False

        # Sample from both distributions
        version_samples = self._rng.beta(
            version.bandit_alpha,
            version.bandit_beta,
            size=num_samples,
        )
        best_samples = self._rng.beta(
            best_version.bandit_alpha,
            best_version.bandit_beta,
            size=num_samples,
        )

        # Count how often version is worse than best
        worse_count = np.sum(version_samples < best_samples)
        prob_worse = float(worse_count / num_samples)

        return prob_worse >= threshold

    def get_elimination_candidates(
        self,
        versions: list[PromptVersion],
        threshold: float = DEFAULT_ELIMINATION_THRESHOLD,
        num_samples: int = 10000,
    ) -> list[uuid.UUID]:
        """Get list of versions that should be eliminated.

        Args:
            versions: List of versions to analyze
            threshold: Probability threshold for elimination
            num_samples: Number of Monte Carlo samples

        Returns:
            List of version IDs that should be eliminated
        """
        if len(versions) < 2:
            return []

        # Find current best (highest mean estimate)
        best_version = max(
            versions,
            key=lambda v: v.bandit_alpha / (v.bandit_alpha + v.bandit_beta),
        )

        candidates: list[uuid.UUID] = []
        for version in versions:
            if version.id != best_version.id and self.should_eliminate(
                version, best_version, threshold, num_samples
            ):
                candidates.append(version.id)

        return candidates

    def compare_versions(
        self,
        versions: list[PromptVersion],
        winner_threshold: float = DEFAULT_WINNER_THRESHOLD,
        elimination_threshold: float = DEFAULT_ELIMINATION_THRESHOLD,
        num_samples: int = 10000,
    ) -> ComparisonResult:
        """Comprehensive comparison of all versions.

        Args:
            versions: List of versions to compare
            winner_threshold: Threshold to declare winner
            elimination_threshold: Threshold to recommend elimination
            num_samples: Number of Monte Carlo samples

        Returns:
            ComparisonResult with full analysis
        """
        if not versions:
            return ComparisonResult(
                versions=[],
                winner_id=None,
                winner_probability=None,
                recommended_action="no_versions",
                min_samples_needed=0,
            )

        # Compute probability best for all versions
        probabilities = self.compute_probability_best(versions, num_samples)

        # Build version stats
        version_stats: list[VersionStats] = []
        for version in versions:
            ci = self.compute_credible_interval(version)
            mean = version.bandit_alpha / (version.bandit_alpha + version.bandit_beta)
            sample_size = version.reward_count

            # Compute booking rate from denormalized counters
            booking_rate = None
            if version.successful_calls > 0:
                booking_rate = version.booked_appointments / version.successful_calls

            version_stats.append(
                VersionStats(
                    version_id=version.id,
                    version_number=version.version_number,
                    is_active=version.is_active,
                    is_baseline=version.is_baseline,
                    arm_status=version.arm_status,
                    alpha=version.bandit_alpha,
                    beta=version.bandit_beta,
                    sample_size=sample_size,
                    mean_estimate=mean,
                    probability_best=probabilities.get(version.id, 0.0),
                    credible_interval=ci,
                    booking_rate=booking_rate,
                )
            )

        # Sort by probability best descending
        version_stats.sort(key=lambda v: v.probability_best, reverse=True)

        # Detect winner
        winner_result = self.detect_winner(versions, winner_threshold, num_samples)

        # Determine recommended action
        total_samples = sum(v.reward_count for v in versions)
        min_samples_needed = MIN_SAMPLES_FOR_ANALYSIS * len(versions)

        if total_samples < min_samples_needed:
            recommended_action = "continue"
        elif winner_result.is_conclusive:
            recommended_action = "declare_winner"
        else:
            # Check if any should be eliminated
            elimination_candidates = self.get_elimination_candidates(
                versions, elimination_threshold, num_samples
            )
            recommended_action = "eliminate_worst" if elimination_candidates else "continue"

        return ComparisonResult(
            versions=version_stats,
            winner_id=winner_result.winner_id,
            winner_probability=winner_result.winner_probability,
            recommended_action=recommended_action,
            min_samples_needed=max(0, min_samples_needed - total_samples),
        )

    def get_mean_estimate(self, version: PromptVersion) -> float:
        """Get the mean estimate of the conversion rate.

        Args:
            version: Prompt version

        Returns:
            Mean of the Beta distribution (alpha / (alpha + beta))
        """
        return version.bandit_alpha / (version.bandit_alpha + version.bandit_beta)

    def get_variance(self, version: PromptVersion) -> float:
        """Get the variance of the conversion rate estimate.

        Args:
            version: Prompt version

        Returns:
            Variance of the Beta distribution
        """
        alpha = version.bandit_alpha
        beta = version.bandit_beta
        return (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))

    def get_standard_error(self, version: PromptVersion) -> float:
        """Get the standard error of the conversion rate estimate.

        Args:
            version: Prompt version

        Returns:
            Standard deviation of the Beta distribution
        """
        return float(np.sqrt(self.get_variance(version)))


# Convenience function for single-use
def compare_prompt_versions(
    versions: list[PromptVersion],
    winner_threshold: float = DEFAULT_WINNER_THRESHOLD,
) -> ComparisonResult:
    """Compare prompt versions and return analysis.

    Args:
        versions: List of versions to compare
        winner_threshold: Threshold to declare winner

    Returns:
        ComparisonResult with full analysis
    """
    service = BanditStatisticsService()
    return service.compare_versions(versions, winner_threshold)
