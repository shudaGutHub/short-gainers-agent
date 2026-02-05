"""
News data ingestion from Alpha Vantage.

Fetches news and sentiment for catalyst analysis.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.clients.alpha_vantage import AlphaVantageClient, AlphaVantageError
from src.models.ticker import NewsFeed, NewsItem


@dataclass
class NewsResult:
    """Result of news fetch operation."""

    feed: Optional[NewsFeed]
    source: str  # "alpha_vantage" or "none"
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.feed is not None and len(self.feed.items) > 0

    @property
    def item_count(self) -> int:
        if self.feed is None:
            return 0
        return len(self.feed.items)


async def fetch_news(
    ticker: str,
    av_client: Optional[AlphaVantageClient],
    limit: int = 20,
) -> NewsResult:
    """
    Fetch news for a ticker from Alpha Vantage.

    Args:
        ticker: Stock symbol
        av_client: Alpha Vantage client
        limit: Max articles to fetch

    Returns:
        NewsResult with news items
    """
    if av_client is None:
        return NewsResult(
            feed=None,
            source="none",
            error="No Alpha Vantage client provided",
        )

    try:
        feed = await av_client.get_news(ticker, limit=limit)
        return NewsResult(feed=feed, source="alpha_vantage")
    except AlphaVantageError as e:
        return NewsResult(
            feed=None,
            source="alpha_vantage",
            error=f"API error: {str(e)}",
        )
    except Exception as e:
        return NewsResult(
            feed=None,
            source="alpha_vantage",
            error=f"Unexpected error: {str(e)}",
        )


async def fetch_news_batch(
    tickers: list[str],
    av_client: Optional[AlphaVantageClient],
    limit: int = 20,
) -> dict[str, NewsResult]:
    """
    Fetch news for multiple tickers.

    Args:
        tickers: List of stock symbols
        av_client: Alpha Vantage client
        limit: Max articles per ticker

    Returns:
        Dict mapping ticker to NewsResult
    """
    results = {}

    for ticker in tickers:
        result = await fetch_news(
            ticker=ticker,
            av_client=av_client,
            limit=limit,
        )
        results[ticker] = result

    return results


# -----------------------------------------------------------------------------
# Helper functions for news analysis
# -----------------------------------------------------------------------------


def get_today_headlines(result: NewsResult) -> list[str]:
    """Extract headlines from today's news."""
    if not result.is_success:
        return []

    today = datetime.now().date()
    return [
        item.title
        for item in result.feed.items
        if item.published_at.date() == today
    ]


def get_recent_headlines(result: NewsResult, max_count: int = 10) -> list[str]:
    """Extract most recent headlines."""
    if not result.is_success:
        return []

    return [item.title for item in result.feed.items[:max_count]]


def get_headlines_with_sources(result: NewsResult, max_count: int = 10) -> list[tuple[str, str]]:
    """Extract headlines with their sources."""
    if not result.is_success:
        return []

    return [
        (item.title, item.source)
        for item in result.feed.items[:max_count]
    ]


def get_avg_sentiment_score(result: NewsResult) -> Optional[float]:
    """
    Calculate average sentiment score from Alpha Vantage sentiment.

    AV sentiment ranges from -1 (bearish) to +1 (bullish).
    """
    if not result.is_success:
        return None

    scores = [
        float(item.ticker_sentiment)
        for item in result.feed.items
        if item.ticker_sentiment is not None
    ]

    if not scores:
        return None

    return sum(scores) / len(scores)


def has_earnings_news(result: NewsResult) -> bool:
    """Check if recent news mentions earnings."""
    if not result.is_success:
        return False

    earnings_keywords = [
        "earnings", "eps", "revenue", "profit", "loss",
        "quarter", "q1", "q2", "q3", "q4", "fiscal",
        "beat", "miss", "guidance", "outlook",
    ]

    for item in result.feed.items[:10]:
        title_lower = item.title.lower()
        if any(kw in title_lower for kw in earnings_keywords):
            return True

    return False


def has_fda_news(result: NewsResult) -> bool:
    """Check if recent news mentions FDA/regulatory."""
    if not result.is_success:
        return False

    fda_keywords = [
        "fda", "approval", "approved", "clinical", "trial",
        "phase", "drug", "therapy", "treatment", "regulatory",
    ]

    for item in result.feed.items[:10]:
        title_lower = item.title.lower()
        if any(kw in title_lower for kw in fda_keywords):
            return True

    return False


def has_ma_news(result: NewsResult) -> bool:
    """Check if recent news mentions M&A."""
    if not result.is_success:
        return False

    ma_keywords = [
        "merger", "acquisition", "acquire", "acquired", "buyout",
        "takeover", "deal", "offer", "bid", "purchase",
    ]

    for item in result.feed.items[:10]:
        title_lower = item.title.lower()
        if any(kw in title_lower for kw in ma_keywords):
            return True

    return False


def detect_catalyst_keywords(result: NewsResult) -> dict[str, bool]:
    """
    Scan news for various catalyst keywords.

    Returns dict with catalyst type presence flags.
    """
    return {
        "earnings": has_earnings_news(result),
        "fda": has_fda_news(result),
        "ma": has_ma_news(result),
    }


def format_headlines_for_claude(result: NewsResult, max_count: int = 10) -> str:
    """
    Format headlines for Claude sentiment analysis prompt.

    Returns formatted string suitable for the Claude prompt.
    """
    if not result.is_success:
        return "No recent news available."

    headlines = get_headlines_with_sources(result, max_count)

    if not headlines:
        return "No recent news available."

    lines = []
    for title, source in headlines:
        lines.append(f"- [{source}] {title}")

    return "\n".join(lines)
