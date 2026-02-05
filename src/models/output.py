"""
Models for the final agent output.

These models structure the agent response for downstream consumption.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.models.candidate import ShortCandidate


class MarketContext(BaseModel):
    """High-level market context for the trading day."""

    date: datetime
    total_gainers_screened: int
    passed_prefilter: int
    nasdaq_only: bool = True
    market_hours: bool = True
    notes: list[str] = Field(default_factory=list)


class AgentOutput(BaseModel):
    """
    Complete output from the short gainers agent.

    Includes both human-readable summary and machine-readable data.
    """

    # Metadata
    run_timestamp: datetime = Field(default_factory=datetime.now)
    context: MarketContext

    # Results
    candidates: list[ShortCandidate] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(
        default_factory=list, description="Tickers that failed pre-filter"
    )

    # Summary
    summary: str = ""
    no_candidates_reason: Optional[str] = None

    @property
    def has_candidates(self) -> bool:
        return len(self.candidates) > 0

    @property
    def top_candidate(self) -> Optional[ShortCandidate]:
        """Return highest scored candidate or None."""
        return self.candidates[0] if self.candidates else None

    def to_structured_output(self) -> str:
        """
        Generate full structured output per agent spec.

        Returns:
            Multi-line string with summary + machine-readable lines.
        """
        lines = []

        # Natural language summary
        lines.append("=" * 70)
        lines.append("SHORT GAINERS AGENT REPORT")
        lines.append(f"Date: {self.context.date.strftime('%Y-%m-%d')}")
        lines.append(f"Run: {self.run_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)
        lines.append("")
        lines.append("SUMMARY:")
        lines.append(self.summary)
        lines.append("")

        if not self.has_candidates:
            lines.append(f"NO SUITABLE CANDIDATES: {self.no_candidates_reason or 'Unknown'}")
            return "\n".join(lines)

        # Machine-readable section
        lines.append("-" * 70)
        lines.append("RANKED CANDIDATES (best to worst):")
        lines.append(
            "TICKER | SCORE | TECH_NOTES | NEWS_NOTES | RISK_FLAGS | EXPRESSION | KEY_LEVELS"
        )
        lines.append("-" * 70)

        for candidate in self.candidates:
            lines.append(candidate.to_output_line())

        # Detailed catalyst/news assessment section
        lines.append("")
        lines.append("=" * 70)
        lines.append("CATALYST / NEWS ASSESSMENT DETAIL")
        lines.append("=" * 70)

        for candidate in self.candidates:
            lines.append("")
            lines.append(f"[{candidate.ticker}] +{candidate.change_percent:.1f}%")
            lines.append(candidate.news_assessment.detailed_summary())
            
            if candidate.news_assessment.justifies_repricing:
                lines.append("  >>> WARNING: Fundamental repricing detected - SHORT NOT RECOMMENDED <<<")

        lines.append("")
        lines.append("-" * 70)
        lines.append(f"Total candidates: {len(self.candidates)}")
        lines.append(f"Excluded tickers: {len(self.excluded_tickers)}")

        if self.context.notes:
            lines.append("")
            lines.append("NOTES:")
            for note in self.context.notes:
                lines.append(f"  - {note}")

        return "\n".join(lines)

    def to_json_output(self) -> dict:
        """Return JSON-serializable dict for API consumers."""
        return {
            "run_timestamp": self.run_timestamp.isoformat(),
            "context": {
                "date": self.context.date.isoformat(),
                "total_screened": self.context.total_gainers_screened,
                "passed_filter": self.context.passed_prefilter,
            },
            "summary": self.summary,
            "candidates": [
                {
                    "ticker": c.ticker,
                    "score": float(c.final_score),
                    "tech_score": float(c.tech_score),
                    "expression": c.preferred_expression.value,
                    "risk_flags": [f.value for f in c.risk_flags],
                    "key_levels": {k: float(v) for k, v in c.key_levels.to_dict().items()},
                }
                for c in self.candidates
            ],
            "excluded": self.excluded_tickers,
        }
