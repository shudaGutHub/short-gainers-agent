"""Tests for ranking and output modules."""

from decimal import Decimal

import pytest

from src.ranking.ranker import (
    RISK_PENALTIES,
    RankingInput,
    compute_risk_penalty,
    determine_expression,
    get_top_candidates,
    rank_candidate,
    rank_candidates_batch,
    summarize_rankings,
)
from src.output.formatter import (
    build_agent_output,
    format_compact_output,
    format_full_report,
    format_json_output,
    generate_summary,
)
from src.models.candidate import (
    CatalystClassification,
    KeyLevels,
    NewsAssessment,
    RiskFlag,
    SentimentLevel,
    TechnicalState,
    TradeExpression,
)
from src.sentiment.catalyst import SentimentResult


@pytest.fixture
def mock_tech_state() -> TechnicalState:
    """Create mock technical state."""
    return TechnicalState(
        rsi_daily=Decimal("75"),
        rsi_intraday=Decimal("78"),
        price_above_upper_band=True,
        atr_daily=Decimal("1.50"),
        atr_percent=Decimal("8.5"),
        volume_vs_avg=Decimal("2.5"),
        volume_confirming_price=False,
    )


@pytest.fixture
def mock_key_levels() -> KeyLevels:
    """Create mock key levels."""
    return KeyLevels(
        intraday_high=Decimal("25.50"),
        intraday_low=Decimal("22.00"),
        vwap=Decimal("23.75"),
        prior_day_close=Decimal("20.00"),
        support_1=Decimal("21.00"),
    )


@pytest.fixture
def mock_sentiment_speculative() -> SentimentResult:
    """Create mock speculative sentiment result."""
    return SentimentResult(
        ticker="TEST",
        assessment=NewsAssessment(
            catalyst_type=CatalystClassification.SPECULATIVE,
            sentiment=SentimentLevel.MIXED,
            summary="Vague AI PR",
            justifies_repricing=False,
            confidence=Decimal("0.6"),
        ),
        score_adjustment=1.2,
        raw_adjustment=1.5,
        analysis_source="claude",
    )


@pytest.fixture
def mock_sentiment_earnings() -> SentimentResult:
    """Create mock earnings sentiment result."""
    return SentimentResult(
        ticker="TEST",
        assessment=NewsAssessment(
            catalyst_type=CatalystClassification.EARNINGS,
            sentiment=SentimentLevel.STRONGLY_POSITIVE,
            summary="Q4 beat estimates",
            justifies_repricing=True,
            confidence=Decimal("0.9"),
        ),
        score_adjustment=-3.5,
        raw_adjustment=-4.2,
        analysis_source="claude",
    )


class TestComputeRiskPenalty:
    """Tests for risk penalty calculation."""

    def test_no_flags_no_penalty(self):
        """No risk flags should give zero penalty."""
        penalty = compute_risk_penalty([RiskFlag.NONE])
        assert penalty == 0.0

    def test_single_flag(self):
        """Single flag should give corresponding penalty."""
        penalty = compute_risk_penalty([RiskFlag.MICROCAP])
        assert penalty == RISK_PENALTIES[RiskFlag.MICROCAP]

    def test_multiple_flags_sum(self):
        """Multiple flags should sum penalties."""
        flags = [RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE]
        penalty = compute_risk_penalty(flags)
        expected = RISK_PENALTIES[RiskFlag.MICROCAP] + RISK_PENALTIES[RiskFlag.HIGH_SQUEEZE]
        assert penalty == expected

    def test_duplicate_flags_counted_once(self):
        """Duplicate flags should only count once."""
        flags = [RiskFlag.MICROCAP, RiskFlag.MICROCAP]
        penalty = compute_risk_penalty(flags)
        assert penalty == RISK_PENALTIES[RiskFlag.MICROCAP]


class TestDetermineExpression:
    """Tests for trade expression determination."""

    def test_avoid_dangerous_combo(self, mock_sentiment_speculative):
        """Should avoid dangerous flag combinations."""
        expression = determine_expression(
            final_score=7.0,
            risk_flags=[RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE],
            beta=Decimal("1.5"),
            sentiment_result=mock_sentiment_speculative,
        )
        assert expression == TradeExpression.AVOID

    def test_avoid_fundamental_repricing(self, mock_sentiment_earnings):
        """Should avoid fundamental repricing."""
        expression = determine_expression(
            final_score=5.0,
            risk_flags=[],
            beta=Decimal("1.5"),
            sentiment_result=mock_sentiment_earnings,
        )
        assert expression == TradeExpression.AVOID

    def test_avoid_low_score(self, mock_sentiment_speculative):
        """Should avoid low scores."""
        expression = determine_expression(
            final_score=2.0,
            risk_flags=[],
            beta=Decimal("1.5"),
            sentiment_result=mock_sentiment_speculative,
        )
        assert expression == TradeExpression.AVOID

    def test_puts_for_squeeze_risk(self, mock_sentiment_speculative):
        """Should recommend puts for high squeeze risk."""
        expression = determine_expression(
            final_score=6.0,
            risk_flags=[RiskFlag.HIGH_SQUEEZE],
            beta=Decimal("1.5"),
            sentiment_result=mock_sentiment_speculative,
        )
        assert expression == TradeExpression.BUY_PUTS

    def test_shares_for_clean_setup(self, mock_sentiment_speculative):
        """Should recommend shares for clean setups."""
        expression = determine_expression(
            final_score=7.0,
            risk_flags=[],
            beta=Decimal("1.5"),
            sentiment_result=mock_sentiment_speculative,
        )
        assert expression == TradeExpression.SHORT_SHARES


class TestRankCandidate:
    """Tests for single candidate ranking."""

    def test_speculative_candidate(
        self, mock_tech_state, mock_key_levels, mock_sentiment_speculative
    ):
        """Should rank speculative candidate favorably."""
        input_data = RankingInput(
            ticker="SPEC",
            current_price=Decimal("25.00"),
            change_percent=Decimal("35.0"),
            tech_score=Decimal("7.0"),
            tech_state=mock_tech_state,
            sentiment_result=mock_sentiment_speculative,
            risk_flags=[],
            key_levels=mock_key_levels,
            beta=Decimal("1.5"),
        )
        
        result = rank_candidate(input_data)
        
        assert result.ticker == "SPEC"
        assert float(result.final_score) > 6.0
        assert result.expression != TradeExpression.AVOID

    def test_earnings_penalized(
        self, mock_tech_state, mock_key_levels, mock_sentiment_earnings
    ):
        """Should penalize earnings-driven moves."""
        input_data = RankingInput(
            ticker="EARN",
            current_price=Decimal("30.00"),
            change_percent=Decimal("25.0"),
            tech_score=Decimal("7.0"),
            tech_state=mock_tech_state,
            sentiment_result=mock_sentiment_earnings,
            risk_flags=[],
            key_levels=mock_key_levels,
            beta=Decimal("1.5"),
        )
        
        result = rank_candidate(input_data)
        
        assert float(result.final_score) < 5.0
        assert result.expression == TradeExpression.AVOID


class TestRankCandidatesBatch:
    """Tests for batch ranking."""

    def test_sorts_descending(
        self, mock_tech_state, mock_key_levels, mock_sentiment_speculative
    ):
        """Should sort candidates by score descending."""
        inputs = [
            RankingInput(
                ticker="LOW",
                current_price=Decimal("15.00"),
                change_percent=Decimal("10.0"),
                tech_score=Decimal("3.0"),
                tech_state=mock_tech_state,
                sentiment_result=mock_sentiment_speculative,
                risk_flags=[RiskFlag.HIGH_SQUEEZE],
                key_levels=mock_key_levels,
                beta=Decimal("1.5"),
            ),
            RankingInput(
                ticker="HIGH",
                current_price=Decimal("40.00"),
                change_percent=Decimal("30.0"),
                tech_score=Decimal("8.0"),
                tech_state=mock_tech_state,
                sentiment_result=mock_sentiment_speculative,
                risk_flags=[],
                key_levels=mock_key_levels,
                beta=Decimal("1.5"),
            ),
        ]
        
        results = rank_candidates_batch(inputs)
        
        assert results[0].ticker == "HIGH"
        assert results[1].ticker == "LOW"


class TestSummarizeRankings:
    """Tests for ranking summary."""

    def test_empty_results(self):
        """Should handle empty results."""
        summary = summarize_rankings([])
        assert summary["total"] == 0
        assert summary["avg_score"] == 0.0


class TestOutputFormatting:
    """Tests for output formatting."""

    def test_summary_no_candidates(self):
        """Should generate summary for no candidates."""
        summary = generate_summary([], total_screened=20, date="2026-01-27")
        assert "No viable short candidates" in summary

    def test_full_report(
        self, mock_tech_state, mock_key_levels, mock_sentiment_speculative
    ):
        """Should format complete report."""
        inputs = [
            RankingInput(
                ticker="TEST",
                current_price=Decimal("22.00"),
                change_percent=Decimal("25.0"),
                tech_score=Decimal("7.0"),
                tech_state=mock_tech_state,
                sentiment_result=mock_sentiment_speculative,
                risk_flags=[],
                key_levels=mock_key_levels,
                beta=Decimal("1.5"),
            ),
        ]
        
        results = rank_candidates_batch(inputs)
        output = build_agent_output(
            results=results,
            excluded_tickers=["EXCL1"],
            total_screened=10,
            date="2026-01-27",
        )
        
        report = format_full_report(output)
        
        assert "SHORT GAINERS AGENT REPORT" in report
        assert "TEST" in report

    def test_json_output(
        self, mock_tech_state, mock_key_levels, mock_sentiment_speculative
    ):
        """Should format valid JSON."""
        import json
        
        inputs = [
            RankingInput(
                ticker="TEST",
                current_price=Decimal("22.00"),
                change_percent=Decimal("25.0"),
                tech_score=Decimal("7.0"),
                tech_state=mock_tech_state,
                sentiment_result=mock_sentiment_speculative,
                risk_flags=[],
                key_levels=mock_key_levels,
                beta=Decimal("1.5"),
            ),
        ]
        
        results = rank_candidates_batch(inputs)
        output = build_agent_output(
            results=results,
            excluded_tickers=[],
            total_screened=10,
            date="2026-01-27",
        )
        
        json_str = format_json_output(output)
        data = json.loads(json_str)
        
        assert "candidates" in data
        assert data["candidates"][0]["ticker"] == "TEST"

    def test_compact_output(
        self, mock_tech_state, mock_key_levels, mock_sentiment_speculative
    ):
        """Should format compact CSV-like output."""
        inputs = [
            RankingInput(
                ticker="TEST",
                current_price=Decimal("22.00"),
                change_percent=Decimal("25.0"),
                tech_score=Decimal("7.0"),
                tech_state=mock_tech_state,
                sentiment_result=mock_sentiment_speculative,
                risk_flags=[],
                key_levels=mock_key_levels,
                beta=Decimal("1.5"),
            ),
        ]
        
        results = rank_candidates_batch(inputs)
        output = build_agent_output(
            results=results,
            excluded_tickers=[],
            total_screened=10,
            date="2026-01-27",
        )
        
        compact = format_compact_output(output)
        
        assert "TEST" in compact
