"""
Price data ingestion with Alpha Vantage primary and yfinance fallback.

Handles daily and intraday OHLCV data fetching with caching.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from src.clients.alpha_vantage import AlphaVantageClient, AlphaVantageError
from src.clients.yfinance_client import YFinanceClient
from src.models.ticker import OHLCV, OHLCVSeries


@dataclass
class PriceDataResult:
    """Result of price data fetch operation."""

    daily: Optional[OHLCVSeries]
    intraday: Optional[OHLCVSeries]
    source: str  # "alpha_vantage", "yfinance", or "mixed"
    errors: list[str]

    @property
    def has_daily(self) -> bool:
        return self.daily is not None and not self.daily.is_empty

    @property
    def has_intraday(self) -> bool:
        return self.intraday is not None and not self.intraday.is_empty

    @property
    def is_complete(self) -> bool:
        return self.has_daily and self.has_intraday

    def get_current_price(self) -> Optional[Decimal]:
        """Get most recent closing price."""
        if self.has_intraday:
            return self.intraday.bars[0].close
        if self.has_daily:
            return self.daily.bars[0].close
        return None

    def get_prior_close(self) -> Optional[Decimal]:
        """Get prior day's closing price."""
        if self.has_daily and len(self.daily.bars) >= 2:
            return self.daily.bars[1].close
        return None

    def get_intraday_high(self) -> Optional[Decimal]:
        """Get today's intraday high."""
        if not self.has_intraday:
            return None
        return max(b.high for b in self.intraday.bars)

    def get_intraday_low(self) -> Optional[Decimal]:
        """Get today's intraday low."""
        if not self.has_intraday:
            return None
        return min(b.low for b in self.intraday.bars)

    def calculate_vwap(self) -> Optional[Decimal]:
        """Calculate VWAP from intraday data."""
        if not self.has_intraday:
            return None

        total_pv = Decimal("0")
        total_volume = 0

        for bar in self.intraday.bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_pv += typical_price * bar.volume
            total_volume += bar.volume

        if total_volume == 0:
            return None

        return total_pv / total_volume


async def fetch_daily_ohlcv(
    ticker: str,
    av_client: Optional[AlphaVantageClient],
    yf_client: Optional[YFinanceClient],
    days: int = 60,
) -> tuple[Optional[OHLCVSeries], str, Optional[str]]:
    """
    Fetch daily OHLCV with fallback.

    Args:
        ticker: Stock symbol
        av_client: Alpha Vantage client (primary)
        yf_client: yfinance client (fallback)
        days: Number of days to fetch

    Returns:
        Tuple of (OHLCVSeries or None, source, error or None)
    """
    # Try Alpha Vantage first
    if av_client is not None:
        try:
            series = await av_client.get_daily_ohlcv(ticker, outputsize="full")
            if not series.is_empty:
                # Trim to requested days
                cutoff = datetime.now() - timedelta(days=days)
                trimmed_bars = [b for b in series.bars if b.timestamp >= cutoff]
                return (
                    OHLCVSeries(ticker=ticker, interval="daily", bars=trimmed_bars),
                    "alpha_vantage",
                    None,
                )
        except AlphaVantageError as e:
            pass  # Fall through to yfinance
        except Exception as e:
            pass  # Fall through to yfinance

    # Fallback to yfinance
    if yf_client is not None:
        try:
            series = yf_client.get_daily_ohlcv(ticker, days=days)
            if not series.is_empty:
                return (series, "yfinance", None)
        except Exception as e:
            return (None, "none", f"yfinance error: {str(e)}")

    return (None, "none", "No data source available")


async def fetch_intraday_ohlcv(
    ticker: str,
    av_client: Optional[AlphaVantageClient],
    yf_client: Optional[YFinanceClient],
    interval: str = "15min",
) -> tuple[Optional[OHLCVSeries], str, Optional[str]]:
    """
    Fetch intraday OHLCV with fallback.

    Args:
        ticker: Stock symbol
        av_client: Alpha Vantage client (primary)
        yf_client: yfinance client (fallback)
        interval: Bar interval ("5min", "15min", "30min", "60min")

    Returns:
        Tuple of (OHLCVSeries or None, source, error or None)
    """
    # Try Alpha Vantage first
    if av_client is not None:
        try:
            series = await av_client.get_intraday_ohlcv(
                ticker, interval=interval, outputsize="full"
            )
            if not series.is_empty:
                return (series, "alpha_vantage", None)
        except AlphaVantageError as e:
            pass  # Fall through to yfinance
        except Exception as e:
            pass  # Fall through to yfinance

    # Fallback to yfinance
    if yf_client is not None:
        try:
            # yfinance uses different interval notation
            yf_interval = interval.replace("min", "m")
            series = yf_client.get_intraday_ohlcv(ticker, interval=yf_interval, days=7)
            if not series.is_empty:
                return (series, "yfinance", None)
        except Exception as e:
            return (None, "none", f"yfinance error: {str(e)}")

    return (None, "none", "No data source available")


async def fetch_price_data(
    ticker: str,
    av_client: Optional[AlphaVantageClient],
    yf_client: Optional[YFinanceClient],
    days: int = 60,
    intraday_interval: str = "15min",
) -> PriceDataResult:
    """
    Fetch complete price data for a ticker.

    Args:
        ticker: Stock symbol
        av_client: Alpha Vantage client
        yf_client: yfinance fallback client
        days: Days of daily history
        intraday_interval: Intraday bar size

    Returns:
        PriceDataResult with daily and intraday data
    """
    errors = []
    sources = set()

    # Fetch daily
    daily, daily_source, daily_error = await fetch_daily_ohlcv(
        ticker, av_client, yf_client, days
    )
    if daily_error:
        errors.append(f"Daily: {daily_error}")
    if daily_source != "none":
        sources.add(daily_source)

    # Fetch intraday
    intraday, intraday_source, intraday_error = await fetch_intraday_ohlcv(
        ticker, av_client, yf_client, intraday_interval
    )
    if intraday_error:
        errors.append(f"Intraday: {intraday_error}")
    if intraday_source != "none":
        sources.add(intraday_source)

    # Determine overall source
    if len(sources) == 0:
        source = "none"
    elif len(sources) == 1:
        source = sources.pop()
    else:
        source = "mixed"

    return PriceDataResult(
        daily=daily,
        intraday=intraday,
        source=source,
        errors=errors,
    )


async def fetch_price_data_batch(
    tickers: list[str],
    av_client: Optional[AlphaVantageClient],
    yf_client: Optional[YFinanceClient],
    days: int = 60,
    intraday_interval: str = "15min",
) -> dict[str, PriceDataResult]:
    """
    Fetch price data for multiple tickers.

    Note: This fetches sequentially to respect rate limits.
    For Alpha Vantage premium, this is ~1 req/sec.

    Args:
        tickers: List of stock symbols
        av_client: Alpha Vantage client
        yf_client: yfinance fallback client
        days: Days of daily history
        intraday_interval: Intraday bar size

    Returns:
        Dict mapping ticker to PriceDataResult
    """
    results = {}

    for ticker in tickers:
        result = await fetch_price_data(
            ticker=ticker,
            av_client=av_client,
            yf_client=yf_client,
            days=days,
            intraday_interval=intraday_interval,
        )
        results[ticker] = result

    return results


# -----------------------------------------------------------------------------
# Helper functions for extracting data from price results
# -----------------------------------------------------------------------------


def get_current_price(result: PriceDataResult) -> Optional[Decimal]:
    """Extract most recent close price from price data."""
    if result.has_intraday:
        bar = result.intraday.most_recent()
        if bar:
            return bar.close
    if result.has_daily:
        bar = result.daily.most_recent()
        if bar:
            return bar.close
    return None


def get_prior_close(result: PriceDataResult) -> Optional[Decimal]:
    """Extract prior day's close price."""
    if result.has_daily and len(result.daily.bars) >= 2:
        return result.daily.bars[1].close
    return None


def get_intraday_high(result: PriceDataResult) -> Optional[Decimal]:
    """Extract today's intraday high."""
    if not result.has_intraday:
        return None

    today = datetime.now().date()
    today_bars = [b for b in result.intraday.bars if b.timestamp.date() == today]

    if not today_bars:
        return None

    return max(b.high for b in today_bars)


def get_intraday_low(result: PriceDataResult) -> Optional[Decimal]:
    """Extract today's intraday low."""
    if not result.has_intraday:
        return None

    today = datetime.now().date()
    today_bars = [b for b in result.intraday.bars if b.timestamp.date() == today]

    if not today_bars:
        return None

    return min(b.low for b in today_bars)


def calculate_vwap(result: PriceDataResult) -> Optional[Decimal]:
    """
    Calculate VWAP for today's session.

    VWAP = Sum(Price * Volume) / Sum(Volume)
    Using typical price = (H + L + C) / 3
    """
    if not result.has_intraday:
        return None

    today = datetime.now().date()
    today_bars = [b for b in result.intraday.bars if b.timestamp.date() == today]

    if not today_bars:
        return None

    total_pv = Decimal("0")
    total_volume = 0

    for bar in today_bars:
        typical_price = (bar.high + bar.low + bar.close) / 3
        total_pv += typical_price * bar.volume
        total_volume += bar.volume

    if total_volume == 0:
        return None

    return total_pv / total_volume
