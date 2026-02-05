"""
Integration tests for the Short Gainers Agent.

These tests verify end-to-end functionality with mocked external services.
"""

import json
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.ticker import GainerRecord, OHLCVSeries, OHLCV, Fundamentals, NewsFeed, NewsItem
from src.models.candidate import (
    CatalystClassification,
    KeyLevels,
    NewsAssessment,
    RiskFlag,
    SentimentLevel,
    TechnicalState,
    TradeExpression,
)
from src.ingest.gainers import GainersResult
from src.ingest.price import PriceDataResult
from src.ingest.fundamentals import FundamentalsResult
from src.ingest.news import NewsResult
from src.filters.prefilter import FilteredTicker
from src.ranking.ranker import RankingInput, rank_candidates_batch
from src.output.formatter import build_agent_output, format_full_report, format_json_output
from src.sentiment.catalyst import SentimentResult


# -----------------------------------------------------------------------------
# Fixtures - Mock Data Generators
# -----------------------------------------------------------------------------

def make_ohlcv_bars(
    ticker: str,
    days: int = 60,
    start_price: float = 10.0,
    daily_return: float = 0.01,
    volume: int = 1_000_000,
) -> list[OHLCV]:
    """Generate mock OHLCV bars."""
    bars = []
    price = start_price
    
    for i in range(days):
        date = datetime.now() - timedelta(days=days - i - 1)
        open_price = price
        high_price = price * 1.02
        low_price = price * 0.98
        close_price = price * (1 + daily_return)
        
        bars.append(OHLCV(
            timestamp=date,
            open=Decimal(str(round(open_price, 2))),
            high=Decimal(str(round(high_price, 2))),
            low=Decimal(str(round(low_price, 2))),
            close=Decimal(str(round(close_price, 2))),
            volume=volume,
        ))
        
        price = float(close_price)
    
    # Most recent bar first
    bars.reverse()
    return bars


def make_parabolic_bars(
    ticker: str,
    days: int = 60,
    start_price: float = 5.0,
    final_price: float = 25.0,
) -> list[OHLCV]:
    """Generate parabolic price action (for short candidates)."""
    bars = []
    
    for i in range(days):
        date = datetime.now() - timedelta(days=days - i - 1)
        
        # Exponential growth in last 10 days
        if i < days - 10:
            price = start_price * (1 + 0.01 * i)
        else:
            # Parabolic move
            days_into_move = i - (days - 10)
            price = start_price * 2 * (1.15 ** days_into_move)
        
        price = min(price, final_price)
        
        bars.append(OHLCV(
            timestamp=date,
            open=Decimal(str(round(price * 0.98, 2))),
            high=Decimal(str(round(price * 1.05, 2))),
            low=Decimal(str(round(price * 0.95, 2))),
            close=Decimal(str(round(price, 2))),
            volume=2_000_000 if i >= days - 10 else 500_000,
        ))
    
    bars.reverse()
    return bars


@pytest.fixture
def mock_gainers() -> list[GainerRecord]:
    """Create mock top gainers."""
    return [
        GainerRecord(
            ticker="SPEC",
            price=Decimal("25.00"),
            change_amount=Decimal("7.50"),
            change_percentage=Decimal("42.86"),
            volume=5_000_000,
        ),
        GainerRecord(
            ticker="EARN",
            price=Decimal("150.00"),
            change_amount=Decimal("30.00"),
            change_percentage=Decimal("25.00"),
            volume=10_000_000,
        ),
        GainerRecord(
            ticker="SQZE",
            price=Decimal("8.00"),
            change_amount=Decimal("4.00"),
            change_percentage=Decimal("100.00"),
            volume=50_000_000,
        ),
    ]


@pytest.fixture
def mock_fundamentals_large() -> Fundamentals:
    """Large cap fundamentals."""
    return Fundamentals(
        ticker="EARN",
        market_cap=50_000_000_000,
        sector="Technology",
        exchange="NASDAQ",
        beta=Decimal("1.2"),
        avg_volume=8_000_000,
    )


@pytest.fixture
def mock_fundamentals_micro() -> Fundamentals:
    """Microcap fundamentals (squeeze risk)."""
    return Fundamentals(
        ticker="SQZE",
        market_cap=80_000_000,
        sector="Healthcare",
        exchange="NASDAQ",
        beta=Decimal("3.5"),
        avg_volume=200_000,
    )


@pytest.fixture
def mock_news_speculative() -> NewsFeed:
    """Speculative news (good short)."""
    return NewsFeed(
        ticker="SPEC",
        items=[
            NewsItem(
                title="Company Exploring Potential AI Opportunities",
                url="https://example.com/1",
                source="PR Newswire",
                published_at=datetime.now(),
                summary="Company announces it may consider AI initiatives.",
            ),
        ],
    )


@pytest.fixture
def mock_news_earnings() -> NewsFeed:
    """Earnings news (bad short)."""
    return NewsFeed(
        ticker="EARN",
        items=[
            NewsItem(
                title="Company Reports Record Q4 Earnings, Beats Estimates",
                url="https://example.com/2",
                source="Reuters",
                published_at=datetime.now(),
                summary="Revenue up 40% YoY, EPS beats by 25%.",
            ),
        ],
    )


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------

class TestEndToEndRanking:
    """Test complete ranking flow with mock data."""

    def test_speculative_candidate_ranks_high(self):
        """Speculative catalyst + overextended technicals = good short."""
        # Setup
        tech_state = TechnicalState(
            rsi_daily=Decimal("82"),
            rsi_intraday=Decimal("85"),
            price_above_upper_band=True,
            atr_daily=Decimal("1.50"),
            atr_percent=Decimal("6.0"),
            volume_vs_avg=Decimal("3.0"),
            volume_confirming_price=False,
        )
        
        sentiment = SentimentResult(
            ticker="SPEC",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.SPECULATIVE,
                sentiment=SentimentLevel.MIXED,
                summary="Vague AI PR",
                justifies_repricing=False,
                confidence=Decimal("0.7"),
            ),
            score_adjustment=1.5,
            raw_adjustment=1.8,
            analysis_source="heuristic",
        )
        
        key_levels = KeyLevels(
            intraday_high=Decimal("26.00"),
            intraday_low=Decimal("22.00"),
            vwap=Decimal("24.00"),
            prior_day_close=Decimal("17.50"),
        )
        
        # Rank
        inputs = [RankingInput(
            ticker="SPEC",
            current_price=Decimal("25.00"),
            change_percent=Decimal("42.86"),
            tech_score=Decimal("7.5"),
            tech_state=tech_state,
            sentiment_result=sentiment,
            risk_flags=[],
            key_levels=key_levels,
            market_cap=500_000_000,
            beta=Decimal("1.8"),
        )]
        
        results = rank_candidates_batch(inputs)
        
        # Assert
        assert len(results) == 1
        assert float(results[0].final_score) >= 7.0
        assert results[0].expression == TradeExpression.SHORT_SHARES

    def test_earnings_candidate_ranks_low(self):
        """Earnings beat = avoid short."""
        tech_state = TechnicalState(
            rsi_daily=Decimal("75"),
            price_above_upper_band=True,
            atr_daily=Decimal("5.00"),
            atr_percent=Decimal("3.3"),
            volume_vs_avg=Decimal("2.0"),
            volume_confirming_price=True,
        )
        
        sentiment = SentimentResult(
            ticker="EARN",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.EARNINGS,
                sentiment=SentimentLevel.STRONGLY_POSITIVE,
                summary="Q4 beat estimates by 25%",
                justifies_repricing=True,
                confidence=Decimal("0.9"),
            ),
            score_adjustment=-4.0,
            raw_adjustment=-5.5,
            analysis_source="heuristic",
        )
        
        key_levels = KeyLevels(
            intraday_high=Decimal("155.00"),
            prior_day_close=Decimal("120.00"),
        )
        
        inputs = [RankingInput(
            ticker="EARN",
            current_price=Decimal("150.00"),
            change_percent=Decimal("25.00"),
            tech_score=Decimal("6.0"),
            tech_state=tech_state,
            sentiment_result=sentiment,
            risk_flags=[],
            key_levels=key_levels,
            market_cap=50_000_000_000,
            beta=Decimal("1.2"),
        )]
        
        results = rank_candidates_batch(inputs)
        
        assert len(results) == 1
        assert float(results[0].final_score) < 4.0
        assert results[0].expression == TradeExpression.AVOID

    def test_squeeze_candidate_gets_puts(self):
        """High squeeze risk = use puts not shares."""
        tech_state = TechnicalState(
            rsi_daily=Decimal("90"),
            price_above_upper_band=True,
            atr_daily=Decimal("2.00"),
            atr_percent=Decimal("25.0"),
            volume_vs_avg=Decimal("10.0"),
            volume_confirming_price=True,
        )
        
        sentiment = SentimentResult(
            ticker="SQZE",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.MEME_SOCIAL,
                sentiment=SentimentLevel.MIXED,
                summary="Reddit attention",
                justifies_repricing=False,
                confidence=Decimal("0.6"),
            ),
            score_adjustment=1.5,
            raw_adjustment=2.0,
            analysis_source="heuristic",
        )
        
        key_levels = KeyLevels(
            intraday_high=Decimal("10.00"),
            prior_day_close=Decimal("4.00"),
        )
        
        inputs = [RankingInput(
            ticker="SQZE",
            current_price=Decimal("8.00"),
            change_percent=Decimal("100.00"),
            tech_score=Decimal("8.0"),
            tech_state=tech_state,
            sentiment_result=sentiment,
            risk_flags=[RiskFlag.HIGH_SQUEEZE],
            key_levels=key_levels,
            market_cap=80_000_000,
            beta=Decimal("3.5"),
        )]
        
        results = rank_candidates_batch(inputs)
        
        assert len(results) == 1
        # Should recommend puts due to squeeze risk
        assert results[0].expression == TradeExpression.BUY_PUTS


class TestOutputGeneration:
    """Test report generation."""

    def test_full_report_contains_all_sections(self):
        """Full report should have header, summary, candidates, catalysts."""
        tech_state = TechnicalState(
            rsi_daily=Decimal("78"),
            price_above_upper_band=True,
            atr_daily=Decimal("1.00"),
            atr_percent=Decimal("5.0"),
            volume_vs_avg=Decimal("2.0"),
            volume_confirming_price=False,
        )
        
        sentiment = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.SPECULATIVE,
                sentiment=SentimentLevel.MIXED,
                summary="Test catalyst",
                justifies_repricing=False,
                confidence=Decimal("0.6"),
            ),
            score_adjustment=1.0,
            raw_adjustment=1.2,
            analysis_source="heuristic",
        )
        
        inputs = [RankingInput(
            ticker="TEST",
            current_price=Decimal("20.00"),
            change_percent=Decimal("30.00"),
            tech_score=Decimal("7.0"),
            tech_state=tech_state,
            sentiment_result=sentiment,
            risk_flags=[],
            key_levels=KeyLevels(),
            beta=Decimal("1.5"),
        )]
        
        results = rank_candidates_batch(inputs)
        output = build_agent_output(
            results=results,
            excluded_tickers=["EXCL1", "EXCL2"],
            total_screened=10,
            date="2026-01-27",
        )
        
        report = format_full_report(output)
        
        # Check sections
        assert "SHORT GAINERS AGENT REPORT" in report
        assert "SUMMARY:" in report
        assert "RANKED CANDIDATES" in report
        assert "CATALYST" in report
        assert "TEST" in report
        assert "2026-01-27" in report

    def test_json_output_is_valid(self):
        """JSON output should be parseable."""
        tech_state = TechnicalState(
            rsi_daily=Decimal("75"),
            price_above_upper_band=True,
            atr_daily=Decimal("1.00"),
            atr_percent=Decimal("5.0"),
            volume_vs_avg=Decimal("2.0"),
            volume_confirming_price=False,
        )
        
        sentiment = SentimentResult(
            ticker="JSON",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.UNKNOWN,
                sentiment=SentimentLevel.MIXED,
                summary="Test",
                justifies_repricing=False,
                confidence=Decimal("0.5"),
            ),
            score_adjustment=0.5,
            raw_adjustment=0.5,
            analysis_source="heuristic",
        )
        
        inputs = [RankingInput(
            ticker="JSON",
            current_price=Decimal("50.00"),
            change_percent=Decimal("20.00"),
            tech_score=Decimal("6.0"),
            tech_state=tech_state,
            sentiment_result=sentiment,
            risk_flags=[],
            key_levels=KeyLevels(),
            beta=Decimal("1.0"),
        )]
        
        results = rank_candidates_batch(inputs)
        output = build_agent_output(
            results=results,
            excluded_tickers=[],
            total_screened=5,
            date="2026-01-27",
        )
        
        json_str = format_json_output(output)
        data = json.loads(json_str)
        
        assert "candidates" in data
        assert "summary" in data
        assert "context" in data
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["ticker"] == "JSON"


class TestMultipleCandidateRanking:
    """Test ranking multiple candidates together."""

    def test_candidates_sorted_by_score(self):
        """Candidates should be sorted best to worst."""
        base_tech = TechnicalState(
            rsi_daily=Decimal("75"),
            price_above_upper_band=True,
            atr_daily=Decimal("1.00"),
            atr_percent=Decimal("5.0"),
            volume_vs_avg=Decimal("2.0"),
            volume_confirming_price=False,
        )
        
        good_sentiment = SentimentResult(
            ticker="GOOD",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.SPECULATIVE,
                sentiment=SentimentLevel.MIXED,
                summary="Vague PR",
                justifies_repricing=False,
                confidence=Decimal("0.7"),
            ),
            score_adjustment=1.5,
            raw_adjustment=1.8,
            analysis_source="heuristic",
        )
        
        bad_sentiment = SentimentResult(
            ticker="BAD",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.EARNINGS,
                sentiment=SentimentLevel.POSITIVE,
                summary="Earnings beat",
                justifies_repricing=True,
                confidence=Decimal("0.8"),
            ),
            score_adjustment=-2.5,
            raw_adjustment=-3.0,
            analysis_source="heuristic",
        )
        
        inputs = [
            RankingInput(
                ticker="BAD",
                current_price=Decimal("100.00"),
                change_percent=Decimal("20.00"),
                tech_score=Decimal("6.0"),
                tech_state=base_tech,
                sentiment_result=bad_sentiment,
                risk_flags=[],
                key_levels=KeyLevels(),
                beta=Decimal("1.0"),
            ),
            RankingInput(
                ticker="GOOD",
                current_price=Decimal("30.00"),
                change_percent=Decimal("35.00"),
                tech_score=Decimal("8.0"),
                tech_state=base_tech,
                sentiment_result=good_sentiment,
                risk_flags=[],
                key_levels=KeyLevels(),
                beta=Decimal("1.5"),
            ),
        ]
        
        results = rank_candidates_batch(inputs)
        
        assert results[0].ticker == "GOOD"  # Higher score first
        assert results[1].ticker == "BAD"
        assert float(results[0].final_score) > float(results[1].final_score)
