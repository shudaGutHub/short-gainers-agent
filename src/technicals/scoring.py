"""
Technical scoring for short candidates.

Combines multiple indicators into a single 0-10 score where:
- 10 = extremely overbought, high probability of pullback
- 0 = no short edge, strong uptrend with confirmation
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pandas as pd

from config.settings import Settings, Thresholds
from src.models.candidate import TechnicalState
from src.technicals.indicators import (
    BollingerResult,
    MACDResult,
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
from src.models.ticker import OHLCVSeries


@dataclass
class TechScoreBreakdown:
    """Detailed breakdown of technical score components."""

    rsi_score: float = 0.0
    bollinger_score: float = 0.0
    macd_score: float = 0.0
    volume_score: float = 0.0
    momentum_score: float = 0.0
    pattern_score: float = 0.0
    total_score: float = 0.0

    def __str__(self) -> str:
        return (
            f"RSI={self.rsi_score:.1f} BB={self.bollinger_score:.1f} "
            f"MACD={self.macd_score:.1f} VOL={self.volume_score:.1f} "
            f"MOM={self.momentum_score:.1f} PAT={self.pattern_score:.1f} "
            f"TOTAL={self.total_score:.1f}"
        )


def score_rsi(rsi: Optional[Decimal], settings: Settings) -> float:
    """
    Score RSI for short attractiveness.

    Higher RSI = more overbought = higher score.

    Args:
        rsi: Current RSI value (0-100)
        settings: Config settings

    Returns:
        Score from 0.0 to 2.0
    """
    if rsi is None:
        return 0.0

    rsi_val = float(rsi)

    if rsi_val >= 90:
        return 2.0  # Extremely overbought
    elif rsi_val >= 80:
        return 1.7
    elif rsi_val >= 70:
        return 1.3
    elif rsi_val >= 60:
        return 0.8
    elif rsi_val >= 50:
        return 0.3
    else:
        return 0.0  # Not overbought


def score_bollinger(bb: BollingerResult) -> float:
    """
    Score Bollinger Bands position for short attractiveness.

    Price above upper band = overextended = higher score.

    Args:
        bb: BollingerResult with current values

    Returns:
        Score from 0.0 to 2.0
    """
    if bb.percent_b is None:
        return 0.0

    pct_b = float(bb.percent_b)

    if bb.price_above_upper:
        return 2.0  # Above upper band - very overextended
    elif pct_b >= 0.95:
        return 1.7  # Near upper band
    elif pct_b >= 0.80:
        return 1.3
    elif pct_b >= 0.60:
        return 0.7
    elif pct_b >= 0.50:
        return 0.3
    else:
        return 0.0  # Below middle band


def score_macd(macd: MACDResult) -> float:
    """
    Score MACD for short attractiveness.

    Declining histogram after being positive = momentum weakening = higher score.

    Args:
        macd: MACDResult with current values

    Returns:
        Score from 0.0 to 1.5
    """
    if macd.histogram is None:
        return 0.0

    hist = float(macd.histogram)
    score = 0.0

    # Histogram declining is bearish for longs (good for shorts)
    if macd.histogram_declining:
        score += 0.8

    # Histogram positive but small = momentum weakening
    if hist > 0 and hist < 0.1:
        score += 0.4

    # MACD line below signal line = bearish crossover
    if macd.macd_line is not None and macd.signal_line is not None:
        if float(macd.macd_line) < float(macd.signal_line):
            score += 0.3

    return min(score, 1.5)


def score_volume(
    volume_vs_avg: Optional[Decimal],
    volume_confirming: bool,
) -> float:
    """
    Score volume characteristics for short attractiveness.

    Volume divergence (price up, volume down) = higher score.

    Args:
        volume_vs_avg: Current volume as multiple of average
        volume_confirming: Whether volume confirms price direction

    Returns:
        Score from 0.0 to 1.5
    """
    score = 0.0

    # Volume divergence is bearish for longs
    if not volume_confirming:
        score += 1.0

    # Low relative volume on up move = weak conviction
    if volume_vs_avg is not None:
        vol_ratio = float(volume_vs_avg)
        if vol_ratio < 0.7:
            score += 0.5  # Very low volume
        elif vol_ratio < 1.0:
            score += 0.2  # Below average

    return min(score, 1.5)


def score_momentum(
    roc_1d: Optional[Decimal],
    roc_3d: Optional[Decimal],
    roc_5d: Optional[Decimal],
) -> float:
    """
    Score momentum/ROC for short attractiveness.

    Extremely high ROC = parabolic move = higher score.

    Args:
        roc_1d: 1-day rate of change
        roc_3d: 3-day rate of change
        roc_5d: 5-day rate of change

    Returns:
        Score from 0.0 to 1.5
    """
    score = 0.0

    # Extreme 1-day move
    if roc_1d is not None:
        r1 = float(roc_1d)
        if r1 >= 50:
            score += 0.6
        elif r1 >= 30:
            score += 0.4
        elif r1 >= 20:
            score += 0.2

    # Extreme multi-day move
    if roc_5d is not None:
        r5 = float(roc_5d)
        if r5 >= 100:
            score += 0.6
        elif r5 >= 50:
            score += 0.4
        elif r5 >= 30:
            score += 0.2

    # Decelerating momentum (3d < 5d scaled)
    if roc_3d is not None and roc_5d is not None:
        r3 = float(roc_3d)
        r5 = float(roc_5d)
        # If 3-day ROC is less than 60% of 5-day, momentum slowing
        if r5 > 0 and r3 < r5 * 0.6:
            score += 0.3

    return min(score, 1.5)


def score_patterns(lower_high: bool, exhaustion: bool) -> float:
    """
    Score price patterns for short attractiveness.

    Reversal patterns = higher score.

    Args:
        lower_high: Whether lower high pattern detected
        exhaustion: Whether exhaustion candle detected

    Returns:
        Score from 0.0 to 1.5
    """
    score = 0.0

    if lower_high:
        score += 0.8

    if exhaustion:
        score += 0.7

    return min(score, 1.5)


def compute_technical_score(
    daily_df: pd.DataFrame,
    intraday_df: Optional[pd.DataFrame],
    settings: Settings,
) -> tuple[Decimal, TechScoreBreakdown, TechnicalState]:
    """
    Compute comprehensive technical score for short attractiveness.

    Args:
        daily_df: Daily OHLCV DataFrame
        intraday_df: Intraday OHLCV DataFrame (optional)
        settings: Config settings

    Returns:
        Tuple of (score 0-10, breakdown, TechnicalState)
    """
    breakdown = TechScoreBreakdown()

    # --- RSI ---
    rsi_daily = get_current_rsi(daily_df, settings.rsi_period)
    rsi_intraday = None
    if intraday_df is not None and not intraday_df.empty:
        rsi_intraday = get_current_rsi(intraday_df, settings.rsi_period)

    # Use higher of daily/intraday RSI
    rsi_for_scoring = rsi_daily
    if rsi_intraday is not None and rsi_daily is not None:
        rsi_for_scoring = max(rsi_daily, rsi_intraday)

    breakdown.rsi_score = score_rsi(rsi_for_scoring, settings)

    # --- Bollinger Bands ---
    bb = get_current_bollinger(daily_df, settings.bollinger_window, settings.bollinger_std)
    breakdown.bollinger_score = score_bollinger(bb)

    # --- MACD ---
    macd = get_current_macd(
        daily_df, settings.macd_fast, settings.macd_slow, settings.macd_signal
    )
    breakdown.macd_score = score_macd(macd)

    # --- Volume ---
    volume_vs_avg = get_volume_vs_average(daily_df, 20)
    volume_confirming = is_volume_confirming_price(daily_df, 5)
    breakdown.volume_score = score_volume(volume_vs_avg, volume_confirming)

    # --- Momentum ---
    roc_1d = get_current_roc(daily_df, 1)
    roc_3d = get_current_roc(daily_df, 3)
    roc_5d = get_current_roc(daily_df, 5)
    breakdown.momentum_score = score_momentum(roc_1d, roc_3d, roc_5d)

    # --- Patterns ---
    lower_high = detect_lower_high(daily_df, 10)
    exhaustion = detect_exhaustion_candle(daily_df)

    # Also check intraday for patterns
    if intraday_df is not None and not intraday_df.empty:
        lower_high = lower_high or detect_lower_high(intraday_df, 20)
        exhaustion = exhaustion or detect_exhaustion_candle(intraday_df)

    breakdown.pattern_score = score_patterns(lower_high, exhaustion)

    # --- Total Score ---
    # Weighted sum, max 10
    raw_total = (
        breakdown.rsi_score * settings.weight_rsi / 0.20
        + breakdown.bollinger_score * settings.weight_bollinger / 0.20
        + breakdown.macd_score * settings.weight_macd / 0.15
        + breakdown.volume_score * settings.weight_volume / 0.15
        + breakdown.momentum_score * settings.weight_momentum / 0.15
        + breakdown.pattern_score * settings.weight_pattern / 0.15
    )

    # Normalize to 0-10 scale
    breakdown.total_score = min(raw_total, 10.0)

    # --- Build TechnicalState ---
    atr_daily = get_current_atr(daily_df, settings.atr_period)
    atr_pct = get_atr_percent(daily_df, settings.atr_period)
    obv_trend = get_obv_trend(daily_df, 5)

    tech_state = TechnicalState(
        rsi_daily=rsi_daily,
        rsi_intraday=rsi_intraday,
        macd_line=macd.macd_line,
        macd_signal=macd.signal_line,
        macd_histogram=macd.histogram,
        macd_histogram_declining=macd.histogram_declining,
        bollinger_upper=bb.upper,
        bollinger_middle=bb.middle,
        bollinger_lower=bb.lower,
        bollinger_position=bb.percent_b,
        price_above_upper_band=bb.price_above_upper,
        atr_daily=atr_daily,
        atr_percent=atr_pct,
        obv_trend=obv_trend,
        volume_vs_avg=volume_vs_avg,
        volume_confirming_price=volume_confirming,
        roc_1d=roc_1d,
        roc_3d=roc_3d,
        roc_5d=roc_5d,
        lower_high_forming=lower_high,
        exhaustion_candle=exhaustion,
    )

    return Decimal(str(round(breakdown.total_score, 1))), breakdown, tech_state


def compute_technical_score_from_series(
    daily: OHLCVSeries,
    intraday: Optional[OHLCVSeries],
    settings: Settings,
) -> tuple[Decimal, TechScoreBreakdown, TechnicalState]:
    """
    Convenience wrapper that accepts OHLCVSeries.

    Args:
        daily: Daily OHLCVSeries
        intraday: Intraday OHLCVSeries (optional)
        settings: Config settings

    Returns:
        Tuple of (score 0-10, breakdown, TechnicalState)
    """
    daily_df = series_to_dataframe(daily)

    intraday_df = None
    if intraday is not None and not intraday.is_empty:
        intraday_df = series_to_dataframe(intraday)

    return compute_technical_score(daily_df, intraday_df, settings)


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------


def is_technically_overextended(tech_state: TechnicalState) -> bool:
    """
    Quick check if technical state indicates overextension.

    Returns True if multiple overbought signals present.
    """
    signals = 0

    if tech_state.rsi_daily is not None and tech_state.rsi_daily >= 70:
        signals += 1

    if tech_state.price_above_upper_band:
        signals += 1

    if tech_state.roc_5d is not None and tech_state.roc_5d >= 50:
        signals += 1

    return signals >= 2


def get_sizing_hint(tech_state: TechnicalState, price: Decimal) -> str:
    """
    Generate position sizing hint based on ATR.

    Args:
        tech_state: TechnicalState with ATR data
        price: Current price

    Returns:
        Human-readable sizing hint
    """
    if tech_state.atr_daily is None:
        return "ATR unavailable - use 5% of price as stop distance"

    atr = float(tech_state.atr_daily)
    atr_pct = float(tech_state.atr_percent) if tech_state.atr_percent else (atr / float(price) * 100)

    return (
        f"1R = ${atr:.2f} ({atr_pct:.1f}% of price). "
        f"Size position so 1 ATR adverse move = 1R loss."
    )
