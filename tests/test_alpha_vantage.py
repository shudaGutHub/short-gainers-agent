"""Tests for Alpha Vantage client."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.models.ticker import GainerRecord


class TestGainerRecord:
    """Tests for GainerRecord model parsing."""

    def test_parse_percentage_with_sign(self):
        """Should strip % from percentage strings."""
        record = GainerRecord(
            ticker="TEST",
            price=Decimal("10.00"),
            change_amount=Decimal("1.00"),
            change_percentage="10.5432%",
            volume=100000,
        )
        assert record.change_percentage == Decimal("10.5432")

    def test_parse_percentage_without_sign(self):
        """Should handle percentage without % sign."""
        record = GainerRecord(
            ticker="TEST",
            price=Decimal("10.00"),
            change_amount=Decimal("1.00"),
            change_percentage=Decimal("10.5432"),
            volume=100000,
        )
        assert record.change_percentage == Decimal("10.5432")


class TestSampleFixture:
    """Tests using sample fixture data."""

    @pytest.fixture
    def sample_gainers(self) -> dict:
        """Load sample gainers fixture."""
        fixture_path = Path(__file__).parent / "fixtures" / "sample_gainers.json"
        with open(fixture_path) as f:
            return json.load(f)

    def test_parse_sample_gainers(self, sample_gainers: dict):
        """Should parse all sample gainers."""
        gainers_raw = sample_gainers["top_gainers"]
        
        records = []
        for item in gainers_raw:
            record = GainerRecord(
                ticker=item["ticker"],
                price=Decimal(item["price"]),
                change_amount=Decimal(item["change_amount"]),
                change_percentage=item["change_percentage"],
                volume=int(item["volume"]),
            )
            records.append(record)

        assert len(records) == 5
        assert records[0].ticker == "ACME"
        assert records[0].change_percentage == Decimal("37.0123")
        assert records[0].volume == 5678901

    def test_gainers_sorted_by_change(self, sample_gainers: dict):
        """Sample gainers should be sorted by change percentage."""
        gainers_raw = sample_gainers["top_gainers"]
        percentages = [
            Decimal(item["change_percentage"].rstrip("%"))
            for item in gainers_raw
        ]
        
        # Verify descending order
        for i in range(len(percentages) - 1):
            assert percentages[i] >= percentages[i + 1]
