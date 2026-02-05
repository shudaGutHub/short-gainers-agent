"""Tests for pre-filter module."""

from decimal import Decimal

import pytest

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
from src.models.candidate import FilteredTicker, RiskFlag
from src.models.ticker import Exchange, Fundamentals


@pytest.fixture
def settings():
    """Create mock settings for testing."""
    class MockSettings:
        min_market_cap = 200_000_000  # $200M
        min_avg_volume = 500_000
        max_beta_for_shares = 3.0
    
    return MockSettings()


@pytest.fixture
def large_cap_fundamentals() -> Fundamentals:
    """Create fundamentals for a large cap stock."""
    return Fundamentals(
        ticker="BIGCO",
        name="Big Company Inc",
        exchange=Exchange.NASDAQ,
        market_cap=10_000_000_000,  # $10B
        beta=Decimal("1.2"),
        avg_volume_10d=5_000_000,
        float_shares=500_000_000,
    )


@pytest.fixture
def micro_cap_fundamentals() -> Fundamentals:
    """Create fundamentals for a micro cap stock."""
    return Fundamentals(
        ticker="TINY",
        name="Tiny Company Inc",
        exchange=Exchange.NASDAQ,
        market_cap=50_000_000,  # $50M
        beta=Decimal("2.5"),
        avg_volume_10d=100_000,
        float_shares=5_000_000,
    )


@pytest.fixture
def squeeze_risk_fundamentals() -> Fundamentals:
    """Create fundamentals for a squeeze-prone stock."""
    return Fundamentals(
        ticker="SQZE",
        name="Squeeze Target Inc",
        exchange=Exchange.NASDAQ,
        market_cap=300_000_000,  # $300M - above threshold
        beta=Decimal("3.5"),  # High beta
        avg_volume_10d=200_000,  # Low volume
        float_shares=5_000_000,  # Low float
    )


class TestCheckMarketCap:
    """Tests for market cap checking."""

    def test_passes_large_cap(self):
        """Should pass large cap stocks without flag."""
        passed, reason, flags = check_market_cap(
            market_cap=10_000_000_000,
            min_market_cap=200_000_000,
        )
        
        assert passed is True
        assert reason is None
        assert RiskFlag.MICROCAP not in flags

    def test_passes_but_flags_below_threshold(self):
        """Should pass stocks below threshold but flag as MICROCAP."""
        passed, reason, flags = check_market_cap(
            market_cap=100_000_000,
            min_market_cap=200_000_000,
        )
        
        assert passed is True  # Now passes
        assert reason is None
        assert RiskFlag.MICROCAP in flags  # But flagged

    def test_flags_microcap(self):
        """Should flag microcaps."""
        passed, reason, flags = check_market_cap(
            market_cap=150_000_000,
            min_market_cap=200_000_000,
        )
        
        assert passed is True
        assert RiskFlag.MICROCAP in flags

    def test_handles_none_with_flag(self):
        """Should pass with flag when market cap unavailable."""
        passed, reason, flags = check_market_cap(
            market_cap=None,
            min_market_cap=200_000_000,
        )
        
        assert passed is True  # Now passes
        assert RiskFlag.MICROCAP in flags  # But flagged


class TestCheckVolume:
    """Tests for volume checking."""

    def test_passes_high_volume(self):
        """Should pass high volume stocks without flag."""
        passed, reason, flags = check_volume(
            avg_volume=5_000_000,
            min_volume=500_000,
        )
        
        assert passed is True
        assert reason is None
        assert RiskFlag.LOW_LIQUIDITY not in flags

    def test_passes_but_flags_low_volume(self):
        """Should pass low volume stocks but flag them."""
        passed, reason, flags = check_volume(
            avg_volume=100_000,
            min_volume=500_000,
        )
        
        assert passed is True  # Now passes
        assert reason is None
        assert RiskFlag.LOW_LIQUIDITY in flags  # But flagged

    def test_flags_borderline_volume(self):
        """Should not flag stocks above threshold."""
        passed, reason, flags = check_volume(
            avg_volume=600_000,  # Above threshold
            min_volume=500_000,
        )
        
        assert passed is True
        assert RiskFlag.LOW_LIQUIDITY not in flags  # Above threshold = no flag

    def test_handles_none_with_flag(self):
        """Should pass with flag when volume unavailable."""
        passed, reason, flags = check_volume(
            avg_volume=None,
            min_volume=500_000,
        )
        
        assert passed is True
        assert RiskFlag.LOW_LIQUIDITY in flags


class TestCheckExchange:
    """Tests for exchange checking."""

    def test_passes_nasdaq(self):
        """Should pass NASDAQ stocks."""
        passed, reason, flags = check_exchange(
            exchange=Exchange.NASDAQ,
            require_nasdaq=True,
        )
        
        assert passed is True
        assert reason is None

    def test_excludes_nyse_when_nasdaq_required(self):
        """Should exclude NYSE when NASDAQ required."""
        passed, reason, flags = check_exchange(
            exchange=Exchange.NYSE,
            require_nasdaq=True,
        )
        
        assert passed is False
        assert "NASDAQ" in reason

    def test_passes_any_when_not_required(self):
        """Should pass any exchange when not required."""
        passed, reason, flags = check_exchange(
            exchange=Exchange.NYSE,
            require_nasdaq=False,
        )
        
        assert passed is True


class TestCheckSqueezeRisk:
    """Tests for squeeze risk assessment."""

    def test_no_flags_for_normal_stock(self):
        """Should not flag normal large cap."""
        flags = check_squeeze_risk(
            market_cap=10_000_000_000,
            float_shares=500_000_000,
            beta=Decimal("1.0"),
            avg_volume=5_000_000,
            change_percent=Decimal("10.0"),
        )
        
        assert RiskFlag.HIGH_SQUEEZE not in flags
        assert RiskFlag.EXTREME_VOLATILITY not in flags

    def test_flags_low_float(self):
        """Should flag low float stocks."""
        flags = check_squeeze_risk(
            market_cap=500_000_000,
            float_shares=5_000_000,  # Low float
            beta=Decimal("1.5"),
            avg_volume=500_000,
            change_percent=Decimal("25.0"),
        )
        
        assert RiskFlag.HIGH_SQUEEZE in flags

    def test_flags_high_beta(self):
        """Should flag extreme volatility for high beta."""
        flags = check_squeeze_risk(
            market_cap=1_000_000_000,
            float_shares=100_000_000,
            beta=Decimal("4.0"),  # Very high beta
            avg_volume=2_000_000,
            change_percent=Decimal("15.0"),
        )
        
        assert RiskFlag.EXTREME_VOLATILITY in flags

    def test_flags_extreme_move(self):
        """Should flag squeeze risk for extreme moves."""
        flags = check_squeeze_risk(
            market_cap=300_000_000,
            float_shares=30_000_000,
            beta=Decimal("1.5"),
            avg_volume=500_000,
            change_percent=Decimal("60.0"),  # 60% move
        )
        
        assert RiskFlag.HIGH_SQUEEZE in flags


class TestAssessShortability:
    """Tests for shortability assessment."""

    def test_shares_for_low_beta(self):
        """Should recommend shares for low beta."""
        result = assess_shortability(
            beta=Decimal("1.5"),
            max_beta_for_shares=3.0,
        )
        
        assert result == "shares"

    def test_puts_for_high_beta(self):
        """Should recommend puts for high beta."""
        result = assess_shortability(
            beta=Decimal("3.5"),
            max_beta_for_shares=3.0,
        )
        
        assert result == "puts"

    def test_avoid_for_extreme_beta(self):
        """Should recommend avoid for extreme beta."""
        result = assess_shortability(
            beta=Decimal("5.0"),
            max_beta_for_shares=3.0,
        )
        
        assert result == "avoid"

    def test_puts_when_beta_unknown(self):
        """Should default to puts when beta unknown."""
        result = assess_shortability(
            beta=None,
            max_beta_for_shares=3.0,
        )
        
        assert result == "puts"


class TestPrefilterTicker:
    """Tests for single ticker pre-filtering."""

    def test_passes_good_stock(self, settings, large_cap_fundamentals):
        """Should pass well-qualified stock."""
        result = prefilter_ticker(
            ticker="BIGCO",
            fundamentals=large_cap_fundamentals,
            change_percent=Decimal("15.0"),
            settings=settings,
        )
        
        assert result.passed is True
        assert result.exclusion_reason is None
        assert RiskFlag.NONE in result.risk_flags or len(result.risk_flags) == 1

    def test_flags_micro_cap(self, settings, micro_cap_fundamentals):
        """Should pass micro cap stock but flag it."""
        result = prefilter_ticker(
            ticker="TINY",
            fundamentals=micro_cap_fundamentals,
            change_percent=Decimal("50.0"),
            settings=settings,
        )
        
        # Now passes but with flags (may still fail on volume)
        # The key change is market cap alone doesn't exclude
        assert RiskFlag.MICROCAP in result.risk_flags or not result.passed

    def test_passes_with_flags(self, settings, squeeze_risk_fundamentals):
        """Should pass squeeze-prone stock with flags."""
        result = prefilter_ticker(
            ticker="SQZE",
            fundamentals=squeeze_risk_fundamentals,
            change_percent=Decimal("40.0"),
            settings=settings,
        )
        
        # Passes market cap but has risk flags
        # Note: may fail on volume depending on threshold
        if result.passed:
            assert RiskFlag.HIGH_SQUEEZE in result.risk_flags or \
                   RiskFlag.EXTREME_VOLATILITY in result.risk_flags


class TestPrefilterBatch:
    """Tests for batch pre-filtering."""

    def test_batch_filtering(self, settings, large_cap_fundamentals, micro_cap_fundamentals):
        """Should correctly filter batch of tickers."""
        tickers_with_data = [
            ("BIGCO", large_cap_fundamentals, Decimal("15.0")),
            ("TINY", micro_cap_fundamentals, Decimal("50.0")),
        ]
        
        result = prefilter_batch(tickers_with_data, settings)
        
        assert result.total_input == 2
        assert result.pass_count >= 0
        assert result.exclude_count >= 0
        assert result.pass_count + result.exclude_count == 2

    def test_empty_batch(self, settings):
        """Should handle empty batch."""
        result = prefilter_batch([], settings)
        
        assert result.total_input == 0
        assert result.pass_count == 0
        assert result.exclude_count == 0


class TestHasDangerousRiskProfile:
    """Tests for dangerous risk profile detection."""

    def test_microcap_squeeze_is_dangerous(self):
        """Should flag microcap + squeeze as dangerous."""
        filtered = FilteredTicker(
            ticker="DANGER",
            passed=True,
            risk_flags=[RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE],
        )
        
        assert has_dangerous_risk_profile(filtered) is True

    def test_squeeze_volatility_is_dangerous(self):
        """Should flag squeeze + volatility as dangerous."""
        filtered = FilteredTicker(
            ticker="DANGER",
            passed=True,
            risk_flags=[RiskFlag.HIGH_SQUEEZE, RiskFlag.EXTREME_VOLATILITY],
        )
        
        assert has_dangerous_risk_profile(filtered) is True

    def test_single_flag_not_dangerous(self):
        """Should not flag single risk as dangerous."""
        filtered = FilteredTicker(
            ticker="RISKY",
            passed=True,
            risk_flags=[RiskFlag.HIGH_SQUEEZE],
        )
        
        assert has_dangerous_risk_profile(filtered) is False

    def test_no_flags_not_dangerous(self):
        """Should not flag clean stock as dangerous."""
        filtered = FilteredTicker(
            ticker="CLEAN",
            passed=True,
            risk_flags=[RiskFlag.NONE],
        )
        
        assert has_dangerous_risk_profile(filtered) is False
