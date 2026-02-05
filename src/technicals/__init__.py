"""
Technical analysis module.

Provides indicator calculations and scoring for short candidates.
"""

from src.technicals.indicators import (
    BollingerResult,
    MACDResult,
    compute_atr,
    compute_bollinger,
    compute_macd,
    compute_obv,
    compute_roc,
    compute_rsi,
    detect_exhaustion_candle,
    detect_lower_high,
    get_atr_percent,
    get_current_atr,
    get_current_bollinger,
    get_current_macd,
    get_current_roc,
    get_current_rsi,
    get_obv_trend,
    get_volume_vs_average,
    is_volume_confirming_price,
    series_to_dataframe,
)
from src.technicals.scoring import (
    TechScoreBreakdown,
    compute_technical_score,
    compute_technical_score_from_series,
    get_sizing_hint,
    is_technically_overextended,
    score_bollinger,
    score_macd,
    score_momentum,
    score_patterns,
    score_rsi,
    score_volume,
)

__all__ = [
    # Indicator dataclasses
    "BollingerResult",
    "MACDResult",
    # Indicator functions
    "compute_atr",
    "compute_bollinger",
    "compute_macd",
    "compute_obv",
    "compute_roc",
    "compute_rsi",
    "detect_exhaustion_candle",
    "detect_lower_high",
    "get_atr_percent",
    "get_current_atr",
    "get_current_bollinger",
    "get_current_macd",
    "get_current_roc",
    "get_current_rsi",
    "get_obv_trend",
    "get_volume_vs_average",
    "is_volume_confirming_price",
    "series_to_dataframe",
    # Scoring
    "TechScoreBreakdown",
    "compute_technical_score",
    "compute_technical_score_from_series",
    "get_sizing_hint",
    "is_technically_overextended",
    "score_bollinger",
    "score_macd",
    "score_momentum",
    "score_patterns",
    "score_rsi",
    "score_volume",
]
