"""
Pre-filtering module.

Applies safety checks and risk assessment to filter short candidates.
"""

from src.filters.prefilter import (
    PrefilterResult,
    assess_shortability,
    check_exchange,
    check_market_cap,
    check_squeeze_risk,
    check_volume,
    get_risk_summary,
    has_dangerous_risk_profile,
    prefilter_batch,
    prefilter_ticker,
    summarize_exclusions,
)

__all__ = [
    "PrefilterResult",
    "assess_shortability",
    "check_exchange",
    "check_market_cap",
    "check_squeeze_risk",
    "check_volume",
    "get_risk_summary",
    "has_dangerous_risk_profile",
    "prefilter_batch",
    "prefilter_ticker",
    "summarize_exclusions",
]
