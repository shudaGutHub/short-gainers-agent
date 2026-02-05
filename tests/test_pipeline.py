"""Tests for pipeline orchestration."""

from decimal import Decimal

import pytest

from src.main import parse_manual_gainers
from src.pipeline import PipelineConfig


class TestPipelineConfig:
    """Tests for pipeline configuration."""

    def test_default_config(self):
        """Should create config with defaults."""
        config = PipelineConfig()
        
        assert config.max_tickers == 20
        assert config.min_change_percent == 10.0
        assert config.use_claude is True
        assert config.output_format == "full"
        assert config.verbose is False

    def test_custom_config(self):
        """Should accept custom values."""
        config = PipelineConfig(
            max_tickers=10,
            min_change_percent=20.0,
            use_claude=False,
            output_format="json",
            verbose=True,
        )
        
        assert config.max_tickers == 10
        assert config.min_change_percent == 20.0
        assert config.use_claude is False
        assert config.output_format == "json"
        assert config.verbose is True


class TestParseManualGainers:
    """Tests for manual gainer parsing."""

    def test_parse_basic(self):
        """Should parse basic ticker/change pairs."""
        gainers = parse_manual_gainers(
            tickers_str="AAPL,MSFT,NVDA",
            changes_str="15.5,12.3,20.1",
        )
        
        assert len(gainers) == 3
        assert gainers[0].ticker == "AAPL"
        assert gainers[0].change_percentage == Decimal("15.5")
        assert gainers[1].ticker == "MSFT"
        assert gainers[2].ticker == "NVDA"

    def test_parse_with_prices(self):
        """Should parse with custom prices."""
        gainers = parse_manual_gainers(
            tickers_str="AAPL,MSFT",
            changes_str="15.5,12.3",
            prices_str="150.00,300.00",
        )
        
        assert gainers[0].price == Decimal("150.00")
        assert gainers[1].price == Decimal("300.00")

    def test_uppercase_tickers(self):
        """Should uppercase tickers."""
        gainers = parse_manual_gainers(
            tickers_str="aapl,msft",
            changes_str="10,20",
        )
        
        assert gainers[0].ticker == "AAPL"
        assert gainers[1].ticker == "MSFT"

    def test_mismatched_counts_error(self):
        """Should error on mismatched counts."""
        with pytest.raises(ValueError, match="count"):
            parse_manual_gainers(
                tickers_str="AAPL,MSFT,NVDA",
                changes_str="15.5,12.3",  # Missing one
            )

    def test_mismatched_price_count_error(self):
        """Should error on mismatched price count."""
        with pytest.raises(ValueError, match="count"):
            parse_manual_gainers(
                tickers_str="AAPL,MSFT",
                changes_str="15.5,12.3",
                prices_str="150.00",  # Missing one
            )
