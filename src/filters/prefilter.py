"""
Pre-filtering module for short candidates.

Applies safety checks to exclude dangerous or untradeable tickers
and flags remaining tickers with risk indicators.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from config.settings import Settings, Thresholds
from src.models.candidate import FilteredTicker, RiskFlag
from src.models.ticker import Exchange, Fundamentals


@dataclass
class PrefilterResult:
    """Result of pre-filtering a list of tickers."""

    passed: list[FilteredTicker]
    excluded: list[FilteredTicker]
    total_input: int
    
    @property
    def pass_count(self) -> int:
        return len(self.passed)
    
    @property
    def exclude_count(self) -> int:
        return len(self.excluded)
    
    @property
    def pass_rate(self) -> float:
        if self.total_input == 0:
            return 0.0
        return self.pass_count / self.total_input

    def get_passed_tickers(self) -> list[str]:
        """Return list of ticker symbols that passed."""
        return [t.ticker for t in self.passed]

    def get_excluded_tickers(self) -> list[str]:
        """Return list of ticker symbols that were excluded."""
        return [t.ticker for t in self.excluded]


# -----------------------------------------------------------------------------
# Individual filter functions (pure, stateless)
# -----------------------------------------------------------------------------


def check_market_cap(
    market_cap: Optional[int],
    min_market_cap: int,
) -> tuple[bool, Optional[str], list[RiskFlag]]:
    """
    Check market cap and flag if below threshold.

    Note: Does NOT exclude - just flags for risk assessment.

    Args:
        market_cap: Company market cap in dollars
        min_market_cap: Threshold for flagging as microcap

    Returns:
        Tuple of (passed, exclusion_reason, risk_flags)
    """
    if market_cap is None:
        # Can't verify - pass with flag
        return True, None, [RiskFlag.MICROCAP]

    # Flag if below threshold but don't exclude
    if market_cap < min_market_cap:
        return True, None, [RiskFlag.MICROCAP]

    return True, None, []


def check_volume(
    avg_volume: Optional[int],
    min_volume: int,
) -> tuple[bool, Optional[str], list[RiskFlag]]:
    """
    Check average volume and flag if below threshold.

    Note: Does NOT exclude - just flags for risk assessment.

    Args:
        avg_volume: Average daily volume in shares
        min_volume: Threshold for flagging as low liquidity

    Returns:
        Tuple of (passed, exclusion_reason, risk_flags)
    """
    if avg_volume is None:
        # Can't verify - pass with flag
        return True, None, [RiskFlag.LOW_LIQUIDITY]

    # Flag if below threshold but don't exclude
    if avg_volume < min_volume:
        return True, None, [RiskFlag.LOW_LIQUIDITY]

    return True, None, []


def check_exchange(
    exchange: Optional[Exchange],
    require_nasdaq: bool = True,
) -> tuple[bool, Optional[str], list[RiskFlag]]:
    """
    Check if ticker is listed on required exchange.

    Args:
        exchange: Exchange enum value
        require_nasdaq: Whether to require NASDAQ listing

    Returns:
        Tuple of (passed, exclusion_reason, risk_flags)
    """
    if not require_nasdaq:
        return True, None, []

    if exchange is None:
        # Can't verify - pass with caution
        return True, None, []

    if exchange != Exchange.NASDAQ:
        return False, f"Not listed on NASDAQ (exchange: {exchange.value})", []

    return True, None, []


def check_squeeze_risk(
    market_cap: Optional[int],
    float_shares: Optional[int],
    beta: Optional[Decimal],
    avg_volume: Optional[int],
    change_percent: Decimal,
) -> list[RiskFlag]:
    """
    Assess squeeze risk based on multiple factors.

    High squeeze risk indicators:
    - Very low float relative to market cap
    - High beta
    - Extreme single-day move
    - Low volume relative to float

    Args:
        market_cap: Market capitalization
        float_shares: Float shares (may be None)
        beta: Stock beta
        avg_volume: Average daily volume
        change_percent: Today's percentage change

    Returns:
        List of risk flags (may include HIGH_SQUEEZE, EXTREME_VOLATILITY)
    """
    flags = []
    squeeze_signals = 0

    # Check float
    if float_shares is not None and float_shares < Thresholds.LOW_FLOAT_THRESHOLD:
        squeeze_signals += 2  # Low float is strong signal

    # Check beta
    if beta is not None and float(beta) > Thresholds.HIGH_BETA_THRESHOLD:
        squeeze_signals += 1
        flags.append(RiskFlag.EXTREME_VOLATILITY)

    # Check for extreme move
    if float(change_percent) > 50:
        squeeze_signals += 2  # 50%+ move is extreme
    elif float(change_percent) > 30:
        squeeze_signals += 1

    # Check days to cover (if we have float and volume)
    if float_shares is not None and avg_volume is not None and avg_volume > 0:
        days_to_cover = float_shares / avg_volume
        if days_to_cover < 1:
            squeeze_signals += 1  # Very easy to squeeze

    # Micro-cap with big move = squeeze risk
    if market_cap is not None and market_cap < 500_000_000 and float(change_percent) > 20:
        squeeze_signals += 1

    # Flag if multiple squeeze signals
    if squeeze_signals >= 2:
        flags.append(RiskFlag.HIGH_SQUEEZE)

    return flags


def assess_shortability(
    beta: Optional[Decimal],
    max_beta_for_shares: float,
) -> str:
    """
    Determine preferred short expression based on volatility.

    Args:
        beta: Stock beta
        max_beta_for_shares: Maximum beta for direct shorting

    Returns:
        "shares", "puts", or "avoid"
    """
    if beta is None:
        return "puts"  # Default to defined risk without beta info

    beta_val = float(beta)

    if beta_val > max_beta_for_shares * 1.5:
        return "avoid"  # Too volatile
    elif beta_val > max_beta_for_shares:
        return "puts"  # High volatility - use options
    else:
        return "shares"  # Acceptable for direct short


# -----------------------------------------------------------------------------
# Main pre-filter function
# -----------------------------------------------------------------------------


def prefilter_ticker(
    ticker: str,
    fundamentals: Optional[Fundamentals],
    change_percent: Decimal,
    settings: Settings,
) -> FilteredTicker:
    """
    Apply all pre-filters to a single ticker.

    Args:
        ticker: Stock symbol
        fundamentals: Fundamentals data (may be None)
        change_percent: Today's percentage change
        settings: Configuration settings

    Returns:
        FilteredTicker with pass/fail status and risk flags
    """
    all_flags: list[RiskFlag] = []
    exclusion_reasons: list[str] = []

    # Extract data from fundamentals
    market_cap = fundamentals.market_cap if fundamentals else None
    avg_volume = fundamentals.avg_volume_10d if fundamentals else None
    exchange = fundamentals.exchange if fundamentals else None
    beta = fundamentals.beta if fundamentals else None
    float_shares = fundamentals.float_shares if fundamentals else None

    # --- Market Cap Check ---
    passed_mcap, reason_mcap, flags_mcap = check_market_cap(
        market_cap, settings.min_market_cap
    )
    if not passed_mcap:
        exclusion_reasons.append(reason_mcap)
    all_flags.extend(flags_mcap)

    # --- Volume Check ---
    passed_vol, reason_vol, flags_vol = check_volume(
        avg_volume, settings.min_avg_volume
    )
    if not passed_vol:
        exclusion_reasons.append(reason_vol)
    all_flags.extend(flags_vol)

    # --- Exchange Check ---
    passed_exch, reason_exch, flags_exch = check_exchange(exchange, require_nasdaq=True)
    if not passed_exch:
        exclusion_reasons.append(reason_exch)
    all_flags.extend(flags_exch)

    # --- Squeeze Risk (flags only, doesn't exclude) ---
    squeeze_flags = check_squeeze_risk(
        market_cap=market_cap,
        float_shares=float_shares,
        beta=beta,
        avg_volume=avg_volume,
        change_percent=change_percent,
    )
    all_flags.extend(squeeze_flags)

    # --- Determine final status ---
    passed = len(exclusion_reasons) == 0

    # Deduplicate flags
    unique_flags = list(set(all_flags))
    if not unique_flags:
        unique_flags = [RiskFlag.NONE]

    return FilteredTicker(
        ticker=ticker,
        passed=passed,
        risk_flags=unique_flags,
        exclusion_reason="; ".join(exclusion_reasons) if exclusion_reasons else None,
        market_cap=market_cap,
        avg_volume=avg_volume,
        beta=beta,
    )


def prefilter_batch(
    tickers_with_data: list[tuple[str, Optional[Fundamentals], Decimal]],
    settings: Settings,
) -> PrefilterResult:
    """
    Apply pre-filters to a batch of tickers.

    Args:
        tickers_with_data: List of (ticker, fundamentals, change_percent) tuples
        settings: Configuration settings

    Returns:
        PrefilterResult with passed and excluded tickers
    """
    passed = []
    excluded = []

    for ticker, fundamentals, change_pct in tickers_with_data:
        result = prefilter_ticker(ticker, fundamentals, change_pct, settings)

        if result.passed:
            passed.append(result)
        else:
            excluded.append(result)

    return PrefilterResult(
        passed=passed,
        excluded=excluded,
        total_input=len(tickers_with_data),
    )


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def summarize_exclusions(result: PrefilterResult) -> dict[str, int]:
    """
    Summarize exclusion reasons for reporting.

    Returns:
        Dict mapping reason category to count
    """
    reasons = {}

    for ticker in result.excluded:
        if ticker.exclusion_reason:
            # Extract first reason keyword
            reason = ticker.exclusion_reason.split()[0] if ticker.exclusion_reason else "Unknown"
            if "Market" in ticker.exclusion_reason:
                reason = "Market cap"
            elif "volume" in ticker.exclusion_reason.lower():
                reason = "Volume"
            elif "NASDAQ" in ticker.exclusion_reason:
                reason = "Exchange"
            else:
                reason = "Other"

            reasons[reason] = reasons.get(reason, 0) + 1

    return reasons


def get_risk_summary(result: PrefilterResult) -> dict[str, int]:
    """
    Summarize risk flags for passed tickers.

    Returns:
        Dict mapping risk flag to count
    """
    flags = {}

    for ticker in result.passed:
        for flag in ticker.risk_flags:
            if flag != RiskFlag.NONE:
                flags[flag.value] = flags.get(flag.value, 0) + 1

    return flags


def has_dangerous_risk_profile(filtered: FilteredTicker) -> bool:
    """
    Check if ticker has combination of risks that make it dangerous to short.

    Returns True if:
    - Has both MICROCAP and HIGH_SQUEEZE
    - Has both HIGH_SQUEEZE and EXTREME_VOLATILITY
    """
    flags = set(filtered.risk_flags)

    dangerous_combos = [
        {RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE},
        {RiskFlag.HIGH_SQUEEZE, RiskFlag.EXTREME_VOLATILITY},
        {RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE, RiskFlag.LOW_LIQUIDITY},
    ]

    for combo in dangerous_combos:
        if combo.issubset(flags):
            return True

    return False
