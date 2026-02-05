"""
Dashboard Generator Module
Generates rich HTML dashboards for short candidate analysis.
Can process individual tickers or batch lists from NASDAQ movers.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import html


@dataclass
class FinancialData:
    """Financial statement data for a ticker."""
    # Income Statement
    revenue_ttm: Optional[float] = None
    revenue_prior_year: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    ebitda: Optional[float] = None
    
    # Cash Flow
    operating_cash_flow: Optional[float] = None
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    capex: Optional[float] = None
    
    # Balance Sheet
    cash: Optional[float] = None
    total_debt: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    shareholders_equity: Optional[float] = None
    shares_outstanding: Optional[float] = None
    
    # Derived
    revenue_growth: Optional[float] = None
    price_to_sales: Optional[float] = None
    is_profitable: bool = False
    currency: str = "USD"


@dataclass
class DashboardData:
    """All data needed to generate a dashboard."""
    # Basic info
    ticker: str
    company_name: str
    exchange: str
    sector: str
    industry: str
    
    # Price data
    current_price: float
    prior_close: float
    change_percent: float
    intraday_high: float
    intraday_low: float
    volume: int
    avg_volume: int
    week_52_high: float
    week_52_low: float
    
    # Technical indicators
    rsi_14: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None
    bollinger_percent_above: Optional[float] = None
    atr_14: Optional[float] = None
    atr_prior: Optional[float] = None
    
    # Risk flags
    risk_flags: list = None
    composite_risk: str = "MEDIUM"
    
    # Catalyst/Sentiment
    catalyst_type: str = "UNKNOWN"
    has_fundamental_catalyst: bool = False
    company_statement: Optional[str] = None
    exchange_inquiry: bool = False
    
    # Scoring
    technical_score: float = 0.0
    sentiment_adjustment: float = 0.0
    risk_penalties: dict = None
    final_score: float = 0.0
    expression: str = "AVOID"
    
    # Financial data
    financials: Optional[FinancialData] = None
    
    # Key levels
    key_levels: dict = None
    
    # Timeline events
    timeline_events: list = None
    
    # Metadata
    analysis_date: str = None
    ipo_date: Optional[str] = None
    
    def __post_init__(self):
        if self.risk_flags is None:
            self.risk_flags = []
        if self.risk_penalties is None:
            self.risk_penalties = {}
        if self.key_levels is None:
            self.key_levels = {}
        if self.timeline_events is None:
            self.timeline_events = []
        if self.analysis_date is None:
            self.analysis_date = datetime.now().strftime("%Y-%m-%d")


def generate_dashboard_html(data: DashboardData) -> str:
    """Generate a complete HTML dashboard for a ticker."""
    
    # Calculate derived values
    volume_ratio = data.volume / data.avg_volume if data.avg_volume > 0 else 0
    off_high_pct = ((data.current_price - data.intraday_high) / data.intraday_high * 100) if data.intraday_high > 0 else 0
    
    # RSI gauge width
    rsi_width = min(99, data.rsi_14) if data.rsi_14 else 50
    
    # Bollinger gauge width
    bb_width = min(99, max(1, 50 + (data.bollinger_percent_above or 0))) if data.bollinger_percent_above else 50
    
    # ATR expansion
    atr_expansion = data.atr_14 / data.atr_prior if data.atr_prior and data.atr_prior > 0 else 1
    
    # Risk flags HTML
    risk_flags_html = ""
    for flag in data.risk_flags:
        flag_class = "red" if flag in ["HIGH_SQUEEZE", "EXTREME_VOLATILITY", "MICROCAP"] else "yellow"
        risk_flags_html += f'<span class="flag {flag_class}">{html.escape(flag)}</span>\n'
    
    # Risk penalties HTML
    penalties_html = ""
    for penalty_name, penalty_value in data.risk_penalties.items():
        penalties_html += f'''<div class="metric-row">
                    <span class="metric-label">{html.escape(penalty_name)}</span>
                    <span class="metric-value danger">{penalty_value:+.1f}</span>
                </div>\n'''
    
    # Key levels HTML
    levels_html = ""
    level_icons = {
        "resistance": "red_circle",
        "current": "round_pushpin", 
        "psychological": "yellow_circle",
        "support": "green_circle",
        "prior_close": "green_circle",
        "average": "green_circle",
        "low": "green_circle"
    }
    for level_name, level_price in sorted(data.key_levels.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0):
        icon = "&#128308;" if "high" in level_name.lower() or "resist" in level_name.lower() else (
            "&#128205;" if "current" in level_name.lower() else (
                "&#128993;" if "psych" in level_name.lower() else "&#128994;"
            )
        )
        levels_html += f'''<tr>
                        <td>{icon} {html.escape(level_name)}</td>
                        <td class="price">${level_price:,.2f}</td>
                    </tr>\n'''
    
    # Timeline HTML
    timeline_html = ""
    for event in data.timeline_events:
        event_date = event.get("date", "")
        event_text = event.get("event", "")
        event_style = 'style="color: #ef4444;"' if event.get("highlight") else ""
        timeline_html += f'''<div class="timeline-item">
                        <div class="timeline-date">{html.escape(event_date)}</div>
                        <div class="timeline-event" {event_style}>{html.escape(event_text)}</div>
                    </div>\n'''
    
    # Financial section HTML
    financials_html = ""
    if data.financials:
        f = data.financials
        
        # Format currency values
        def fmt_currency(val, currency="S$"):
            if val is None:
                return "N/A"
            if abs(val) >= 1_000_000:
                return f"{currency}{val/1_000_000:.1f}M"
            elif abs(val) >= 1_000:
                return f"{currency}{val/1_000:.0f}K"
            else:
                return f"{currency}{val:,.0f}"
        
        def fmt_pct(val):
            if val is None:
                return "N/A"
            return f"{val:.1f}%"
        
        # Determine value classes
        ni_class = "success" if f.net_income and f.net_income > 0 else "danger"
        ocf_class = "success" if f.operating_cash_flow and f.operating_cash_flow > 0 else "danger"
        growth_class = "success" if f.revenue_growth and f.revenue_growth > 0 else "danger"
        
        # Calculate implied market cap and P/S
        implied_mkt_cap = data.current_price * (f.shares_outstanding or 0)
        ps_ratio = implied_mkt_cap / f.revenue_ttm if f.revenue_ttm and f.revenue_ttm > 0 else None
        
        financials_html = f'''
        <!-- Financial Analysis Section -->
        <div class="grid" style="margin-top: 20px;">
            <!-- Cash Flow Analysis -->
            <div class="card" style="grid-column: span 2;">
                <div class="card-title">&#128176; Cash Flow & Financial Sustainability</div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">
                    <div>
                        <h4 style="color: #60a5fa; margin-bottom: 10px;">Income Statement</h4>
                        <div class="metric-row">
                            <span class="metric-label">Revenue (TTM)</span>
                            <span class="metric-value">{fmt_currency(f.revenue_ttm, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Gross Margin</span>
                            <span class="metric-value">{fmt_pct(f.gross_margin)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Net Income</span>
                            <span class="metric-value {ni_class}">{fmt_currency(f.net_income, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">EBITDA</span>
                            <span class="metric-value">{fmt_currency(f.ebitda, f.currency)}</span>
                        </div>
                    </div>
                    <div>
                        <h4 style="color: #60a5fa; margin-bottom: 10px;">Cash Flow</h4>
                        <div class="metric-row">
                            <span class="metric-label">Operating CF</span>
                            <span class="metric-value {ocf_class}">{fmt_currency(f.operating_cash_flow, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Investing CF</span>
                            <span class="metric-value">{fmt_currency(f.investing_cash_flow, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Financing CF</span>
                            <span class="metric-value">{fmt_currency(f.financing_cash_flow, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">CapEx</span>
                            <span class="metric-value">{fmt_currency(f.capex, f.currency)}</span>
                        </div>
                    </div>
                    <div>
                        <h4 style="color: #60a5fa; margin-bottom: 10px;">Balance Sheet</h4>
                        <div class="metric-row">
                            <span class="metric-label">Cash</span>
                            <span class="metric-value">{fmt_currency(f.cash, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Total Debt</span>
                            <span class="metric-value warning">{fmt_currency(f.total_debt, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Equity</span>
                            <span class="metric-value">{fmt_currency(f.shareholders_equity, f.currency)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">Shares Out</span>
                            <span class="metric-value">{f.shares_outstanding/1_000_000:.1f}M</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Valuation Reality Check -->
            <div class="card">
                <div class="card-title">&#127917; Valuation Reality Check</div>
                <div class="metric-row">
                    <span class="metric-label">Current Price</span>
                    <span class="metric-value danger">${data.current_price:.2f}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Implied Market Cap</span>
                    <span class="metric-value danger">${implied_mkt_cap/1_000_000:.0f}M</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Revenue (TTM)</span>
                    <span class="metric-value">{fmt_currency(f.revenue_ttm, "$")}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Price/Sales</span>
                    <span class="metric-value {"danger" if ps_ratio and ps_ratio > 50 else "warning" if ps_ratio and ps_ratio > 15 else ""}">{f"{ps_ratio:.0f}x" if ps_ratio else "N/A"}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Profitable?</span>
                    <span class="metric-value {"success" if f.is_profitable else "danger"}">{"YES" if f.is_profitable else "NO"}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Revenue Growth</span>
                    <span class="metric-value {growth_class}">{fmt_pct(f.revenue_growth)}</span>
                </div>
            </div>
            
            <!-- Sustainability Assessment -->
            <div class="card">
                <div class="card-title">&#128202; Sustainability</div>
                <div class="metric-row">
                    <span class="metric-label">Business Model</span>
                    <span class="metric-value">{html.escape(data.industry[:20] if data.industry else "Unknown")}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Scale</span>
                    <span class="metric-value {"danger" if f.revenue_ttm and f.revenue_ttm < 10_000_000 else "warning" if f.revenue_ttm and f.revenue_ttm < 100_000_000 else "success"}">{
                        "MICRO" if f.revenue_ttm and f.revenue_ttm < 10_000_000 else 
                        "SMALL" if f.revenue_ttm and f.revenue_ttm < 100_000_000 else 
                        "MID" if f.revenue_ttm and f.revenue_ttm < 1_000_000_000 else "LARGE"
                    }</span>
                </div>
                {"<div style='background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; border-radius: 8px; padding: 12px; margin-top: 15px;'><strong style='color: #ef4444;'>&#9888; VALUATION CONCERN:</strong><p style='color: #fca5a5; margin-top: 5px; font-size: 0.9rem;'>P/S ratio of " + f"{ps_ratio:.0f}x" + " is extremely elevated for this type of company.</p></div>" if ps_ratio and ps_ratio > 50 else ""}
            </div>
        </div>
        '''
    
    # Expression color
    expr_color = {
        "BUY_PUTS": "#fbbf24",
        "PUT_SPREADS": "#f97316",
        "SHORT_SHARES": "#22c55e",
        "AVOID": "#ef4444"
    }.get(data.expression, "#888")
    
    # Build final HTML
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(data.ticker)} Short Analysis - {data.analysis_date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        
        .header {{
            text-align: center;
            padding: 30px;
            background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
            border-radius: 16px;
            margin-bottom: 20px;
        }}
        .ticker {{ font-size: 3rem; font-weight: 800; }}
        .company {{ font-size: 1.2rem; opacity: 0.9; margin-top: 5px; }}
        .price-change {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-top: 15px;
        }}
        .price-current {{ font-size: 1.5rem; opacity: 0.9; }}
        
        .score-card {{
            background: linear-gradient(135deg, #1e40af 0%, #1e3a8a 100%);
            border-radius: 16px;
            padding: 30px;
            text-align: center;
            margin-bottom: 20px;
        }}
        .score-value {{ font-size: 5rem; font-weight: 800; }}
        .score-label {{ font-size: 1.2rem; opacity: 0.8; }}
        .expression {{
            display: inline-block;
            background: {expr_color};
            color: #000;
            padding: 10px 30px;
            border-radius: 30px;
            font-weight: 700;
            font-size: 1.3rem;
            margin-top: 15px;
        }}
        
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
        
        .card {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
        }}
        .card-title {{
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #888;
            margin-bottom: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            padding-bottom: 10px;
        }}
        
        .metric-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .metric-label {{ color: #aaa; }}
        .metric-value {{ font-weight: 600; }}
        .metric-value.danger {{ color: #ef4444; }}
        .metric-value.warning {{ color: #fbbf24; }}
        .metric-value.success {{ color: #22c55e; }}
        
        .risk-flags {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 10px;
        }}
        .flag {{
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        .flag.red {{ background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444; }}
        .flag.yellow {{ background: rgba(251, 191, 36, 0.2); color: #fbbf24; border: 1px solid #fbbf24; }}
        .flag.green {{ background: rgba(34, 197, 94, 0.2); color: #22c55e; border: 1px solid #22c55e; }}
        
        .gauge {{
            height: 20px;
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }}
        .gauge-fill {{
            height: 100%;
            border-radius: 10px;
            transition: width 0.5s;
        }}
        .gauge-fill.extreme {{ background: linear-gradient(90deg, #ef4444, #dc2626); }}
        .gauge-fill.high {{ background: linear-gradient(90deg, #f97316, #ea580c); }}
        .gauge-fill.medium {{ background: linear-gradient(90deg, #fbbf24, #f59e0b); }}
        
        .level-table {{ width: 100%; }}
        .level-table td {{ padding: 8px 5px; }}
        .level-table .price {{ text-align: right; font-family: monospace; font-size: 1.1rem; }}
        
        .warning-box {{
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid #ef4444;
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }}
        .warning-title {{
            color: #ef4444;
            font-weight: 700;
            font-size: 1.1rem;
            margin-bottom: 10px;
        }}
        .warning-list {{ list-style: none; }}
        .warning-list li {{
            padding: 8px 0;
            border-bottom: 1px solid rgba(239, 68, 68, 0.2);
            color: #fca5a5;
        }}
        .warning-list li:last-child {{ border-bottom: none; }}
        
        .catalyst-box {{
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid #22c55e;
            border-radius: 8px;
            padding: 15px;
            margin-top: 15px;
        }}
        .catalyst-type {{
            font-weight: 700;
            color: #22c55e;
        }}
        
        .timeline {{
            position: relative;
            padding-left: 30px;
        }}
        .timeline::before {{
            content: '';
            position: absolute;
            left: 10px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: rgba(255,255,255,0.2);
        }}
        .timeline-item {{
            position: relative;
            padding: 10px 0;
        }}
        .timeline-item::before {{
            content: '';
            position: absolute;
            left: -24px;
            top: 15px;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #667eea;
        }}
        .timeline-date {{ color: #888; font-size: 0.85rem; }}
        .timeline-event {{ margin-top: 3px; }}
        
        .footer {{
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.85rem;
            margin-top: 30px;
        }}
        
        .back-link {{
            display: inline-block;
            margin-bottom: 20px;
            color: #60a5fa;
            text-decoration: none;
        }}
        .back-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <a href="index.html" class="back-link">&larr; Back to Summary</a>
        
        <!-- Header -->
        <div class="header">
            <div class="ticker">{html.escape(data.ticker)}</div>
            <div class="company">{html.escape(data.company_name)} &bull; {html.escape(data.exchange)}</div>
            <div class="price-change">{data.change_percent:+.2f}%</div>
            <div class="price-current">${data.current_price:.2f} (from ${data.prior_close:.2f})</div>
        </div>
        
        <!-- Score Card -->
        <div class="score-card">
            <div class="score-label">SHORT SCORE</div>
            <div class="score-value">{data.final_score:.1f}</div>
            <div class="score-label">out of 10</div>
            <div class="expression">&#127919; {data.expression.replace("_", " ")}</div>
        </div>
        
        <!-- Main Grid -->
        <div class="grid">
            <!-- Price Data -->
            <div class="card">
                <div class="card-title">&#128202; Price Data</div>
                <div class="metric-row">
                    <span class="metric-label">Current Price</span>
                    <span class="metric-value">${data.current_price:.2f}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Prior Close</span>
                    <span class="metric-value">${data.prior_close:.2f}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Intraday High</span>
                    <span class="metric-value danger">${data.intraday_high:.2f}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Intraday Low</span>
                    <span class="metric-value">${data.intraday_low:.2f}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Volume</span>
                    <span class="metric-value warning">{data.volume/1_000_000:.1f}M ({volume_ratio:.1f}x avg)</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">52-Week Range</span>
                    <span class="metric-value">${data.week_52_low:.2f} - ${data.week_52_high:.2f}</span>
                </div>
            </div>
            
            <!-- Technical Indicators -->
            <div class="card">
                <div class="card-title">&#128200; Technical Indicators</div>
                <div class="metric-row">
                    <span class="metric-label">RSI (14)</span>
                    <span class="metric-value {"danger" if data.rsi_14 and data.rsi_14 > 80 else "warning" if data.rsi_14 and data.rsi_14 > 70 else ""}">{data.rsi_14:.2f if data.rsi_14 else "N/A"}</span>
                </div>
                <div class="gauge"><div class="gauge-fill {"extreme" if data.rsi_14 and data.rsi_14 > 80 else "high" if data.rsi_14 and data.rsi_14 > 70 else "medium"}" style="width: {rsi_width}%"></div></div>
                
                <div class="metric-row">
                    <span class="metric-label">Bollinger Position</span>
                    <span class="metric-value {"danger" if data.bollinger_percent_above and data.bollinger_percent_above > 50 else "warning" if data.bollinger_percent_above and data.bollinger_percent_above > 20 else ""}">{f"{data.bollinger_percent_above:.0f}% Above Upper" if data.bollinger_percent_above and data.bollinger_percent_above > 0 else "Within Bands" if data.bollinger_percent_above is not None else "N/A"}</span>
                </div>
                <div class="gauge"><div class="gauge-fill {"extreme" if data.bollinger_percent_above and data.bollinger_percent_above > 50 else "high" if data.bollinger_percent_above and data.bollinger_percent_above > 20 else "medium"}" style="width: {bb_width}%"></div></div>
                
                <div class="metric-row">
                    <span class="metric-label">ATR (14)</span>
                    <span class="metric-value {"danger" if atr_expansion > 5 else "warning" if atr_expansion > 2 else ""}">${data.atr_14:.2f if data.atr_14 else 0:.2f} ({atr_expansion:.1f}x expansion)</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Off Intraday High</span>
                    <span class="metric-value warning">{off_high_pct:.1f}%</span>
                </div>
            </div>
            
            <!-- Risk Assessment -->
            <div class="card">
                <div class="card-title">&#9888;&#65039; Risk Flags</div>
                <div class="risk-flags">
                    {risk_flags_html}
                </div>
                <div class="metric-row" style="margin-top: 20px;">
                    <span class="metric-label">Exchange</span>
                    <span class="metric-value {"warning" if "NASDAQ" not in data.exchange.upper() else ""}">{html.escape(data.exchange)}</span>
                </div>
                {f'<div class="metric-row"><span class="metric-label">IPO Date</span><span class="metric-value warning">{html.escape(data.ipo_date)}</span></div>' if data.ipo_date else ""}
                <div class="metric-row">
                    <span class="metric-label">Composite Risk</span>
                    <span class="metric-value {"danger" if data.composite_risk == "HIGH" else "warning" if data.composite_risk == "MEDIUM" else "success"}">{data.composite_risk}</span>
                </div>
            </div>
            
            <!-- Catalyst Analysis -->
            <div class="card">
                <div class="card-title">&#128240; Catalyst Analysis</div>
                <div class="metric-row">
                    <span class="metric-label">Classification</span>
                    <span class="metric-value {"success" if not data.has_fundamental_catalyst else "danger"}">{html.escape(data.catalyst_type)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Fundamental Catalyst</span>
                    <span class="metric-value {"danger" if data.has_fundamental_catalyst else "success"}">{"IDENTIFIED" if data.has_fundamental_catalyst else "NONE IDENTIFIED"}</span>
                </div>
                {f'<div class="metric-row"><span class="metric-label">Company Statement</span><span class="metric-value">{html.escape(data.company_statement[:30] + "..." if len(data.company_statement) > 30 else data.company_statement)}</span></div>' if data.company_statement else ""}
                {f'<div class="metric-row"><span class="metric-label">Exchange Inquiry</span><span class="metric-value warning">Yes - unusual activity</span></div>' if data.exchange_inquiry else ""}
                <div class="catalyst-box">
                    <span class="catalyst-type">{"&#10004; FAVORABLE FOR SHORT" if not data.has_fundamental_catalyst else "&#10008; UNFAVORABLE - Fundamental catalyst present"}</span><br>
                    <small>{"No fundamental justification for the move." if not data.has_fundamental_catalyst else "Move may be justified by fundamental news."}</small>
                </div>
            </div>
            
            <!-- Score Breakdown -->
            <div class="card">
                <div class="card-title">&#129518; Score Calculation</div>
                <div class="metric-row">
                    <span class="metric-label">Technical Score</span>
                    <span class="metric-value">+{data.technical_score:.1f}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Sentiment Adjustment</span>
                    <span class="metric-value {"success" if data.sentiment_adjustment > 0 else "danger" if data.sentiment_adjustment < 0 else ""}">{data.sentiment_adjustment:+.1f}</span>
                </div>
                {penalties_html}
                <div class="metric-row" style="border-top: 2px solid rgba(255,255,255,0.2); margin-top: 10px; padding-top: 15px;">
                    <span class="metric-label"><strong>FINAL SCORE</strong></span>
                    <span class="metric-value" style="font-size: 1.5rem; color: #60a5fa;"><strong>{data.final_score:.1f} / 10</strong></span>
                </div>
            </div>
            
            <!-- Key Levels -->
            <div class="card">
                <div class="card-title">&#127919; Key Levels</div>
                <table class="level-table">
                    {levels_html}
                </table>
            </div>
        </div>
        
        {financials_html}
        
        <!-- Warning Box -->
        <div class="warning-box">
            <div class="warning-title">&#128680; CRITICAL WARNINGS - READ BEFORE TRADING</div>
            <ul class="warning-list">
                {"<li><strong>SQUEEZE RISK (SEVERE):</strong> High squeeze potential detected. DO NOT SHORT SHARES DIRECTLY.</li>" if "HIGH_SQUEEZE" in data.risk_flags else ""}
                {"<li><strong>EXTREME VOLATILITY:</strong> Stock showing extreme volatility. Size positions accordingly.</li>" if "EXTREME_VOLATILITY" in data.risk_flags else ""}
                {"<li><strong>MICROCAP:</strong> Low liquidity microcap. Wider spreads and slippage expected.</li>" if "MICROCAP" in data.risk_flags else ""}
                <li><strong>TIMING:</strong> Overextended stocks can stay irrational longer than expected. Size for adverse moves.</li>
                <li><strong>IV CRUSH:</strong> Options premiums may be elevated. Consider spreads to reduce cost.</li>
            </ul>
        </div>
        
        <!-- Trade Structure & Timeline -->
        <div class="grid" style="margin-top: 20px;">
            <div class="card" style="background: linear-gradient(135deg, rgba(251, 191, 36, 0.1), rgba(245, 158, 11, 0.1)); border-color: #fbbf24;">
                <div class="card-title" style="color: #fbbf24;">&#128161; Suggested Trade Structure</div>
                <div class="metric-row">
                    <span class="metric-label">Expression</span>
                    <span class="metric-value" style="color: {expr_color};">{data.expression.replace("_", " ")}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Position Size</span>
                    <span class="metric-value">{"SMALL" if data.composite_risk == "HIGH" else "MODERATE" if data.composite_risk == "MEDIUM" else "NORMAL"}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Stop Trigger</span>
                    <span class="metric-value">New highs above ${data.intraday_high:.2f}</span>
                </div>
            </div>
            
            {f'<div class="card"><div class="card-title">&#128197; Timeline</div><div class="timeline">{timeline_html}</div></div>' if timeline_html else ""}
        </div>
        
        <div class="footer">
            <p>Generated by Short Gainers Agent v0.2.0 | Analysis Date: {data.analysis_date}</p>
            <p style="margin-top: 10px;">&#9888;&#65039; This is research only, not investment advice. Trading involves substantial risk of loss.</p>
        </div>
    </div>
</body>
</html>'''
    
    return html_content


def generate_index_html(candidates: list, analysis_date: str = None) -> str:
    """Generate an index page summarizing all analyzed candidates."""
    
    if analysis_date is None:
        analysis_date = datetime.now().strftime("%Y-%m-%d")
    
    # Sort by score descending
    sorted_candidates = sorted(candidates, key=lambda x: x.final_score, reverse=True)
    
    # Build table rows
    rows_html = ""
    for i, c in enumerate(sorted_candidates, 1):
        score_class = "success" if c.final_score >= 7 else "warning" if c.final_score >= 5 else "danger"
        expr_color = {
            "BUY_PUTS": "#fbbf24",
            "PUT_SPREADS": "#f97316",
            "SHORT_SHARES": "#22c55e",
            "AVOID": "#ef4444"
        }.get(c.expression, "#888")
        
        flags_html = " ".join([f'<span class="flag-mini">{f}</span>' for f in c.risk_flags[:2]])
        
        rows_html += f'''<tr onclick="window.location='{c.ticker}.html'" style="cursor: pointer;">
            <td>{i}</td>
            <td><strong>{html.escape(c.ticker)}</strong></td>
            <td>{html.escape(c.company_name[:25] + "..." if len(c.company_name) > 25 else c.company_name)}</td>
            <td class="{score_class}">{c.final_score:.1f}</td>
            <td style="color: {expr_color};">{c.expression.replace("_", " ")}</td>
            <td class="{"danger" if c.change_percent > 50 else "warning" if c.change_percent > 20 else ""}">{c.change_percent:+.1f}%</td>
            <td>${c.current_price:.2f}</td>
            <td>{c.rsi_14:.1f if c.rsi_14 else "N/A"}</td>
            <td>{flags_html}</td>
        </tr>\n'''
    
    # Statistics
    total = len(candidates)
    actionable = len([c for c in candidates if c.expression != "AVOID"])
    avg_score = sum(c.final_score for c in candidates) / total if total > 0 else 0
    high_squeeze = len([c for c in candidates if "HIGH_SQUEEZE" in c.risk_flags])
    
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Short Gainers Analysis - {analysis_date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        
        .header {{
            text-align: center;
            padding: 30px;
            background: linear-gradient(135deg, #1e40af 0%, #1e3a8a 100%);
            border-radius: 16px;
            margin-bottom: 20px;
        }}
        .header h1 {{ font-size: 2rem; margin-bottom: 10px; }}
        .header p {{ opacity: 0.8; }}
        
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-value {{ font-size: 2rem; font-weight: 700; }}
        .stat-label {{ font-size: 0.85rem; color: #888; margin-top: 5px; }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            overflow: hidden;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        th {{
            background: rgba(255,255,255,0.1);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 1px;
        }}
        tr:hover {{
            background: rgba(255,255,255,0.05);
        }}
        
        .danger {{ color: #ef4444; }}
        .warning {{ color: #fbbf24; }}
        .success {{ color: #22c55e; }}
        
        .flag-mini {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7rem;
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            margin-right: 4px;
        }}
        
        .footer {{
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.85rem;
        }}
        
        .legend {{
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-top: 20px;
            flex-wrap: wrap;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: #888;
        }}
        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>&#128200; Short Gainers Analysis</h1>
            <p>Analysis Date: {analysis_date} | Click any row for detailed analysis</p>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{total}</div>
                <div class="stat-label">Tickers Analyzed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #22c55e;">{actionable}</div>
                <div class="stat-label">Actionable Candidates</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{avg_score:.1f}</div>
                <div class="stat-label">Avg Short Score</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #ef4444;">{high_squeeze}</div>
                <div class="stat-label">High Squeeze Risk</div>
            </div>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Ticker</th>
                    <th>Company</th>
                    <th>Score</th>
                    <th>Expression</th>
                    <th>Change</th>
                    <th>Price</th>
                    <th>RSI</th>
                    <th>Flags</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        
        <div class="legend">
            <div class="legend-item"><div class="legend-dot" style="background: #22c55e;"></div> Score 7+ (Strong)</div>
            <div class="legend-item"><div class="legend-dot" style="background: #fbbf24;"></div> Score 5-7 (Moderate)</div>
            <div class="legend-item"><div class="legend-dot" style="background: #ef4444;"></div> Score &lt;5 (Weak/Avoid)</div>
        </div>
        
        <div class="footer">
            <p>Generated by Short Gainers Agent v0.2.0</p>
            <p style="margin-top: 10px;">&#9888;&#65039; This is research only, not investment advice. Trading involves substantial risk of loss.</p>
        </div>
    </div>
</body>
</html>'''
    
    return html_content
