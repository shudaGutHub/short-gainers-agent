"""Tests for scoring algorithm."""

import pytest

from short_gainers_agent.analysis.scoring import ScoringEngine, calculate_short_score
from short_gainers_agent.data.models import (
    CatalystAnalysis,
    CatalystClassification,
    RiskFlag,
    TechnicalIndicators,
    TradeExpression,
)


class TestScoringEngine:
    """Tests for ScoringEngine class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = ScoringEngine()

    def test_rsi_extreme_score(self):
        """RSI >= 90 should give max component score."""
        score = self.engine._score_rsi(95.0)
        assert score == 2.5

    def test_rsi_high_score(self):
        """RSI >= 80 should give 2.0."""
        score = self.engine._score_rsi(82.0)
        assert score == 2.0

    def test_rsi_none(self):
        """None RSI should give 0."""
        score = self.engine._score_rsi(None)
        assert score == 0.0

    def test_bollinger_extreme(self):
        """Position >= 80% above upper should give max."""
        score = self.engine._score_bollinger(85.0)
        assert score == 2.5

    def test_bollinger_high(self):
        """Position >= 50% above upper should give 2.0."""
        score = self.engine._score_bollinger(55.0)
        assert score == 2.0

    def test_change_extreme(self):
        """Change >= 100% should give max."""
        score = self.engine._score_change(150.0)
        assert score == 2.5

    def test_change_high(self):
        """Change >= 50% should give 2.0."""
        score = self.engine._score_change(60.0)
        assert score == 2.0

    def test_reversal_extreme(self):
        """40%+ pullback from high should give max."""
        score = self.engine._score_reversal(-45.0)
        assert score == 2.5

    def test_reversal_none(self):
        """None should give 0."""
        score = self.engine._score_reversal(None)
        assert score == 0.0

    def test_sentiment_no_catalyst(self):
        """No catalyst should give positive adjustment."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.UNKNOWN,
            has_fundamental_catalyst=False,
        )
        adjustment = self.engine._score_sentiment(catalyst)
        assert adjustment == 2.0

    def test_sentiment_speculative(self):
        """Speculative should give positive adjustment."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.SPECULATIVE,
            has_fundamental_catalyst=False,
        )
        adjustment = self.engine._score_sentiment(catalyst)
        assert adjustment == 1.5

    def test_sentiment_fundamental(self):
        """Fundamental catalyst should give negative adjustment."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.FUNDAMENTAL_REPRICING,
            has_fundamental_catalyst=True,
        )
        adjustment = self.engine._score_sentiment(catalyst)
        assert adjustment == -2.0

    def test_risk_penalty_calculation(self):
        """Risk penalties should sum correctly."""
        flags = [RiskFlag.HIGH_SQUEEZE, RiskFlag.EXTREME_VOLATILITY]
        penalty = self.engine._calculate_risk_penalty(flags)
        assert penalty == -3.5  # -2.0 + -1.5


class TestTradeExpression:
    """Tests for trade expression determination."""

    def setup_method(self):
        self.engine = ScoringEngine()

    def test_avoid_low_score(self):
        """Score < 4.0 should AVOID."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.SPECULATIVE,
            has_fundamental_catalyst=False,
        )
        expr = self.engine.determine_trade_expression(3.0, [], catalyst)
        assert expr == TradeExpression.AVOID

    def test_avoid_fundamental_catalyst(self):
        """Fundamental catalyst should AVOID regardless of score."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.FUNDAMENTAL_REPRICING,
            has_fundamental_catalyst=True,
        )
        expr = self.engine.determine_trade_expression(8.0, [], catalyst)
        assert expr == TradeExpression.AVOID

    def test_avoid_new_listing(self):
        """NEW_LISTING flag should AVOID."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.SPECULATIVE,
            has_fundamental_catalyst=False,
        )
        expr = self.engine.determine_trade_expression(
            8.0, [RiskFlag.NEW_LISTING], catalyst
        )
        assert expr == TradeExpression.AVOID

    def test_buy_puts_squeeze_risk(self):
        """HIGH_SQUEEZE should use BUY_PUTS."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.SPECULATIVE,
            has_fundamental_catalyst=False,
        )
        expr = self.engine.determine_trade_expression(
            7.0, [RiskFlag.HIGH_SQUEEZE], catalyst
        )
        assert expr == TradeExpression.BUY_PUTS

    def test_put_spreads_volatility(self):
        """EXTREME_VOLATILITY without squeeze should use PUT_SPREADS."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.SPECULATIVE,
            has_fundamental_catalyst=False,
        )
        expr = self.engine.determine_trade_expression(
            7.0, [RiskFlag.EXTREME_VOLATILITY], catalyst
        )
        assert expr == TradeExpression.PUT_SPREADS

    def test_short_shares_clean_setup(self):
        """Clean setup with high score should SHORT_SHARES."""
        catalyst = CatalystAnalysis(
            classification=CatalystClassification.SPECULATIVE,
            has_fundamental_catalyst=False,
        )
        expr = self.engine.determine_trade_expression(7.0, [], catalyst)
        assert expr == TradeExpression.SHORT_SHARES


class TestCalculateShortScore:
    """Integration tests for complete scoring."""

    def test_tcgl_like_scenario(self, extreme_technicals, sample_catalyst_speculative):
        """Test TCGL-like extreme scenario."""
        risk_flags = [RiskFlag.HIGH_SQUEEZE, RiskFlag.EXTREME_VOLATILITY, RiskFlag.NON_NASDAQ]

        score, breakdown, expression = calculate_short_score(
            technicals=extreme_technicals,
            catalyst=sample_catalyst_speculative,
            risk_flags=risk_flags,
            change_percent=941.0,
            off_high_percent=-33.0,
        )

        # Should have high technical score
        assert breakdown.technical_score >= 8.0

        # Should have positive sentiment adjustment (speculative)
        assert breakdown.sentiment_adjustment > 0

        # Should have significant risk penalty
        assert breakdown.risk_penalty < -3.0

        # Final score should be reasonable
        assert 6.0 <= score <= 9.0

        # With HIGH_SQUEEZE, should recommend puts
        assert expression == TradeExpression.BUY_PUTS

    def test_fundamental_catalyst_scenario(self, sample_technicals, sample_catalyst_fundamental):
        """Fundamental catalyst should result in AVOID."""
        risk_flags = [RiskFlag.FUNDAMENTAL_CATALYST]

        score, breakdown, expression = calculate_short_score(
            technicals=sample_technicals,
            catalyst=sample_catalyst_fundamental,
            risk_flags=risk_flags,
            change_percent=50.0,
            off_high_percent=-10.0,
        )

        # Should have negative sentiment adjustment
        assert breakdown.sentiment_adjustment < 0

        # Should AVOID
        assert expression == TradeExpression.AVOID

    def test_score_clamping(self, extreme_technicals, sample_catalyst_speculative):
        """Score should be clamped to 0-10."""
        # Scenario that would theoretically exceed 10
        score, breakdown, expression = calculate_short_score(
            technicals=extreme_technicals,
            catalyst=sample_catalyst_speculative,
            risk_flags=[],  # No penalties
            change_percent=200.0,
            off_high_percent=-50.0,
        )

        assert 0.0 <= score <= 10.0
