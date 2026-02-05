#!/usr/bin/env python3
"""
Short Gainers Batch Analysis CLI

Usage:
    # Analyze NASDAQ top gainers (primary source)
    python -m short_gainers_agent.batch_cli --source nasdaq

    # Analyze Alpha Vantage top gainers (legacy mode)
    python -m short_gainers_agent.batch_cli --top-gainers

    # Analyze specific tickers
    python -m short_gainers_agent.batch_cli --tickers TCGL,AAPL,MSFT

    # Analyze with change percentages
    python -m short_gainers_agent.batch_cli --tickers TCGL,AAPL --changes 941,5

    # Multiple sources combined
    python -m short_gainers_agent.batch_cli --source nasdaq,watchlist --watchlist ./tickers.csv

    # Custom output directory
    python -m short_gainers_agent.batch_cli --source nasdaq -o ./my_reports
"""

import argparse
import os
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Generate short candidate analysis dashboards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze NASDAQ top gainers (recommended)
  python batch_cli.py --source nasdaq

  # Analyze NASDAQ losers
  python batch_cli.py --source nasdaq --nasdaq-category losers

  # Combine multiple sources
  python batch_cli.py --source nasdaq,alpha_vantage --max 30

  # Use watchlist file
  python batch_cli.py --source watchlist --watchlist ./my_watchlist.csv

  # Use screener export (Finviz, TradingView)
  python batch_cli.py --source screener --screener ./finviz_export.csv

  # Multiple sources with deduplication
  python batch_cli.py --source nasdaq,watchlist --watchlist ./tickers.csv

  # Legacy: Analyze Alpha Vantage top gainers
  python batch_cli.py --top-gainers

  # Analyze specific tickers
  python batch_cli.py --tickers TCGL,AAPL,MSFT

  # Analyze with known change percentages
  python batch_cli.py --tickers TCGL,AAPL --changes 941,5

  # Limit to 10 tickers, min 20% change
  python batch_cli.py --source nasdaq --max 10 --min-change 20

  # Skip financial statements (faster)
  python batch_cli.py --tickers TCGL --no-financials
"""
    )
    
    # Input source (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--source", "-s",
        type=str,
        help="Comma-separated list of ticker sources: nasdaq, alpha_vantage, watchlist, screener"
    )
    input_group.add_argument(
        "--top-gainers",
        action="store_true",
        help="[Legacy] Analyze top gainers from Alpha Vantage"
    )
    input_group.add_argument(
        "--tickers", "-t",
        type=str,
        help="Comma-separated list of tickers to analyze"
    )
    input_group.add_argument(
        "--file", "-f",
        type=str,
        help="File containing tickers (one per line, or CSV with ticker,change columns)"
    )

    # Source-specific options
    parser.add_argument(
        "--nasdaq-category",
        type=str,
        choices=["gainers", "losers", "most_active", "all"],
        default="gainers",
        help="NASDAQ category: gainers, losers, most_active, or all (default: gainers)"
    )
    parser.add_argument(
        "--watchlist",
        type=str,
        help="Path to watchlist file (CSV, TXT, or JSON)"
    )
    parser.add_argument(
        "--screener",
        type=str,
        help="Path to screener export file (Finviz, TradingView CSV, or JSON)"
    )
    
    # Optional inputs
    parser.add_argument(
        "--changes", "-c",
        type=str,
        help="Comma-separated change percentages (must match --tickers count)"
    )
    parser.add_argument(
        "--prices", "-p",
        type=str,
        help="Comma-separated prices (must match --tickers count)"
    )
    
    # Configuration
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="./reports",
        help="Output directory for reports (default: ./reports)"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        help="Maximum tickers to analyze (default: 20)"
    )
    parser.add_argument(
        "--min-change",
        type=float,
        default=10.0,
        help="Minimum percent change for top gainers filter (default: 10.0)"
    )
    parser.add_argument(
        "--no-financials",
        action="store_true",
        help="Skip fetching financial statements (faster)"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="Alpha Vantage API key (or set ALPHA_VANTAGE_API_KEY env var)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()

    # Get API key (may not be required for NASDAQ-only source)
    api_key = args.api_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "")

    # Validate source-specific arguments
    if args.source:
        sources = [s.strip().lower() for s in args.source.split(",")]
        if "watchlist" in sources and not args.watchlist:
            print("Error: --watchlist path required when using 'watchlist' source", file=sys.stderr)
            sys.exit(1)
        if "screener" in sources and not args.screener:
            print("Error: --screener path required when using 'screener' source", file=sys.stderr)
            sys.exit(1)
        if "alpha_vantage" in sources and not api_key:
            print("Error: Alpha Vantage API key required for 'alpha_vantage' source", file=sys.stderr)
            print("Set ALPHA_VANTAGE_API_KEY environment variable or use --api-key", file=sys.stderr)
            sys.exit(1)

    # For legacy --top-gainers and any source needing Alpha Vantage
    if args.top_gainers and not api_key:
        print("Error: Alpha Vantage API key required.", file=sys.stderr)
        print("Set ALPHA_VANTAGE_API_KEY environment variable or use --api-key", file=sys.stderr)
        sys.exit(1)

    # Parse tickers based on input mode
    tickers = None
    use_top_gainers = args.top_gainers
    sources = None
    nasdaq_category = args.nasdaq_category
    watchlist_path = args.watchlist
    screener_path = args.screener

    if args.source:
        # New multi-source mode
        sources = [s.strip().lower() for s in args.source.split(",")]

    elif args.tickers:
        ticker_list = [t.strip().upper() for t in args.tickers.split(",")]

        # Parse changes if provided
        changes = None
        if args.changes:
            changes = [float(c.strip()) for c in args.changes.split(",")]
            if len(changes) != len(ticker_list):
                print("Error: --changes count must match --tickers count", file=sys.stderr)
                sys.exit(1)

        # Parse prices if provided
        prices = None
        if args.prices:
            prices = [float(p.strip()) for p in args.prices.split(",")]
            if len(prices) != len(ticker_list):
                print("Error: --prices count must match --tickers count", file=sys.stderr)
                sys.exit(1)

        tickers = []
        for i, ticker in enumerate(ticker_list):
            tickers.append({
                "ticker": ticker,
                "change_percent": changes[i] if changes else None,
                "current_price": prices[i] if prices else None
            })

    elif args.file:
        # Read tickers from file
        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)

        tickers = []
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split(",")
                ticker = parts[0].strip().upper()
                change = float(parts[1].strip()) if len(parts) > 1 else None
                price = float(parts[2].strip()) if len(parts) > 2 else None

                tickers.append({
                    "ticker": ticker,
                    "change_percent": change,
                    "current_price": price
                })

    # Import and run
    try:
        from .batch_processor import run_batch_analysis_sync
    except ImportError:
        # Handle running as script vs module
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.batch_processor import run_batch_analysis_sync

    verbose = not args.quiet

    if verbose:
        print("=" * 60)
        print("Short Gainers Batch Analysis")
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        if sources:
            print(f"Sources: {', '.join(sources)}")
            if "nasdaq" in sources:
                print(f"NASDAQ category: {nasdaq_category}")

    try:
        result = run_batch_analysis_sync(
            tickers=tickers,
            use_top_gainers=use_top_gainers,
            sources=sources,
            nasdaq_category=nasdaq_category,
            watchlist_path=watchlist_path,
            screener_path=screener_path,
            alpha_vantage_key=api_key,
            output_dir=args.output,
            max_tickers=args.max,
            min_change=args.min_change,
            include_financials=not args.no_financials,
            verbose=verbose
        )

        if verbose:
            print("\n" + "=" * 60)
            print("Results")
            print("=" * 60)
            print(f"Tickers analyzed: {result['count']}")
            print(f"Reports directory: {result['output_dir']}")
            print(f"Index page: {result['output_dir']}/index.html")
            print("\nGenerated files:")
            for f in result['files'][:10]:
                print(f"  {os.path.basename(f)}")
            if len(result['files']) > 10:
                print(f"  ... and {len(result['files']) - 10} more")

        # Return success
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
