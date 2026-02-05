"""Command-line interface for Short Gainers Agent."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from .agent import Agent
from .config import get_config
from .data.models import AnalysisResult, RiskFlag, TradeExpression
from .output.dashboard import DashboardGenerator

console = Console()

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def setup_logging(verbose: bool):
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.getLogger("short_gainers_agent").setLevel(level)


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
    return Text(f"{score:.1f}", style=f"bold {color}")


def format_expression(expr: TradeExpression) -> Text:
    """Format trade expression with color coding."""
    colors = {
        TradeExpression.SHORT_SHARES: "green",
        TradeExpression.BUY_PUTS: "yellow",
        TradeExpression.PUT_SPREADS: "orange1",
        TradeExpression.AVOID: "red",
    }
    return Text(expr.value, style=f"bold {colors.get(expr, 'white')}")


def format_flags(flags: list[RiskFlag]) -> Text:
    """Format risk flags with color coding."""
    if not flags:
        return Text("NONE", style="dim")

    text = Text()
    for i, flag in enumerate(flags):
        if i > 0:
            text.append(", ")
        color = "red" if flag in [RiskFlag.HIGH_SQUEEZE, RiskFlag.NEW_LISTING] else "yellow"
        text.append(flag.value, style=color)
    return text


def display_result(result: AnalysisResult):
    """Display single analysis result in rich format."""
    # Header
    change_color = "green" if result.change >= 0 else "red"
    header = Text()
    header.append(f"{result.symbol}", style="bold white")
    if result.name:
        header.append(f" - {result.name}", style="dim")

    # Price info
    price_text = Text()
    price_text.append(f"${result.price:.2f} ", style="bold")
    price_text.append(
        f"({result.change:+.2f} / {result.change_percent:+.2f}%)",
        style=change_color,
    )

    # Build table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    table.add_row("Price", price_text)
    table.add_row("Short Score", format_score(result.short_score))
    table.add_row("Expression", format_expression(result.trade_expression))
    table.add_row("Risk Flags", format_flags(result.risk_flags))

    # Technicals
    tech = result.technicals
    if tech.rsi_14:
        rsi_color = "red" if tech.rsi_14 > 70 else "white"
        table.add_row("RSI (14)", Text(f"{tech.rsi_14:.1f}", style=rsi_color))
    if tech.bb_position is not None:
        bb_color = "red" if tech.bb_position > 0 else "white"
        table.add_row("Bollinger", Text(f"{tech.bb_position:+.1f}% vs upper", style=bb_color))

    # Catalyst
    table.add_row("Catalyst", Text(result.catalyst.classification.value, style="cyan"))

    # Score breakdown
    breakdown = result.score_breakdown
    breakdown_text = Text()
    breakdown_text.append(f"Tech: {breakdown.technical_score:.1f} ")
    breakdown_text.append(f"Sent: {breakdown.sentiment_adjustment:+.1f} ", style="cyan")
    breakdown_text.append(f"Risk: {breakdown.risk_penalty:+.1f}", style="red")
    table.add_row("Breakdown", breakdown_text)

    # Warnings
    if result.warnings:
        warnings_text = Text("\n".join(result.warnings), style="yellow")
        table.add_row("Warnings", warnings_text)

    # Create panel
    panel = Panel(
        table,
        title=header,
        subtitle=f"Generated: {result.generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        border_style="blue",
    )
    console.print(panel)


def display_batch_results(results: list[AnalysisResult]):
    """Display batch results as a table."""
    table = Table(title="Analysis Results", show_lines=True)

    table.add_column("Symbol", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("Score", justify="center")
    table.add_column("Expression", justify="center")
    table.add_column("Risk Flags")

    for r in results:
        change_style = "green" if r.change >= 0 else "red"
        table.add_row(
            r.symbol,
            f"${r.price:.2f}",
            Text(f"{r.change_percent:+.2f}%", style=change_style),
            format_score(r.short_score),
            format_expression(r.trade_expression),
            format_flags(r.risk_flags),
        )

    console.print(table)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def main(ctx, verbose):
    """Short Gainers Agent - Identify short-selling opportunities."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.command()
@click.argument("symbol")
@click.option("--dashboard", "-d", is_flag=True, help="Generate HTML dashboard")
@click.option("--output", "-o", type=click.Path(), help="Output directory for dashboard")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.pass_context
def analyze(ctx, symbol: str, dashboard: bool, output: str | None, json_output: bool):
    """Analyze a single symbol for short opportunity."""

    async def run():
        config = get_config()
        async with Agent(config) as agent:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task(f"Analyzing {symbol}...", total=None)
                result = await agent.analyze(symbol)

        if json_output:
            console.print_json(result.model_dump_json(indent=2))
        else:
            display_result(result)

        if dashboard:
            output_dir = Path(output) if output else config.output_directory
            output_dir.mkdir(parents=True, exist_ok=True)

            generator = DashboardGenerator()
            html = generator.generate(result)

            filename = f"{symbol}_analysis_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
            filepath = output_dir / filename

            filepath.write_text(html)
            console.print(f"\n[green]Dashboard saved to:[/green] {filepath}")

    asyncio.run(run())


@main.command()
@click.argument("symbols", nargs=-1)
@click.option("--source", type=click.Choice(["custom", "top_gainers"]), default="custom")
@click.option("--limit", "-n", default=10, help="Number of symbols to analyze")
@click.option("--min-change", type=float, help="Minimum % change filter")
@click.option("--output", "-o", type=click.Path(), help="Output directory for reports")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.pass_context
def batch(
    ctx,
    symbols: tuple[str, ...],
    source: str,
    limit: int,
    min_change: float | None,
    output: str | None,
    json_output: bool,
):
    """Batch analyze multiple symbols."""

    async def run():
        config = get_config()
        async with Agent(config) as agent:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                if source == "top_gainers":
                    progress.add_task(f"Analyzing top {limit} gainers...", total=None)
                    batch_result = await agent.analyze_top_gainers(
                        limit=limit,
                        min_change_percent=min_change,
                    )
                else:
                    if not symbols:
                        console.print("[red]Error:[/red] No symbols provided")
                        return
                    progress.add_task(f"Analyzing {len(symbols)} symbols...", total=None)
                    batch_result = await agent.analyze_batch(symbols)

        if json_output:
            console.print_json(batch_result.model_dump_json(indent=2))
        else:
            # Summary panel
            summary = batch_result.summary
            summary_text = (
                f"Total: {summary.total_analyzed} | "
                f"Actionable: {summary.actionable_count} | "
                f"Avg Score: {summary.avg_score:.1f} | "
                f"High Squeeze: {summary.high_squeeze_count} | "
                f"Time: {summary.processing_time_ms}ms"
            )
            console.print(Panel(summary_text, title="Batch Summary", border_style="blue"))

            # Results table
            display_batch_results(batch_result.results)

            # Errors
            if batch_result.errors:
                console.print("\n[red]Errors:[/red]")
                for err in batch_result.errors:
                    console.print(f"  {err['symbol']}: {err['error']}")

        # Save to output directory
        if output:
            output_dir = Path(output)
            output_dir.mkdir(parents=True, exist_ok=True)

            filename = f"batch_analysis_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = output_dir / filename

            filepath.write_text(batch_result.model_dump_json(indent=2))
            console.print(f"\n[green]Results saved to:[/green] {filepath}")

    asyncio.run(run())


@main.command()
@click.argument("symbol")
@click.pass_context
def score(ctx, symbol: str):
    """Quick score check for a symbol (minimal output)."""

    async def run():
        async with Agent() as agent:
            result = await agent.analyze(symbol, include_fundamentals=False)

        # One-line output
        console.print(result.to_summary())

    asyncio.run(run())


@main.command()
@click.argument("symbol")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.pass_context
def dashboard(ctx, symbol: str, output: str | None):
    """Generate HTML dashboard for a symbol."""

    async def run():
        config = get_config()
        async with Agent(config) as agent:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task(f"Generating dashboard for {symbol}...", total=None)
                result = await agent.analyze(symbol)

        generator = DashboardGenerator()
        html = generator.generate(result)

        if output:
            filepath = Path(output)
        else:
            output_dir = config.output_directory
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{symbol}_dashboard_{datetime.utcnow().strftime('%Y%m%d')}.html"
            filepath = output_dir / filename

        filepath.write_text(html)
        console.print(f"[green]Dashboard saved to:[/green] {filepath}")

    asyncio.run(run())


@main.command()
@click.pass_context
def gainers(ctx):
    """List today's top gainers."""

    async def run():
        async with Agent() as agent:
            gainers = await agent.get_top_gainers(limit=20)

        table = Table(title="Top Gainers Today")
        table.add_column("Symbol", style="bold")
        table.add_column("Price", justify="right")
        table.add_column("Change %", justify="right")
        table.add_column("Volume", justify="right")

        for g in gainers:
            table.add_row(
                g.symbol,
                f"${g.price:.2f}",
                Text(f"+{g.change_percent:.2f}%", style="green"),
                f"{g.volume:,}",
            )

        console.print(table)

    asyncio.run(run())


if __name__ == "__main__":
    main()
