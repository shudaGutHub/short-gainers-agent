"""Risk flag detection for short candidates."""

import logging
from datetime import datetime, timedelta

from ..config import RiskConfig, get_risk_config
from ..data.models import (
    CatalystAnalysis,
    CatalystClassification,
    Fundamentals,
    Quote,
    RiskFlag,
    TechnicalIndicators,
)

logger = logging.getLogger(__name__)


class RiskDetector:
    """Detects risk flags that affect scoring and trade expression."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or get_risk_config()

    def detect_all(
        self,
        quote: Quote,
        technicals: TechnicalIndicators | None = None,
        fundamentals: Fundamentals | None = None,
        catalyst: CatalystAnalysis | None = None,
    ) -> list[RiskFlag]:
        """
        Detect all applicable risk flags.

        Args:
            quote: Current quote data
            technicals: Technical indicators (optional)
            fundamentals: Company fundamentals (optional)
            catalyst: Catalyst analysis (optional)

        Returns:
            List of detected risk flags
        """
        flags: list[RiskFlag] = []

        # HIGH_SQUEEZE detection
        if self._detect_high_squeeze(quote, fundamentals):
            flags.append(RiskFlag.HIGH_SQUEEZE)

        # EXTREME_VOLATILITY detection
        if self._detect_extreme_volatility(quote, technicals):
            flags.append(RiskFlag.EXTREME_VOLATILITY)

        # MICROCAP detection
        if self._detect_microcap(fundamentals):
            flags.append(RiskFlag.MICROCAP)

        # LOW_LIQUIDITY detection
        if self._detect_low_liquidity(quote):
            flags.append(RiskFlag.LOW_LIQUIDITY)

        # NON_NASDAQ detection
        if self._detect_non_nasdaq(fundamentals):
            flags.append(RiskFlag.NON_NASDAQ)

        # NEW_LISTING detection
        if self._detect_new_listing(fundamentals):
            flags.append(RiskFlag.NEW_LISTING)

        # FUNDAMENTAL_CATALYST detection
        if self._detect_fundamental_catalyst(catalyst):
            flags.append(RiskFlag.FUNDAMENTAL_CATALYST)

        logger.debug(f"Detected risk flags for {quote.symbol}: {flags}")
        return flags

    def _detect_high_squeeze(
        self, quote: Quote, fundamentals: Fundamentals | None
    ) -> bool:
        """
        Detect HIGH_SQUEEZE risk.

        Triggered by:
        - Extreme daily move (>200%)
        - Recent IPO (within 90 days)
        - Low float indicators (inferred from recent IPO + extreme move)
        """
        cfg = self.config

        # Extreme move suggests potential squeeze dynamics
        if abs(quote.change_percent) >= cfg.squeeze_change_threshold:
            return True

        # Recent IPO implies potentially low float
        if fundamentals and fundamentals.ipo_date:
            try:
                ipo_date = datetime.strptime(fundamentals.ipo_date, "%Y-%m-%d")
                days_since_ipo = (datetime.utcnow() - ipo_date).days
                if days_since_ipo <= cfg.squeeze_ipo_days:
                    # Recent IPO with significant move
                    if abs(quote.change_percent) >= 50:
                        return True
            except ValueError:
                pass

        return False

    def _detect_extreme_volatility(
        self, quote: Quote, technicals: TechnicalIndicators | None
    ) -> bool:
        """
        Detect EXTREME_VOLATILITY risk.

        Triggered by:
        - ATR expansion > 5x normal
        - Daily move > 50%
        """
        cfg = self.config

        # Daily move threshold
        if abs(quote.change_percent) >= cfg.volatility_daily_change:
            return True

        # ATR expansion (if available)
        if technicals and technicals.atr_expansion:
            if technicals.atr_expansion >= cfg.volatility_atr_multiplier:
                return True

        return False

    def _detect_microcap(self, fundamentals: Fundamentals | None) -> bool:
        """Detect MICROCAP risk (market cap < $300M)."""
        if not fundamentals or not fundamentals.market_cap:
            return False

        return fundamentals.market_cap < self.config.microcap_threshold

    def _detect_low_liquidity(self, quote: Quote) -> bool:
        """Detect LOW_LIQUIDITY risk (avg volume < 100K)."""
        # Note: We're using current volume as proxy; ideally use avg volume
        # This is a simplified check - could be enhanced with historical data
        return quote.volume < self.config.low_volume_threshold

    def _detect_non_nasdaq(self, fundamentals: Fundamentals | None) -> bool:
        """Detect NON_NASDAQ risk."""
        if not fundamentals or not fundamentals.exchange:
            return False

        nasdaq_exchanges = ["NASDAQ", "NMS", "NGS", "NCM"]
        return fundamentals.exchange.upper() not in nasdaq_exchanges

    def _detect_new_listing(self, fundamentals: Fundamentals | None) -> bool:
        """Detect NEW_LISTING risk (IPO within 90 days)."""
        if not fundamentals or not fundamentals.ipo_date:
            return False

        try:
            ipo_date = datetime.strptime(fundamentals.ipo_date, "%Y-%m-%d")
            days_since_ipo = (datetime.utcnow() - ipo_date).days
            return days_since_ipo <= self.config.new_listing_days
        except ValueError:
            return False

    def _detect_fundamental_catalyst(
        self, catalyst: CatalystAnalysis | None
    ) -> bool:
        """Detect FUNDAMENTAL_CATALYST risk."""
        if not catalyst:
            return False

        return (
            catalyst.has_fundamental_catalyst
            or catalyst.classification == CatalystClassification.FUNDAMENTAL_REPRICING
        )


def detect_risk_flags(
    quote: Quote,
    technicals: TechnicalIndicators | None = None,
    fundamentals: Fundamentals | None = None,
    catalyst: CatalystAnalysis | None = None,
) -> list[RiskFlag]:
    """
    Convenience function to detect all risk flags.

    Args:
        quote: Current quote data
        technicals: Technical indicators (optional)
        fundamentals: Company fundamentals (optional)
        catalyst: Catalyst analysis (optional)

    Returns:
        List of detected risk flags
    """
    detector = RiskDetector()
    return detector.detect_all(
        quote=quote,
        technicals=technicals,
        fundamentals=fundamentals,
        catalyst=catalyst,
    )


# Risk flag metadata for UI/reporting
RISK_FLAG_INFO: dict[RiskFlag, dict] = {
    RiskFlag.HIGH_SQUEEZE: {
        "label": "SQUEEZE",
        "color": "red",
        "icon": "warning",
        "tooltip": "High short squeeze risk - low float or extreme recent move",
        "severity": "critical",
    },
    RiskFlag.EXTREME_VOLATILITY: {
        "label": "VOLATILE",
        "color": "red",
        "icon": "trending_up",
        "tooltip": "Extreme volatility - ATR expansion >5x or daily move >50%",
        "severity": "high",
    },
    RiskFlag.MICROCAP: {
        "label": "MICRO",
        "color": "yellow",
        "icon": "analytics",
        "tooltip": "Microcap stock - market cap <$300M",
        "severity": "medium",
    },
    RiskFlag.LOW_LIQUIDITY: {
        "label": "ILLIQUID",
        "color": "yellow",
        "icon": "water_drop",
        "tooltip": "Low liquidity - average volume <100K",
        "severity": "medium",
    },
    RiskFlag.NON_NASDAQ: {
        "label": "NON-NDQ",
        "color": "yellow",
        "icon": "account_balance",
        "tooltip": "Not listed on NASDAQ - may have different trading characteristics",
        "severity": "low",
    },
    RiskFlag.NEW_LISTING: {
        "label": "NEW",
        "color": "red",
        "icon": "new_releases",
        "tooltip": "Recently listed - limited trading history and no borrow available",
        "severity": "critical",
    },
    RiskFlag.FUNDAMENTAL_CATALYST: {
        "label": "CATALYST",
        "color": "red",
        "icon": "newspaper",
        "tooltip": "Fundamental catalyst present - shorting into news is dangerous",
        "severity": "critical",
    },
}
