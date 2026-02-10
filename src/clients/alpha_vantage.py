"""
Alpha Vantage API client with rate limiting and caching.

Handles all direct API interactions with Alpha Vantage endpoints.
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

import httpx

from src.models.ticker import (
    Exchange,
    Fundamentals,
    GainerRecord,
    NewsFeed,
    NewsItem,
    OHLCV,
    OHLCVSeries,
)


class AlphaVantageError(Exception):
    """Base exception for AV API errors."""

    pass


class RateLimitError(AlphaVantageError):
    """Raised when rate limit is exceeded."""

    pass


class InvalidResponseError(AlphaVantageError):
    """Raised when API returns unexpected data."""

    pass


class AlphaVantageClient:
    """
    Async client for Alpha Vantage API.

    Implements rate limiting and response parsing for all required endpoints.
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str,
        rate_limit_rpm: int = 75,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.rate_limit_rpm = rate_limit_rpm
        self.request_delay = 60.0 / rate_limit_rpm
        self.timeout = timeout
        self._last_request_time: Optional[float] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AlphaVantageClient":
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _throttle(self) -> None:
        """Enforce rate limiting between requests."""
        if self._last_request_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time
            if elapsed < self.request_delay:
                await asyncio.sleep(self.request_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _request(self, params: dict[str, str]) -> dict[str, Any]:
        """Make rate-limited request to AV API."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)

        await self._throttle()

        params["apikey"] = self.api_key
        response = await self._client.get(self.BASE_URL, params=params)
        response.raise_for_status()

        data = response.json()

        # Check for AV error responses
        if "Error Message" in data:
            raise InvalidResponseError(data["Error Message"])
        if "Note" in data and "API call frequency" in data.get("Note", ""):
            raise RateLimitError(data["Note"])
        if "Information" in data and "API call frequency" in data.get("Information", ""):
            raise RateLimitError(data["Information"])

        return data

    # -------------------------------------------------------------------------
    # TOP GAINERS / LOSERS
    # -------------------------------------------------------------------------

    async def get_top_gainers(self) -> list[GainerRecord]:
        """
        Fetch today's top NASDAQ gainers.

        Returns:
            List of GainerRecord sorted by change_percentage descending.
        """
        data = await self._request({"function": "TOP_GAINERS_LOSERS"})

        gainers_raw = data.get("top_gainers", [])
        if not gainers_raw:
            return []

        gainers = []
        for item in gainers_raw:
            try:
                record = GainerRecord(
                    ticker=item["ticker"],
                    price=Decimal(item["price"]),
                    change_amount=Decimal(item["change_amount"]),
                    change_percentage=item["change_percentage"],
                    volume=int(item["volume"]),
                )
                gainers.append(record)
            except (KeyError, ValueError) as e:
                # Skip malformed records
                continue

        return gainers

    # -------------------------------------------------------------------------
    # PRICE DATA
    # -------------------------------------------------------------------------

    async def get_daily_ohlcv(
        self,
        ticker: str,
        outputsize: str = "full",
    ) -> OHLCVSeries:
        """
        Fetch daily OHLCV data for a ticker.

        Args:
            ticker: Stock symbol
            outputsize: "compact" (100 days) or "full" (20+ years)

        Returns:
            OHLCVSeries with bars in reverse chronological order.
        """
        data = await self._request({
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "outputsize": outputsize,
        })

        time_series = data.get("Time Series (Daily)", {})
        bars = self._parse_ohlcv(time_series, date_format="%Y-%m-%d")

        return OHLCVSeries(ticker=ticker, interval="daily", bars=bars)

    async def get_intraday_ohlcv(
        self,
        ticker: str,
        interval: str = "15min",
        outputsize: str = "full",
    ) -> OHLCVSeries:
        """
        Fetch intraday OHLCV data for a ticker.

        Args:
            ticker: Stock symbol
            interval: "1min", "5min", "15min", "30min", "60min"
            outputsize: "compact" (100 bars) or "full" (30 days)

        Returns:
            OHLCVSeries with bars in reverse chronological order.
        """
        data = await self._request({
            "function": "TIME_SERIES_INTRADAY",
            "symbol": ticker,
            "interval": interval,
            "outputsize": outputsize,
        })

        key = f"Time Series ({interval})"
        time_series = data.get(key, {})
        bars = self._parse_ohlcv(time_series, date_format="%Y-%m-%d %H:%M:%S")

        return OHLCVSeries(ticker=ticker, interval=interval, bars=bars)

    def _parse_ohlcv(
        self,
        time_series: dict[str, dict],
        date_format: str,
    ) -> list[OHLCV]:
        """Parse AV time series format into OHLCV list."""
        bars = []
        for timestamp_str, values in time_series.items():
            try:
                bar = OHLCV(
                    timestamp=datetime.strptime(timestamp_str, date_format),
                    open=Decimal(values["1. open"]),
                    high=Decimal(values["2. high"]),
                    low=Decimal(values["3. low"]),
                    close=Decimal(values["4. close"]),
                    volume=int(values["5. volume"]),
                )
                bars.append(bar)
            except (KeyError, ValueError):
                continue

        # Sort reverse chronological (most recent first)
        bars.sort(key=lambda x: x.timestamp, reverse=True)
        return bars

    # -------------------------------------------------------------------------
    # FUNDAMENTALS
    # -------------------------------------------------------------------------

    async def get_fundamentals(self, ticker: str) -> Fundamentals:
        """
        Fetch company fundamentals from OVERVIEW endpoint.

        Args:
            ticker: Stock symbol

        Returns:
            Fundamentals model (fields may be None if not available)
        """
        data = await self._request({
            "function": "OVERVIEW",
            "symbol": ticker,
        })

        # Map exchange string to enum
        exchange_str = data.get("Exchange", "").upper()
        exchange = Exchange.NASDAQ if "NASDAQ" in exchange_str else (
            Exchange.NYSE if "NYSE" in exchange_str else Exchange.OTHER
        )

        return Fundamentals(
            ticker=ticker,
            name=data.get("Name"),
            exchange=exchange,
            sector=data.get("Sector"),
            industry=data.get("Industry"),
            market_cap=self._parse_int(data.get("MarketCapitalization")),
            beta=self._parse_decimal(data.get("Beta")),
            pe_ratio=self._parse_decimal(data.get("PERatio")),
            eps=self._parse_decimal(data.get("EPS")),
            shares_outstanding=self._parse_int(data.get("SharesOutstanding")),
            avg_volume_10d=self._parse_int(data.get("10DayAverageVolume")),
            week_52_high=self._parse_decimal(data.get("52WeekHigh")),
            week_52_low=self._parse_decimal(data.get("52WeekLow")),
        )

    # -------------------------------------------------------------------------
    # NEWS
    # -------------------------------------------------------------------------

    async def get_news(
        self,
        ticker: str,
        limit: int = 50,
    ) -> NewsFeed:
        """
        Fetch news and sentiment for a ticker.

        Args:
            ticker: Stock symbol
            limit: Max articles to return

        Returns:
            NewsFeed with NewsItems
        """
        data = await self._request({
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "limit": str(limit),
        })

        feed_data = data.get("feed", [])
        items = []

        for article in feed_data[:limit]:
            try:
                # Find ticker-specific sentiment
                ticker_sentiment = None
                relevance = None
                for ts in article.get("ticker_sentiment", []):
                    if ts.get("ticker") == ticker:
                        ticker_sentiment = self._parse_decimal(
                            ts.get("ticker_sentiment_score")
                        )
                        relevance = self._parse_decimal(ts.get("relevance_score"))
                        break

                item = NewsItem(
                    title=article["title"],
                    url=article["url"],
                    source=article.get("source", "Unknown"),
                    published_at=datetime.strptime(
                        article["time_published"], "%Y%m%dT%H%M%S"
                    ),
                    summary=article.get("summary"),
                    ticker_sentiment=ticker_sentiment,
                    relevance_score=relevance,
                )
                items.append(item)
            except (KeyError, ValueError):
                continue

        return NewsFeed(
            ticker=ticker,
            items=items,
            fetched_at=datetime.now(),
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
        """Safely parse string to Decimal."""
        if value is None or value == "None" or value == "-":
            return None
        try:
            return Decimal(value)
        except Exception:
            return None

    @staticmethod
    def _parse_int(value: Optional[str]) -> Optional[int]:
        """Safely parse string to int."""
        if value is None or value == "None" or value == "-":
            return None
        try:
            return int(value)
        except Exception:
            return None
