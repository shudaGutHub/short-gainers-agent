"""
NASDAQ Market Activity Client

Fetches market movers (gainers, losers, most active) from NASDAQ's API.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

import httpx


class NasdaqCategory(str, Enum):
    """NASDAQ market activity categories."""
    GAINERS = "gainers"
    LOSERS = "losers"
    MOST_ACTIVE = "most_active"
    ALL = "all"


class NasdaqClientError(Exception):
    """Base exception for NASDAQ client errors."""
    pass


class NasdaqRateLimitError(NasdaqClientError):
    """Rate limit exceeded."""
    pass


class NasdaqResponseError(NasdaqClientError):
    """Invalid or unexpected response from NASDAQ API."""
    pass


@dataclass
class NasdaqTicker:
    """Ticker data from NASDAQ market activity."""
    ticker: str
    name: str
    price: Decimal
    change_amount: Decimal
    change_percent: Decimal
    volume: int
    market_cap: Optional[int] = None
    country: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class NasdaqClient:
    """
    Client for fetching NASDAQ market activity data.

    Usage:
        async with NasdaqClient() as client:
            gainers = await client.fetch_gainers(limit=25)
            losers = await client.fetch_losers(limit=25)
            active = await client.fetch_most_active(limit=25)
    """

    # Primary endpoint for market movers (gainers/losers/active)
    MARKET_MOVERS_URL = "https://api.nasdaq.com/api/marketmovers"
    # Fallback screener endpoint
    SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"

    # NASDAQ API requires specific headers to avoid blocking
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/stocks",
    }

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize NASDAQ client.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            headers=self.DEFAULT_HEADERS,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self.DEFAULT_HEADERS,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
            )
        return self._client

    async def _fetch_with_retry(self, url: str, params: dict) -> dict:
        """
        Fetch data with retry logic and exponential backoff.

        Args:
            url: API endpoint URL
            params: Query parameters

        Returns:
            JSON response data

        Raises:
            NasdaqClientError: On persistent failures
            NasdaqRateLimitError: On rate limiting
        """
        client = self._get_client()
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = await client.get(url, params=params)

                if response.status_code == 429:
                    raise NasdaqRateLimitError("Rate limit exceeded")

                if response.status_code != 200:
                    raise NasdaqResponseError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()

                # Check for API-level errors
                if data.get("status", {}).get("rCode") != 200:
                    error_msg = data.get("status", {}).get("bCodeMessage", "Unknown error")
                    raise NasdaqResponseError(f"API error: {error_msg}")

                return data

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                raise NasdaqClientError(f"Connection failed after {self.max_retries} attempts: {e}")

            except NasdaqRateLimitError:
                # On rate limit, wait longer before retry
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (4 ** attempt)  # More aggressive backoff
                    await asyncio.sleep(delay)
                    continue
                raise

        raise NasdaqClientError(f"Request failed: {last_error}")

    def _parse_ticker(self, row: dict) -> Optional[NasdaqTicker]:
        """
        Parse a single ticker from NASDAQ API response.

        Args:
            row: Dictionary with ticker data from API

        Returns:
            NasdaqTicker object or None if parsing fails
        """
        try:
            # Handle various field formats from NASDAQ API
            ticker = row.get("symbol", "").strip()
            if not ticker:
                return None

            name = row.get("name", "").strip()

            # Parse price - may be string with $ or numeric
            price_str = str(row.get("lastsale", row.get("price", "0")))
            price_str = price_str.replace("$", "").replace(",", "").strip()
            price = Decimal(price_str) if price_str else Decimal("0")

            # Parse change amount
            change_str = str(row.get("netchange", "0"))
            change_str = change_str.replace("$", "").replace(",", "").strip()
            change_amount = Decimal(change_str) if change_str else Decimal("0")

            # Parse change percent - may be string with % or numeric
            pct_str = str(row.get("pctchange", "0"))
            pct_str = pct_str.replace("%", "").replace(",", "").strip()
            change_percent = Decimal(pct_str) if pct_str else Decimal("0")

            # Parse volume - may have commas or be in format like "1.2M"
            vol_str = str(row.get("volume", "0"))
            vol_str = vol_str.replace(",", "").strip()
            if vol_str.upper().endswith("M"):
                volume = int(float(vol_str[:-1]) * 1_000_000)
            elif vol_str.upper().endswith("K"):
                volume = int(float(vol_str[:-1]) * 1_000)
            elif vol_str.upper().endswith("B"):
                volume = int(float(vol_str[:-1]) * 1_000_000_000)
            else:
                volume = int(float(vol_str)) if vol_str else 0

            # Parse market cap - may be formatted as string
            mkt_cap_str = str(row.get("marketCap", ""))
            market_cap = None
            if mkt_cap_str:
                mkt_cap_str = mkt_cap_str.replace(",", "").replace("$", "").strip()
                if mkt_cap_str:
                    try:
                        market_cap = int(float(mkt_cap_str))
                    except (ValueError, TypeError):
                        pass

            return NasdaqTicker(
                ticker=ticker,
                name=name,
                price=price,
                change_amount=change_amount,
                change_percent=change_percent,
                volume=volume,
                market_cap=market_cap,
                country=row.get("country"),
                sector=row.get("sector"),
                industry=row.get("industry"),
            )
        except (ValueError, TypeError, KeyError) as e:
            # Log and skip malformed data
            return None

    def _parse_market_mover(self, row: dict) -> Optional[NasdaqTicker]:
        """
        Parse a ticker from the market movers API response.

        Args:
            row: Dictionary with ticker data from market movers API

        Returns:
            NasdaqTicker object or None if parsing fails
        """
        try:
            ticker = row.get("symbol", "").strip()
            if not ticker:
                return None

            name = row.get("name", "").strip()

            # Parse price - format: "$172.06"
            price_str = str(row.get("lastSalePrice", "0"))
            price_str = price_str.replace("$", "").replace(",", "").strip()
            price = Decimal(price_str) if price_str else Decimal("0")

            # Parse change amount - format: "+0.095" or "-2.13"
            change_str = str(row.get("lastSaleChange", "0"))
            change_str = change_str.replace("$", "").replace(",", "").replace("+", "").strip()
            change_amount = Decimal(change_str) if change_str else Decimal("0")

            # Parse change percent - format: "+656.0154%" or "-1.223%"
            pct_str = str(row.get("change", "0"))
            pct_str = pct_str.replace("%", "").replace(",", "").replace("+", "").strip()
            change_percent = Decimal(pct_str) if pct_str else Decimal("0")

            # Volume not directly available in market movers, default to 0
            volume = 0

            return NasdaqTicker(
                ticker=ticker,
                name=name,
                price=price,
                change_amount=change_amount,
                change_percent=change_percent,
                volume=volume,
            )
        except (ValueError, TypeError, KeyError):
            return None

    async def _fetch_market_movers(
        self,
        mover_type: str = "gainers",
        exchange: str = "nasdaq",
        limit: int = 25,
        min_price: float = 0,
    ) -> list[NasdaqTicker]:
        """
        Fetch data from NASDAQ market movers API (primary source).

        Args:
            mover_type: Type of movers - 'gainers', 'losers', or 'active'
            exchange: Exchange filter (nasdaq, nyse, amex)
            limit: Maximum number of results
            min_price: Minimum price filter

        Returns:
            List of NasdaqTicker objects
        """
        params = {
            "assetclass": "stocks",
            "exchange": exchange.lower(),
        }

        # Map mover type to API parameter
        if mover_type == "gainers":
            params["marketmoverstype"] = "gainers"
        elif mover_type == "losers":
            params["marketmoverstype"] = "decliners"
        elif mover_type == "active":
            params["marketmoverstype"] = "volume"

        data = await self._fetch_with_retry(self.MARKET_MOVERS_URL, params)

        # Navigate to the correct data section
        stocks_data = data.get("data", {}).get("STOCKS", {})

        # Map mover type to response key
        section_map = {
            "gainers": "MostAdvanced",
            "losers": "MostDeclined",
            "active": "MostActiveByShareVolume",
        }
        section_key = section_map.get(mover_type, "MostAdvanced")

        rows = stocks_data.get(section_key, {}).get("table", {}).get("rows", [])

        tickers = []
        for row in rows[:limit]:
            ticker = self._parse_market_mover(row)
            if ticker:
                # Apply price filter
                if float(ticker.price) >= min_price:
                    tickers.append(ticker)

        return tickers

    async def _fetch_screener(
        self,
        sort_column: str,
        sort_order: str = "desc",
        limit: int = 25,
        exchange: str = "NASDAQ",
        min_price: float = 0,
        min_volume: int = 0,
    ) -> list[NasdaqTicker]:
        """
        Fetch data from NASDAQ screener API (fallback source).

        Args:
            sort_column: Column to sort by (changepct, volume, etc.)
            sort_order: Sort direction (asc or desc)
            limit: Maximum number of results
            exchange: Exchange filter (NASDAQ, NYSE, AMEX, or empty for all)
            min_price: Minimum price filter
            min_volume: Minimum volume filter

        Returns:
            List of NasdaqTicker objects
        """
        params = {
            "tableonly": "true",
            "limit": str(limit),
            "offset": "0",
            "sortcolumn": sort_column,
            "sortorder": sort_order,
        }

        if exchange:
            params["exchange"] = exchange

        data = await self._fetch_with_retry(self.SCREENER_URL, params)

        # Extract rows from response
        rows = data.get("data", {}).get("table", {}).get("rows", [])

        tickers = []
        for row in rows:
            ticker = self._parse_ticker(row)
            if ticker:
                # Apply filters
                if float(ticker.price) >= min_price and ticker.volume >= min_volume:
                    tickers.append(ticker)

        return tickers

    async def fetch_gainers(
        self,
        limit: int = 25,
        exchange: str = "NASDAQ",
        min_price: float = 1.0,
        min_volume: int = 100_000,
    ) -> list[NasdaqTicker]:
        """
        Fetch top gainers (stocks with highest % increase).

        Uses the market movers API which provides real-time top gainers
        from the NASDAQ website.

        Args:
            limit: Maximum number of results
            exchange: Exchange filter (nasdaq, nyse, amex)
            min_price: Minimum price filter
            min_volume: Minimum volume filter (not used for market movers)

        Returns:
            List of NasdaqTicker objects sorted by change_percent descending
        """
        return await self._fetch_market_movers(
            mover_type="gainers",
            exchange=exchange.lower(),
            limit=limit,
            min_price=min_price,
        )

    async def fetch_losers(
        self,
        limit: int = 25,
        exchange: str = "NASDAQ",
        min_price: float = 1.0,
        min_volume: int = 100_000,
    ) -> list[NasdaqTicker]:
        """
        Fetch top losers (stocks with highest % decrease).

        Uses the market movers API which provides real-time top decliners
        from the NASDAQ website.

        Args:
            limit: Maximum number of results
            exchange: Exchange filter (nasdaq, nyse, amex)
            min_price: Minimum price filter
            min_volume: Minimum volume filter (not used for market movers)

        Returns:
            List of NasdaqTicker objects sorted by change_percent ascending
        """
        return await self._fetch_market_movers(
            mover_type="losers",
            exchange=exchange.lower(),
            limit=limit,
            min_price=min_price,
        )

    async def fetch_most_active(
        self,
        limit: int = 25,
        exchange: str = "NASDAQ",
        min_price: float = 1.0,
        min_volume: int = 100_000,
    ) -> list[NasdaqTicker]:
        """
        Fetch most active stocks (highest volume).

        Uses the market movers API which provides real-time most active stocks
        from the NASDAQ website.

        Args:
            limit: Maximum number of results
            exchange: Exchange filter (nasdaq, nyse, amex)
            min_price: Minimum price filter
            min_volume: Minimum volume filter (not used for market movers)

        Returns:
            List of NasdaqTicker objects sorted by volume descending
        """
        return await self._fetch_market_movers(
            mover_type="active",
            exchange=exchange.lower(),
            limit=limit,
            min_price=min_price,
        )

    async def fetch_most_active_screener(
        self,
        limit: int = 25,
        exchange: str = "NASDAQ",
        min_price: float = 1.0,
        min_volume: int = 100_000,
    ) -> list[NasdaqTicker]:
        """
        Fetch most active stocks using the screener API (fallback).

        Args:
            limit: Maximum number of results
            exchange: Exchange filter
            min_price: Minimum price filter
            min_volume: Minimum volume filter

        Returns:
            List of NasdaqTicker objects sorted by volume descending
        """
        return await self._fetch_screener(
            sort_column="volume",
            sort_order="desc",
            limit=limit,
            exchange=exchange,
            min_price=min_price,
            min_volume=min_volume,
        )

    async def fetch_market_movers(
        self,
        category: NasdaqCategory = NasdaqCategory.GAINERS,
        limit: int = 25,
        exchange: str = "NASDAQ",
        min_price: float = 1.0,
        min_volume: int = 100_000,
    ) -> list[NasdaqTicker]:
        """
        Fetch market movers by category.

        Args:
            category: Type of movers to fetch
            limit: Maximum number of results per category
            exchange: Exchange filter
            min_price: Minimum price filter
            min_volume: Minimum volume filter

        Returns:
            List of NasdaqTicker objects
        """
        if category == NasdaqCategory.GAINERS:
            return await self.fetch_gainers(limit, exchange, min_price, min_volume)
        elif category == NasdaqCategory.LOSERS:
            return await self.fetch_losers(limit, exchange, min_price, min_volume)
        elif category == NasdaqCategory.MOST_ACTIVE:
            return await self.fetch_most_active(limit, exchange, min_price, min_volume)
        elif category == NasdaqCategory.ALL:
            # Fetch all categories and combine
            gainers, losers, active = await asyncio.gather(
                self.fetch_gainers(limit, exchange, min_price, min_volume),
                self.fetch_losers(limit, exchange, min_price, min_volume),
                self.fetch_most_active(limit, exchange, min_price, min_volume),
                return_exceptions=True,
            )

            # Combine and deduplicate
            result = []
            seen = set()

            for ticker_list in [gainers, losers, active]:
                if isinstance(ticker_list, Exception):
                    continue
                for ticker in ticker_list:
                    if ticker.ticker not in seen:
                        seen.add(ticker.ticker)
                        result.append(ticker)

            return result
        else:
            raise ValueError(f"Unknown category: {category}")

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
