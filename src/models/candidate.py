"""
Models for short candidate analysis and scoring.

These models represent derived/computed data from the analysis pipeline.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskFlag(str, Enum):
    """Risk flags that may be attached to candidates."""

    MICROCAP = "MICROCAP"
    HIGH_SQUEEZE = "HIGH_SQUEEZE"
    FUNDAMENTAL_REPRICING = "FUNDAMENTAL_REPRICING"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    WARRANT = "WARRANT"
    NONE = "NONE"


class TradeExpression(str, Enum):
    """Preferred way to express a short view."""

    SHORT_SHARES = "SHORT_SHARES"
    BUY_PUTS = "BUY_PUTS"
    PUT_SPREADS = "PUT_SPREADS"
    AVOID = "AVOID"


class CatalystClassification(str, Enum):
    """Classification of the news catalyst driving the move."""

    EARNINGS = "EARNINGS"
    FDA = "FDA"
    MA = "MA"  # Merger/Acquisition
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    CONTRACT = "CONTRACT"
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    SPECULATIVE = "SPECULATIVE"
    MEME_SOCIAL = "MEME_SOCIAL"
    UNKNOWN = "UNKNOWN"

    @property
    def is_fundamental(self) -> bool:
        """Returns True if this catalyst typically justifies repricing."""
        return self in {
            CatalystClassification.EARNINGS,
            CatalystClassification.FDA,
            CatalystClassification.MA,
            CatalystClassification.CONTRACT,
        }


class SentimentLevel(str, Enum):
    """Overall sentiment assessment."""

    STRONGLY_POSITIVE = "strongly_positive"
    POSITIVE = "positive"
    MIXED = "mixed"
    NEGATIVE = "negative"
    STRONGLY_NEGATIVE = "strongly_negative"


class TechnicalState(BaseModel):
    """Snapshot of technical indicator values for a ticker."""

    # RSI
    rsi_daily: Optional[Decimal] = None
    rsi_intraday: Optional[Decimal] = None

    # MACD
    macd_line: Optional[Decimal] = None
    macd_signal: Optional[Decimal] = None
    macd_histogram: Optional[Decimal] = None
    macd_histogram_declining: bool = False

    # Bollinger Bands
    bollinger_upper: Optional[Decimal] = None
    bollinger_middle: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    bollinger_position: Optional[Decimal] = Field(
        default=None, description="0=lower band, 0.5=middle, 1=upper band"
    )
    price_above_upper_band: bool = False

    # Volatility
    atr_daily: Optional[Decimal] = None
    atr_percent: Optional[Decimal] = Field(
        default=None, description="ATR as percentage of price"
    )

    # Volume
    obv_trend: Optional[str] = Field(
        default=None, description="rising, falling, or flat"
    )
    volume_vs_avg: Optional[Decimal] = Field(
        default=None, description="Today volume / 20-day avg"
    )
    volume_confirming_price: bool = True

    # Momentum
    roc_1d: Optional[Decimal] = None
    roc_3d: Optional[Decimal] = None
    roc_5d: Optional[Decimal] = None

    # Pattern detection
    lower_high_forming: bool = False
    exhaustion_candle: bool = False

    def summary(self) -> str:
        """Generate compact technical notes string."""
        parts = []

        if self.rsi_daily is not None:
            parts.append(f"RSI {self.rsi_daily:.0f}")
            if self.rsi_intraday is not None:
                parts.append(f"(intra {self.rsi_intraday:.0f})")

        if self.price_above_upper_band:
            parts.append("above upper BB")
        elif self.bollinger_position is not None and self.bollinger_position > Decimal("0.8"):
            parts.append("near upper BB")

        if self.macd_histogram_declining:
            parts.append("MACD fading")

        if not self.volume_confirming_price:
            parts.append("vol divergence")

        if self.lower_high_forming:
            parts.append("lower high forming")

        if self.exhaustion_candle:
            parts.append("exhaustion candle")

        return ", ".join(parts) if parts else "neutral"


class NewsAssessment(BaseModel):
    """Claude-generated assessment of news/catalyst."""

    catalyst_type: CatalystClassification = CatalystClassification.UNKNOWN
    sentiment: SentimentLevel = SentimentLevel.MIXED
    summary: str = ""
    justifies_repricing: bool = False
    confidence: Decimal = Field(
        default=Decimal("0.5"), ge=Decimal("0"), le=Decimal("1")
    )

    def notes(self) -> str:
        """Generate compact news notes string for output line."""
        parts = [f"{self.catalyst_type.value}"]
        
        if self.summary:
            parts.append(f": {self.summary}")
        
        parts.append(f" [{self.sentiment.value}]")
        
        if self.justifies_repricing:
            parts.append(" **FUNDAMENTAL_REPRICING**")
        elif self.catalyst_type in {
            CatalystClassification.SPECULATIVE,
            CatalystClassification.MEME_SOCIAL,
            CatalystClassification.UNKNOWN,
        }:
            parts.append(" [LOW_QUALITY_CATALYST]")
        
        return "".join(parts)

    def detailed_summary(self) -> str:
        """Generate detailed multi-line summary for report section."""
        lines = [
            f"  Catalyst: {self.catalyst_type.value}",
            f"  Sentiment: {self.sentiment.value}",
            f"  Summary: {self.summary}",
            f"  Justifies Repricing: {'YES - AVOID SHORT' if self.justifies_repricing else 'No'}",
            f"  Confidence: {self.confidence:.0%}",
        ]
        return "\n".join(lines)


class KeyLevels(BaseModel):
    """Key price levels for trade management."""

    intraday_high: Optional[Decimal] = None
    intraday_low: Optional[Decimal] = None
    vwap: Optional[Decimal] = None
    prior_day_close: Optional[Decimal] = None
    resistance_1: Optional[Decimal] = None
    support_1: Optional[Decimal] = None

    def to_dict(self) -> dict[str, Decimal]:
        """Return non-None levels as dict."""
        return {
            k: v for k, v in {
                "intraday_high": self.intraday_high,
                "intraday_low": self.intraday_low,
                "vwap": self.vwap,
                "prior_close": self.prior_day_close,
                "resistance": self.resistance_1,
                "support": self.support_1,
            }.items() if v is not None
        }


class ShortCandidate(BaseModel):
    """
    A fully analyzed short candidate with scores and metadata.

    This is the primary output model for the ranking phase.
    """

    ticker: str
    current_price: Decimal
    change_percent: Decimal

    # Scores
    tech_score: Decimal = Field(ge=Decimal("0"), le=Decimal("10"))
    news_adjustment: Decimal = Field(default=Decimal("0"))
    final_score: Decimal = Field(ge=Decimal("0"), le=Decimal("10"))

    # Analysis details
    technical_state: TechnicalState
    news_assessment: NewsAssessment
    risk_flags: list[RiskFlag] = Field(default_factory=list)

    # Trade structure
    preferred_expression: TradeExpression
    key_levels: KeyLevels

    # Metadata
    market_cap: Optional[int] = None
    avg_volume: Optional[int] = None
    sector: Optional[str] = None

    def to_output_line(self) -> str:
        """Generate machine-readable output line per spec."""
        risk_str = ",".join(f.value for f in self.risk_flags) if self.risk_flags else "NONE"
        levels_str = " | ".join(
            f"{k}={v:.2f}" for k, v in self.key_levels.to_dict().items()
        )

        return (
            f"{self.ticker} | "
            f"{self.final_score:.1f} | "
            f"{self.technical_state.summary()} | "
            f"{self.news_assessment.notes()} | "
            f"{risk_str} | "
            f"{self.preferred_expression.value} | "
            f"{levels_str}"
        )


class FilteredTicker(BaseModel):
    """Result of pre-filter stage - ticker with risk assessment."""

    ticker: str
    passed: bool
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    exclusion_reason: Optional[str] = None
    market_cap: Optional[int] = None
    avg_volume: Optional[int] = None
    beta: Optional[Decimal] = None
