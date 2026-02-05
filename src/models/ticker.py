"""
Data models for ticker information from Alpha Vantage.

These models represent raw data from API responses.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class GainerRecord(BaseModel):
    """A single record from the TOP_GAINERS_LOSERS endpoint."""

    ticker: str
    price: Decimal
    change_amount: Decimal
    change_percentage: Decimal
    volume: int

    @field_validator("change_percentage", mode="before")
    @classmethod
    def strip_percentage_sign(cls, v: str | Decimal) -> Decimal:
        """Remove trailing % from percentage strings."""
        if isinstance(v, str):
            return Decimal(v.rstrip("%"))
        return v


class OHLCV(BaseModel):
    """Single OHLCV bar (works for both daily and intraday)."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class OHLCVSeries(BaseModel):
    """Time series of OHLCV data for a ticker."""

    ticker: str
    interval: str  # "daily", "15min", "5min", etc.
    bars: list[OHLCV]

    @property
    def is_empty(self) -> bool:
        return len(self.bars) == 0

    def most_recent(self) -> Optional[OHLCV]:
        """Return most recent bar or None if empty."""
        return self.bars[0] if self.bars else None


class Exchange(str, Enum):
    """Supported exchanges."""

    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    OTHER = "OTHER"


class Fundamentals(BaseModel):
    """Company fundamentals from OVERVIEW endpoint."""

    ticker: str
    name: Optional[str] = None
    exchange: Optional[Exchange] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[int] = None
    beta: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    eps: Optional[Decimal] = None
    shares_outstanding: Optional[int] = None
    float_shares: Optional[int] = Field(default=None, description="Often unavailable")
    avg_volume_10d: Optional[int] = None
    week_52_high: Optional[Decimal] = None
    week_52_low: Optional[Decimal] = None

    @property
    def is_nasdaq(self) -> bool:
        return self.exchange == Exchange.NASDAQ

    @property
    def has_sufficient_data(self) -> bool:
        """Check if we have minimum required data for analysis."""
        return self.market_cap is not None and self.market_cap > 0


class NewsItem(BaseModel):
    """Single news article from NEWS_SENTIMENT endpoint."""

    title: str
    url: str
    source: str
    published_at: datetime
    summary: Optional[str] = None
    ticker_sentiment: Optional[Decimal] = Field(
        default=None, description="AV sentiment score for this ticker"
    )
    relevance_score: Optional[Decimal] = None


class NewsFeed(BaseModel):
    """Collection of news items for a ticker."""

    ticker: str
    items: list[NewsItem]
    fetched_at: datetime

    @property
    def has_recent_news(self) -> bool:
        """Check if there is news from today."""
        if not self.items:
            return False
        today = datetime.now().date()
        return any(item.published_at.date() == today for item in self.items)
