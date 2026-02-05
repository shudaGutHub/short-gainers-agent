#!/usr/bin/env python3
"""
Example: Batch Analysis Usage

This script demonstrates how to use the batch analysis functionality
to generate dashboards for multiple tickers.
"""

import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.batch_processor import (
    BatchAnalyzer,
    BatchConfig,
    TickerInput,
    run_batch_analysis,
)


async def example_top_gainers():
    """Example: Analyze top NASDAQ gainers."""
    print("=" * 60)
    print("Example 1: Analyze Top Gainers")
    print("=" * 60)
    
    result = await run_batch_analysis(
        use_top_gainers=True,
        output_dir="./reports/top_gainers",
        max_tickers=10,
        min_change=15.0,  # Only analyze stocks up 15%+
        include_financials=True,
        verbose=True
    )
    
    print(f"\nGenerated {result['count']} reports in {result['output_dir']}")
    return result


async def example_manual_tickers():
    """Example: Analyze specific tickers."""
    print("\n" + "=" * 60)
    print("Example 2: Analyze Specific Tickers")
    print("=" * 60)
    
    # You can specify tickers as:
    # 1. Simple strings
    # 2. TickerInput objects with additional data
    # 3. Dicts with ticker, change_percent, current_price
    
    tickers = [
        # Simple string - will fetch all data
        "AAPL",
        
        # With known change percentage
        {"ticker": "MSFT", "change_percent": 2.5},
        
        # With change and price
        TickerInput(ticker="NVDA", change_percent=5.0, current_price=500.0),
    ]
    
    result = await run_batch_analysis(
        tickers=tickers,
        output_dir="./reports/manual",
        include_financials=True,
        verbose=True
    )
    
    print(f"\nGenerated {result['count']} reports in {result['output_dir']}")
    return result


async def example_custom_config():
    """Example: Using custom configuration."""
    print("\n" + "=" * 60)
    print("Example 3: Custom Configuration")
    print("=" * 60)
    
    # Get API key
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        print("Set ALPHA_VANTAGE_API_KEY environment variable")
        return None
    
    # Create custom config
    config = BatchConfig(
        output_dir="./reports/custom",
        max_tickers=5,
        min_change_percent=10.0,
        include_financials=False,  # Skip financials for speed
        generate_index=True,
        verbose=True
    )
    
    # Create analyzer
    analyzer = BatchAnalyzer(api_key, config)
    
    # Define tickers
    tickers = [
        TickerInput("TCGL", 941.0, 90.90),
        TickerInput("AAPL", 1.5),
    ]
    
    # Run analysis
    print("Analyzing tickers...")
    dashboards = await analyzer.analyze_tickers(tickers)
    
    # Generate reports
    print("Generating reports...")
    result = analyzer.generate_reports(dashboards)
    
    print(f"\nGenerated {result['count']} reports in {result['output_dir']}")
    return result


async def example_from_file():
    """Example: Load tickers from a file."""
    print("\n" + "=" * 60)
    print("Example 4: Load from File")
    print("=" * 60)
    
    # Create example ticker file
    ticker_file = "./example_tickers.txt"
    
    with open(ticker_file, "w") as f:
        f.write("""# Example ticker file
# Format: TICKER,change_percent,price (change and price are optional)
AAPL,2.5,180.00
MSFT,1.8
GOOGL
NVDA,3.2,500.00
""")
    
    print(f"Created example file: {ticker_file}")
    
    # Read tickers from file
    tickers = []
    with open(ticker_file, "r") as f:
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
    
    print(f"Loaded {len(tickers)} tickers from file")
    
    # Run analysis
    result = await run_batch_analysis(
        tickers=tickers,
        output_dir="./reports/from_file",
        include_financials=True,
        verbose=True
    )
    
    print(f"\nGenerated {result['count']} reports in {result['output_dir']}")
    
    # Cleanup
    os.remove(ticker_file)
    
    return result


async def main():
    """Run all examples."""
    print("Short Gainers Batch Analysis Examples")
    print("=" * 60)
    print()
    
    # Check for API key
    if not os.environ.get("ALPHA_VANTAGE_API_KEY"):
        print("WARNING: ALPHA_VANTAGE_API_KEY not set")
        print("Set this environment variable to run the examples")
        print()
        print("Example:")
        print("  export ALPHA_VANTAGE_API_KEY=your_key_here")
        print("  python examples/batch_analysis_example.py")
        return
    
    # Run examples (uncomment the ones you want to run)
    
    # Example 1: Top gainers
    # await example_top_gainers()
    
    # Example 2: Manual tickers
    await example_manual_tickers()
    
    # Example 3: Custom config
    # await example_custom_config()
    
    # Example 4: From file
    # await example_from_file()
    
    print("\n" + "=" * 60)
    print("All examples complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
