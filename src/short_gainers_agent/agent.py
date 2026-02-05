"""Main agent orchestrator for short candidate analysis."""

import asyncio
import logging
from datetime import datetime
from typing import Sequence

from .analysis.risk import detect_risk_flags
from .analysis.scoring import ScoringEngine
from .config import Config, get_config
from .data.alpha_vantage import AlphaVantageClient
from .data.models import (
    AnalysisResult,
    BatchResult,
    BatchSummary,
    CatalystAnalysis,
    CatalystClassification,
    DataFreshness,
    Fundamentals,
    KeyLevels,
    Quote,
    RiskFlag,
    ScoreBreakdown,
    TechnicalIndicators,
    TradeExpression,
)

logger = logging.getLogger(__name__)


class Agent:
    """
    Short Gainers Agent - autonomous analysis of short-selling opportunities.

    This agent orchestrates the complete analysis pipeline:
    1. Data ingestion from Alpha Vantage
    2. Technical indicator calculation
    3. Catalyst/sentiment analysis
    4. Risk flag detection
    5. Score calculation
    6. Trade expression determination
    """

    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.client = AlphaVantageClient(self.config)
        self.scorer = ScoringEngine()

    async def close(self):
        """Clean up resources."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def analyze(
        self,
        symbol: str,
        quote: Quote | None = None,
        include_fundamentals: bool = True,
    ) -> AnalysisResult:
        """
        Perform complete analysis on a single symbol.

        Args:
            symbol: Stock ticker symbol
            quote: Pre-fetched quote (optional, will fetch if not provided)
            include_fundamentals: Whether to fetch fundamentals data

        Returns:
            AnalysisResult with complete analysis
        """
        symbol = symbol.upper()
        logger.info(f"Analyzing {symbol}")
        start_time = datetime.utcnow()
        warnings: list[str] = []

        # 1. Get quote if not provided
        if quote is None:
            quote = await self.client.get_quote(symbol)
            if quote is None:
                raise ValueError(f"Could not fetch quote for {symbol}")

        # 2. Fetch data in parallel
        tasks = [
            self.client.get_technicals(symbol, quote.price),
            self.client.get_news_sentiment(symbol),
        ]

        if include_fundamentals:
            tasks.append(self.client.get_fundamentals(symbol))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Unpack results
        technicals_result = results[0]
        catalyst_result = results[1]
        fundamentals = results[2] if include_fundamentals and len(results) > 2 else None

        # Handle exceptions
        if isinstance(technicals_result, Exception):
            logger.warning(f"Failed to fetch technicals for {symbol}: {technicals_result}")
            warnings.append(f"Technical indicators unavailable: {technicals_result}")
            technicals = TechnicalIndicators()
        else:
            technicals = technicals_result.indicators

        if isinstance(catalyst_result, Exception):
            logger.warning(f"Failed to fetch catalyst for {symbol}: {catalyst_result}")
            warnings.append(f"Catalyst analysis unavailable: {catalyst_result}")
            catalyst = CatalystAnalysis(
                classification=CatalystClassification.UNKNOWN,
                has_fundamental_catalyst=False,
            )
        else:
            catalyst = catalyst_result

        if isinstance(fundamentals, Exception):
            logger.warning(f"Failed to fetch fundamentals for {symbol}: {fundamentals}")
            warnings.append(f"Fundamentals unavailable: {fundamentals}")
            fundamentals = None

        # 3. Detect risk flags
        risk_flags = detect_risk_flags(
            quote=quote,
            technicals=technicals,
            fundamentals=fundamentals,
            catalyst=catalyst,
        )

        # 4. Calculate off-high percentage
        off_high_percent = None
        if quote.high and quote.price:
            off_high_percent = ((quote.price - quote.high) / quote.high) * 100

        # 5. Calculate score
        breakdown = self.scorer.calculate_score(
            technicals=technicals,
            catalyst=catalyst,
            risk_flags=risk_flags,
            change_percent=quote.change_percent,
            off_high_percent=off_high_percent,
        )

        # 6. Determine trade expression
        trade_expression = self.scorer.determine_trade_expression(
            score=breakdown.final_score,
            risk_flags=risk_flags,
            catalyst=catalyst,
        )

        # 7. Build key levels
        key_levels = KeyLevels(
            intraday_high=quote.high,
            intraday_low=quote.low,
            previous_close=quote.previous_close,
            support=quote.previous_close,  # Simplified - gap fill level
            resistance=quote.high,
            sma_20=technicals.sma_20,
            sma_50=technicals.sma_50,
        )

        # 8. Determine data freshness
        freshness = DataFreshness.REALTIME
        if quote.latest_trading_day:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            if quote.latest_trading_day != today:
                freshness = DataFreshness.DELAYED

        # 9. Build result
        result = AnalysisResult(
            symbol=symbol,
            name=fundamentals.name if fundamentals else None,
            exchange=fundamentals.exchange if fundamentals else None,
            price=quote.price,
            change=quote.change,
            change_percent=quote.change_percent,
            volume=quote.volume,
            short_score=breakdown.final_score,
            score_breakdown=breakdown,
            trade_expression=trade_expression,
            risk_flags=risk_flags,
            technicals=technicals,
            catalyst=catalyst,
            key_levels=key_levels,
            fundamentals=fundamentals,
            data_freshness=freshness,
            warnings=warnings,
        )

        elapsed_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        logger.info(
            f"Analysis complete for {symbol}: "
            f"score={breakdown.final_score:.1f}, "
            f"expression={trade_expression.value}, "
            f"flags={[f.value for f in risk_flags]}, "
            f"time={elapsed_ms}ms"
        )

        return result

    async def analyze_batch(
        self,
        symbols: Sequence[str],
        include_fundamentals: bool = True,
    ) -> BatchResult:
        """
        Analyze multiple symbols with rate limiting.

        Args:
            symbols: List of ticker symbols
            include_fundamentals: Whether to fetch fundamentals

        Returns:
            BatchResult with all analysis results and summary
        """
        logger.info(f"Starting batch analysis of {len(symbols)} symbols")
        start_time = datetime.utcnow()

        results: list[AnalysisResult] = []
        errors: list[dict[str, str]] = []

        # Process sequentially to respect rate limits
        for symbol in symbols:
            try:
                result = await self.analyze(
                    symbol=symbol,
                    include_fundamentals=include_fundamentals,
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to analyze {symbol}: {e}")
                errors.append({"symbol": symbol, "error": str(e)})

        # Calculate summary
        elapsed_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        actionable = [r for r in results if r.short_score >= self.config.actionable_score_threshold]
        high_squeeze = [r for r in results if RiskFlag.HIGH_SQUEEZE in r.risk_flags]

        summary = BatchSummary(
            total_analyzed=len(results),
            actionable_count=len(actionable),
            avg_score=sum(r.short_score for r in results) / max(len(results), 1),
            high_squeeze_count=len(high_squeeze),
            processing_time_ms=elapsed_ms,
        )

        # Sort results by score descending
        results.sort(key=lambda r: r.short_score, reverse=True)

        logger.info(
            f"Batch analysis complete: "
            f"{summary.total_analyzed} analyzed, "
            f"{summary.actionable_count} actionable, "
            f"avg_score={summary.avg_score:.2f}, "
            f"time={elapsed_ms}ms"
        )

        return BatchResult(
            results=results,
            summary=summary,
            errors=errors,
        )

    async def get_top_gainers(self, limit: int = 20) -> list[Quote]:
        """
        Fetch today's top gainers.

        Args:
            limit: Maximum number of gainers to return

        Returns:
            List of Quote objects for top gainers
        """
        data = await self.client.get_top_gainers_losers()
        gainers = data.get("top_gainers", [])[:limit]

        quotes = []
        for g in gainers:
            quotes.append(
                Quote(
                    symbol=g.get("ticker", ""),
                    price=float(g.get("price", 0)),
                    change=float(g.get("change_amount", 0)),
                    change_percent=float(g.get("change_percentage", "0%").rstrip("%")),
                    volume=int(g.get("volume", 0)),
                    previous_close=float(g.get("price", 0)) - float(g.get("change_amount", 0)),
                )
            )

        return quotes

    async def analyze_top_gainers(
        self,
        limit: int = 10,
        min_change_percent: float | None = None,
    ) -> BatchResult:
        """
        Analyze today's top gainers.

        Args:
            limit: Number of top gainers to analyze
            min_change_percent: Minimum % change filter

        Returns:
            BatchResult with analysis of top gainers
        """
        gainers = await self.get_top_gainers(limit=20)

        # Apply filter
        if min_change_percent:
            gainers = [g for g in gainers if g.change_percent >= min_change_percent]

        gainers = gainers[:limit]
        symbols = [g.symbol for g in gainers]

        logger.info(f"Analyzing top {len(symbols)} gainers: {symbols}")

        # Use batch analysis
        return await self.analyze_batch(symbols)


# Convenience function for one-off analysis
async def analyze_symbol(symbol: str) -> AnalysisResult:
    """Quick analysis of a single symbol."""
    async with Agent() as agent:
        return await agent.analyze(symbol)
