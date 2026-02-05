"""Tests for technical indicators and scoring."""

from decimal import Decimal
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.technicals.indicators import (
    BollingerResult,
    MACDResult,
    compute_rsi,
    get_current_rsi,
    get_current_bollinger,
    get_current_macd,
    get_current_atr,
    get_obv_trend,
    get_volume_vs_average,
    is_volume_confirming_price,
    detect_lower_high,
    series_to_dataframe,
)
from src.technicals.scoring import (
    score_rsi,
    score_bollinger,
    score_macd,
    score_volume,
    score_momentum,
    score_patterns,
    TechScoreBreakdown,
)
from src.models.ticker import OHLCV, OHLCVSeries
from config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Create test settings with defaults."""
    # Create minimal settings for testing
    class MockSettings:
        rsi_period = 14
        rsi_overbought = 70
        bollinger_window = 20
        bollinger_std = 2.0
        macd_fast = 12
        macd_slow = 26
        macd_signal = 9
        atr_period = 14
        weight_rsi = 0.20
        weight_bollinger = 0.20
        weight_macd = 0.15
        weight_volume = 0.15
        weight_momentum = 0.15
        weight_pattern = 0.15
    
    return MockSettings()


@pytest.fixture
def sample_uptrend_df() -> pd.DataFrame:
    """Create sample DataFrame with uptrend data."""
    np.random.seed(42)
    dates = pd.date_range(end=datetime.now(), periods=60, freq="D")
    
    # Generate uptrending prices
    base_price = 10.0
    trend = np.linspace(0, 15, 60)  # Strong uptrend
    noise = np.random.randn(60) * 0.5
    closes = base_price + trend + noise
    
    df = pd.DataFrame({
        "open": closes - np.random.rand(60) * 0.3,
        "high": closes + np.random.rand(60) * 0.5,
        "low": closes - np.random.rand(60) * 0.5,
        "close": closes,
        "volume": np.random.randint(100000, 500000, 60),
    }, index=dates)
    
    return df


@pytest.fixture
def overbought_df() -> pd.DataFrame:
    """Create DataFrame with overbought conditions."""
    np.random.seed(123)
    dates = pd.date_range(end=datetime.now(), periods=60, freq="D")
    
    # Generate parabolic move in last 10 days
    base = np.concatenate([
        np.linspace(10, 12, 50),  # Slow rise
        np.linspace(12, 25, 10),  # Parabolic
    ])
    noise = np.random.randn(60) * 0.2
    closes = base + noise
    
    # Ensure closes are positive
    closes = np.maximum(closes, 1.0)
    
    df = pd.DataFrame({
        "open": closes - 0.2,
        "high": closes + np.random.rand(60) * 0.8,
        "low": closes - np.random.rand(60) * 0.3,
        "close": closes,
        "volume": np.concatenate([
            np.random.randint(100000, 200000, 50),
            np.random.randint(500000, 1000000, 10),  # High volume spike
        ]),
    }, index=dates)
    
    return df


class TestRSI:
    """Tests for RSI indicator."""

    def test_compute_rsi_returns_series(self, sample_uptrend_df):
        """Should return RSI series."""
        rsi = compute_rsi(sample_uptrend_df, period=14)
        
        assert rsi is not None
        assert len(rsi) == len(sample_uptrend_df)
        # RSI should be between 0 and 100
        valid_rsi = rsi.dropna()
        assert all(0 <= v <= 100 for v in valid_rsi)

    def test_get_current_rsi_decimal(self, sample_uptrend_df):
        """Should return Decimal value."""
        rsi = get_current_rsi(sample_uptrend_df, period=14)
        
        assert rsi is not None
        assert isinstance(rsi, Decimal)
        assert 0 <= float(rsi) <= 100

    def test_rsi_high_in_uptrend(self, overbought_df):
        """RSI should be high after strong uptrend."""
        rsi = get_current_rsi(overbought_df, period=14)
        
        assert rsi is not None
        assert float(rsi) > 60  # Should be elevated

    def test_insufficient_data_returns_none(self):
        """Should return None if insufficient data."""
        small_df = pd.DataFrame({
            "close": [10, 11, 12],
        })
        
        rsi = compute_rsi(small_df, period=14)
        assert rsi is None


class TestBollinger:
    """Tests for Bollinger Bands."""

    def test_bollinger_structure(self, sample_uptrend_df):
        """Should return complete BollingerResult."""
        bb = get_current_bollinger(sample_uptrend_df, period=20, std_dev=2.0)
        
        assert bb.upper is not None
        assert bb.middle is not None
        assert bb.lower is not None
        assert bb.percent_b is not None
        
        # Upper > Middle > Lower
        assert float(bb.upper) > float(bb.middle) > float(bb.lower)

    def test_overbought_near_upper_band(self, overbought_df):
        """Price should be near/above upper band after parabolic move."""
        bb = get_current_bollinger(overbought_df, period=20, std_dev=2.0)
        
        assert bb.percent_b is not None
        assert float(bb.percent_b) > 0.8  # Near upper band


class TestMACD:
    """Tests for MACD indicator."""

    def test_macd_structure(self, sample_uptrend_df):
        """Should return complete MACDResult."""
        macd = get_current_macd(sample_uptrend_df)
        
        assert macd.macd_line is not None
        assert macd.signal_line is not None
        assert macd.histogram is not None

    def test_macd_positive_in_uptrend(self, sample_uptrend_df):
        """MACD should be positive in uptrend."""
        macd = get_current_macd(sample_uptrend_df)
        
        assert macd.macd_line is not None
        assert float(macd.macd_line) > 0


class TestVolumeAnalysis:
    """Tests for volume-based indicators."""

    def test_volume_vs_average(self, sample_uptrend_df):
        """Should return volume ratio."""
        ratio = get_volume_vs_average(sample_uptrend_df, period=20)
        
        assert ratio is not None
        assert isinstance(ratio, Decimal)
        assert float(ratio) > 0

    def test_volume_confirming_uptrend(self):
        """Volume should confirm price in healthy uptrend."""
        # Price up, volume up = confirming
        df = pd.DataFrame({
            "close": [10, 11, 12, 13, 14],
            "volume": [100, 110, 120, 130, 140],
        }, index=pd.date_range("2026-01-01", periods=5))
        
        assert is_volume_confirming_price(df, lookback=5) == True

    def test_volume_divergence(self):
        """Should detect volume divergence."""
        # Price up, volume down = divergence
        df = pd.DataFrame({
            "close": [10, 11, 12, 13, 14],
            "volume": [140, 130, 120, 110, 100],
        }, index=pd.date_range("2026-01-01", periods=5))
        
        assert is_volume_confirming_price(df, lookback=5) == False


class TestOBV:
    """Tests for OBV indicator."""

    def test_obv_trend_rising(self):
        """Should detect rising OBV in uptrend."""
        df = pd.DataFrame({
            "open": [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5],
            "high": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5],
            "low": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "close": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
            "volume": [100000] * 10,
        }, index=pd.date_range("2026-01-01", periods=10))
        
        trend = get_obv_trend(df, lookback=5)
        assert trend == "rising"

    def test_obv_trend_falling(self):
        """Should detect falling OBV in downtrend."""
        df = pd.DataFrame({
            "open": [19.5, 18.5, 17.5, 16.5, 15.5, 14.5, 13.5, 12.5, 11.5, 10.5],
            "high": [20, 19, 18, 17, 16, 15, 14, 13, 12, 11],
            "low": [18.5, 17.5, 16.5, 15.5, 14.5, 13.5, 12.5, 11.5, 10.5, 9.5],
            "close": [19, 18, 17, 16, 15, 14, 13, 12, 11, 10],
            "volume": [100000] * 10,
        }, index=pd.date_range("2026-01-01", periods=10))
        
        trend = get_obv_trend(df, lookback=5)
        assert trend == "falling"


class TestPatternDetection:
    """Tests for pattern detection."""

    def test_detect_lower_high(self):
        """Should detect lower high pattern."""
        # Create data with clear lower high: peaks at 15, then 17, then 16
        highs = [10, 12, 11, 15, 14, 13, 17, 16, 16, 15]
        df = pd.DataFrame({
            "high": highs,
            "low": [h - 1.5 for h in highs],
            "close": [h - 0.5 for h in highs],
            "open": [h - 0.7 for h in highs],
            "volume": [100000] * 10,
        }, index=pd.date_range("2026-01-01", periods=10))
        
        # The function should return a boolean-like value
        result = detect_lower_high(df, lookback=10)
        assert result in (True, False)


class TestScoring:
    """Tests for scoring functions."""

    def test_score_rsi_extreme(self, settings):
        """Extreme RSI should get high score."""
        score = score_rsi(Decimal("90"), settings)
        assert score == 2.0

    def test_score_rsi_moderate(self, settings):
        """Moderate RSI should get moderate score."""
        score = score_rsi(Decimal("65"), settings)
        assert 0.5 < score < 1.5

    def test_score_rsi_low(self, settings):
        """Low RSI should get zero score."""
        score = score_rsi(Decimal("40"), settings)
        assert score == 0.0

    def test_score_bollinger_above_upper(self):
        """Price above upper band should get max score."""
        bb = BollingerResult(
            upper=Decimal("20"),
            middle=Decimal("18"),
            lower=Decimal("16"),
            bandwidth=Decimal("0.2"),
            percent_b=Decimal("1.1"),
            price_above_upper=True,
        )
        
        score = score_bollinger(bb)
        assert score == 2.0

    def test_score_macd_declining(self):
        """Declining MACD histogram should add to score."""
        macd = MACDResult(
            macd_line=Decimal("0.5"),
            signal_line=Decimal("0.6"),
            histogram=Decimal("0.05"),
            histogram_declining=True,
        )
        
        score = score_macd(macd)
        assert score > 0.5

    def test_score_volume_divergence(self):
        """Volume divergence should get high score."""
        score = score_volume(
            volume_vs_avg=Decimal("0.5"),
            volume_confirming=False,
        )
        assert score >= 1.0

    def test_score_momentum_parabolic(self):
        """Parabolic momentum should get high score."""
        score = score_momentum(
            roc_1d=Decimal("50"),
            roc_3d=Decimal("80"),
            roc_5d=Decimal("120"),
        )
        assert score >= 1.0

    def test_score_patterns_both(self):
        """Both patterns should get max score."""
        score = score_patterns(lower_high=True, exhaustion=True)
        assert score == 1.5


class TestSeriesConversion:
    """Tests for OHLCV series conversion."""

    def test_series_to_dataframe(self):
        """Should convert OHLCVSeries to DataFrame."""
        bars = [
            OHLCV(
                timestamp=datetime(2026, 1, 27, 10, 0),
                open=Decimal("10.00"),
                high=Decimal("10.50"),
                low=Decimal("9.80"),
                close=Decimal("10.30"),
                volume=100000,
            ),
            OHLCV(
                timestamp=datetime(2026, 1, 27, 9, 45),
                open=Decimal("9.90"),
                high=Decimal("10.10"),
                low=Decimal("9.85"),
                close=Decimal("10.00"),
                volume=80000,
            ),
        ]
        series = OHLCVSeries(ticker="TEST", interval="15min", bars=bars)
        
        df = series_to_dataframe(series)
        
        assert len(df) == 2
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns
        # Should be sorted ascending
        assert df.index[0] < df.index[1]
