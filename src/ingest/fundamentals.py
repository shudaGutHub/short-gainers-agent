"""
Fundamentals data ingestion with Alpha Vantage primary and yfinance fallback.

Fetches company fundamentals for pre-filtering and risk assessment.
"""

from dataclasses import dataclass
from typing import Optional

from src.clients.alpha_vantage import AlphaVantageClient, AlphaVantageError
from src.clients.yfinance_client import YFinanceClient
from src.models.ticker import Exchange, Fundamentals


@dataclass
class FundamentalsResult:
    """Result of fundamentals fetch operation."""

    data: Optional[Fundamentals]
    source: str  # "alpha_vantage", "yfinance", or "none"
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.data is not None and self.data.has_sufficient_data


async def fetch_fundamentals(
    ticker: str,
    av_client: Optional[AlphaVantageClient],
    yf_client: Optional[YFinanceClient],
) -> FundamentalsResult:
    """
    Fetch company fundamentals with fallback.

    Args:
        ticker: Stock symbol
        av_client: Alpha Vantage client (primary)
        yf_client: yfinance client (fallback)

    Returns:
        FundamentalsResult with company data
    """
    # Try Alpha Vantage first
    if av_client is not None:
        try:
            data = await av_client.get_fundamentals(ticker)
            if data.has_sufficient_data:
                return FundamentalsResult(data=data, source="alpha_vantage")
        except AlphaVantageError as e:
            pass  # Fall through to yfinance
        except Exception as e:
            pass  # Fall through to yfinance

    # Fallback to yfinance
    if yf_client is not None:
        try:
            data = yf_client.get_fundamentals(ticker)
            if data.has_sufficient_data:
                return FundamentalsResult(data=data, source="yfinance")
            else:
                return FundamentalsResult(
                    data=data,
                    source="yfinance",
                    error="Insufficient data from yfinance",
                )
        except Exception as e:
            return FundamentalsResult(
                data=None,
                source="none",
                error=f"yfinance error: {str(e)}",
            )

    return FundamentalsResult(
        data=None,
        source="none",
        error="No data source available",
    )


async def fetch_fundamentals_batch(
    tickers: list[str],
    av_client: Optional[AlphaVantageClient],
    yf_client: Optional[YFinanceClient],
) -> dict[str, FundamentalsResult]:
    """
    Fetch fundamentals for multiple tickers.

    Args:
        tickers: List of stock symbols
        av_client: Alpha Vantage client
        yf_client: yfinance fallback client

    Returns:
        Dict mapping ticker to FundamentalsResult
    """
    results = {}

    for ticker in tickers:
        result = await fetch_fundamentals(
            ticker=ticker,
            av_client=av_client,
            yf_client=yf_client,
        )
        results[ticker] = result

    return results


# -----------------------------------------------------------------------------
# Helper functions for fundamentals analysis
# -----------------------------------------------------------------------------


def is_nasdaq_listed(result: FundamentalsResult) -> bool:
    """Check if ticker is listed on NASDAQ."""
    if not result.is_success:
        return False
    return result.data.exchange == Exchange.NASDAQ


def get_market_cap(result: FundamentalsResult) -> Optional[int]:
    """Extract market cap from fundamentals."""
    if not result.is_success:
        return None
    return result.data.market_cap


def get_beta(result: FundamentalsResult) -> Optional[float]:
    """Extract beta from fundamentals."""
    if not result.is_success:
        return None
    if result.data.beta is None:
        return None
    return float(result.data.beta)


def get_avg_volume(result: FundamentalsResult) -> Optional[int]:
    """Extract average volume from fundamentals."""
    if not result.is_success:
        return None
    return result.data.avg_volume_10d


def estimate_float(result: FundamentalsResult) -> Optional[int]:
    """
    Estimate float shares.

    Float is often unavailable. If not present, estimate as 80% of shares outstanding.
    This is a rough approximation.
    """
    if not result.is_success:
        return None

    if result.data.float_shares is not None:
        return result.data.float_shares

    if result.data.shares_outstanding is not None:
        # Rough estimate: 80% of outstanding is float
        return int(result.data.shares_outstanding * 0.8)

    return None


def is_near_52_week_high(result: FundamentalsResult, current_price: float) -> bool:
    """
    Check if current price is within 10% of 52-week high.

    This can indicate overextension.
    """
    if not result.is_success:
        return False
    if result.data.week_52_high is None:
        return False

    high = float(result.data.week_52_high)
    threshold = high * 0.9

    return current_price >= threshold


def calculate_price_vs_52_week_range(
    result: FundamentalsResult, current_price: float
) -> Optional[float]:
    """
    Calculate where current price sits in 52-week range.

    Returns:
        Float from 0.0 (at 52w low) to 1.0 (at 52w high), or None if unavailable
    """
    if not result.is_success:
        return None
    if result.data.week_52_high is None or result.data.week_52_low is None:
        return None

    high = float(result.data.week_52_high)
    low = float(result.data.week_52_low)

    if high == low:
        return 0.5

    return (current_price - low) / (high - low)
