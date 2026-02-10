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

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

  # Deploy to Netlify and send WhatsApp notification
  python batch_cli.py --source nasdaq --deploy --netlify-site your-site-id --notify-whatsapp +1234567890

  # Deploy only (no notification)
  python batch_cli.py --source nasdaq --deploy --netlify-site singular-douhua-5443a7

  # Send email notification (requires SMTP env vars)
  python batch_cli.py --source nasdaq --deploy --netlify-site your-site --notify-email team@example.com
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
        help="Base output directory for reports (default: ./reports)"
    )
    parser.add_argument(
        "--date-folder",
        action="store_true",
        default=True,
        help="Create date-based subdirectory (default: True)"
    )
    parser.add_argument(
        "--no-date-folder",
        action="store_true",
        help="Don't create date-based subdirectory"
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
        "--no-news",
        action="store_true",
        help="Skip news sentiment analysis (faster)"
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

    # Deployment options
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy reports to Netlify after analysis"
    )
    parser.add_argument(
        "--netlify-site",
        type=str,
        metavar="SITE_ID",
        help="Netlify site ID (e.g., singular-douhua-5443a7) or set NETLIFY_SITE_ID env var"
    )

    # Notification options
    parser.add_argument(
        "--notify-email",
        type=str,
        metavar="EMAIL",
        help="Send email notification to this address (comma-separated for multiple)"
    )
    parser.add_argument(
        "--notify-whatsapp",
        type=str,
        metavar="PHONE",
        help="Send WhatsApp notification to this number (with country code, e.g., +1234567890)"
    )
    parser.add_argument(
        "--report-url",
        type=str,
        default=None,
        help="Public URL for reports (auto-set if --deploy is used)"
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

    # Determine output directory (with optional date subfolder)
    output_dir = args.output
    if args.date_folder and not args.no_date_folder:
        date_str = datetime.now().strftime('%Y-%m-%d')
        output_dir = os.path.join(args.output, date_str)

    if verbose:
        print("=" * 60)
        print("Short Gainers Batch Analysis")
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        if sources:
            print(f"Sources: {', '.join(sources)}")
            if "nasdaq" in sources:
                print(f"NASDAQ category: {nasdaq_category}")
        print(f"Output: {output_dir}")

    try:
        result = run_batch_analysis_sync(
            tickers=tickers,
            use_top_gainers=use_top_gainers,
            sources=sources,
            nasdaq_category=nasdaq_category,
            watchlist_path=watchlist_path,
            screener_path=screener_path,
            alpha_vantage_key=api_key,
            output_dir=output_dir,
            max_tickers=args.max,
            min_change=args.min_change,
            include_financials=not args.no_financials,
            include_news=not args.no_news,
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

        # Deploy to Netlify if requested
        report_url = args.report_url or "http://localhost:5000"

        if args.deploy:
            from .deploy import deploy_to_netlify

            if verbose:
                print("\n" + "=" * 60)
                print("Deploying to Netlify")
                print("=" * 60)

            site_id = args.netlify_site or os.environ.get("NETLIFY_SITE_ID", "")
            if not site_id:
                print("Error: --netlify-site or NETLIFY_SITE_ID env var required for deployment")
            else:
                deploy_result = deploy_to_netlify(
                    reports_dir=result['output_dir'],
                    site_id=site_id,
                )

                if deploy_result.success:
                    report_url = deploy_result.url
                    print(f"Deployed successfully!")
                    print(f"Live URL: {report_url}")
                else:
                    print(f"Deployment failed: {deploy_result.error}")

        # Send notifications if configured
        if args.notify_email or args.notify_whatsapp:
            from .notifications import (
                NotificationConfig,
                send_notifications,
                open_whatsapp_web,
            )

            # Get list of tickers analyzed
            tickers_analyzed = [
                os.path.basename(f).replace(".html", "")
                for f in result.get("files", [])
                if f.endswith(".html") and "index" not in f.lower()
            ]

            if verbose:
                print("\n" + "=" * 60)
                print("Sending Notifications")
                print("=" * 60)

            # Email notification
            if args.notify_email:
                config = NotificationConfig(
                    email_enabled=True,
                    smtp_server=os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
                    smtp_port=int(os.environ.get("SMTP_PORT", "587")),
                    smtp_username=os.environ.get("SMTP_USERNAME", ""),
                    smtp_password=os.environ.get("SMTP_PASSWORD", ""),
                    email_from=os.environ.get("EMAIL_FROM", ""),
                    email_to=[e.strip() for e in args.notify_email.split(",")],
                    report_url=report_url,
                )
                send_notifications(result, tickers_analyzed, config)

            # WhatsApp notification (opens WhatsApp Web)
            if args.notify_whatsapp:
                phone = args.notify_whatsapp.replace("+", "").replace("-", "").replace(" ", "")
                
                # Build detailed message with key indicators for each ticker
                ticker_summaries = []
                dashboards = result.get("dashboards", [])
                for d in dashboards[:10]:  # Limit to 10 for message length
                    rsi = f"RSI:{d.rsi_14:.0f}" if d.rsi_14 else "RSI:--"
                    bb = f"BB:{d.bollinger_percent_above:+.0f}%" if d.bollinger_percent_above else "BB:--"
                    score = f"Score:{d.final_score:.1f}"
                    expr = d.expression
                    chg = f"{d.change_percent:+.1f}%"
                    ticker_summaries.append(f"*{d.ticker}* {chg} | {rsi} | {bb} | {score} | {expr}")
                
                ticker_details = "\n".join(ticker_summaries) if ticker_summaries else "No analysis data"
                
                message = f"""*Short Gainers Report* 📊

{ticker_details}

View Full Reports: {report_url}"""

                if verbose:
                    print(f"Opening WhatsApp Web for {args.notify_whatsapp}...")
                open_whatsapp_web(phone, message)

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
