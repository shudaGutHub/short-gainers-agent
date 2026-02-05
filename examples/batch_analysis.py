"""Example: Batch analyze top gainers."""

import asyncio

from short_gainers_agent import Agent
from short_gainers_agent.output import DashboardGenerator


async def main():
    async with Agent() as agent:
        # Analyze today's top 10 gainers
        print("Fetching and analyzing top gainers...")
        batch_result = await agent.analyze_top_gainers(limit=10)

        # Print summary
        summary = batch_result.summary
        print(f"\nBatch Summary:")
        print(f"  Total Analyzed: {summary.total_analyzed}")
        print(f"  Actionable (score >= 6): {summary.actionable_count}")
        print(f"  Average Score: {summary.avg_score:.2f}")
        print(f"  High Squeeze Risk: {summary.high_squeeze_count}")
        print(f"  Processing Time: {summary.processing_time_ms}ms")

        # Print results table
        print(f"\n{'Symbol':<8} {'Score':>6} {'Expression':<15} {'Change':>8} {'Flags'}")
        print("-" * 60)

        for r in batch_result.results:
            flags = ",".join(f.value[:5] for f in r.risk_flags[:2]) or "NONE"
            print(
                f"{r.symbol:<8} {r.short_score:>6.1f} {r.trade_expression.value:<15} "
                f"{r.change_percent:>+7.1f}% {flags}"
            )

        # Generate dashboard for top pick
        if batch_result.results:
            top_pick = batch_result.results[0]
            print(f"\nGenerating dashboard for top pick: {top_pick.symbol}")

            generator = DashboardGenerator()
            html = generator.generate(top_pick)

            filename = f"{top_pick.symbol}_dashboard.html"
            with open(filename, "w") as f:
                f.write(html)
            print(f"Dashboard saved to: {filename}")

        # Handle errors
        if batch_result.errors:
            print(f"\nErrors encountered:")
            for err in batch_result.errors:
                print(f"  {err['symbol']}: {err['error']}")


if __name__ == "__main__":
    asyncio.run(main())
