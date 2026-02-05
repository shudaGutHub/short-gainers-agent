#!/usr/bin/env python3
"""
Short Gainers Agent - CLI Entry Point

Usage:
    python -m short_gainers_agent [OPTIONS]
    
    or if installed:
    short-gainers [OPTIONS]

Examples:
    # Run with defaults
    python -m short_gainers_agent
    
    # Run with JSON output
    python -m short_gainers_agent --format json
    
    # Run with manual tickers
    python -m short_gainers_agent --tickers AAPL,MSFT,NVDA --changes 15.5,12.3,20.1
    
    # Run in verbose mode
    python -m short_gainers_agent -v
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from config.settings import Settings
from src.models.ticker import GainerRecord
from src.pipeline import PipelineConfig, run_pipeline_sync


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Short Gainers Agent - Screen NASDAQ top gainers for short opportunities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  short-gainers                     Run with defaults (fetch top gainers from API)
  short-gainers --format json       Output as JSON
  short-gainers --format compact    Output as CSV-like compact format
  short-gainers -v                  Verbose mode with progress output
  short-gainers --max 10            Limit to top 10 gainers
  short-gainers --min-change 20     Only screen gainers up 20%+
  short-gainers --no-claude         Skip Claude sentiment analysis
  short-gainers --tickers AAPL,NVDA --changes 25.5,30.2
                                    Manual tickers with change percentages
        """,
    )
    
    # Output options
    parser.add_argument(
        "-f", "--format",
        choices=["full", "json", "compact"],
        default="full",
        help="Output format (default: full)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        help="Write output to file instead of stdout",
    )
    
    # Filtering options
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        help="Maximum number of tickers to screen (default: 20)",
    )
    parser.add_argument(
        "--min-change",
        type=float,
        default=10.0,
        help="Minimum percent change to include (default: 10.0)",
    )
    
    # Analysis options
    parser.add_argument(
        "--no-claude",
        action="store_true",
        help="Skip Claude API for sentiment analysis (use heuristics only)",
    )
    
    # Manual input
    parser.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated list of tickers to analyze",
    )
    parser.add_argument(
        "--changes",
        type=str,
        help="Comma-separated list of percent changes (must match --tickers)",
    )
    parser.add_argument(
        "--prices",
        type=str,
        help="Comma-separated list of current prices (must match --tickers)",
    )
    
    # Misc
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output with progress updates",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="short-gainers-agent 0.1.0",
    )
    
    return parser.parse_args()


def parse_manual_gainers(
    tickers_str: str,
    changes_str: str,
    prices_str: str = None,
) -> list[GainerRecord]:
    """
    Parse manual ticker/change/price inputs.
    
    Args:
        tickers_str: Comma-separated tickers
        changes_str: Comma-separated change percentages
        prices_str: Optional comma-separated prices
        
    Returns:
        List of GainerRecord
    """
    tickers = [t.strip().upper() for t in tickers_str.split(",")]
    changes = [float(c.strip()) for c in changes_str.split(",")]
    
    if len(tickers) != len(changes):
        raise ValueError(
            f"Ticker count ({len(tickers)}) must match change count ({len(changes)})"
        )
    
    prices = None
    if prices_str:
        prices = [float(p.strip()) for p in prices_str.split(",")]
        if len(prices) != len(tickers):
            raise ValueError(
                f"Price count ({len(prices)}) must match ticker count ({len(tickers)})"
            )
    
    gainers = []
    for i, (ticker, change) in enumerate(zip(tickers, changes)):
        price = Decimal(str(prices[i])) if prices else Decimal("100.00")
        gainers.append(
            GainerRecord(
                ticker=ticker,
                price=price,
                change_amount=price * Decimal(str(change)) / Decimal("100"),
                change_percentage=Decimal(str(change)),
                volume=1_000_000,  # Default
            )
        )
    
    return gainers


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    # Load settings
    try:
        settings = Settings()
    except Exception as e:
        print(f"Error loading settings: {e}", file=sys.stderr)
        print("Make sure .env file exists with required API keys", file=sys.stderr)
        return 1
    
    # Build pipeline config
    config = PipelineConfig(
        max_tickers=args.max,
        min_change_percent=args.min_change,
        use_claude=not args.no_claude,
        output_format=args.format,
        verbose=args.verbose,
    )
    
    # Parse manual gainers if provided
    manual_gainers = None
    if args.tickers:
        if not args.changes:
            print("Error: --changes required when using --tickers", file=sys.stderr)
            return 1
        
        try:
            manual_gainers = parse_manual_gainers(
                args.tickers,
                args.changes,
                args.prices,
            )
        except ValueError as e:
            print(f"Error parsing manual inputs: {e}", file=sys.stderr)
            return 1
        
        if args.verbose:
            print(f"Using {len(manual_gainers)} manual tickers")
    
    # Run pipeline
    if args.verbose:
        print("=" * 60)
        print("SHORT GAINERS AGENT")
        print("=" * 60)
        print()
    
    try:
        result = run_pipeline_sync(
            settings=settings,
            config=config,
            manual_gainers=manual_gainers,
        )
    except Exception as e:
        print(f"Pipeline error: {e}", file=sys.stderr)
        return 1
    
    # Output results
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(result.output)
        if args.verbose:
            print(f"\nOutput written to {output_path}")
    else:
        print(result.output)
    
    # Print summary to stderr if verbose
    if args.verbose:
        print(file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Completed in {result.duration_seconds:.1f}s", file=sys.stderr)
        print(f"Screened: {result.tickers_screened}", file=sys.stderr)
        print(f"Excluded: {result.tickers_excluded}", file=sys.stderr)
        print(f"Candidates: {result.candidates_found}", file=sys.stderr)
        if result.errors:
            print(f"Errors: {len(result.errors)}", file=sys.stderr)
    
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
