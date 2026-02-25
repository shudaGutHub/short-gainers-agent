# Short Gainers Agent

An autonomous trading research agent for identifying and ranking short candidates among top percentage gainers.

## Features

- **7-Layer Analysis Pipeline**: Data ingestion, pre-filtering, technical analysis, sentiment/catalyst analysis, ranking, and output generation
- **Rich HTML Dashboards**: Interactive visual reports for each candidate with technical indicators, risk flags, and trade recommendations
- **Batch Processing**: Analyze NASDAQ top gainers or any list of tickers automatically
- **Financial Analysis**: Cash flow, sustainability assessment, and valuation reality checks
- **Risk-Aware Scoring**: Automatic trade expression selection (SHORT_SHARES, BUY_PUTS, PUT_SPREADS, AVOID)

## Setup

```bash
# 1. Clone the project
git clone <repo-url> && cd short-gainers-agent

# 2. Create a virtual environment and install
python -m venv venv
venv\Scripts\activate        # Windows
pip install -e .

# 3. Create .env from the example and add your API keys
copy .env.example .env
# Edit .env and set ALPHA_VANTAGE_API_KEY
# Also set NETLIFY_AUTH_TOKEN if you want auto-deploy
```

## Usage

### Run once (analyze + deploy)

```bash
python -m src.batch_cli --top-gainers --deploy --netlify-site 016ab674-a973-46a3-b463-8db18018b182
```

Or double-click **`run_scheduled.bat`** — it activates the venv, runs analysis, deploys, and logs to `logs/`.

### Auto-refresh every 15 minutes (market hours)

The scheduler runs the analysis automatically Mon-Fri, 9:30 AM - 4:00 PM ET.

**One-time setup** (requires Administrator):

```powershell
# Right-click Start → Terminal (Admin), then:
cd C:\Users\salee\BITBUCKET\short-gainers-agent
powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
```

That's it. The task appears in Windows Task Scheduler as **ShortGainersRefresh**.

**Manage the scheduler:**

| Action | Command |
|--------|---------|
| Check status | Open Task Scheduler → find `ShortGainersRefresh` |
| Run manually | Right-click the task → Run |
| Pause | Right-click the task → Disable |
| Resume | Right-click the task → Enable |
| Remove | `Unregister-ScheduledTask -TaskName ShortGainersRefresh` (Admin PowerShell) |
| View logs | Check `logs/` folder — one file per run |

### Adding tickers to the watchlist

The file `watchlist.txt` contains extra tickers that are always included alongside the NASDAQ top gainers. To add a ticker:

1. Edit `watchlist.txt` — add one ticker per line (lines starting with `#` are ignored)
2. Run the analysis to regenerate reports and deploy:
   - Double-click `run_scheduled.bat`, **or**
   - Run manually: `python -m src.batch_cli --source nasdaq --extra-tickers-file watchlist.txt --deploy --netlify-site 016ab674-a973-46a3-b463-8db18018b182`
3. Reports are deployed to [kaos-short.netlify.app](https://kaos-short.netlify.app)

> **Note:** A `git push` alone does NOT update the live site. The site is not built by Netlify — the analysis runs locally and the generated HTML is deployed to Netlify. You must run `run_scheduled.bat` (or wait for the next scheduled run) for changes to appear.

### Other CLI examples

```bash
# Specific tickers
python -m src.batch_cli --tickers TCGL,AAPL,MSFT

# With known change percentages
python -m src.batch_cli --tickers TCGL,AAPL --changes 941,5

# Limit results, higher threshold
python -m src.batch_cli --top-gainers --max 10 --min-change 20

# Skip financials for faster analysis
python -m src.batch_cli --tickers TCGL --no-financials

# Multi-source with watchlist
python -m src.batch_cli --source nasdaq,watchlist --watchlist ./tickers.csv
```

## Output

**Live dashboard:** [kaos-short.netlify.app](https://kaos-short.netlify.app)

Reports are generated to `reports/YYYY-MM-DD/` and deployed to Netlify. Each run shows a "Last Updated" timestamp on the page.

1. **Index Page** (`index.html`): Summary table of all candidates sorted by score
2. **Individual Dashboards** (`TICKER.html`): Rich visual analysis for each ticker including:
   - Price data and technical indicators (RSI, Bollinger Bands, ATR, MACD)
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
short-gainers-agent/
├── watchlist.txt              # Extra tickers always included in analysis
├── run_scheduled.bat          # Run analysis + deploy (double-click or scheduled)
├── setup_scheduler.ps1        # One-time: register Windows Task Scheduler job
├── src/
│   ├── batch_cli.py           # Command-line interface
│   ├── batch_processor.py     # Batch analysis engine
│   ├── dashboard_generator.py # HTML report generator
│   ├── deploy.py              # Netlify deployment
│   ├── pipeline.py            # Main orchestration
│   ├── clients/               # API clients
│   ├── ingest/                # Data ingestion (NASDAQ, watchlists, screeners)
│   ├── technicals/            # Technical analysis
│   ├── filters/               # Pre-filtering
│   ├── sentiment/             # Catalyst analysis
│   ├── ranking/               # Scoring logic
│   ├── output/                # Output formatting
│   └── models/                # Data models
├── tests/                     # Unit and integration tests
├── reports/                   # Generated reports (gitignored)
└── logs/                      # Scheduler run logs (gitignored)
```

## Requirements

- Python 3.11+
- Windows (for scheduled auto-refresh; analysis works on any OS)
- Alpha Vantage API key ([get one free](https://www.alphavantage.co/support/#api-key))
- Netlify CLI + auth token (for auto-deploy)

## Configuration

All config lives in `.env` (copy from `.env.example`):

```bash
# Required
ALPHA_VANTAGE_API_KEY=your_key_here

# Required for deploy
NETLIFY_AUTH_TOKEN=your_token_here

# Optional (for Claude-based sentiment analysis)
ANTHROPIC_API_KEY=your_key_here
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

## Disclaimer

This is research software only, not investment advice. Trading involves substantial risk of loss.
