"""Seasonal-business primitives that outlive any one campaign feature.

Holiday lighting is bought once a year, which makes "which season does this
belong to?" a question several parts of the product need to answer the same way.
This package owns that arithmetic so a renewal campaign, a report, and a saved
segment can never disagree about who last season's customers were.
"""

from app.services.seasonal.christmas_renewal import (
    ChristmasSeason,
    current_season,
    prior_season_christmas_condition,
    resolve_christmas_season,
)

__all__ = [
    "ChristmasSeason",
    "current_season",
    "prior_season_christmas_condition",
    "resolve_christmas_season",
]
