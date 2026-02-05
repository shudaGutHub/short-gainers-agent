"""
Technical indicator calculations using pandas-ta.

All functions are pure and stateless - they take price data and return indicator values.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.models.ticker import OHLCVSeries


def series_to_dataframe(series: OHLCVSeries) -> pd.DataFrame:
    """
    Convert OHLCVSeries to pandas DataFrame for indicator calculations.

    Args:
        series: OHLCVSeries with OHLCV bars

    Returns:
        DataFrame with columns: open, high, low, close, volume (lowercase)
        Index is timestamp, sorted ascending (oldest first)
    """
    if series.is_empty:
        return pd.DataFrame()

    data = [
        {
            "timestamp": bar.timestamp,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": bar.volume,
        }
        for bar in series.bars
    ]

    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    df.sort_index(ascending=True, inplace=True)

    return df


# -----------------------------------------------------------------------------
# RSI - Relative Strength Index
# -----------------------------------------------------------------------------


def compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    """
    Compute RSI (Relative Strength Index).

    Args:
        df: DataFrame with 'close' column
        period: RSI period (default 14)

    Returns:
        Series of RSI values, or None if insufficient data
    """
    if df.empty or len(df) < period + 1:
        return None

    return ta.rsi(df["close"], length=period)


def get_current_rsi(df: pd.DataFrame, period: int = 14) -> Optional[Decimal]:
    """Get most recent RSI value."""
    rsi = compute_rsi(df, period)
    if rsi is None or rsi.empty:
        return None

    latest = rsi.iloc[-1]
    if pd.isna(latest):
        return None

    return Decimal(str(round(latest, 2)))


# -----------------------------------------------------------------------------
# MACD - Moving Average Convergence Divergence
# -----------------------------------------------------------------------------


@dataclass
class MACDResult:
    """MACD indicator values."""

    macd_line: Optional[Decimal]
    signal_line: Optional[Decimal]
    histogram: Optional[Decimal]
    histogram_declining: bool = False


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[pd.DataFrame]:
    """
    Compute MACD indicator.

    Args:
        df: DataFrame with 'close' column
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line period (default 9)

    Returns:
        DataFrame with MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9 columns
    """
    if df.empty or len(df) < slow + signal:
        return None

    return ta.macd(df["close"], fast=fast, slow=slow, signal=signal)


def get_current_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """Get most recent MACD values."""
    macd_df = compute_macd(df, fast, slow, signal)

    if macd_df is None or macd_df.empty:
        return MACDResult(None, None, None)

    col_macd = f"MACD_{fast}_{slow}_{signal}"
    col_signal = f"MACDs_{fast}_{slow}_{signal}"
    col_hist = f"MACDh_{fast}_{slow}_{signal}"

    macd_line = macd_df[col_macd].iloc[-1]
    signal_line = macd_df[col_signal].iloc[-1]
    histogram = macd_df[col_hist].iloc[-1]

    # Check if histogram is declining (momentum weakening)
    histogram_declining = False
    if len(macd_df) >= 3:
        hist_series = macd_df[col_hist].iloc[-3:]
        if not hist_series.isna().any():
            # Declining if each value is less than previous
            histogram_declining = (
                hist_series.iloc[-1] < hist_series.iloc[-2] < hist_series.iloc[-3]
            )

    return MACDResult(
        macd_line=Decimal(str(round(macd_line, 4))) if not pd.isna(macd_line) else None,
        signal_line=Decimal(str(round(signal_line, 4))) if not pd.isna(signal_line) else None,
        histogram=Decimal(str(round(histogram, 4))) if not pd.isna(histogram) else None,
        histogram_declining=histogram_declining,
    )


# -----------------------------------------------------------------------------
# Bollinger Bands
# -----------------------------------------------------------------------------


@dataclass
class BollingerResult:
    """Bollinger Bands values."""

    upper: Optional[Decimal]
    middle: Optional[Decimal]
    lower: Optional[Decimal]
    bandwidth: Optional[Decimal]
    percent_b: Optional[Decimal]  # 0 = at lower, 1 = at upper
    price_above_upper: bool = False


def compute_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> Optional[pd.DataFrame]:
    """
    Compute Bollinger Bands.

    Args:
        df: DataFrame with 'close' column
        period: SMA period (default 20)
        std_dev: Standard deviation multiplier (default 2.0)

    Returns:
        DataFrame with BBL, BBM, BBU, BBB, BBP columns
    """
    if df.empty or len(df) < period:
        return None

    return ta.bbands(df["close"], length=period, std=std_dev)


def get_current_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    """Get most recent Bollinger Bands values."""
    bb_df = compute_bollinger(df, period, std_dev)

    if bb_df is None or bb_df.empty:
        return BollingerResult(None, None, None, None, None)

    # pandas-ta column naming can vary, find columns dynamically
    cols = bb_df.columns.tolist()
    
    col_lower = [c for c in cols if c.startswith("BBL_")][0] if any(c.startswith("BBL_") for c in cols) else None
    col_middle = [c for c in cols if c.startswith("BBM_")][0] if any(c.startswith("BBM_") for c in cols) else None
    col_upper = [c for c in cols if c.startswith("BBU_")][0] if any(c.startswith("BBU_") for c in cols) else None
    col_bandwidth = [c for c in cols if c.startswith("BBB_")][0] if any(c.startswith("BBB_") for c in cols) else None
    col_percent = [c for c in cols if c.startswith("BBP_")][0] if any(c.startswith("BBP_") for c in cols) else None

    upper = bb_df[col_upper].iloc[-1] if col_upper else None
    middle = bb_df[col_middle].iloc[-1] if col_middle else None
    lower = bb_df[col_lower].iloc[-1] if col_lower else None
    bandwidth = bb_df[col_bandwidth].iloc[-1] if col_bandwidth else None
    percent_b = bb_df[col_percent].iloc[-1] if col_percent else None

    current_close = df["close"].iloc[-1]
    price_above_upper = current_close > upper if upper is not None and not pd.isna(upper) else False

    return BollingerResult(
        upper=Decimal(str(round(upper, 4))) if upper is not None and not pd.isna(upper) else None,
        middle=Decimal(str(round(middle, 4))) if middle is not None and not pd.isna(middle) else None,
        lower=Decimal(str(round(lower, 4))) if lower is not None and not pd.isna(lower) else None,
        bandwidth=Decimal(str(round(bandwidth, 4))) if bandwidth is not None and not pd.isna(bandwidth) else None,
        percent_b=Decimal(str(round(percent_b, 4))) if percent_b is not None and not pd.isna(percent_b) else None,
        price_above_upper=price_above_upper,
    )


# -----------------------------------------------------------------------------
# ATR - Average True Range
# -----------------------------------------------------------------------------


def compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    """
    Compute ATR (Average True Range).

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: ATR period (default 14)

    Returns:
        Series of ATR values
    """
    if df.empty or len(df) < period + 1:
        return None

    return ta.atr(df["high"], df["low"], df["close"], length=period)


def get_current_atr(df: pd.DataFrame, period: int = 14) -> Optional[Decimal]:
    """Get most recent ATR value."""
    atr = compute_atr(df, period)
    if atr is None or atr.empty:
        return None

    latest = atr.iloc[-1]
    if pd.isna(latest):
        return None

    return Decimal(str(round(latest, 4)))


def get_atr_percent(df: pd.DataFrame, period: int = 14) -> Optional[Decimal]:
    """Get ATR as percentage of current price."""
    atr = get_current_atr(df, period)
    if atr is None:
        return None

    current_price = df["close"].iloc[-1]
    if current_price == 0:
        return None

    atr_pct = (float(atr) / current_price) * 100
    return Decimal(str(round(atr_pct, 2)))


# -----------------------------------------------------------------------------
# OBV - On Balance Volume
# -----------------------------------------------------------------------------


def compute_obv(df: pd.DataFrame) -> Optional[pd.Series]:
    """
    Compute OBV (On Balance Volume).

    Args:
        df: DataFrame with 'close' and 'volume' columns

    Returns:
        Series of OBV values
    """
    if df.empty or len(df) < 2:
        return None

    return ta.obv(df["close"], df["volume"])


def get_obv_trend(df: pd.DataFrame, lookback: int = 5) -> Optional[str]:
    """
    Determine OBV trend over recent bars.

    Args:
        df: DataFrame with price/volume data
        lookback: Number of bars to analyze

    Returns:
        "rising", "falling", or "flat"
    """
    obv = compute_obv(df)
    if obv is None or len(obv) < lookback:
        return None

    recent_obv = obv.iloc[-lookback:]

    # Simple linear regression slope
    x = np.arange(len(recent_obv))
    y = recent_obv.values

    if np.any(np.isnan(y)):
        return None

    slope = np.polyfit(x, y, 1)[0]

    # Normalize slope by OBV magnitude
    obv_range = recent_obv.max() - recent_obv.min()
    if obv_range == 0:
        return "flat"

    normalized_slope = slope / (obv_range / len(recent_obv))

    if normalized_slope > 0.1:
        return "rising"
    elif normalized_slope < -0.1:
        return "falling"
    else:
        return "flat"


# -----------------------------------------------------------------------------
# ROC - Rate of Change / Momentum
# -----------------------------------------------------------------------------


def compute_roc(df: pd.DataFrame, period: int = 10) -> Optional[pd.Series]:
    """
    Compute ROC (Rate of Change).

    Args:
        df: DataFrame with 'close' column
        period: ROC period

    Returns:
        Series of ROC values (percentage change)
    """
    if df.empty or len(df) < period + 1:
        return None

    return ta.roc(df["close"], length=period)


def get_current_roc(df: pd.DataFrame, period: int = 10) -> Optional[Decimal]:
    """Get most recent ROC value."""
    roc = compute_roc(df, period)
    if roc is None or roc.empty:
        return None

    latest = roc.iloc[-1]
    if pd.isna(latest):
        return None

    return Decimal(str(round(latest, 2)))


# -----------------------------------------------------------------------------
# Volume Analysis
# -----------------------------------------------------------------------------


def get_volume_vs_average(df: pd.DataFrame, period: int = 20) -> Optional[Decimal]:
    """
    Get current volume as multiple of average volume.

    Args:
        df: DataFrame with 'volume' column
        period: Averaging period

    Returns:
        Ratio of current volume to average (e.g., 2.5 = 250% of average)
    """
    if df.empty or len(df) < period:
        return None

    avg_volume = df["volume"].iloc[-period:].mean()
    current_volume = df["volume"].iloc[-1]

    if avg_volume == 0:
        return None

    ratio = current_volume / avg_volume
    return Decimal(str(round(ratio, 2)))


def is_volume_confirming_price(df: pd.DataFrame, lookback: int = 5) -> bool:
    """
    Check if volume confirms price movement.

    For an upward move, volume should be rising with price.
    Divergence (price up, volume down) is bearish.

    Args:
        df: DataFrame with price/volume data
        lookback: Number of bars to analyze

    Returns:
        True if volume confirms price direction
    """
    if df.empty or len(df) < lookback:
        return True  # Default to True if insufficient data

    recent = df.iloc[-lookback:]

    price_change = recent["close"].iloc[-1] - recent["close"].iloc[0]
    volume_change = recent["volume"].iloc[-1] - recent["volume"].iloc[0]

    # Price up + volume up = confirming
    # Price up + volume down = divergence (not confirming)
    if price_change > 0:
        return bool(volume_change > 0)

    # Price down + volume up = confirming selling
    # Price down + volume down = not confirming
    return bool(volume_change > 0)


# -----------------------------------------------------------------------------
# Pattern Detection
# -----------------------------------------------------------------------------


def detect_lower_high(df: pd.DataFrame, lookback: int = 10) -> bool:
    """
    Detect if price is forming a lower high pattern.

    This is a potential reversal signal after an uptrend.

    Args:
        df: DataFrame with 'high' column
        lookback: Number of bars to analyze

    Returns:
        True if lower high pattern detected
    """
    if df.empty or len(df) < lookback:
        return False

    recent = df.iloc[-lookback:]
    highs = recent["high"].values

    # Find peaks (local maxima)
    peaks = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            peaks.append((i, highs[i]))

    if len(peaks) < 2:
        return False

    # Check if most recent peak is lower than previous
    return bool(peaks[-1][1] < peaks[-2][1])


def detect_exhaustion_candle(df: pd.DataFrame) -> bool:
    """
    Detect exhaustion candle pattern.

    Characteristics:
    - Large range (high volatility)
    - Long upper wick (rejection)
    - Close near low of range
    - High volume

    Args:
        df: DataFrame with OHLCV data

    Returns:
        True if exhaustion pattern detected
    """
    if df.empty or len(df) < 20:
        return False

    last = df.iloc[-1]
    recent = df.iloc[-20:]

    # Calculate average range
    avg_range = (recent["high"] - recent["low"]).mean()
    current_range = last["high"] - last["low"]

    # Large range (> 1.5x average)
    if current_range < avg_range * 1.5:
        return False

    # Calculate upper wick ratio
    body_top = max(last["open"], last["close"])
    upper_wick = last["high"] - body_top
    upper_wick_ratio = upper_wick / current_range if current_range > 0 else 0

    # Long upper wick (> 40% of range)
    if upper_wick_ratio < 0.4:
        return False

    # Close in lower half of range
    close_position = (last["close"] - last["low"]) / current_range if current_range > 0 else 0.5
    if close_position > 0.5:
        return False

    # High volume (> 1.5x average)
    avg_volume = recent["volume"].mean()
    if last["volume"] < avg_volume * 1.5:
        return False

    return True
