"""Tests for data ingestion module."""

import json
from decimal import Decimal
from datetime import datetime
from pathlib import Path

import pytest

from src.ingest.gainers import (
    GainersResult,
    create_manual_gainers,
    filter_nasdaq_gainers,
)
from src.ingest.news import (
    NewsResult,
    has_earnings_news,
    has_fda_news,
    has_ma_news,
    format_headlines_for_claude,
)
from src.models.ticker import GainerRecord, NewsFeed, NewsItem


class TestFilterNasdaqGainers:
    """Tests for gainer filtering logic."""

    def test_filters_low_price(self):
        """Should filter out stocks below min price."""
        gainers = [
            GainerRecord(
                ticker="PENNY",
                price=Decimal("0.50"),
                change_amount=Decimal("0.10"),
                change_percentage=Decimal("25.0"),
                volume=1_000_000,
            ),
            GainerRecord(
                ticker="GOOD",
                price=Decimal("10.00"),
                change_amount=Decimal("2.00"),
                change_percentage=Decimal("25.0"),
                volume=1_000_000,
            ),
        ]

        filtered = filter_nasdaq_gainers(gainers, min_price=1.0, min_volume=100_000)

        assert len(filtered) == 1
        assert filtered[0].ticker == "GOOD"

    def test_filters_low_volume(self):
        """Should filter out low volume stocks."""
        gainers = [
            GainerRecord(
                ticker="LOWV",  # Low volume
                price=Decimal("10.00"),
                change_amount=Decimal("2.00"),
                change_percentage=Decimal("25.0"),
                volume=50_000,
            ),
            GainerRecord(
                ticker="HIGHV",  # High volume
                price=Decimal("10.00"),
                change_amount=Decimal("2.00"),
                change_percentage=Decimal("25.0"),
                volume=500_000,
            ),
        ]

        filtered = filter_nasdaq_gainers(gainers, min_price=1.0, min_volume=100_000)

        assert len(filtered) == 1
        assert filtered[0].ticker == "HIGHV"

    def test_filters_long_tickers(self):
        """Should filter out OTC-style long tickers."""
        gainers = [
            GainerRecord(
                ticker="TOOLNG",  # 6 chars - too long (>5)
                price=Decimal("10.00"),
                change_amount=Decimal("2.00"),
                change_percentage=Decimal("25.0"),
                volume=500_000,
            ),
            GainerRecord(
                ticker="GOOD",  # 4 chars - ok
                price=Decimal("10.00"),
                change_amount=Decimal("2.00"),
                change_percentage=Decimal("25.0"),
                volume=500_000,
            ),
        ]

        filtered = filter_nasdaq_gainers(gainers, min_price=1.0, min_volume=100_000)

        assert len(filtered) == 1
        assert filtered[0].ticker == "GOOD"


class TestCreateManualGainers:
    """Tests for manual gainer creation."""

    def test_creates_valid_records(self):
        """Should create GainerRecords from tuples."""
        tickers = [
            ("AAPL", 150.0, 5.0, 1_000_000),
            ("MSFT", 300.0, 3.0, 500_000),
        ]

        result = create_manual_gainers(tickers)

        assert result.is_success
        assert result.count == 2
        assert result.source == "manual"
        assert result.gainers[0].ticker == "AAPL"
        assert result.gainers[0].change_percentage == Decimal("5.0")


class TestNewsCatalystDetection:
    """Tests for news catalyst keyword detection."""

    def _make_news_result(self, titles: list[str]) -> NewsResult:
        """Helper to create NewsResult from titles."""
        items = [
            NewsItem(
                title=title,
                url="http://example.com",
                source="Test",
                published_at=datetime.now(),
            )
            for title in titles
        ]
        feed = NewsFeed(ticker="TEST", items=items, fetched_at=datetime.now())
        return NewsResult(feed=feed, source="test")

    def test_detects_earnings_news(self):
        """Should detect earnings-related headlines."""
        result = self._make_news_result([
            "Company XYZ Reports Q3 Earnings Beat",
            "Revenue Tops Estimates",
        ])

        assert has_earnings_news(result) is True

    def test_detects_fda_news(self):
        """Should detect FDA-related headlines."""
        result = self._make_news_result([
            "FDA Approves New Drug Treatment",
            "Clinical Trial Phase 3 Results Positive",
        ])

        assert has_fda_news(result) is True

    def test_detects_ma_news(self):
        """Should detect M&A-related headlines."""
        result = self._make_news_result([
            "Company A to Acquire Company B for $5B",
            "Merger Deal Announced",
        ])

        assert has_ma_news(result) is True

    def test_no_false_positives(self):
        """Should not detect catalysts in unrelated news."""
        result = self._make_news_result([
            "Company Opens New Office in Texas",
            "CEO Speaks at Industry Conference",
        ])

        assert has_earnings_news(result) is False
        assert has_fda_news(result) is False
        assert has_ma_news(result) is False


class TestFormatHeadlinesForClaude:
    """Tests for Claude prompt formatting."""

    def test_formats_headlines_with_sources(self):
        """Should format headlines with source attribution."""
        items = [
            NewsItem(
                title="Big News Story",
                url="http://example.com",
                source="Reuters",
                published_at=datetime.now(),
            ),
            NewsItem(
                title="Another Story",
                url="http://example.com",
                source="Bloomberg",
                published_at=datetime.now(),
            ),
        ]
        feed = NewsFeed(ticker="TEST", items=items, fetched_at=datetime.now())
        result = NewsResult(feed=feed, source="test")

        formatted = format_headlines_for_claude(result)

        assert "[Reuters] Big News Story" in formatted
        assert "[Bloomberg] Another Story" in formatted

    def test_handles_empty_news(self):
        """Should handle no news gracefully."""
        result = NewsResult(feed=None, source="none", error="No news")

        formatted = format_headlines_for_claude(result)

        assert "No recent news" in formatted
