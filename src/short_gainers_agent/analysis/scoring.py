"""Scoring algorithm for short candidate evaluation."""

import logging

from ..config import ScoringConfig, get_scoring_config
from ..data.models import (
    AnalysisResult,
    CatalystAnalysis,
    CatalystClassification,
    RiskFlag,
    ScoreBreakdown,
    TechnicalIndicators,
    TradeExpression,
)

logger = logging.getLogger(__name__)


class ScoringEngine:
    """Calculates short scores based on technical, sentiment, and risk factors."""

    def __init__(self, config: ScoringConfig | None = None):
        self.config = config or get_scoring_config()

    def calculate_score(
        self,
        technicals: TechnicalIndicators,
        catalyst: CatalystAnalysis,
        risk_flags: list[RiskFlag],
        change_percent: float,
        off_high_percent: float | None = None,
    ) -> ScoreBreakdown:
        """
        Calculate complete score breakdown.

        Args:
            technicals: Technical indicators
            catalyst: Catalyst analysis result
            risk_flags: Detected risk flags
            change_percent: Daily change percentage
            off_high_percent: Percentage off intraday high (negative)

        Returns:
            ScoreBreakdown with all components
        """
        breakdown = ScoreBreakdown()

        # 1. RSI Component (max 2.5)
        breakdown.rsi_component = self._score_rsi(technicals.rsi_14)

        # 2. Bollinger Component (max 2.5)
        breakdown.bollinger_component = self._score_bollinger(technicals.bb_position)

        # 3. Change % Component (max 2.5)
        breakdown.change_component = self._score_change(change_percent)

        # 4. Reversal Component (max 2.5)
        breakdown.reversal_component = self._score_reversal(off_high_percent)

        # 5. Sentiment Adjustment
        breakdown.sentiment_adjustment = self._score_sentiment(catalyst)

        # 6. Risk Penalties
        breakdown.risk_penalty = self._calculate_risk_penalty(risk_flags)

        logger.debug(
            f"Score breakdown: tech={breakdown.technical_score:.2f}, "
            f"sentiment={breakdown.sentiment_adjustment:+.2f}, "
            f"risk={breakdown.risk_penalty:+.2f}, "
            f"final={breakdown.final_score:.2f}"
        )

        return breakdown

    def _score_rsi(self, rsi: float | None) -> float:
        """Score RSI component (0-2.5). Higher RSI = higher score."""
        if rsi is None:
            return 0.0

        cfg = self.config
        if rsi >= cfg.rsi_extreme:
            return cfg.rsi_max
        elif rsi >= cfg.rsi_high:
            return 2.0
        elif rsi >= cfg.rsi_elevated:
            return 1.5
        elif rsi >= cfg.rsi_moderate:
            return 1.0
        else:
            return 0.5

    def _score_bollinger(self, bb_position: float | None) -> float:
        """Score Bollinger position (0-2.5). Further above upper band = higher score."""
        if bb_position is None:
            return 0.0

        cfg = self.config
        if bb_position >= cfg.bb_extreme:
            return cfg.bollinger_max
        elif bb_position >= cfg.bb_high:
            return 2.0
        elif bb_position >= cfg.bb_elevated:
            return 1.5
        elif bb_position >= cfg.bb_moderate:
            return 1.0
        else:
            return 0.5

    def _score_change(self, change_percent: float) -> float:
        """Score daily change % (0-2.5). Larger move = higher score."""
        change = abs(change_percent)
        cfg = self.config

        if change >= cfg.change_extreme:
            return cfg.change_max
        elif change >= cfg.change_high:
            return 2.0
        elif change >= cfg.change_elevated:
            return 1.5
        elif change >= cfg.change_moderate:
            return 1.0
        else:
            return 0.5

    def _score_reversal(self, off_high_percent: float | None) -> float:
        """
        Score reversal signals (0-2.5).
        
        If price has pulled back significantly from intraday high,
        it suggests exhaustion and reversal potential.
        """
        if off_high_percent is None:
            return 0.0

        # off_high_percent is typically negative (e.g., -33% means 33% below high)
        pullback = abs(off_high_percent)

        if pullback >= 40:
            return self.config.reversal_max
        elif pullback >= 30:
            return 2.0
        elif pullback >= 20:
            return 1.5
        elif pullback >= 10:
            return 1.0
        else:
            return 0.5

    def _score_sentiment(self, catalyst: CatalystAnalysis) -> float:
        """Calculate sentiment adjustment based on catalyst analysis."""
        cfg = self.config

        if catalyst.has_fundamental_catalyst:
            return cfg.sentiment_fundamental

        match catalyst.classification:
            case CatalystClassification.SPECULATIVE:
                return cfg.sentiment_speculative
            case CatalystClassification.MEME:
                return cfg.sentiment_meme
            case CatalystClassification.UNKNOWN:
                return cfg.sentiment_no_catalyst
            case _:
                return 0.0

    def _calculate_risk_penalty(self, risk_flags: list[RiskFlag]) -> float:
        """Calculate total risk penalty from flags."""
        cfg = self.config
        penalties = {
            RiskFlag.HIGH_SQUEEZE: cfg.penalty_high_squeeze,
            RiskFlag.EXTREME_VOLATILITY: cfg.penalty_extreme_volatility,
            RiskFlag.MICROCAP: cfg.penalty_microcap,
            RiskFlag.LOW_LIQUIDITY: cfg.penalty_low_liquidity,
            RiskFlag.NON_NASDAQ: cfg.penalty_non_nasdaq,
            RiskFlag.NEW_LISTING: cfg.penalty_new_listing,
            RiskFlag.FUNDAMENTAL_CATALYST: cfg.penalty_fundamental_catalyst,
        }

        total_penalty = sum(penalties.get(flag, 0) for flag in risk_flags)
        return total_penalty

    def determine_trade_expression(
        self,
        score: float,
        risk_flags: list[RiskFlag],
        catalyst: CatalystAnalysis,
    ) -> TradeExpression:
        """
        Determine recommended trade expression based on score and risk profile.

        Logic:
        1. AVOID if score < 4.0 or fundamental catalyst present or new listing
        2. BUY_PUTS if HIGH_SQUEEZE flag (limited risk vs short squeeze)
        3. PUT_SPREADS if EXTREME_VOLATILITY (reduce vega exposure)
        4. SHORT_SHARES if clean setup with good score
        """
        # Check for AVOID conditions
        if score < 4.0:
            return TradeExpression.AVOID

        if catalyst.has_fundamental_catalyst:
            return TradeExpression.AVOID

        if RiskFlag.NEW_LISTING in risk_flags:
            return TradeExpression.AVOID

        if RiskFlag.FUNDAMENTAL_CATALYST in risk_flags:
            return TradeExpression.AVOID

        # Check for squeeze risk -> puts only
        if RiskFlag.HIGH_SQUEEZE in risk_flags:
            return TradeExpression.BUY_PUTS

        # Check for extreme volatility -> spreads to manage IV
        if RiskFlag.EXTREME_VOLATILITY in risk_flags:
            return TradeExpression.PUT_SPREADS

        # Clean setup with decent score -> can short shares
        if score >= 6.0:
            return TradeExpression.SHORT_SHARES

        # Marginal score -> use puts for defined risk
        return TradeExpression.BUY_PUTS


def calculate_short_score(
    technicals: TechnicalIndicators,
    catalyst: CatalystAnalysis,
    risk_flags: list[RiskFlag],
    change_percent: float,
    off_high_percent: float | None = None,
) -> tuple[float, ScoreBreakdown, TradeExpression]:
    """
    Convenience function to calculate complete scoring.

    Returns:
        Tuple of (final_score, breakdown, trade_expression)
    """
    engine = ScoringEngine()

    breakdown = engine.calculate_score(
        technicals=technicals,
        catalyst=catalyst,
        risk_flags=risk_flags,
        change_percent=change_percent,
        off_high_percent=off_high_percent,
    )

    expression = engine.determine_trade_expression(
        score=breakdown.final_score,
        risk_flags=risk_flags,
        catalyst=catalyst,
    )

    return breakdown.final_score, breakdown, expression
