"""Tests for sentiment/catalyst analysis module."""

from decimal import Decimal
from datetime import datetime

import pytest

from src.sentiment.catalyst import (
    CATALYST_SCORE_ADJUSTMENTS,
    SentimentResult,
    compute_score_adjustment,
    format_catalyst_summary,
    get_risk_flag_from_sentiment,
    heuristic_catalyst_detection,
    should_avoid_short,
)
from src.models.candidate import (
    CatalystClassification,
    NewsAssessment,
    RiskFlag,
    SentimentLevel,
)
from src.models.ticker import NewsFeed, NewsItem


class TestCatalystScoreAdjustments:
    """Tests for score adjustment constants."""

    def test_fundamental_catalysts_are_negative(self):
        """Fundamental catalysts should have negative adjustments (penalize shorts)."""
        fundamental = [
            CatalystClassification.EARNINGS,
            CatalystClassification.FDA,
            CatalystClassification.MA,
            CatalystClassification.UPGRADE,
        ]
        
        for catalyst in fundamental:
            assert CATALYST_SCORE_ADJUSTMENTS[catalyst] < 0

    def test_speculative_catalysts_are_positive(self):
        """Speculative catalysts should have positive adjustments (boost shorts)."""
        speculative = [
            CatalystClassification.SPECULATIVE,
            CatalystClassification.MEME_SOCIAL,
        ]
        
        for catalyst in speculative:
            assert CATALYST_SCORE_ADJUSTMENTS[catalyst] > 0


class TestComputeScoreAdjustment:
    """Tests for score adjustment computation."""

    def test_earnings_beat_penalizes(self):
        """Strong earnings should heavily penalize short score."""
        assessment = NewsAssessment(
            catalyst_type=CatalystClassification.EARNINGS,
            sentiment=SentimentLevel.STRONGLY_POSITIVE,
            summary="Q4 earnings beat estimates",
            justifies_repricing=True,
            confidence=Decimal("0.9"),
        )
        
        capped, raw = compute_score_adjustment(assessment)
        
        assert capped < 0
        assert capped <= -3.0  # Should be significant penalty

    def test_meme_pump_boosts(self):
        """Meme/social pump should boost short score."""
        assessment = NewsAssessment(
            catalyst_type=CatalystClassification.MEME_SOCIAL,
            sentiment=SentimentLevel.MIXED,
            summary="Reddit attention driving volume",
            justifies_repricing=False,
            confidence=Decimal("0.7"),
        )
        
        capped, raw = compute_score_adjustment(assessment)
        
        assert capped > 0

    def test_low_confidence_reduces_adjustment(self):
        """Low confidence should reduce adjustment magnitude."""
        high_conf = NewsAssessment(
            catalyst_type=CatalystClassification.FDA,
            sentiment=SentimentLevel.STRONGLY_POSITIVE,
            summary="FDA approval",
            justifies_repricing=True,
            confidence=Decimal("1.0"),
        )
        
        low_conf = NewsAssessment(
            catalyst_type=CatalystClassification.FDA,
            sentiment=SentimentLevel.STRONGLY_POSITIVE,
            summary="FDA approval",
            justifies_repricing=True,
            confidence=Decimal("0.3"),
        )
        
        _, high_raw = compute_score_adjustment(high_conf)
        _, low_raw = compute_score_adjustment(low_conf)
        
        assert abs(low_raw) < abs(high_raw)

    def test_adjustment_is_capped(self):
        """Adjustment should be capped within bounds."""
        extreme_bad = NewsAssessment(
            catalyst_type=CatalystClassification.MA,
            sentiment=SentimentLevel.STRONGLY_POSITIVE,
            summary="Acquisition announced",
            justifies_repricing=True,
            confidence=Decimal("1.0"),
        )
        
        capped, raw = compute_score_adjustment(extreme_bad)
        
        assert capped >= -5.0
        assert capped <= 3.0


class TestHeuristicCatalystDetection:
    """Tests for heuristic fallback detection."""

    def test_detects_earnings(self):
        """Should detect earnings-related headlines."""
        headlines = [
            "Company X Reports Q3 Earnings Beat",
            "Revenue Tops Analyst Estimates",
        ]
        
        result = heuristic_catalyst_detection(headlines, Decimal("25.0"))
        
        assert result.catalyst_type == CatalystClassification.EARNINGS
        assert result.justifies_repricing is True

    def test_detects_fda(self):
        """Should detect FDA-related headlines."""
        headlines = [
            "FDA Grants Approval for New Drug Treatment",
            "Clinical Trial Phase 3 Success",
        ]
        
        result = heuristic_catalyst_detection(headlines, Decimal("50.0"))
        
        assert result.catalyst_type == CatalystClassification.FDA
        assert result.justifies_repricing is True

    def test_detects_ma(self):
        """Should detect M&A headlines."""
        headlines = [
            "Company A to Acquire Company B",
            "Merger Deal Valued at $5B",
        ]
        
        result = heuristic_catalyst_detection(headlines, Decimal("30.0"))
        
        assert result.catalyst_type == CatalystClassification.MA
        assert result.justifies_repricing is True

    def test_detects_meme(self):
        """Should detect meme/social headlines."""
        headlines = [
            "Stock Surges on Reddit WSB Attention",
            "Short Squeeze Potential Discussed",
        ]
        
        result = heuristic_catalyst_detection(headlines, Decimal("100.0"))
        
        assert result.catalyst_type == CatalystClassification.MEME_SOCIAL
        assert result.justifies_repricing is False

    def test_detects_speculative(self):
        """Should detect speculative/vague PR."""
        headlines = [
            "Company Exploring Potential AI Opportunities",
            "May Consider Strategic Options",
        ]
        
        result = heuristic_catalyst_detection(headlines, Decimal("20.0"))
        
        assert result.catalyst_type == CatalystClassification.SPECULATIVE
        assert result.justifies_repricing is False

    def test_unknown_for_unrelated_news(self):
        """Should return unknown for unrelated news."""
        headlines = [
            "CEO Speaks at Industry Conference",
            "Company Opens New Office",
        ]
        
        result = heuristic_catalyst_detection(headlines, Decimal("15.0"))
        
        assert result.catalyst_type == CatalystClassification.UNKNOWN

    def test_low_confidence_for_heuristics(self):
        """Heuristic detection should have low confidence."""
        headlines = ["FDA Approval Announced"]
        
        result = heuristic_catalyst_detection(headlines, Decimal("30.0"))
        
        assert result.confidence == Decimal("0.5")  # Heuristics capped at 0.5


class TestShouldAvoidShort:
    """Tests for short avoidance logic."""

    def test_avoid_high_confidence_repricing(self):
        """Should avoid short on high-confidence fundamental repricing."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.FDA,
                sentiment=SentimentLevel.STRONGLY_POSITIVE,
                summary="FDA approval",
                justifies_repricing=True,
                confidence=Decimal("0.9"),
            ),
            score_adjustment=-4.0,
            raw_adjustment=-5.5,
            analysis_source="claude",
        )
        
        assert should_avoid_short(result) is True

    def test_dont_avoid_low_confidence_repricing(self):
        """Should not avoid on low-confidence repricing."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.CONTRACT,
                sentiment=SentimentLevel.POSITIVE,
                summary="Small contract win",
                justifies_repricing=True,
                confidence=Decimal("0.4"),  # Low confidence
            ),
            score_adjustment=-1.0,
            raw_adjustment=-1.2,
            analysis_source="heuristic",
        )
        
        assert should_avoid_short(result) is False

    def test_avoid_very_negative_adjustment(self):
        """Should avoid on very negative adjustment regardless of repricing flag."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.MA,
                sentiment=SentimentLevel.STRONGLY_POSITIVE,
                summary="Acquisition at premium",
                justifies_repricing=False,  # Even without this flag
                confidence=Decimal("0.8"),
            ),
            score_adjustment=-3.5,  # Very negative
            raw_adjustment=-4.0,
            analysis_source="claude",
        )
        
        assert should_avoid_short(result) is True

    def test_dont_avoid_speculative(self):
        """Should not avoid on speculative catalyst."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.SPECULATIVE,
                sentiment=SentimentLevel.MIXED,
                summary="Vague PR about AI",
                justifies_repricing=False,
                confidence=Decimal("0.6"),
            ),
            score_adjustment=1.0,
            raw_adjustment=1.2,
            analysis_source="claude",
        )
        
        assert should_avoid_short(result) is False


class TestGetRiskFlagFromSentiment:
    """Tests for risk flag extraction."""

    def test_returns_repricing_flag(self):
        """Should return FUNDAMENTAL_REPRICING flag when applicable."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.EARNINGS,
                sentiment=SentimentLevel.POSITIVE,
                summary="Earnings beat",
                justifies_repricing=True,
                confidence=Decimal("0.8"),
            ),
            score_adjustment=-2.0,
            raw_adjustment=-2.5,
            analysis_source="claude",
        )
        
        flag = get_risk_flag_from_sentiment(result)
        
        assert flag == RiskFlag.FUNDAMENTAL_REPRICING

    def test_returns_none_for_speculative(self):
        """Should return None for speculative catalyst."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.MEME_SOCIAL,
                sentiment=SentimentLevel.MIXED,
                summary="Reddit pump",
                justifies_repricing=False,
                confidence=Decimal("0.7"),
            ),
            score_adjustment=1.5,
            raw_adjustment=1.8,
            analysis_source="claude",
        )
        
        flag = get_risk_flag_from_sentiment(result)
        
        assert flag is None


class TestFormatCatalystSummary:
    """Tests for summary formatting."""

    def test_formats_correctly(self):
        """Should format summary with all components."""
        result = SentimentResult(
            ticker="TEST",
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.EARNINGS,
                sentiment=SentimentLevel.POSITIVE,
                summary="Q3 beat estimates",
                justifies_repricing=True,
                confidence=Decimal("0.85"),
            ),
            score_adjustment=-2.5,
            raw_adjustment=-3.0,
            analysis_source="claude",
        )
        
        summary = format_catalyst_summary(result)
        
        assert "EARNINGS" in summary
        assert "Q3 beat estimates" in summary
        assert "positive" in summary
        assert "-2.5" in summary

    def test_handles_no_assessment(self):
        """Should handle missing assessment gracefully."""
        result = SentimentResult(
            ticker="TEST",
            assessment=None,
            score_adjustment=0.0,
            raw_adjustment=0.0,
            analysis_source="none",
            error="API error",
        )
        
        summary = format_catalyst_summary(result)
        
        assert "No analysis" in summary
