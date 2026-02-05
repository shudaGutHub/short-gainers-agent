"""
Ranking module.

Combines technical scores with sentiment adjustments to produce final rankings.
"""

from src.ranking.ranker import (
    RISK_PENALTIES,
    RankingInput,
    RankingResult,
    compute_risk_penalty,
    determine_expression,
    get_top_candidates,
    has_dangerous_risk_profile_from_flags,
    rank_candidate,
    rank_candidates_batch,
    summarize_rankings,
)

__all__ = [
    "RISK_PENALTIES",
    "RankingInput",
    "RankingResult",
    "compute_risk_penalty",
    "determine_expression",
    "get_top_candidates",
    "has_dangerous_risk_profile_from_flags",
    "rank_candidate",
    "rank_candidates_batch",
    "summarize_rankings",
]
