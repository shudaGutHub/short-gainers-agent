"""
Batch Analysis Processor
Fetches data and generates dashboards for multiple tickers.
Can process NASDAQ top gainers or any list of tickers.
Supports multiple ticker sources with deduplication.

Now includes full analysis pipeline:
- News sentiment analysis (Claude AI or heuristic fallback)
- Catalyst classification
- Advanced technical indicators (MACD, OBV, ROC, patterns)
- Complete 6-component technical scoring
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
import json

import pandas as pd

from .dashboard_generator import (
    DashboardData,
    FinancialData,
    generate_dashboard_html,
    generate_index_html,
)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""
    output_dir: str = "./reports"
    max_tickers: int = 20
    min_change_percent: float = 10.0
    include_financials: bool = True
    generate_index: bool = True
    verbose: bool = True
    # Multi-source configuration
    sources: Optional[list[str]] = None  # e.g., ["nasdaq", "alpha_vantage", "watchlist"]
    nasdaq_category: str = "gainers"  # gainers, losers, most_active, all
    watchlist_path: Optional[str] = None
    screener_path: Optional[str] = None
    min_price: float = 1.0
    min_volume: int = 100_000
    # Advanced analysis options
    include_news_analysis: bool = True  # Fetch and analyze news sentiment
    use_claude_sentiment: bool = False  # Use Claude AI for sentiment (requires ANTHROPIC_API_KEY)
    include_advanced_technicals: bool = True  # MACD, OBV, ROC, patterns


@dataclass
class TickerInput:
    """Input data for a single ticker."""
    ticker: str
    change_percent: Optional[float] = None
    current_price: Optional[float] = None
    is_warrant: bool = False
    underlying_ticker: Optional[str] = None


# Known tickers ending in W that are NOT warrants
_NOT_WARRANTS = {"BMW", "SCHW", "SNOW", "FLOW", "GLOW", "GROW", "KNOW", "SHOW", "STEW", "VIEW"}


def is_warrant(ticker: str) -> bool:
    """Detect if a ticker is a warrant by suffix pattern."""
    if len(ticker) < 4:
        return False
    if ticker.upper() in _NOT_WARRANTS:
        return False
    return ticker.upper().endswith("W")


def get_underlying(warrant_ticker: str) -> str:
    """Strip trailing W to get underlying stock symbol."""
    return warrant_ticker.upper().rstrip("W")


def expand_warrants(ticker_inputs: list[TickerInput]) -> list[TickerInput]:
    """
    Process ticker list: flag warrants and inject underlying stocks.

    For each warrant detected:
    1. Mark it with is_warrant=True and set underlying_ticker
    2. If the underlying is not already in the list, add it as a new TickerInput
    """
    existing_tickers = {t.ticker.upper() for t in ticker_inputs}
    new_inputs: list[TickerInput] = []

    for ti in ticker_inputs:
        if is_warrant(ti.ticker):
            ti.is_warrant = True
            ti.underlying_ticker = get_underlying(ti.ticker)

            # Add underlying if not already present
            if ti.underlying_ticker not in existing_tickers:
                existing_tickers.add(ti.underlying_ticker)
                new_inputs.append(TickerInput(
                    ticker=ti.underlying_ticker,
                ))

    ticker_inputs.extend(new_inputs)
    return ticker_inputs


class BatchAnalyzer:
    """
    Batch analyzer for generating dashboards from ticker lists.

    Usage:
        analyzer = BatchAnalyzer(alpha_vantage_key="YOUR_KEY")

        # From top gainers
        results = await analyzer.analyze_top_gainers()

        # From manual list
        tickers = [TickerInput("TCGL", 941.0), TickerInput("AAPL", 5.0)]
        results = await analyzer.analyze_tickers(tickers)
    """
    
    def __init__(
        self,
        alpha_vantage_key: str,
        config: Optional[BatchConfig] = None
    ):
        self.av_key = alpha_vantage_key
        self.config = config or BatchConfig()
        self.base_url = "https://www.alphavantage.co/query"
        
    async def _fetch_json(self, params: dict) -> dict:
        """Fetch JSON from Alpha Vantage API."""
        import aiohttp
        
        params["apikey"] = self.av_key
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {}
    
    async def fetch_top_gainers(self) -> list:
        """Fetch top gainers from Alpha Vantage."""
        data = await self._fetch_json({"function": "TOP_GAINERS_LOSERS"})
        
        gainers = []
        for item in data.get("top_gainers", [])[:self.config.max_tickers]:
            ticker = item.get("ticker", "")
            change_str = item.get("change_percentage", "0%").replace("%", "")
            price_str = item.get("price", "0")
            
            try:
                change = float(change_str)
                price = float(price_str)
                
                if change >= self.config.min_change_percent:
                    gainers.append(TickerInput(
                        ticker=ticker,
                        change_percent=change,
                        current_price=price
                    ))
            except ValueError:
                continue
        
        return gainers
    
    async def fetch_quote(self, ticker: str) -> dict:
        """Fetch current quote for a ticker."""
        data = await self._fetch_json({
            "function": "GLOBAL_QUOTE",
            "symbol": ticker
        })
        return data.get("Global Quote", {})
    
    async def fetch_company_overview(self, ticker: str) -> dict:
        """Fetch company overview/fundamentals."""
        return await self._fetch_json({
            "function": "COMPANY_OVERVIEW",
            "symbol": ticker
        })
    
    async def fetch_daily_prices(self, ticker: str, outputsize: str = "compact") -> list:
        """Fetch daily OHLCV data."""
        data = await self._fetch_json({
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "outputsize": outputsize
        })
        
        time_series = data.get("Time Series (Daily)", {})
        prices = []
        for date, values in sorted(time_series.items(), reverse=True):
            prices.append({
                "date": date,
                "open": float(values.get("1. open", 0)),
                "high": float(values.get("2. high", 0)),
                "low": float(values.get("3. low", 0)),
                "close": float(values.get("4. close", 0)),
                "volume": int(values.get("5. volume", 0))
            })
        return prices
    
    async def fetch_rsi(self, ticker: str, period: int = 14) -> list:
        """Fetch RSI indicator."""
        data = await self._fetch_json({
            "function": "RSI",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period),
            "series_type": "close"
        })
        
        rsi_data = data.get("Technical Analysis: RSI", {})
        return [
            {"date": date, "rsi": float(values.get("RSI", 0))}
            for date, values in sorted(rsi_data.items(), reverse=True)
        ]
    
    async def fetch_bbands(self, ticker: str, period: int = 20) -> list:
        """Fetch Bollinger Bands."""
        data = await self._fetch_json({
            "function": "BBANDS",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period),
            "series_type": "close"
        })
        
        bb_data = data.get("Technical Analysis: BBANDS", {})
        return [
            {
                "date": date,
                "upper": float(values.get("Real Upper Band", 0)),
                "middle": float(values.get("Real Middle Band", 0)),
                "lower": float(values.get("Real Lower Band", 0))
            }
            for date, values in sorted(bb_data.items(), reverse=True)
        ]
    
    async def fetch_atr(self, ticker: str, period: int = 14) -> list:
        """Fetch Average True Range."""
        data = await self._fetch_json({
            "function": "ATR",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period)
        })
        
        atr_data = data.get("Technical Analysis: ATR", {})
        return [
            {"date": date, "atr": float(values.get("ATR", 0))}
            for date, values in sorted(atr_data.items(), reverse=True)
        ]
    
    async def fetch_income_statement(self, ticker: str) -> dict:
        """Fetch income statement."""
        return await self._fetch_json({
            "function": "INCOME_STATEMENT",
            "symbol": ticker
        })
    
    async def fetch_cash_flow(self, ticker: str) -> dict:
        """Fetch cash flow statement."""
        return await self._fetch_json({
            "function": "CASH_FLOW",
            "symbol": ticker
        })
    
    async def fetch_balance_sheet(self, ticker: str) -> dict:
        """Fetch balance sheet."""
        return await self._fetch_json({
            "function": "BALANCE_SHEET",
            "symbol": ticker
        })
    
    async def fetch_news(self, ticker: str, limit: int = 10) -> list:
        """Fetch news/sentiment for ticker."""
        data = await self._fetch_json({
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "limit": str(limit)
        })
        return data.get("feed", [])

    async def fetch_macd(self, ticker: str, fast: int = 12, slow: int = 26, signal: int = 9) -> list:
        """Fetch MACD indicator."""
        data = await self._fetch_json({
            "function": "MACD",
            "symbol": ticker,
            "interval": "daily",
            "fastperiod": str(fast),
            "slowperiod": str(slow),
            "signalperiod": str(signal),
            "series_type": "close"
        })

        macd_data = data.get("Technical Analysis: MACD", {})
        return [
            {
                "date": date,
                "macd": float(values.get("MACD", 0)),
                "signal": float(values.get("MACD_Signal", 0)),
                "histogram": float(values.get("MACD_Hist", 0))
            }
            for date, values in sorted(macd_data.items(), reverse=True)
        ]
    
    def _parse_float(self, value, default: float = 0.0) -> float:
        """Safely parse a float value."""
        if value is None or value == "None" or value == "-":
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _parse_int(self, value, default: int = 0) -> int:
        """Safely parse an int value."""
        if value is None or value == "None" or value == "-":
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
    
    async def analyze_ticker(self, ticker_input: TickerInput) -> Optional[DashboardData]:
        """
        Analyze a single ticker and return dashboard data.

        Now includes full analysis pipeline:
        - News sentiment analysis with catalyst classification
        - Advanced technical indicators (MACD, volume analysis, momentum)
        - Pattern detection (lower highs, exhaustion candles)
        """
        ticker = ticker_input.ticker

        if self.config.verbose:
            print(f"  Analyzing {ticker}...")

        try:
            # Fetch all data concurrently - now including MACD and news
            quote_task = self.fetch_quote(ticker)
            overview_task = self.fetch_company_overview(ticker)
            prices_task = self.fetch_daily_prices(ticker)
            rsi_task = self.fetch_rsi(ticker)
            bbands_task = self.fetch_bbands(ticker)
            atr_task = self.fetch_atr(ticker)
            macd_task = self.fetch_macd(ticker)

            tasks = [quote_task, overview_task, prices_task, rsi_task, bbands_task, atr_task, macd_task]

            # Add news fetch if enabled
            if self.config.include_news_analysis:
                news_task = self.fetch_news(ticker)
                tasks.append(news_task)

            if self.config.include_financials:
                income_task = self.fetch_income_statement(ticker)
                cashflow_task = self.fetch_cash_flow(ticker)
                balance_task = self.fetch_balance_sheet(ticker)
                tasks.extend([income_task, cashflow_task, balance_task])

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Unpack results - now includes MACD
            quote = results[0] if not isinstance(results[0], Exception) else {}
            overview = results[1] if not isinstance(results[1], Exception) else {}
            prices = results[2] if not isinstance(results[2], Exception) else []
            rsi_data = results[3] if not isinstance(results[3], Exception) else []
            bbands_data = results[4] if not isinstance(results[4], Exception) else []
            atr_data = results[5] if not isinstance(results[5], Exception) else []
            macd_data = results[6] if not isinstance(results[6], Exception) else []

            # News data (if enabled)
            news_data = []
            result_offset = 7
            if self.config.include_news_analysis:
                news_data = results[7] if not isinstance(results[7], Exception) else []
                result_offset = 8

            # Financial data (if enabled)
            income_data = {}
            cashflow_data = {}
            balance_data = {}
            if self.config.include_financials:
                income_data = results[result_offset] if len(results) > result_offset and not isinstance(results[result_offset], Exception) else {}
                cashflow_data = results[result_offset + 1] if len(results) > result_offset + 1 and not isinstance(results[result_offset + 1], Exception) else {}
                balance_data = results[result_offset + 2] if len(results) > result_offset + 2 and not isinstance(results[result_offset + 2], Exception) else {}

            # Extract price data
            current_price = ticker_input.current_price or self._parse_float(quote.get("05. price"))
            prior_close = self._parse_float(quote.get("08. previous close"))
            change_percent = ticker_input.change_percent or self._parse_float(quote.get("10. change percent", "0").replace("%", ""))

            # Get intraday high/low from today's data or quote
            intraday_high = self._parse_float(quote.get("03. high"))
            intraday_low = self._parse_float(quote.get("04. low"))

            if prices and len(prices) > 0:
                today = prices[0]
                if intraday_high == 0:
                    intraday_high = today.get("high", current_price)
                if intraday_low == 0:
                    intraday_low = today.get("low", current_price)

            volume = self._parse_int(quote.get("06. volume"))

            # Calculate average volume from historical data
            avg_volume = 0
            if len(prices) > 1:
                recent_volumes = [p["volume"] for p in prices[1:21] if p.get("volume")]
                if recent_volumes:
                    avg_volume = sum(recent_volumes) // len(recent_volumes)

            # Volume ratio (current vs average)
            volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

            # Extract technical indicators
            rsi_14 = rsi_data[0]["rsi"] if rsi_data else None

            bb_upper = bbands_data[0]["upper"] if bbands_data else None
            bb_middle = bbands_data[0]["middle"] if bbands_data else None
            bb_lower = bbands_data[0]["lower"] if bbands_data else None

            # Calculate % above upper band
            bb_percent_above = None
            if bb_upper and bb_middle and current_price > bb_upper:
                band_width = bb_upper - bb_middle
                if band_width > 0:
                    bb_percent_above = ((current_price - bb_upper) / band_width) * 100

            atr_14 = atr_data[0]["atr"] if atr_data else None
            atr_prior = atr_data[1]["atr"] if len(atr_data) > 1 else None

            # Extract MACD indicators
            macd_line = macd_data[0]["macd"] if macd_data else None
            macd_signal = macd_data[0]["signal"] if macd_data else None
            macd_histogram = macd_data[0]["histogram"] if macd_data else None
            macd_histogram_declining = False
            if len(macd_data) >= 3:
                # Check if histogram is declining over last 3 bars
                h1, h2, h3 = macd_data[0]["histogram"], macd_data[1]["histogram"], macd_data[2]["histogram"]
                macd_histogram_declining = h1 < h2 < h3

            # Calculate momentum (ROC - Rate of Change)
            roc_1d = None
            roc_5d = None
            if len(prices) >= 2:
                roc_1d = ((prices[0]["close"] - prices[1]["close"]) / prices[1]["close"]) * 100 if prices[1]["close"] > 0 else None
            if len(prices) >= 6:
                roc_5d = ((prices[0]["close"] - prices[5]["close"]) / prices[5]["close"]) * 100 if prices[5]["close"] > 0 else None

            # Volume divergence detection (price up, volume down = bearish divergence)
            volume_confirming = True
            if len(prices) >= 5:
                price_change = prices[0]["close"] - prices[4]["close"]
                vol_change = prices[0]["volume"] - prices[4]["volume"]
                # Price up but volume down = divergence (not confirming)
                if price_change > 0 and vol_change < 0:
                    volume_confirming = False

            # Pattern detection - Lower High
            lower_high_forming = False
            if len(prices) >= 10:
                highs = [p["high"] for p in prices[:10]]
                # Find peaks
                peaks = []
                for i in range(1, len(highs) - 1):
                    if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                        peaks.append(highs[i])
                if len(peaks) >= 2 and peaks[0] < peaks[1]:
                    lower_high_forming = True

            # Pattern detection - Exhaustion Candle
            exhaustion_candle = False
            if len(prices) >= 20:
                today = prices[0]
                avg_range = sum((p["high"] - p["low"]) for p in prices[1:21]) / 20
                current_range = today["high"] - today["low"]

                if current_range > avg_range * 1.5:  # Large range
                    body_top = max(today["open"], today["close"])
                    upper_wick = today["high"] - body_top
                    upper_wick_ratio = upper_wick / current_range if current_range > 0 else 0
                    close_position = (today["close"] - today["low"]) / current_range if current_range > 0 else 0.5
                    avg_vol = sum(p["volume"] for p in prices[1:21]) / 20

                    # Long upper wick, close in lower half, high volume
                    if upper_wick_ratio > 0.4 and close_position < 0.5 and today["volume"] > avg_vol * 1.5:
                        exhaustion_candle = True

            # Extract overview data
            company_name = overview.get("Name", ticker)
            exchange = overview.get("Exchange", "Unknown")
            sector = overview.get("Sector", "Unknown")
            industry = overview.get("Industry", "Unknown")
            week_52_high = self._parse_float(overview.get("52WeekHigh"))
            week_52_low = self._parse_float(overview.get("52WeekLow"))
            shares_outstanding = self._parse_float(overview.get("SharesOutstanding"))

            # Update 52-week high if today's high exceeds it
            if intraday_high > week_52_high:
                week_52_high = intraday_high

            # =====================================================================
            # NEWS SENTIMENT ANALYSIS
            # =====================================================================
            catalyst_type = "UNKNOWN"
            sentiment_level = "MIXED"
            news_summary = "No news available"
            justifies_repricing = False
            sentiment_confidence = 0.5

            if news_data and self.config.include_news_analysis:
                headlines = [item.get("title", "") for item in news_data[:10]]
                text = " ".join(headlines).lower()

                # Heuristic catalyst detection (fallback when Claude not available)
                earnings_keywords = ["earnings", "eps", "revenue", "profit", "beat", "miss", "guidance", "quarterly"]
                fda_keywords = ["fda", "approval", "approved", "clinical", "trial", "phase", "drug"]
                ma_keywords = ["merger", "acquisition", "acquire", "buyout", "takeover", "deal", "bought"]
                upgrade_keywords = ["upgrade", "price target", "outperform", "buy rating", "overweight"]
                contract_keywords = ["contract", "award", "partnership", "agreement", "deal signed"]
                meme_keywords = ["reddit", "wsb", "squeeze", "moon", "apes", "yolo", "meme"]
                speculative_keywords = ["potential", "could", "may", "exploring", "considering", "rumor"]

                # Priority order for detection
                if any(kw in text for kw in fda_keywords):
                    catalyst_type = "FDA"
                    sentiment_level = "STRONGLY_POSITIVE"
                    justifies_repricing = True
                    news_summary = "FDA/clinical news detected"
                    sentiment_confidence = 0.7
                elif any(kw in text for kw in ma_keywords):
                    catalyst_type = "M&A"
                    sentiment_level = "STRONGLY_POSITIVE"
                    justifies_repricing = True
                    news_summary = "M&A activity detected"
                    sentiment_confidence = 0.7
                elif any(kw in text for kw in earnings_keywords):
                    catalyst_type = "EARNINGS"
                    sentiment_level = "POSITIVE"
                    justifies_repricing = True
                    news_summary = "Earnings-related news detected"
                    sentiment_confidence = 0.6
                elif any(kw in text for kw in upgrade_keywords):
                    catalyst_type = "UPGRADE"
                    sentiment_level = "POSITIVE"
                    justifies_repricing = False
                    news_summary = "Analyst upgrade detected"
                    sentiment_confidence = 0.5
                elif any(kw in text for kw in contract_keywords):
                    catalyst_type = "CONTRACT"
                    sentiment_level = "POSITIVE"
                    justifies_repricing = False
                    news_summary = "Contract/partnership news detected"
                    sentiment_confidence = 0.5
                elif any(kw in text for kw in meme_keywords):
                    catalyst_type = "MEME_SOCIAL"
                    sentiment_level = "MIXED"
                    justifies_repricing = False
                    news_summary = "Social/meme activity detected"
                    sentiment_confidence = 0.4
                elif any(kw in text for kw in speculative_keywords):
                    catalyst_type = "SPECULATIVE"
                    sentiment_level = "MIXED"
                    justifies_repricing = False
                    news_summary = "Speculative/vague PR detected"
                    sentiment_confidence = 0.4

                # Big move without clear catalyst is suspicious (good for shorting)
                if change_percent > 50 and not justifies_repricing:
                    sentiment_level = "MIXED"

            # =====================================================================
            # BUILD FINANCIAL DATA
            # =====================================================================
            financials = None
            if self.config.include_financials:
                annual_income = income_data.get("annualReports", [{}])[0] if income_data.get("annualReports") else {}
                quarterly_income = income_data.get("quarterlyReports", [{}])[0] if income_data.get("quarterlyReports") else {}
                annual_cf = cashflow_data.get("annualReports", [{}])[0] if cashflow_data.get("annualReports") else {}
                quarterly_cf = cashflow_data.get("quarterlyReports", [{}])[0] if cashflow_data.get("quarterlyReports") else {}
                annual_bs = balance_data.get("annualReports", [{}])[0] if balance_data.get("annualReports") else {}
                quarterly_bs = balance_data.get("quarterlyReports", [{}])[0] if balance_data.get("quarterlyReports") else {}

                # Use most recent data available
                revenue = self._parse_float(quarterly_income.get("totalRevenue")) or self._parse_float(annual_income.get("totalRevenue"))
                revenue_prior = self._parse_float(annual_income.get("totalRevenue"))
                gross_profit = self._parse_float(quarterly_income.get("grossProfit")) or self._parse_float(annual_income.get("grossProfit"))
                net_income = self._parse_float(quarterly_income.get("netIncome")) or self._parse_float(annual_income.get("netIncome"))
                ebitda = self._parse_float(quarterly_income.get("ebitda")) or self._parse_float(annual_income.get("ebitda"))

                op_cf = self._parse_float(quarterly_cf.get("operatingCashflow")) or self._parse_float(annual_cf.get("operatingCashflow"))
                inv_cf = self._parse_float(quarterly_cf.get("cashflowFromInvestment")) or self._parse_float(annual_cf.get("cashflowFromInvestment"))
                fin_cf = self._parse_float(quarterly_cf.get("cashflowFromFinancing")) or self._parse_float(annual_cf.get("cashflowFromFinancing"))
                capex = self._parse_float(quarterly_cf.get("capitalExpenditures")) or self._parse_float(annual_cf.get("capitalExpenditures"))

                cash = self._parse_float(quarterly_bs.get("cashAndCashEquivalentsAtCarryingValue")) or self._parse_float(annual_bs.get("cashAndCashEquivalentsAtCarryingValue"))
                total_debt = self._parse_float(quarterly_bs.get("shortLongTermDebtTotal")) or self._parse_float(annual_bs.get("shortLongTermDebtTotal"))
                total_assets = self._parse_float(quarterly_bs.get("totalAssets")) or self._parse_float(annual_bs.get("totalAssets"))
                total_liabilities = self._parse_float(quarterly_bs.get("totalLiabilities")) or self._parse_float(annual_bs.get("totalLiabilities"))
                equity = self._parse_float(quarterly_bs.get("totalShareholderEquity")) or self._parse_float(annual_bs.get("totalShareholderEquity"))
                shares = self._parse_float(quarterly_bs.get("commonStockSharesOutstanding")) or self._parse_float(annual_bs.get("commonStockSharesOutstanding")) or shares_outstanding

                # Calculate derived metrics
                gross_margin = (gross_profit / revenue * 100) if revenue and revenue > 0 else None
                revenue_growth = ((revenue - revenue_prior) / revenue_prior * 100) if revenue and revenue_prior and revenue_prior > 0 else None

                # Determine currency from data
                currency = annual_income.get("reportedCurrency", "USD")
                if currency == "None" or not currency:
                    currency = "USD"

                financials = FinancialData(
                    revenue_ttm=revenue,
                    revenue_prior_year=revenue_prior,
                    gross_margin=gross_margin,
                    operating_income=self._parse_float(annual_income.get("operatingIncome")),
                    net_income=net_income,
                    ebitda=ebitda,
                    operating_cash_flow=op_cf,
                    investing_cash_flow=inv_cf,
                    financing_cash_flow=fin_cf,
                    capex=capex,
                    cash=cash,
                    total_debt=total_debt,
                    total_assets=total_assets,
                    total_liabilities=total_liabilities,
                    shareholders_equity=equity,
                    shares_outstanding=shares,
                    revenue_growth=revenue_growth,
                    is_profitable=net_income > 0 if net_income else False,
                    currency=currency
                )

            # =====================================================================
            # RISK FLAGS
            # =====================================================================
            risk_flags = []

            # High squeeze risk (recent IPO, low float, extreme move)
            if change_percent > 100 or (shares_outstanding and shares_outstanding < 50_000_000):
                risk_flags.append("HIGH_SQUEEZE")

            # Extreme volatility
            if change_percent > 50 or (atr_14 and atr_prior and atr_14 / atr_prior > 5):
                risk_flags.append("EXTREME_VOLATILITY")

            # Microcap
            if shares_outstanding and current_price:
                mkt_cap = shares_outstanding * current_price
                if mkt_cap < 300_000_000:
                    risk_flags.append("MICROCAP")

            # Non-NASDAQ
            if exchange and "NASDAQ" not in exchange.upper():
                risk_flags.append("NON_NASDAQ")

            # Low liquidity
            if avg_volume and avg_volume < 100_000:
                risk_flags.append("LOW_LIQUIDITY")

            # Fundamental repricing detected
            if justifies_repricing:
                risk_flags.append("FUNDAMENTAL_REPRICING")

            # Warrant flag
            if ticker_input.is_warrant:
                risk_flags.append("WARRANT")

            # Calculate composite risk
            composite_risk = "LOW"
            if len(risk_flags) >= 3 or "HIGH_SQUEEZE" in risk_flags or "FUNDAMENTAL_REPRICING" in risk_flags:
                composite_risk = "HIGH"
            elif len(risk_flags) >= 1:
                composite_risk = "MEDIUM"

            # =====================================================================
            # ENHANCED TECHNICAL SCORING (6-component system)
            # =====================================================================

            # 1. RSI component (max 2.0)
            rsi_score = 0.0
            if rsi_14:
                if rsi_14 >= 90:
                    rsi_score = 2.0
                elif rsi_14 >= 80:
                    rsi_score = 1.7
                elif rsi_14 >= 70:
                    rsi_score = 1.3
                elif rsi_14 >= 60:
                    rsi_score = 0.8
                elif rsi_14 >= 50:
                    rsi_score = 0.3

            # 2. Bollinger component (max 2.0)
            bb_score = 0.0
            if bb_percent_above is not None:
                if bb_percent_above >= 80:
                    bb_score = 2.0
                elif bb_percent_above >= 50:
                    bb_score = 1.7
                elif bb_percent_above >= 20:
                    bb_score = 1.3
                elif bb_percent_above > 0:
                    bb_score = 1.0
            elif bb_upper and current_price:
                # Price not above upper band, but near it
                if bb_upper > 0:
                    pct_b = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_lower and (bb_upper - bb_lower) > 0 else 0.5
                    if pct_b >= 0.95:
                        bb_score = 1.7
                    elif pct_b >= 0.80:
                        bb_score = 1.3

            # 3. MACD component (max 1.5)
            macd_score = 0.0
            if macd_histogram_declining:
                macd_score += 0.8
            if macd_histogram is not None and macd_histogram > 0 and macd_histogram < 0.1:
                macd_score += 0.4  # Histogram positive but weakening
            if macd_line is not None and macd_signal is not None and macd_line < macd_signal:
                macd_score += 0.3  # Bearish crossover
            macd_score = min(macd_score, 1.5)

            # 4. Volume component (max 1.5)
            volume_score = 0.0
            if not volume_confirming:
                volume_score += 1.0  # Volume divergence = bearish
            if volume_ratio < 0.7:
                volume_score += 0.5  # Very low volume
            elif volume_ratio < 1.0:
                volume_score += 0.2  # Below average
            volume_score = min(volume_score, 1.5)

            # 5. Momentum component (max 1.5)
            momentum_score = 0.0
            if roc_1d is not None:
                if roc_1d >= 50:
                    momentum_score += 0.6
                elif roc_1d >= 30:
                    momentum_score += 0.4
                elif roc_1d >= 20:
                    momentum_score += 0.2
            if roc_5d is not None:
                if roc_5d >= 100:
                    momentum_score += 0.6
                elif roc_5d >= 50:
                    momentum_score += 0.4
                elif roc_5d >= 30:
                    momentum_score += 0.2
            # Decelerating momentum
            if roc_1d is not None and roc_5d is not None and roc_5d > 0:
                if roc_1d < roc_5d * 0.6 / 5:  # Scaled for 1-day vs 5-day
                    momentum_score += 0.3
            momentum_score = min(momentum_score, 1.5)

            # 6. Pattern component (max 1.5)
            pattern_score = 0.0
            if lower_high_forming:
                pattern_score += 0.8
            if exhaustion_candle:
                pattern_score += 0.7
            pattern_score = min(pattern_score, 1.5)

            # Calculate base technical score (0-10)
            tech_score = rsi_score + bb_score + macd_score + volume_score + momentum_score + pattern_score
            tech_score = min(tech_score, 10.0)

            # =====================================================================
            # SENTIMENT ADJUSTMENT (based on catalyst analysis)
            # =====================================================================
            # Score adjustments based on catalyst type (from catalyst.py logic)
            catalyst_adjustments = {
                "EARNINGS": -3.0,      # Strong earnings = don't short
                "FDA": -4.0,           # FDA approval = regime change
                "M&A": -5.0,           # M&A = price floor established
                "UPGRADE": -2.0,       # Analyst upgrade = institutional support
                "CONTRACT": -1.5,      # Contract win = some fundamental support
                "SPECULATIVE": 1.5,    # Vague PR = good short
                "MEME_SOCIAL": 2.0,    # Meme pump = excellent short (but risky)
                "UNKNOWN": 0.5,        # No clear catalyst = slight boost
            }

            sentiment_adjustments = {
                "STRONGLY_POSITIVE": -1.0,
                "POSITIVE": -0.5,
                "MIXED": 0.5,
                "NEGATIVE": 1.0,
                "STRONGLY_NEGATIVE": 1.5,
            }

            sentiment_adj = catalyst_adjustments.get(catalyst_type, 0.0)
            sentiment_adj += sentiment_adjustments.get(sentiment_level, 0.0)

            # Scale by confidence
            sentiment_adj *= sentiment_confidence

            # Cap adjustment to [-5, +3] range
            sentiment_adj = max(-5.0, min(3.0, sentiment_adj))

            # =====================================================================
            # RISK PENALTIES
            # =====================================================================
            risk_penalties = {}
            if "HIGH_SQUEEZE" in risk_flags:
                risk_penalties["HIGH_SQUEEZE"] = -2.0
            if "EXTREME_VOLATILITY" in risk_flags:
                risk_penalties["EXTREME_VOLATILITY"] = -1.5
            if "MICROCAP" in risk_flags:
                risk_penalties["MICROCAP"] = -1.0
            if "NON_NASDAQ" in risk_flags:
                risk_penalties["NON_NASDAQ"] = -0.5
            if "LOW_LIQUIDITY" in risk_flags:
                risk_penalties["LOW_LIQUIDITY"] = -0.5
            if "FUNDAMENTAL_REPRICING" in risk_flags:
                risk_penalties["FUNDAMENTAL_REPRICING"] = -2.0

            total_penalty = sum(risk_penalties.values())

            # Final score
            final_score = max(0, min(10, tech_score + sentiment_adj + total_penalty))

            # =====================================================================
            # TRADE EXPRESSION
            # =====================================================================
            if final_score < 4.0 or justifies_repricing:
                expression = "AVOID"
            elif "HIGH_SQUEEZE" in risk_flags and "MICROCAP" in risk_flags:
                expression = "AVOID"
            elif "HIGH_SQUEEZE" in risk_flags:
                expression = "BUY_PUTS"
            elif "EXTREME_VOLATILITY" in risk_flags:
                expression = "PUT_SPREADS"
            else:
                expression = "SHORT_SHARES"

            # Build key levels
            key_levels = {
                "Intraday High (Resistance)": intraday_high,
                "Current Price": current_price,
                "Prior Close (Gap Fill)": prior_close,
            }
            if week_52_low and week_52_low > 0:
                key_levels["52-Week Low"] = week_52_low

            # Build dashboard data with enhanced fields
            dashboard = DashboardData(
                ticker=ticker,
                company_name=company_name,
                exchange=exchange,
                sector=sector,
                industry=industry,
                current_price=current_price,
                prior_close=prior_close,
                change_percent=change_percent,
                intraday_high=intraday_high,
                intraday_low=intraday_low,
                volume=volume,
                avg_volume=avg_volume,
                week_52_high=week_52_high,
                week_52_low=week_52_low,
                rsi_14=rsi_14,
                bollinger_upper=bb_upper,
                bollinger_middle=bb_middle,
                bollinger_lower=bb_lower,
                bollinger_percent_above=bb_percent_above,
                atr_14=atr_14,
                atr_prior=atr_prior,
                risk_flags=risk_flags,
                composite_risk=composite_risk,
                catalyst_type=catalyst_type,
                has_fundamental_catalyst=justifies_repricing,
                technical_score=tech_score,
                sentiment_adjustment=sentiment_adj,
                risk_penalties=risk_penalties,
                final_score=final_score,
                expression=expression,
                financials=financials,
                key_levels=key_levels,
                # Enhanced fields
                macd_line=macd_line,
                macd_signal=macd_signal,
                macd_histogram=macd_histogram,
                macd_histogram_declining=macd_histogram_declining,
                volume_ratio=volume_ratio,
                volume_confirming=volume_confirming,
                roc_1d=roc_1d,
                roc_5d=roc_5d,
                lower_high_forming=lower_high_forming,
                exhaustion_candle=exhaustion_candle,
                news_summary=news_summary,
                sentiment_level=sentiment_level,
                sentiment_confidence=sentiment_confidence,
                # Warrant info
                is_warrant=ticker_input.is_warrant,
                underlying_ticker=ticker_input.underlying_ticker,
                # Score breakdown for transparency
                rsi_score=rsi_score,
                bb_score=bb_score,
                macd_score=macd_score,
                volume_score=volume_score,
                momentum_score=momentum_score,
                pattern_score=pattern_score,
            )

            return dashboard

        except Exception as e:
            if self.config.verbose:
                print(f"    Error analyzing {ticker}: {e}")
                import traceback
                traceback.print_exc()
            return None
    
    async def analyze_tickers(self, tickers: list) -> list:
        """Analyze a list of tickers and return dashboard data."""
        results = []
        
        for ticker_input in tickers[:self.config.max_tickers]:
            # Add delay to avoid rate limiting
            await asyncio.sleep(0.5)
            
            dashboard = await self.analyze_ticker(ticker_input)
            if dashboard:
                results.append(dashboard)
        
        return results
    
    async def analyze_top_gainers(self) -> list:
        """Analyze top gainers from market data."""
        if self.config.verbose:
            print("Fetching top gainers...")

        gainers = await self.fetch_top_gainers()

        if self.config.verbose:
            print(f"Found {len(gainers)} gainers above {self.config.min_change_percent}% threshold")

        # Detect warrants and inject underlying tickers
        count_before = len(gainers)
        gainers = expand_warrants(gainers)
        warrants_found = [t for t in gainers if t.is_warrant]
        underlyings_added = len(gainers) - count_before
        if self.config.verbose and warrants_found:
            print(f"Detected {len(warrants_found)} warrant(s): {', '.join(t.ticker for t in warrants_found)}")
            if underlyings_added:
                print(f"  Auto-added {underlyings_added} underlying ticker(s)")

        return await self.analyze_tickers(gainers)
    
    def generate_reports(self, dashboards: list, output_dir: Optional[str] = None) -> dict:
        """Generate HTML reports for all dashboards."""
        output_dir = output_dir or self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        analysis_date = datetime.now().strftime("%Y-%m-%d")
        last_updated = datetime.now().strftime("%I:%M %p ET")
        generated_files = []
        
        # Generate individual dashboards
        for dashboard in dashboards:
            html_content = generate_dashboard_html(dashboard)
            filename = f"{dashboard.ticker}.html"
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            
            generated_files.append(filepath)
            
            if self.config.verbose:
                print(f"  Generated: {filename}")
        
        # Generate index page
        if self.config.generate_index:
            index_html = generate_index_html(dashboards, analysis_date, last_updated)
            index_path = os.path.join(output_dir, "index.html")
            
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(index_html)
            
            generated_files.insert(0, index_path)
            
            if self.config.verbose:
                print(f"  Generated: index.html")

        return {
            "output_dir": output_dir,
            "files": generated_files,
            "count": len(dashboards),
            "analysis_date": analysis_date,
            "dashboards": dashboards,  # Include analysis data for notifications
        }


async def run_batch_analysis(
    tickers: Optional[list] = None,
    use_top_gainers: bool = False,
    sources: Optional[list[str]] = None,
    nasdaq_category: str = "gainers",
    watchlist_path: Optional[str] = None,
    screener_path: Optional[str] = None,
    alpha_vantage_key: Optional[str] = None,
    output_dir: str = "./reports",
    max_tickers: int = 20,
    min_change: float = 10.0,
    min_price: float = 1.0,
    min_volume: int = 100_000,
    include_financials: bool = True,
    include_news: bool = True,
    verbose: bool = True
) -> dict:
    """
    Convenience function to run batch analysis.

    Args:
        tickers: List of ticker strings or TickerInput objects
        use_top_gainers: If True, fetch top gainers from Alpha Vantage (legacy mode)
        sources: List of source names to fetch from (nasdaq, alpha_vantage, watchlist, screener)
        nasdaq_category: NASDAQ category (gainers, losers, most_active, all)
        watchlist_path: Path to watchlist file
        screener_path: Path to screener export file
        alpha_vantage_key: Alpha Vantage API key (or set ALPHA_VANTAGE_API_KEY env var)
        output_dir: Directory for generated reports
        max_tickers: Maximum number of tickers to analyze
        min_change: Minimum % change for top gainers filter
        min_price: Minimum price filter for sources
        min_volume: Minimum volume filter for sources
        include_financials: Whether to fetch financial statements
        include_news: Whether to fetch and analyze news sentiment
        verbose: Print progress

    Returns:
        Dict with output_dir, files list, count, and analysis_date
    """
    # Get API key (may not be required for NASDAQ-only)
    av_key = alpha_vantage_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "")

    # Require API key for legacy mode or alpha_vantage source
    needs_av_key = use_top_gainers or (sources and "alpha_vantage" in sources)
    if needs_av_key and not av_key:
        raise ValueError("Alpha Vantage API key required")

    # Create config
    config = BatchConfig(
        output_dir=output_dir,
        max_tickers=max_tickers,
        min_change_percent=min_change,
        include_financials=include_financials,
        generate_index=True,
        verbose=verbose,
        sources=sources,
        nasdaq_category=nasdaq_category,
        watchlist_path=watchlist_path,
        screener_path=screener_path,
        min_price=min_price,
        min_volume=min_volume,
        include_news_analysis=include_news,
    )

    # Create analyzer
    analyzer = BatchAnalyzer(av_key, config)

    # Determine how to get tickers
    ticker_inputs = []

    if sources:
        # New multi-source mode
        if verbose:
            print(f"Fetching tickers from sources: {', '.join(sources)}...")

        ticker_inputs = await _fetch_from_sources(
            sources=sources,
            config=config,
            av_key=av_key,
            verbose=verbose,
        )

        if verbose:
            print(f"Found {len(ticker_inputs)} unique tickers from all sources")

    elif use_top_gainers:
        # Legacy: fetch from Alpha Vantage
        if verbose:
            print("Running analysis on top gainers (Alpha Vantage)...")
        dashboards = await analyzer.analyze_top_gainers()

        # Generate reports
        if verbose:
            print("Generating reports...")

        result = analyzer.generate_reports(dashboards, output_dir)

        if verbose:
            print(f"\nAnalysis complete!")
            print(f"  Tickers analyzed: {result['count']}")
            print(f"  Reports saved to: {result['output_dir']}")

        return result

    else:
        # Convert provided tickers to TickerInput
        for t in (tickers or []):
            if isinstance(t, str):
                ticker_inputs.append(TickerInput(ticker=t))
            elif isinstance(t, TickerInput):
                ticker_inputs.append(t)
            elif isinstance(t, dict):
                ticker_inputs.append(TickerInput(
                    ticker=t.get("ticker", t.get("symbol", "")),
                    change_percent=t.get("change_percent", t.get("change")),
                    current_price=t.get("current_price", t.get("price"))
                ))

    if not ticker_inputs:
        if verbose:
            print("No tickers to analyze")
        return {
            "output_dir": output_dir,
            "files": [],
            "count": 0,
            "analysis_date": datetime.now().strftime("%Y-%m-%d")
        }

    # Detect warrants and inject underlying tickers
    warrant_count_before = len(ticker_inputs)
    ticker_inputs = expand_warrants(ticker_inputs)
    warrants_found = [t for t in ticker_inputs if t.is_warrant]
    underlyings_added = len(ticker_inputs) - warrant_count_before
    if verbose and warrants_found:
        print(f"Detected {len(warrants_found)} warrant(s): {', '.join(t.ticker for t in warrants_found)}")
        if underlyings_added:
            print(f"  Auto-added {underlyings_added} underlying ticker(s)")

    if verbose:
        print(f"Running analysis on {len(ticker_inputs)} tickers...")

    dashboards = await analyzer.analyze_tickers(ticker_inputs)

    # Generate reports
    if verbose:
        print("Generating reports...")

    result = analyzer.generate_reports(dashboards, output_dir)

    if verbose:
        print(f"\nAnalysis complete!")
        print(f"  Tickers analyzed: {result['count']}")
        print(f"  Reports saved to: {result['output_dir']}")

    return result


async def _fetch_from_sources(
    sources: list[str],
    config: BatchConfig,
    av_key: str,
    verbose: bool = True,
) -> list:
    """
    Fetch tickers from multiple sources and deduplicate.

    Args:
        sources: List of source names
        config: Batch configuration
        av_key: Alpha Vantage API key
        verbose: Print progress

    Returns:
        List of TickerInput objects
    """
    from .ingest.ticker_sources import (
        TickerSourceManager,
        TickerSourceManagerConfig,
        TickerSource,
        NasdaqCategory,
    )

    # Map string category to enum
    category_map = {
        "gainers": NasdaqCategory.GAINERS,
        "losers": NasdaqCategory.LOSERS,
        "most_active": NasdaqCategory.MOST_ACTIVE,
        "all": NasdaqCategory.ALL,
    }

    # Create source manager config
    source_config = TickerSourceManagerConfig(
        nasdaq_category=category_map.get(config.nasdaq_category, NasdaqCategory.GAINERS),
        watchlist_path=config.watchlist_path,
        screener_path=config.screener_path,
        alpha_vantage_key=av_key,
        max_tickers=config.max_tickers,
        min_price=config.min_price,
        min_volume=config.min_volume,
    )

    # Create manager and enable sources
    manager = TickerSourceManager(source_config)
    manager.enable_sources(sources)

    # Fetch from all enabled sources
    tickers, results = await manager.fetch_all_with_results()

    if verbose:
        for result in results:
            status = "OK" if result.is_success else f"Error: {result.error}"
            print(f"  {result.source.value}: {result.count} tickers ({status})")

    return tickers


def run_batch_analysis_sync(*args, **kwargs) -> dict:
    """Synchronous wrapper for run_batch_analysis."""
    return asyncio.run(run_batch_analysis(*args, **kwargs))
