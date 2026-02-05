"""
yfinance fallback client for when Alpha Vantage is unavailable.

Provides same interface as AlphaVantageClient for seamless fallback.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import pandas as pd
import yfinance as yf

from src.models.ticker import (
    Exchange,
    Fundamentals,
    OHLCV,
    OHLCVSeries,
)


class YFinanceClient:
    """
    Synchronous yfinance client as fallback data source.

    Note: yfinance is not async, so this wraps sync calls.
    """

    def get_daily_ohlcv(
        self,
        ticker: str,
        days: int = 60,
    ) -> OHLCVSeries:
        """
        Fetch daily OHLCV data.

        Args:
            ticker: Stock symbol
            days: Number of days to fetch

        Returns:
            OHLCVSeries with bars in reverse chronological order.
        """
        stock = yf.Ticker(ticker)
        end = datetime.now()
        start = end - timedelta(days=days + 10)  # buffer for non-trading days

        df = stock.history(start=start, end=end, interval="1d")
        bars = self._df_to_bars(df)

        return OHLCVSeries(ticker=ticker, interval="daily", bars=bars)

    def get_intraday_ohlcv(
        self,
        ticker: str,
        interval: str = "15m",
        days: int = 7,
    ) -> OHLCVSeries:
        """
        Fetch intraday OHLCV data.

        Note: yfinance intraday is limited to ~7 days for 15m bars.

        Args:
            ticker: Stock symbol
            interval: "1m", "5m", "15m", "30m", "60m"
            days: Number of days (max ~7 for minute data)

        Returns:
            OHLCVSeries with bars in reverse chronological order.
        """
        stock = yf.Ticker(ticker)

        # yfinance uses different interval notation
        yf_interval = interval.replace("min", "m")

        # Max period for intraday depends on interval
        period = f"{min(days, 7)}d"

        df = stock.history(period=period, interval=yf_interval)
        bars = self._df_to_bars(df)

        return OHLCVSeries(ticker=ticker, interval=interval, bars=bars)

    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """
        Fetch company fundamentals.

        Args:
            ticker: Stock symbol

        Returns:
            Fundamentals model
        """
        stock = yf.Ticker(ticker)
        info = stock.info

        # Determine exchange
        exchange_str = info.get("exchange", "").upper()
        if "NASDAQ" in exchange_str or "NMS" in exchange_str:
            exchange = Exchange.NASDAQ
        elif "NYSE" in exchange_str:
            exchange = Exchange.NYSE
        else:
            exchange = Exchange.OTHER

        return Fundamentals(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName"),
            exchange=exchange,
            sector=info.get("sector"),
            industry=info.get("industry"),
            market_cap=info.get("marketCap"),
            beta=self._to_decimal(info.get("beta")),
            pe_ratio=self._to_decimal(info.get("trailingPE")),
            eps=self._to_decimal(info.get("trailingEps")),
            shares_outstanding=info.get("sharesOutstanding"),
            float_shares=info.get("floatShares"),
            avg_volume_10d=info.get("averageVolume10days"),
            week_52_high=self._to_decimal(info.get("fiftyTwoWeekHigh")),
            week_52_low=self._to_decimal(info.get("fiftyTwoWeekLow")),
        )

    def _df_to_bars(self, df: pd.DataFrame) -> list[OHLCV]:
        """Convert pandas DataFrame to list of OHLCV bars."""
        bars = []
        for idx, row in df.iterrows():
            try:
                timestamp = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                bar = OHLCV(
                    timestamp=timestamp,
                    open=Decimal(str(row["Open"])),
                    high=Decimal(str(row["High"])),
                    low=Decimal(str(row["Low"])),
                    close=Decimal(str(row["Close"])),
                    volume=int(row["Volume"]),
                )
                bars.append(bar)
            except (KeyError, ValueError, TypeError):
                continue

        # Sort reverse chronological
        bars.sort(key=lambda x: x.timestamp, reverse=True)
        return bars

    @staticmethod
    def _to_decimal(value) -> Optional[Decimal]:
        """Safely convert to Decimal."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None
