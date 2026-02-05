"""
DuckDB cache for price and fundamentals data.

Reduces API calls by caching fetched data with TTL.
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import duckdb

from src.models.ticker import Fundamentals, OHLCV, OHLCVSeries, Exchange


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def decimal_decoder(dct: dict) -> dict:
    """JSON decoder hook for Decimal fields."""
    # Known decimal fields
    decimal_fields = {
        "price", "open", "high", "low", "close",
        "change_amount", "change_percentage",
        "beta", "pe_ratio", "eps", "week_52_high", "week_52_low",
    }
    for key, value in dct.items():
        if key in decimal_fields and value is not None:
            try:
                dct[key] = Decimal(value)
            except Exception:
                pass
    return dct


class DataCache:
    """
    DuckDB-based cache for market data.

    Stores OHLCV series and fundamentals with configurable TTL.
    """

    def __init__(
        self,
        db_path: Path,
        daily_ttl_hours: int = 24,
        intraday_ttl_hours: int = 1,
        fundamentals_ttl_hours: int = 24,
    ):
        self.db_path = db_path
        self.daily_ttl = timedelta(hours=daily_ttl_hours)
        self.intraday_ttl = timedelta(hours=intraday_ttl_hours)
        self.fundamentals_ttl = timedelta(hours=fundamentals_ttl_hours)

        # Ensure directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with duckdb.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv_cache (
                    ticker VARCHAR,
                    interval VARCHAR,
                    data JSON,
                    cached_at TIMESTAMP,
                    PRIMARY KEY (ticker, interval)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fundamentals_cache (
                    ticker VARCHAR PRIMARY KEY,
                    data JSON,
                    cached_at TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_cache (
                    ticker VARCHAR PRIMARY KEY,
                    data JSON,
                    cached_at TIMESTAMP
                )
            """)

    # -------------------------------------------------------------------------
    # OHLCV Cache
    # -------------------------------------------------------------------------

    def get_ohlcv(self, ticker: str, interval: str) -> Optional[OHLCVSeries]:
        """
        Get cached OHLCV data if not expired.

        Args:
            ticker: Stock symbol
            interval: "daily" or intraday interval

        Returns:
            OHLCVSeries if cached and not expired, else None
        """
        ttl = self.daily_ttl if interval == "daily" else self.intraday_ttl
        cutoff = datetime.now() - ttl

        with duckdb.connect(str(self.db_path)) as conn:
            result = conn.execute("""
                SELECT data, cached_at
                FROM ohlcv_cache
                WHERE ticker = ? AND interval = ? AND cached_at > ?
            """, [ticker, interval, cutoff]).fetchone()

        if result is None:
            return None

        data_json, cached_at = result
        return self._deserialize_ohlcv(ticker, interval, data_json)

    def set_ohlcv(self, series: OHLCVSeries) -> None:
        """
        Cache OHLCV data.

        Args:
            series: OHLCVSeries to cache
        """
        data_json = self._serialize_ohlcv(series)

        with duckdb.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ohlcv_cache (ticker, interval, data, cached_at)
                VALUES (?, ?, ?, ?)
            """, [series.ticker, series.interval, data_json, datetime.now()])

    def _serialize_ohlcv(self, series: OHLCVSeries) -> str:
        """Serialize OHLCVSeries to JSON."""
        bars_data = [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": bar.volume,
            }
            for bar in series.bars
        ]
        return json.dumps(bars_data)

    def _deserialize_ohlcv(
        self, ticker: str, interval: str, data_json: str
    ) -> OHLCVSeries:
        """Deserialize JSON to OHLCVSeries."""
        bars_data = json.loads(data_json)
        bars = [
            OHLCV(
                timestamp=datetime.fromisoformat(b["timestamp"]),
                open=Decimal(b["open"]),
                high=Decimal(b["high"]),
                low=Decimal(b["low"]),
                close=Decimal(b["close"]),
                volume=b["volume"],
            )
            for b in bars_data
        ]
        return OHLCVSeries(ticker=ticker, interval=interval, bars=bars)

    # -------------------------------------------------------------------------
    # Fundamentals Cache
    # -------------------------------------------------------------------------

    def get_fundamentals(self, ticker: str) -> Optional[Fundamentals]:
        """
        Get cached fundamentals if not expired.

        Args:
            ticker: Stock symbol

        Returns:
            Fundamentals if cached and not expired, else None
        """
        cutoff = datetime.now() - self.fundamentals_ttl

        with duckdb.connect(str(self.db_path)) as conn:
            result = conn.execute("""
                SELECT data, cached_at
                FROM fundamentals_cache
                WHERE ticker = ? AND cached_at > ?
            """, [ticker, cutoff]).fetchone()

        if result is None:
            return None

        data_json, cached_at = result
        return self._deserialize_fundamentals(data_json)

    def set_fundamentals(self, data: Fundamentals) -> None:
        """
        Cache fundamentals data.

        Args:
            data: Fundamentals to cache
        """
        data_json = self._serialize_fundamentals(data)

        with duckdb.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO fundamentals_cache (ticker, data, cached_at)
                VALUES (?, ?, ?)
            """, [data.ticker, data_json, datetime.now()])

    def _serialize_fundamentals(self, data: Fundamentals) -> str:
        """Serialize Fundamentals to JSON."""
        return json.dumps(
            {
                "ticker": data.ticker,
                "name": data.name,
                "exchange": data.exchange.value if data.exchange else None,
                "sector": data.sector,
                "industry": data.industry,
                "market_cap": data.market_cap,
                "beta": str(data.beta) if data.beta else None,
                "pe_ratio": str(data.pe_ratio) if data.pe_ratio else None,
                "eps": str(data.eps) if data.eps else None,
                "shares_outstanding": data.shares_outstanding,
                "float_shares": data.float_shares,
                "avg_volume_10d": data.avg_volume_10d,
                "week_52_high": str(data.week_52_high) if data.week_52_high else None,
                "week_52_low": str(data.week_52_low) if data.week_52_low else None,
            }
        )

    def _deserialize_fundamentals(self, data_json: str) -> Fundamentals:
        """Deserialize JSON to Fundamentals."""
        d = json.loads(data_json)

        exchange = None
        if d.get("exchange"):
            try:
                exchange = Exchange(d["exchange"])
            except ValueError:
                exchange = Exchange.OTHER

        return Fundamentals(
            ticker=d["ticker"],
            name=d.get("name"),
            exchange=exchange,
            sector=d.get("sector"),
            industry=d.get("industry"),
            market_cap=d.get("market_cap"),
            beta=Decimal(d["beta"]) if d.get("beta") else None,
            pe_ratio=Decimal(d["pe_ratio"]) if d.get("pe_ratio") else None,
            eps=Decimal(d["eps"]) if d.get("eps") else None,
            shares_outstanding=d.get("shares_outstanding"),
            float_shares=d.get("float_shares"),
            avg_volume_10d=d.get("avg_volume_10d"),
            week_52_high=Decimal(d["week_52_high"]) if d.get("week_52_high") else None,
            week_52_low=Decimal(d["week_52_low"]) if d.get("week_52_low") else None,
        )

    # -------------------------------------------------------------------------
    # Cache Management
    # -------------------------------------------------------------------------

    def clear_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        now = datetime.now()
        daily_cutoff = now - self.daily_ttl
        intraday_cutoff = now - self.intraday_ttl
        fundamentals_cutoff = now - self.fundamentals_ttl

        total_removed = 0

        with duckdb.connect(str(self.db_path)) as conn:
            # Clear expired OHLCV
            result = conn.execute("""
                DELETE FROM ohlcv_cache
                WHERE (interval = 'daily' AND cached_at < ?)
                   OR (interval != 'daily' AND cached_at < ?)
            """, [daily_cutoff, intraday_cutoff])
            total_removed += result.fetchone()[0] if result else 0

            # Clear expired fundamentals
            result = conn.execute("""
                DELETE FROM fundamentals_cache
                WHERE cached_at < ?
            """, [fundamentals_cutoff])
            total_removed += result.fetchone()[0] if result else 0

        return total_removed

    def clear_all(self) -> None:
        """Clear entire cache."""
        with duckdb.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM ohlcv_cache")
            conn.execute("DELETE FROM fundamentals_cache")
            conn.execute("DELETE FROM news_cache")

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics."""
        with duckdb.connect(str(self.db_path)) as conn:
            ohlcv_count = conn.execute(
                "SELECT COUNT(*) FROM ohlcv_cache"
            ).fetchone()[0]
            fundamentals_count = conn.execute(
                "SELECT COUNT(*) FROM fundamentals_cache"
            ).fetchone()[0]
            news_count = conn.execute(
                "SELECT COUNT(*) FROM news_cache"
            ).fetchone()[0]

        return {
            "ohlcv_entries": ohlcv_count,
            "fundamentals_entries": fundamentals_count,
            "news_entries": news_count,
        }
