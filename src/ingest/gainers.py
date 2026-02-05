"""
Top gainers ingestion from Alpha Vantage.

Fetches daily top NASDAQ gainers and filters to relevant universe.
Also provides utilities for loading tickers from watchlists and screener exports.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.clients.alpha_vantage import AlphaVantageClient, AlphaVantageError
from src.models.ticker import GainerRecord


@dataclass
class GainersResult:
    """Result of fetching top gainers."""

    gainers: list[GainerRecord]
    source: str  # "alpha_vantage" or "manual"
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return len(self.gainers) > 0 and self.error is None

    @property
    def count(self) -> int:
        return len(self.gainers)


def filter_nasdaq_gainers(
    gainers: list[GainerRecord],
    min_price: float = 1.0,
    min_volume: int = 100_000,
) -> list[GainerRecord]:
    """
    Filter gainers to tradeable NASDAQ stocks.

    Args:
        gainers: Raw list of gainer records
        min_price: Minimum stock price (filter penny stocks)
        min_volume: Minimum daily volume

    Returns:
        Filtered list of GainerRecord
    """
    filtered = []
    for g in gainers:
        # Price filter
        if float(g.price) < min_price:
            continue

        # Volume filter
        if g.volume < min_volume:
            continue

        # Basic ticker validation (no OTC markers)
        if len(g.ticker) > 5:
            continue

        filtered.append(g)

    return filtered


async def fetch_top_gainers(
    client: AlphaVantageClient,
    limit: int = 20,
    min_price: float = 1.0,
    min_volume: int = 100_000,
) -> GainersResult:
    """
    Fetch today's top gainers from Alpha Vantage.

    Args:
        client: Initialized AlphaVantageClient
        limit: Max number of gainers to return
        min_price: Minimum stock price filter
        min_volume: Minimum volume filter

    Returns:
        GainersResult with filtered gainers
    """
    try:
        raw_gainers = await client.get_top_gainers()

        if not raw_gainers:
            return GainersResult(
                gainers=[],
                source="alpha_vantage",
                error="No gainers returned from API",
            )

        # Apply filters
        filtered = filter_nasdaq_gainers(
            raw_gainers,
            min_price=min_price,
            min_volume=min_volume,
        )

        # Sort by change percentage descending and limit
        filtered.sort(key=lambda x: x.change_percentage, reverse=True)
        filtered = filtered[:limit]

        return GainersResult(
            gainers=filtered,
            source="alpha_vantage",
        )

    except AlphaVantageError as e:
        return GainersResult(
            gainers=[],
            source="alpha_vantage",
            error=f"API error: {str(e)}",
        )
    except Exception as e:
        return GainersResult(
            gainers=[],
            source="alpha_vantage",
            error=f"Unexpected error: {str(e)}",
        )


def create_manual_gainers(tickers_with_change: list[tuple[str, float, float, int]]) -> GainersResult:
    """
    Create GainersResult from manual input.

    Useful for testing or when API is unavailable.

    Args:
        tickers_with_change: List of (ticker, price, change_pct, volume) tuples

    Returns:
        GainersResult with manual entries
    """
    from decimal import Decimal

    gainers = []
    for ticker, price, change_pct, volume in tickers_with_change:
        change_amount = price * (change_pct / (100 + change_pct))
        record = GainerRecord(
            ticker=ticker,
            price=Decimal(str(price)),
            change_amount=Decimal(str(round(change_amount, 2))),
            change_percentage=Decimal(str(change_pct)),
            volume=volume,
        )
        gainers.append(record)

    return GainersResult(
        gainers=gainers,
        source="manual",
    )


@dataclass
class WatchlistEntry:
    """Entry from a watchlist or screener file."""
    ticker: str
    change_percent: Optional[float] = None
    price: Optional[float] = None
    volume: Optional[int] = None


def load_watchlist(filepath: str) -> list[WatchlistEntry]:
    """
    Load tickers from a watchlist file.

    Supports formats:
    - TXT: One ticker per line (optionally with comma-separated data)
    - CSV: ticker,change_percent,price,volume columns (headers optional)
    - JSON: Array of ticker objects or strings

    Args:
        filepath: Path to watchlist file

    Returns:
        List of WatchlistEntry objects

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Watchlist file not found: {filepath}")

    suffix = path.suffix.lower()

    if suffix == ".json":
        return _load_json_watchlist(filepath)
    elif suffix == ".csv":
        return _load_csv_watchlist(filepath)
    else:
        # Treat as plain text (one ticker per line, optional CSV format)
        return _load_txt_watchlist(filepath)


def load_screener_export(
    filepath: str,
    format_hint: Optional[str] = None,
) -> list[WatchlistEntry]:
    """
    Load tickers from a screener export file.

    Supports exports from:
    - Finviz (CSV) - auto-detects by column names
    - TradingView (CSV) - auto-detects by column names
    - Generic CSV with ticker/symbol column
    - JSON arrays

    Args:
        filepath: Path to export file
        format_hint: Optional format hint ('finviz', 'tradingview', 'csv', 'json')

    Returns:
        List of WatchlistEntry objects
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Screener export not found: {filepath}")

    # Auto-detect format from extension if not specified
    if format_hint is None:
        suffix = path.suffix.lower()
        if suffix == ".json":
            format_hint = "json"
        else:
            format_hint = "csv"

    if format_hint == "json":
        return _load_json_watchlist(filepath)
    else:
        return _load_csv_watchlist(filepath)


def _load_txt_watchlist(filepath: str) -> list[WatchlistEntry]:
    """Load tickers from a plain text file (one per line)."""
    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Handle potential CSV format in txt file
            parts = line.split(",")
            ticker = parts[0].strip().upper()
            if not ticker:
                continue

            change = _safe_parse_float(parts[1]) if len(parts) > 1 else None
            price = _safe_parse_float(parts[2]) if len(parts) > 2 else None
            volume = _safe_parse_int(parts[3]) if len(parts) > 3 else None

            entries.append(WatchlistEntry(
                ticker=ticker,
                change_percent=change,
                price=price,
                volume=volume,
            ))
    return entries


def _load_csv_watchlist(filepath: str) -> list[WatchlistEntry]:
    """Load tickers from a CSV file with auto-detection of columns."""
    entries = []

    with open(filepath, "r", encoding="utf-8", newline="") as f:
        # Read sample to detect format
        sample = f.read(2048)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel

        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = True  # Assume header if uncertain

        reader = csv.reader(f, dialect)

        # Read header if present
        header = None
        if has_header:
            header_row = next(reader, None)
            if header_row:
                header = [col.strip().lower() for col in header_row]

        # Find column indices based on common column names
        ticker_idx = _find_column_idx(header, [
            "ticker", "symbol", "stock", "name"
        ])
        change_idx = _find_column_idx(header, [
            "change_percent", "change", "pctchange", "% change", "change %",
            "percent change", "changepct"
        ])
        price_idx = _find_column_idx(header, [
            "price", "last", "lastsale", "close", "current_price", "last price"
        ])
        volume_idx = _find_column_idx(header, [
            "volume", "vol", "avg volume", "avg_volume"
        ])

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

            # Extract other fields
            change = None
            if change_idx is not None and change_idx < len(row):
                change = _safe_parse_float(row[change_idx])

            price = None
            if price_idx is not None and price_idx < len(row):
                price = _safe_parse_float(row[price_idx])

            volume = None
            if volume_idx is not None and volume_idx < len(row):
                volume = _safe_parse_int(row[volume_idx])

            entries.append(WatchlistEntry(
                ticker=ticker,
                change_percent=change,
                price=price,
                volume=volume,
            ))

    return entries


def _load_json_watchlist(filepath: str) -> list[WatchlistEntry]:
    """Load tickers from a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle various JSON structures
    if isinstance(data, dict):
        # Object with tickers array
        data = data.get("tickers", data.get("stocks", data.get("symbols", [])))

    if not isinstance(data, list):
        raise ValueError("JSON must contain an array of ticker objects or strings")

    entries = []
    for item in data:
        if isinstance(item, str):
            # Simple array of ticker strings
            ticker = item.strip().upper()
            if ticker:
                entries.append(WatchlistEntry(ticker=ticker))
        elif isinstance(item, dict):
            ticker = item.get("ticker", item.get("symbol", ""))
            if isinstance(ticker, str):
                ticker = ticker.strip().upper()
            if not ticker:
                continue

            change = _safe_parse_float(item.get("change_percent", item.get("change")))
            price = _safe_parse_float(item.get("price", item.get("last", item.get("close"))))
            volume = _safe_parse_int(item.get("volume"))

            entries.append(WatchlistEntry(
                ticker=ticker,
                change_percent=change,
                price=price,
                volume=volume,
            ))

    return entries


def _find_column_idx(header: Optional[list[str]], candidates: list[str]) -> Optional[int]:
    """Find column index by trying multiple possible column names."""
    if header is None:
        return None

    for name in candidates:
        name_lower = name.lower()
        for i, col in enumerate(header):
            if col == name_lower or name_lower in col:
                return i
    return None


def _safe_parse_float(value) -> Optional[float]:
    """Safely parse a value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not value or value == "-" or value.lower() in ("none", "n/a", ""):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    return None


def _safe_parse_int(value) -> Optional[int]:
    """Safely parse a value to int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value or value == "-" or value.lower() in ("none", "n/a", ""):
            return None
        # Handle suffixes like "1.2M" or "500K"
        value_upper = value.upper()
        try:
            if value_upper.endswith("M"):
                return int(float(value_upper[:-1]) * 1_000_000)
            elif value_upper.endswith("K"):
                return int(float(value_upper[:-1]) * 1_000)
            elif value_upper.endswith("B"):
                return int(float(value_upper[:-1]) * 1_000_000_000)
            else:
                return int(float(value))
        except (ValueError, TypeError):
            return None
    return None
