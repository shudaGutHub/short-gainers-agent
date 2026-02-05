"""
Data ingestion module.

Provides functions for fetching market data from Alpha Vantage
with yfinance fallback and DuckDB caching.
Supports multiple ticker sources including NASDAQ, watchlists, and screener exports.
"""

from src.ingest.gainers import (
    GainersResult,
    WatchlistEntry,
    create_manual_gainers,
    fetch_top_gainers,
    filter_nasdaq_gainers,
    load_watchlist,
    load_screener_export,
)
from src.ingest.ticker_sources import (
    TickerSource,
    TickerSourceManager,
    TickerSourceManagerConfig,
    TickerSourceResult,
    SourceConfig,
)
from src.ingest.price import (
    PriceDataResult,
    calculate_vwap,
    fetch_daily_ohlcv,
    fetch_intraday_ohlcv,
    fetch_price_data,
    fetch_price_data_batch,
    get_current_price,
    get_intraday_high,
    get_intraday_low,
    get_prior_close,
)
from src.ingest.fundamentals import (
    FundamentalsResult,
    calculate_price_vs_52_week_range,
    estimate_float,
    fetch_fundamentals,
    fetch_fundamentals_batch,
    get_avg_volume,
    get_beta,
    get_market_cap,
    is_nasdaq_listed,
    is_near_52_week_high,
)
from src.ingest.news import (
    NewsResult,
    detect_catalyst_keywords,
    fetch_news,
    fetch_news_batch,
    format_headlines_for_claude,
    get_avg_sentiment_score,
    get_recent_headlines,
    get_today_headlines,
    has_earnings_news,
    has_fda_news,
    has_ma_news,
)
from src.ingest.cache import DataCache

__all__ = [
    # Gainers
    "GainersResult",
    "WatchlistEntry",
    "create_manual_gainers",
    "fetch_top_gainers",
    "filter_nasdaq_gainers",
    "load_watchlist",
    "load_screener_export",
    # Ticker Sources
    "TickerSource",
    "TickerSourceManager",
    "TickerSourceManagerConfig",
    "TickerSourceResult",
    "SourceConfig",
    # Price
    "PriceDataResult",
    "calculate_vwap",
    "fetch_daily_ohlcv",
    "fetch_intraday_ohlcv",
    "fetch_price_data",
    "fetch_price_data_batch",
    "get_current_price",
    "get_intraday_high",
    "get_intraday_low",
    "get_prior_close",
    # Fundamentals
    "FundamentalsResult",
    "calculate_price_vs_52_week_range",
    "estimate_float",
    "fetch_fundamentals",
    "fetch_fundamentals_batch",
    "get_avg_volume",
    "get_beta",
    "get_market_cap",
    "is_nasdaq_listed",
    "is_near_52_week_high",
    # News
    "NewsResult",
    "detect_catalyst_keywords",
    "fetch_news",
    "fetch_news_batch",
    "format_headlines_for_claude",
    "get_avg_sentiment_score",
    "get_recent_headlines",
    "get_today_headlines",
    "has_earnings_news",
    "has_fda_news",
    "has_ma_news",
    # Cache
    "DataCache",
]
