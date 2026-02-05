"""
Sentiment and catalyst analysis module.

Classifies news catalysts and adjusts scores based on fundamental vs speculative moves.
"""

from src.sentiment.catalyst import (
    CATALYST_SCORE_ADJUSTMENTS,
    SENTIMENT_ADJUSTMENTS,
    SentimentResult,
    analyze_catalyst,
    analyze_catalysts_batch,
    compute_score_adjustment,
    format_catalyst_summary,
    get_risk_flag_from_sentiment,
    heuristic_catalyst_detection,
    should_avoid_short,
)

__all__ = [
    "CATALYST_SCORE_ADJUSTMENTS",
    "SENTIMENT_ADJUSTMENTS",
    "SentimentResult",
    "analyze_catalyst",
    "analyze_catalysts_batch",
    "compute_score_adjustment",
    "format_catalyst_summary",
    "get_risk_flag_from_sentiment",
    "heuristic_catalyst_detection",
    "should_avoid_short",
]
