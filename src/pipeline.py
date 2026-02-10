"""
Main orchestration pipeline for the Short Gainers Agent.

This module ties together all components:
1. Fetch top gainers
2. Pre-filter candidates
3. Fetch price/fundamentals/news data
4. Compute technical scores
5. Analyze sentiment/catalysts
6. Rank and generate output
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from config.settings import Settings
from src.clients.alpha_vantage import AlphaVantageClient
from src.clients.claude_client import ClaudeClient
from src.filters.prefilter import prefilter_ticker
from src.ingest.fundamentals import fetch_fundamentals
from src.ingest.gainers import fetch_top_gainers, filter_nasdaq_gainers
from src.ingest.news import fetch_news
from src.ingest.price import fetch_price_data
from src.models.candidate import KeyLevels, RiskFlag
from src.models.ticker import Fundamentals, GainerRecord
from src.output.formatter import (
    build_agent_output,
    format_compact_output,
    format_full_report,
    format_json_output,
)
from src.ranking.ranker import RankingInput, rank_candidates_batch
from src.sentiment.catalyst import analyze_catalyst
from src.technicals.indicators import series_to_dataframe
from src.technicals.scoring import compute_technical_score_from_series


@dataclass
class PipelineConfig:
    """Configuration for pipeline run."""
    
    max_tickers: int = 20
    min_change_percent: float = 10.0
    use_claude: bool = True
    output_format: str = "full"  # "full", "json", "compact"
    verbose: bool = False


@dataclass
class PipelineResult:
    """Result of pipeline execution."""
    
    success: bool
    output: str
    candidates_found: int
    tickers_screened: int
    tickers_excluded: int
    errors: list[str]
    duration_seconds: float


async def run_pipeline(
    settings: Settings,
    config: PipelineConfig,
    manual_gainers: Optional[list[GainerRecord]] = None,
) -> PipelineResult:
    """
    Run the complete short gainers analysis pipeline.
    
    Args:
        settings: Application settings
        config: Pipeline configuration
        manual_gainers: Optional manual list of gainers (bypasses API fetch)
        
    Returns:
        PipelineResult with output and metadata
    """
    start_time = datetime.now()
    errors = []
    excluded_tickers = []
    
    # Initialize clients
    av_client = AlphaVantageClient(
        api_key=settings.alpha_vantage_api_key,
        rate_limit_rpm=settings.av_rate_limit_rpm,
    )
    
    claude_client = None
    if config.use_claude and settings.anthropic_api_key:
        claude_client = ClaudeClient(api_key=settings.anthropic_api_key)
    
    try:
        # Step 1: Get top gainers
        if config.verbose:
            print("Step 1: Fetching top gainers...")
        
        if manual_gainers:
            gainers = manual_gainers
        else:
            gainers_result = await fetch_top_gainers(av_client)
            if not gainers_result.gainers:
                return PipelineResult(
                    success=False,
                    output="No gainers data available",
                    candidates_found=0,
                    tickers_screened=0,
                    tickers_excluded=0,
                    errors=["Failed to fetch top gainers"],
                    duration_seconds=(datetime.now() - start_time).total_seconds(),
                )
            gainers = filter_nasdaq_gainers(gainers_result.gainers)
        
        # Filter by minimum change
        gainers = [
            g for g in gainers 
            if float(g.change_percentage) >= config.min_change_percent
        ][:config.max_tickers]
        
        if config.verbose:
            print(f"  Found {len(gainers)} gainers above {config.min_change_percent}% threshold")
        
        total_screened = len(gainers)
        
        if not gainers:
            return PipelineResult(
                success=True,
                output="No gainers above minimum threshold",
                candidates_found=0,
                tickers_screened=0,
                tickers_excluded=0,
                errors=[],
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
        
        # Step 2: Fetch data for each ticker
        if config.verbose:
            print("Step 2: Fetching price/fundamentals/news data...")
        
        ranking_inputs = []
        
        for i, gainer in enumerate(gainers):
            ticker = gainer.ticker
            
            if config.verbose:
                print(f"  [{i+1}/{len(gainers)}] Processing {ticker}...")
            
            try:
                # Fetch all data concurrently
                price_task = fetch_price_data(
                    ticker=ticker,
                    av_client=av_client,
                    yf_client=None,
                    days=settings.lookback_days,
                    intraday_interval=settings.intraday_interval,
                )
                fundamentals_task = fetch_fundamentals(
                    ticker=ticker,
                    av_client=av_client,
                    yf_client=None,
                )
                news_task = fetch_news(
                    ticker=ticker,
                    av_client=av_client,
                )
                
                price_result, fundamentals_result, news_result = await asyncio.gather(
                    price_task, fundamentals_task, news_task,
                    return_exceptions=True,
                )
                
                # Handle exceptions
                if isinstance(price_result, Exception):
                    errors.append(f"{ticker}: Price fetch failed - {price_result}")
                    excluded_tickers.append(ticker)
                    continue
                
                fundamentals = None
                if not isinstance(fundamentals_result, Exception):
                    fundamentals = fundamentals_result.data
                
                news_feed = None
                if not isinstance(news_result, Exception):
                    news_feed = news_result.feed
                
                # Step 3: Pre-filter
                filtered = prefilter_ticker(
                    ticker=ticker,
                    fundamentals=fundamentals,
                    change_percent=gainer.change_percentage,
                    settings=settings,
                )
                
                if not filtered.passed:
                    excluded_tickers.append(ticker)
                    if config.verbose:
                        print(f"    Excluded: {filtered.exclusion_reason}")
                    continue
                
                # Step 4: Technical analysis
                if price_result.daily is None or price_result.daily.is_empty:
                    errors.append(f"{ticker}: No daily price data")
                    excluded_tickers.append(ticker)
                    continue
                
                tech_score, _, tech_state = compute_technical_score_from_series(
                    daily=price_result.daily,
                    intraday=price_result.intraday,
                    settings=settings,
                )
                
                # Step 5: Sentiment analysis
                sentiment_result = await analyze_catalyst(
                    ticker=ticker,
                    change_percent=gainer.change_percentage,
                    news_feed=news_feed,
                    claude_client=claude_client,
                )
                
                # Build key levels
                key_levels = KeyLevels(
                    intraday_high=price_result.get_intraday_high() if price_result.intraday else None,
                    intraday_low=price_result.get_intraday_low() if price_result.intraday else None,
                    vwap=price_result.calculate_vwap() if price_result.intraday else None,
                    prior_day_close=price_result.get_prior_close(),
                )
                
                # Get current price
                current_price = price_result.get_current_price()
                if current_price is None:
                    current_price = gainer.price
                
                # Build ranking input
                ranking_input = RankingInput(
                    ticker=ticker,
                    current_price=current_price,
                    change_percent=gainer.change_percentage,
                    tech_score=tech_score,
                    tech_state=tech_state,
                    sentiment_result=sentiment_result,
                    risk_flags=filtered.risk_flags,
                    key_levels=key_levels,
                    market_cap=filtered.market_cap,
                    avg_volume=filtered.avg_volume,
                    beta=filtered.beta,
                )
                
                ranking_inputs.append(ranking_input)
                
            except Exception as e:
                errors.append(f"{ticker}: Unexpected error - {e}")
                excluded_tickers.append(ticker)
                continue
        
        # Step 6: Rank candidates
        if config.verbose:
            print("Step 6: Ranking candidates...")
        
        if not ranking_inputs:
            output = build_agent_output(
                results=[],
                excluded_tickers=excluded_tickers,
                total_screened=total_screened,
                date=datetime.now().strftime("%Y-%m-%d"),
                notes=errors[:5] if errors else None,
            )
        else:
            ranked_results = rank_candidates_batch(
                inputs=ranking_inputs,
                max_beta_for_shares=settings.max_beta_for_shares,
            )
            
            output = build_agent_output(
                results=ranked_results,
                excluded_tickers=excluded_tickers,
                total_screened=total_screened,
                date=datetime.now().strftime("%Y-%m-%d"),
                notes=errors[:5] if errors else None,
            )
        
        # Step 7: Format output
        if config.output_format == "json":
            output_str = format_json_output(output)
        elif config.output_format == "compact":
            output_str = format_compact_output(output)
        else:
            output_str = format_full_report(output)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        return PipelineResult(
            success=True,
            output=output_str,
            candidates_found=len(output.candidates),
            tickers_screened=total_screened,
            tickers_excluded=len(excluded_tickers),
            errors=errors,
            duration_seconds=duration,
        )
        
    finally:
        await av_client.close()
        if claude_client:
            await claude_client.close()


def run_pipeline_sync(
    settings: Settings,
    config: PipelineConfig,
    manual_gainers: Optional[list[GainerRecord]] = None,
) -> PipelineResult:
    """
    Synchronous wrapper for run_pipeline.
    
    Args:
        settings: Application settings
        config: Pipeline configuration
        manual_gainers: Optional manual list of gainers
        
    Returns:
        PipelineResult
    """
    return asyncio.run(run_pipeline(settings, config, manual_gainers))
