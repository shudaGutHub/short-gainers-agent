"""Pytest configuration and fixtures."""

import pytest

from short_gainers_agent.data.models import (
    CatalystAnalysis,
    CatalystClassification,
    Quote,
    RiskFlag,
    TechnicalIndicators,
)


@pytest.fixture
def sample_quote() -> Quote:
    """Sample quote for testing."""
    return Quote(
        symbol="TEST",
        price=100.0,
        change=50.0,
        change_percent=100.0,
        volume=1_000_000,
        previous_close=50.0,
        open=55.0,
        high=120.0,
        low=50.0,
        latest_trading_day="2026-01-29",
    )


@pytest.fixture
def sample_technicals() -> TechnicalIndicators:
    """Sample technical indicators for testing."""
    return TechnicalIndicators(
        rsi_14=85.0,
        bb_upper=90.0,
        bb_middle=75.0,
        bb_lower=60.0,
        bb_position=11.1,  # 11% above upper band
        atr_14=5.0,
        atr_expansion=3.0,
        sma_20=70.0,
        sma_50=65.0,
        sma_200=55.0,
    )


@pytest.fixture
def sample_catalyst_speculative() -> CatalystAnalysis:
    """Sample speculative catalyst for testing."""
    return CatalystAnalysis(
        classification=CatalystClassification.SPECULATIVE,
        has_fundamental_catalyst=False,
    )


@pytest.fixture
def sample_catalyst_fundamental() -> CatalystAnalysis:
    """Sample fundamental catalyst for testing."""
    return CatalystAnalysis(
        classification=CatalystClassification.FUNDAMENTAL_REPRICING,
        has_fundamental_catalyst=True,
    )


@pytest.fixture
def extreme_technicals() -> TechnicalIndicators:
    """Extreme technical indicators (like TCGL example)."""
    return TechnicalIndicators(
        rsi_14=99.2,
        bb_upper=10.0,
        bb_middle=7.0,
        bb_lower=4.0,
        bb_position=89.0,  # 89% above upper band
        atr_14=9.55,
        atr_expansion=19.0,
        sma_20=7.24,
        sma_50=6.50,
        sma_200=5.00,
    )
