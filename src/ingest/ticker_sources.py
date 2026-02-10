"""
Unified Ticker Source Manager

Manages multiple ticker sources and provides deduplication and combination logic.
"""

import asyncio
import csv
import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Union, TYPE_CHECKING

# Avoid circular import - import at runtime in methods that need it
if TYPE_CHECKING:
    from src.batch_processor import TickerInput

from src.clients.nasdaq_client import NasdaqClient, NasdaqCategory, NasdaqTicker


# Re-export NasdaqCategory for convenience
__all__ = [
    "TickerSource",
    "SourceConfig",
    "TickerSourceResult",
    "TickerSourceManagerConfig",
    "TickerSourceManager",
    "NasdaqCategory",
    "load_watchlist",
    "load_screener_export",
]


class TickerSource(str, Enum):
    """Available ticker sources."""
    NASDAQ = "nasdaq"
    ALPHA_VANTAGE = "alpha_vantage"
    WATCHLIST = "watchlist"
    SCREENER = "screener"
    MANUAL = "manual"


@dataclass
class SourceConfig:
    """Configuration for a ticker source."""
    enabled: bool = True
    priority: int = 0  # Higher priority sources are preferred during deduplication
    min_price: float = 1.0
    min_volume: int = 100_000
    limit: int = 25


@dataclass
class TickerSourceResult:
    """Result from fetching a ticker source."""
    source: TickerSource
    tickers: list  # list[TickerInput] - avoid import at module level
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.tickers)


@dataclass
class TickerSourceManagerConfig:
    """Configuration for the TickerSourceManager."""
    # Source configurations
    sources: dict[TickerSource, SourceConfig] = field(default_factory=dict)

    # NASDAQ-specific options
    nasdaq_category: NasdaqCategory = NasdaqCategory.GAINERS
    nasdaq_exchange: str = "NASDAQ"

    # File paths
    watchlist_path: Optional[str] = None
    screener_path: Optional[str] = None

    # Alpha Vantage
    alpha_vantage_key: Optional[str] = None

    # Manual tickers
    manual_tickers: list = field(default_factory=list)  # list[TickerInput]

    # Global settings
    max_tickers: int = 50  # Max total tickers after deduplication
    min_price: float = 1.0
    min_volume: int = 100_000

    def __post_init__(self):
        # Set default source configs if not provided
        default_sources = {
            TickerSource.NASDAQ: SourceConfig(priority=100),
            TickerSource.ALPHA_VANTAGE: SourceConfig(priority=90),
            TickerSource.WATCHLIST: SourceConfig(priority=80),
            TickerSource.SCREENER: SourceConfig(priority=70),
            TickerSource.MANUAL: SourceConfig(priority=60),
        }
        for source, config in default_sources.items():
            if source not in self.sources:
                self.sources[source] = config


class TickerSourceManager:
    """
    Manages multiple ticker sources and provides unified access.

    Usage:
        config = TickerSourceManagerConfig(
            nasdaq_category=NasdaqCategory.GAINERS,
            watchlist_path="./watchlist.csv",
        )
        manager = TickerSourceManager(config)

        # Enable specific sources
        manager.enable_sources([TickerSource.NASDAQ, TickerSource.WATCHLIST])

        # Fetch from all enabled sources
        tickers = await manager.fetch_all()
    """

    def __init__(self, config: Optional[TickerSourceManagerConfig] = None):
        """
        Initialize the ticker source manager.

        Args:
            config: Configuration for sources
        """
        self.config = config or TickerSourceManagerConfig()
        self._nasdaq_client: Optional[NasdaqClient] = None
        self._enabled_sources: set[TickerSource] = set()

    def enable_sources(self, sources: list[Union[TickerSource, str]]) -> None:
        """
        Enable specific sources for fetching.

        Args:
            sources: List of source names or TickerSource enums
        """
        self._enabled_sources.clear()
        for source in sources:
            if isinstance(source, str):
                try:
                    source = TickerSource(source.lower())
                except ValueError:
                    continue
            self._enabled_sources.add(source)

    def disable_all_sources(self) -> None:
        """Disable all sources."""
        self._enabled_sources.clear()

    def enable_all_sources(self) -> None:
        """Enable all available sources."""
        self._enabled_sources = set(TickerSource)

    def get_enabled_sources(self) -> list[TickerSource]:
        """Get list of currently enabled sources."""
        return list(self._enabled_sources)

    async def _fetch_nasdaq(self) -> TickerSourceResult:
        """Fetch tickers from NASDAQ market activity."""
        from src.batch_processor import TickerInput

        try:
            source_config = self.config.sources.get(
                TickerSource.NASDAQ, SourceConfig()
            )

            async with NasdaqClient() as client:
                nasdaq_tickers = await client.fetch_market_movers(
                    category=self.config.nasdaq_category,
                    limit=source_config.limit,
                    exchange=self.config.nasdaq_exchange,
                    min_price=source_config.min_price or self.config.min_price,
                    min_volume=source_config.min_volume or self.config.min_volume,
                )

            # Convert NasdaqTicker to TickerInput
            tickers = [
                TickerInput(
                    ticker=t.ticker,
                    change_percent=float(t.change_percent),
                    current_price=float(t.price),
                )
                for t in nasdaq_tickers
            ]

            return TickerSourceResult(
                source=TickerSource.NASDAQ,
                tickers=tickers,
            )

        except Exception as e:
            return TickerSourceResult(
                source=TickerSource.NASDAQ,
                tickers=[],
                error=str(e),
            )

    async def _fetch_alpha_vantage(self) -> TickerSourceResult:
        """Fetch tickers from Alpha Vantage top gainers API."""
        from src.batch_processor import TickerInput

        try:
            import aiohttp

            av_key = self.config.alpha_vantage_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
            if not av_key:
                return TickerSourceResult(
                    source=TickerSource.ALPHA_VANTAGE,
                    tickers=[],
                    error="Alpha Vantage API key not configured",
                )

            source_config = self.config.sources.get(
                TickerSource.ALPHA_VANTAGE, SourceConfig()
            )

            url = "https://www.alphavantage.co/query"
            params = {
                "function": "TOP_GAINERS_LOSERS",
                "apikey": av_key,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        return TickerSourceResult(
                            source=TickerSource.ALPHA_VANTAGE,
                            tickers=[],
                            error=f"HTTP {response.status}",
                        )

                    data = await response.json()

            # Parse top gainers
            tickers = []
            for item in data.get("top_gainers", [])[:source_config.limit]:
                ticker = item.get("ticker", "")
                price_str = item.get("price", "0")
                change_str = item.get("change_percentage", "0%").replace("%", "")
                volume_str = item.get("volume", "0")

                try:
                    price = float(price_str)
                    change = float(change_str)
                    volume = int(volume_str)

                    # Apply filters
                    min_price = source_config.min_price or self.config.min_price
                    min_volume = source_config.min_volume or self.config.min_volume

                    if price >= min_price and volume >= min_volume:
                        tickers.append(TickerInput(
                            ticker=ticker,
                            change_percent=change,
                            current_price=price,
                        ))
                except (ValueError, TypeError):
                    continue

            return TickerSourceResult(
                source=TickerSource.ALPHA_VANTAGE,
                tickers=tickers,
            )

        except Exception as e:
            return TickerSourceResult(
                source=TickerSource.ALPHA_VANTAGE,
                tickers=[],
                error=str(e),
            )

    async def _fetch_watchlist(self) -> TickerSourceResult:
        """Load tickers from watchlist file."""
        try:
            if not self.config.watchlist_path:
                return TickerSourceResult(
                    source=TickerSource.WATCHLIST,
                    tickers=[],
                    error="Watchlist path not configured",
                )

            tickers = load_watchlist(self.config.watchlist_path)
            return TickerSourceResult(
                source=TickerSource.WATCHLIST,
                tickers=tickers,
            )

        except Exception as e:
            return TickerSourceResult(
                source=TickerSource.WATCHLIST,
                tickers=[],
                error=str(e),
            )

    async def _fetch_screener(self) -> TickerSourceResult:
        """Load tickers from screener export file."""
        try:
            if not self.config.screener_path:
                return TickerSourceResult(
                    source=TickerSource.SCREENER,
                    tickers=[],
                    error="Screener path not configured",
                )

            tickers = load_screener_export(self.config.screener_path)
            return TickerSourceResult(
                source=TickerSource.SCREENER,
                tickers=tickers,
            )

        except Exception as e:
            return TickerSourceResult(
                source=TickerSource.SCREENER,
                tickers=[],
                error=str(e),
            )

    async def _fetch_manual(self) -> TickerSourceResult:
        """Return manually configured tickers."""
        return TickerSourceResult(
            source=TickerSource.MANUAL,
            tickers=list(self.config.manual_tickers),
        )

    async def fetch_from_source(self, source: TickerSource) -> TickerSourceResult:
        """
        Fetch tickers from a specific source.

        Args:
            source: The source to fetch from

        Returns:
            TickerSourceResult with fetched tickers
        """
        fetch_methods = {
            TickerSource.NASDAQ: self._fetch_nasdaq,
            TickerSource.ALPHA_VANTAGE: self._fetch_alpha_vantage,
            TickerSource.WATCHLIST: self._fetch_watchlist,
            TickerSource.SCREENER: self._fetch_screener,
            TickerSource.MANUAL: self._fetch_manual,
        }

        method = fetch_methods.get(source)
        if not method:
            return TickerSourceResult(
                source=source,
                tickers=[],
                error=f"Unknown source: {source}",
            )

        return await method()

    async def fetch_all(self) -> list:
        """
        Fetch from all enabled sources and return deduplicated tickers.

        Returns:
            List of unique TickerInput objects, sorted by priority
        """
        if not self._enabled_sources:
            return []

        # Fetch from all enabled sources concurrently
        tasks = [
            self.fetch_from_source(source)
            for source in self._enabled_sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all tickers with their source priority
        ticker_map: dict[str, tuple] = {}  # {symbol: (TickerInput, priority)}

        for result in results:
            if isinstance(result, Exception):
                continue

            if not result.is_success:
                continue

            source_config = self.config.sources.get(result.source, SourceConfig())
            priority = source_config.priority

            for ticker in result.tickers:
                symbol = ticker.ticker.upper()

                # Keep ticker with highest priority (richest data)
                if symbol not in ticker_map or priority > ticker_map[symbol][1]:
                    ticker_map[symbol] = (ticker, priority)

        # Extract tickers and sort by priority (highest first)
        sorted_tickers = sorted(
            ticker_map.values(),
            key=lambda x: (-x[1], x[0].ticker),
        )

        # Return just the TickerInput objects, limited to max_tickers
        return [t[0] for t in sorted_tickers[:self.config.max_tickers]]

    async def fetch_all_with_results(self) -> tuple[list, list[TickerSourceResult]]:
        """
        Fetch from all enabled sources and return both tickers and results.

        Returns:
            Tuple of (deduplicated tickers, list of source results)
        """
        if not self._enabled_sources:
            return [], []

        # Fetch from all enabled sources concurrently
        tasks = [
            self.fetch_from_source(source)
            for source in self._enabled_sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and cast to TickerSourceResult
        valid_results = [
            r for r in results
            if isinstance(r, TickerSourceResult)
        ]

        # Collect all tickers with their source priority
        ticker_map: dict[str, tuple] = {}  # {symbol: (TickerInput, priority)}

        for result in valid_results:
            if not result.is_success:
                continue

            source_config = self.config.sources.get(result.source, SourceConfig())
            priority = source_config.priority

            for ticker in result.tickers:
                symbol = ticker.ticker.upper()

                if symbol not in ticker_map or priority > ticker_map[symbol][1]:
                    ticker_map[symbol] = (ticker, priority)

        # Extract tickers and sort by priority
        sorted_tickers = sorted(
            ticker_map.values(),
            key=lambda x: (-x[1], x[0].ticker),
        )

        tickers = [t[0] for t in sorted_tickers[:self.config.max_tickers]]
        return tickers, valid_results


def load_watchlist(filepath: str) -> list:
    """
    Load tickers from a watchlist file.

    Supports formats:
    - TXT: One ticker per line
    - CSV: ticker,change_percent,price columns
    - JSON: Array of {ticker, change_percent, price} objects

    Args:
        filepath: Path to watchlist file

    Returns:
        List of TickerInput objects
    """
    from src.batch_processor import TickerInput

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Watchlist file not found: {filepath}")

    suffix = path.suffix.lower()

    if suffix == ".json":
        return _load_json_tickers(filepath)
    elif suffix == ".csv":
        return _load_csv_tickers(filepath)
    else:
        # Treat as plain text (one ticker per line)
        return _load_txt_tickers(filepath)


def load_screener_export(
    filepath: str,
    format: Optional[str] = None,
) -> list:
    """
    Load tickers from a screener export file.

    Supports exports from:
    - Finviz (CSV)
    - TradingView (CSV)
    - Generic CSV/JSON

    Args:
        filepath: Path to export file
        format: Optional format hint ('finviz', 'tradingview', 'csv', 'json')

    Returns:
        List of TickerInput objects
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Screener export not found: {filepath}")

    # Auto-detect format from extension if not specified
    if format is None:
        suffix = path.suffix.lower()
        if suffix == ".json":
            format = "json"
        else:
            format = "csv"

    if format == "json":
        return _load_json_tickers(filepath)
    else:
        return _load_csv_tickers(filepath)


def _load_txt_tickers(filepath: str) -> list:
    """Load tickers from a plain text file (one per line)."""
    from src.batch_processor import TickerInput

    tickers = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Handle potential CSV format in txt file
            parts = line.split(",")
            ticker = parts[0].strip().upper()
            if ticker:
                change = _safe_float(parts[1]) if len(parts) > 1 else None
                price = _safe_float(parts[2]) if len(parts) > 2 else None
                tickers.append(TickerInput(
                    ticker=ticker,
                    change_percent=change,
                    current_price=price,
                ))
    return tickers


def _load_csv_tickers(filepath: str) -> list:
    """Load tickers from a CSV file."""
    from src.batch_processor import TickerInput

    tickers = []

    with open(filepath, "r", encoding="utf-8", newline="") as f:
        # Try to detect dialect
        sample = f.read(1024)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel

        has_header = csv.Sniffer().has_header(sample)

        reader = csv.reader(f, dialect)

        # Read header if present
        header = None
        if has_header:
            header = [col.strip().lower() for col in next(reader)]

        # Find column indices
        ticker_idx = _find_column_index(header, ["ticker", "symbol", "stock"])
        change_idx = _find_column_index(header, ["change_percent", "change", "pctchange", "% change", "change %"])
        price_idx = _find_column_index(header, ["price", "last", "lastsale", "close", "current_price"])

        for row in reader:
            if not row:
                continue

            # Extract ticker
            if ticker_idx is not None and ticker_idx < len(row):
                ticker = row[ticker_idx].strip().upper()
            elif len(row) > 0:
                ticker = row[0].strip().upper()
            else:
                continue

            if not ticker:
                continue

            # Extract change percent
            change = None
            if change_idx is not None and change_idx < len(row):
                change = _safe_float(row[change_idx])

            # Extract price
            price = None
            if price_idx is not None and price_idx < len(row):
                price = _safe_float(row[price_idx])

            tickers.append(TickerInput(
                ticker=ticker,
                change_percent=change,
                current_price=price,
            ))

    return tickers


def _load_json_tickers(filepath: str) -> list:
    """Load tickers from a JSON file."""
    from src.batch_processor import TickerInput

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle both array of objects and object with tickers key
    if isinstance(data, dict):
        data = data.get("tickers", data.get("stocks", []))

    if not isinstance(data, list):
        raise ValueError("JSON must contain an array of ticker objects")

    tickers = []
    for item in data:
        if isinstance(item, str):
            # Simple array of ticker strings
            tickers.append(TickerInput(ticker=item.upper()))
        elif isinstance(item, dict):
            ticker = item.get("ticker", item.get("symbol", "")).strip().upper()
            if not ticker:
                continue

            change = _safe_float(item.get("change_percent", item.get("change")))
            price = _safe_float(item.get("price", item.get("current_price", item.get("last"))))

            tickers.append(TickerInput(
                ticker=ticker,
                change_percent=change,
                current_price=price,
            ))

    return tickers


def _find_column_index(header: Optional[list[str]], names: list[str]) -> Optional[int]:
    """Find the index of a column by trying multiple possible names."""
    if header is None:
        return None

    for name in names:
        name_lower = name.lower()
        for i, col in enumerate(header):
            if col == name_lower or name_lower in col:
                return i
    return None


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove common formatting
        value = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not value or value == "-" or value.lower() == "none":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    return None
