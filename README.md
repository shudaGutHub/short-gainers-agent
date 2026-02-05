# Short Gainers Agent

An autonomous trading research agent for identifying and ranking short candidates among top percentage gainers.

## Features

- **7-Layer Analysis Pipeline**: Data ingestion, pre-filtering, technical analysis, sentiment/catalyst analysis, ranking, and output generation
- **Rich HTML Dashboards**: Interactive visual reports for each candidate with technical indicators, risk flags, and trade recommendations
- **Batch Processing**: Analyze NASDAQ top gainers or any list of tickers automatically
- **Financial Analysis**: Cash flow, sustainability assessment, and valuation reality checks
- **Risk-Aware Scoring**: Automatic trade expression selection (SHORT_SHARES, BUY_PUTS, PUT_SPREADS, AVOID)

## Installation

```bash
# Clone or download the project
cd short_gainers_agent

# Install dependencies
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"

# Set your API key
export ALPHA_VANTAGE_API_KEY=your_key_here
```

## Quick Start

### 1. Analyze Top Gainers (CLI)

```bash
# Analyze today's top NASDAQ gainers
short-gainers-batch --top-gainers

# Limit to 10 tickers with 20%+ change
short-gainers-batch --top-gainers --max 10 --min-change 20

# Custom output directory
short-gainers-batch --top-gainers -o ./my_reports
```

### 2. Analyze Specific Tickers (CLI)

```bash
# Simple ticker list
short-gainers-batch --tickers TCGL,AAPL,MSFT

# With known change percentages
short-gainers-batch --tickers TCGL,AAPL --changes 941,5

# With prices too
short-gainers-batch --tickers TCGL,AAPL --changes 941,5 --prices 90.90,180.00

# Skip financials for faster analysis
short-gainers-batch --tickers TCGL --no-financials
```

### 3. Analyze from File (CLI)

Create a file `tickers.txt`:
```
# Format: TICKER,change_percent,price
TCGL,941,90.90
AAPL,2.5,180.00
MSFT
```

Then run:
```bash
short-gainers-batch --file tickers.txt
```

### 4. Programmatic Usage (Python)

```python
import asyncio
from src.batch_processor import run_batch_analysis, TickerInput

async def main():
    # Analyze top gainers
    result = await run_batch_analysis(
        use_top_gainers=True,
        output_dir="./reports",
        max_tickers=20,
        min_change=10.0,
        include_financials=True
    )
    
    # Or analyze specific tickers
    tickers = [
        TickerInput("TCGL", 941.0, 90.90),
        TickerInput("AAPL", 2.5),
        "MSFT",  # Simple string also works
    ]
    
    result = await run_batch_analysis(
        tickers=tickers,
        output_dir="./reports/manual"
    )
    
    print(f"Generated {result['count']} reports")
    print(f"Index page: {result['output_dir']}/index.html")

asyncio.run(main())
```

## Output

The agent generates:

1. **Index Page** (`index.html`): Summary table of all candidates sorted by score
2. **Individual Dashboards** (`TICKER.html`): Rich visual analysis for each ticker including:
   - Price data and technical indicators (RSI, Bollinger Bands, ATR)
   - Risk flags and composite risk assessment
   - Catalyst/sentiment analysis
   - Score calculation breakdown
   - Cash flow and financial sustainability
   - Valuation reality check
   - Trade structure recommendations
   - Key levels and warnings

## Scoring System

| Score | Rating | Action |
|-------|--------|--------|
| 8.0 - 10.0 | Excellent | Strong short candidate |
| 6.0 - 7.9 | Good | Viable short candidate |
| 4.0 - 5.9 | Moderate | Proceed with caution |
| 0.0 - 3.9 | Poor | Avoid |

## Trade Expression Logic

- **SHORT_SHARES**: Clean setup, moderate volatility, no squeeze flags
- **BUY_PUTS**: High squeeze risk but attractive technicals
- **PUT_SPREADS**: Extreme volatility, need defined risk
- **AVOID**: Fundamental catalyst present, dangerous setup, or low score

## Risk Flags

| Flag | Description |
|------|-------------|
| `HIGH_SQUEEZE` | Recent IPO, low float, extreme move potential |
| `EXTREME_VOLATILITY` | ATR expansion >5x, single-day move >50% |
| `MICROCAP` | Market cap <$300M |
| `LOW_LIQUIDITY` | Average volume <100K |
| `NON_NASDAQ` | Listed on non-NASDAQ exchange |

## Project Structure

```
short_gainers_agent/
├── src/
│   ├── batch_processor.py     # Batch analysis engine
│   ├── batch_cli.py           # Command-line interface for batch
│   ├── dashboard_generator.py # HTML report generator
│   ├── pipeline.py            # Main orchestration
│   ├── main.py                # Original CLI
│   ├── clients/               # API clients
│   ├── ingest/                # Data ingestion
│   ├── technicals/            # Technical analysis
│   ├── filters/               # Pre-filtering
│   ├── sentiment/             # Catalyst analysis
│   ├── ranking/               # Scoring logic
│   ├── output/                # Output formatting
│   └── models/                # Data models
├── tests/                     # Unit and integration tests
├── examples/                  # Example scripts
└── reports/                   # Generated reports (gitignored)
```

## Requirements

- Python 3.11+
- Alpha Vantage API key (free tier works)
- Dependencies: aiohttp, httpx, pandas, numpy, pydantic

## Configuration

Set environment variables:

```bash
# Required
export ALPHA_VANTAGE_API_KEY=your_key_here

# Optional (for Claude-based sentiment analysis)
export ANTHROPIC_API_KEY=your_key_here
```

## Development

```bash
# Run tests
pytest tests/ -v

# Run specific test file
pytest tests/test_batch.py -v

# Lint
ruff check src/
```

## Implementation Status

| Phase | Module | Status |
|-------|--------|--------|
| 1 | Config, Models, Clients | Done |
| 2 | Ingest (gainers, price, fundamentals) | Done |
| 3 | Technicals (indicators, scoring) | Done |
| 4 | Filters (prefilter, risk flags) | Done |
| 5 | Sentiment (catalyst analysis) | Done |
| 6 | Ranking + Output | Done |
| 7 | Orchestration + CLI | Done |
| 8 | Integration Tests | Done |
| 9 | Batch Processing + Dashboards | Done |

**Total: ~6,500 lines of code, 116+ tests**

## Disclaimer

This is research software only, not investment advice. Trading involves substantial risk of loss. Always do your own due diligence and consult with a qualified financial advisor.
