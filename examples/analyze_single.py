"""Example: Analyze a single symbol."""

import asyncio
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from short_gainers_agent import Agent, Config


console = Console()


def format_score(score: float) -> Text:
    """Format score with color coding."""
    if score >= 7.5:
        color = "green"
    elif score >= 6.0:
        color = "yellow"
    elif score >= 4.0:
        color = "orange1"
    else:
        color = "red"
    return Text(f"{score:.1f}/10", style=f"bold {color}")


def display_result(result):
    """Display analysis result with rich formatting."""
    # Header
    change_color = "green" if result.change >= 0 else "red"
    header = Text()
    header.append(f"{result.symbol}", style="bold white")
    if result.name:
        header.append(f" - {result.name}", style="dim")

    # Build table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    # Price info
    price_text = Text()
    price_text.append(f"${result.price:.2f} ", style="bold")
    price_text.append(f"({result.change:+.2f} / {result.change_percent:+.2f}%)", style=change_color)
    table.add_row("Price", price_text)

    # Score
    table.add_row("Short Score", format_score(result.short_score))

    # Expression
    expr_colors = {"SHORT_SHARES": "green", "BUY_PUTS": "yellow", "PUT_SPREADS": "orange1", "AVOID": "red"}
    expr_text = Text(result.trade_expression.value, style=f"bold {expr_colors.get(result.trade_expression.value, 'white')}")
    table.add_row("Expression", expr_text)

    # Risk flags
    if result.risk_flags:
        flags_text = Text(", ".join(f.value for f in result.risk_flags), style="yellow")
    else:
        flags_text = Text("NONE", style="dim")
    table.add_row("Risk Flags", flags_text)

    # Technicals
    tech = result.technicals
    if tech.rsi_14:
        rsi_color = "red" if tech.rsi_14 > 70 else "white"
        table.add_row("RSI (14)", Text(f"{tech.rsi_14:.1f}", style=rsi_color))
    if tech.bb_position is not None:
        bb_color = "red" if tech.bb_position > 0 else "white"
        table.add_row("Bollinger", Text(f"{tech.bb_position:+.1f}% vs upper", style=bb_color))

    # Score breakdown
    breakdown = result.score_breakdown
    breakdown_text = Text()
    breakdown_text.append(f"Tech: {breakdown.technical_score:.1f}  ")
    breakdown_text.append(f"Sent: {breakdown.sentiment_adjustment:+.1f}  ", style="cyan")
    breakdown_text.append(f"Risk: {breakdown.risk_penalty:+.1f}", style="red")
    table.add_row("Breakdown", breakdown_text)

    # Create panel with decorative border
    panel = Panel(
        table,
        title=header,
        subtitle=f"Generated: {result.generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        border_style="blue",
    )
    console.print(panel)

    # Summary line
    console.print()
    console.rule("[bold blue]Summary[/bold blue]")
    console.print(f"  {result.to_summary()}")
    console.rule(style="blue")


async def main(symbol: str):
    # Initialize with custom config (or use defaults)
    config = Config()

    # Use agent as async context manager
    async with Agent(config) as agent:
        # Analyze the specified symbol
        result = await agent.analyze(symbol)
        display_result(result)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_single.py <SYMBOL>")
        sys.exit(1)
    symbol = sys.argv[1].upper()
    asyncio.run(main(symbol))
