"""Configuration management for Short Gainers Agent."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API Keys
    alpha_vantage_api_key: str = Field(
        default="",
        description="Alpha Vantage API key",
    )

    # Rate Limiting
    api_rate_limit_per_minute: int = Field(
        default=5,
        description="Max API calls per minute (Alpha Vantage free tier = 5)",
    )
    api_call_delay_seconds: float = Field(
        default=12.5,
        description="Delay between API calls in seconds",
    )

    # Caching
    cache_enabled: bool = Field(default=True)
    cache_ttl_seconds: int = Field(
        default=300,
        description="Cache time-to-live in seconds (5 minutes)",
    )
    cache_directory: Path = Field(
        default=Path(".cache"),
        description="Directory for file-based cache",
    )

    # Analysis Thresholds
    min_market_cap: float = Field(
        default=200_000_000,
        description="Minimum market cap for analysis ($200M)",
    )
    min_volume: int = Field(
        default=100_000,
        description="Minimum average volume",
    )
    min_change_percent: float = Field(
        default=10.0,
        description="Minimum % change to consider for analysis",
    )

    # Scoring Thresholds
    actionable_score_threshold: float = Field(
        default=6.0,
        description="Minimum score to be considered actionable",
    )
    high_score_threshold: float = Field(
        default=7.5,
        description="Score threshold for high-conviction picks",
    )

    # Output
    output_directory: Path = Field(
        default=Path("./output"),
        description="Default output directory for reports",
    )
    dashboard_template: str = Field(
        default="dashboard.html",
        description="Jinja2 template name for dashboard",
    )

    # Logging
    log_level: str = Field(default="INFO")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        self.output_directory.mkdir(parents=True, exist_ok=True)


class ScoringConfig(BaseSettings):
    """Scoring algorithm configuration."""

    model_config = SettingsConfigDict(env_prefix="SCORING_")

    # Technical Score Components (max total = 10.0)
    rsi_max: float = 2.5
    bollinger_max: float = 2.5
    change_max: float = 2.5
    reversal_max: float = 2.5

    # RSI Thresholds -> Score
    rsi_extreme: float = 90.0  # -> 2.5
    rsi_high: float = 80.0  # -> 2.0
    rsi_elevated: float = 70.0  # -> 1.5
    rsi_moderate: float = 60.0  # -> 1.0

    # Bollinger Position Thresholds (% above upper band)
    bb_extreme: float = 80.0  # -> 2.5
    bb_high: float = 50.0  # -> 2.0
    bb_elevated: float = 20.0  # -> 1.5
    bb_moderate: float = 0.0  # -> 1.0

    # Change % Thresholds
    change_extreme: float = 100.0  # -> 2.5
    change_high: float = 50.0  # -> 2.0
    change_elevated: float = 25.0  # -> 1.5
    change_moderate: float = 10.0  # -> 1.0

    # Sentiment Adjustments
    sentiment_no_catalyst: float = 2.0
    sentiment_speculative: float = 1.5
    sentiment_meme: float = 1.0
    sentiment_fundamental: float = -2.0

    # Risk Penalties
    penalty_high_squeeze: float = -2.0
    penalty_extreme_volatility: float = -1.5
    penalty_microcap: float = -1.0
    penalty_low_liquidity: float = -0.5
    penalty_non_nasdaq: float = -0.8
    penalty_new_listing: float = -5.0
    penalty_fundamental_catalyst: float = -3.0


class RiskConfig(BaseSettings):
    """Risk detection configuration."""

    model_config = SettingsConfigDict(env_prefix="RISK_")

    # HIGH_SQUEEZE detection
    squeeze_change_threshold: float = 200.0  # % change
    squeeze_ipo_days: int = 90  # Days since IPO

    # EXTREME_VOLATILITY detection
    volatility_atr_multiplier: float = 5.0  # ATR expansion threshold
    volatility_daily_change: float = 50.0  # % daily move

    # MICROCAP detection
    microcap_threshold: float = 300_000_000  # $300M

    # LOW_LIQUIDITY detection
    low_volume_threshold: int = 100_000  # Average daily volume

    # NEW_LISTING detection
    new_listing_days: int = 90  # Days since IPO


@lru_cache
def get_config() -> Config:
    """Get cached configuration instance."""
    return Config()


@lru_cache
def get_scoring_config() -> ScoringConfig:
    """Get cached scoring configuration."""
    return ScoringConfig()


@lru_cache
def get_risk_config() -> RiskConfig:
    """Get cached risk configuration."""
    return RiskConfig()
