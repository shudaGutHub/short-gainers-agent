"""
Configuration settings for the short gainers agent.

Uses pydantic-settings for environment variable loading and validation.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API Keys
    alpha_vantage_api_key: str
    anthropic_api_key: str

    # Cache
    cache_db_path: Path = Path("./data/cache.duckdb")

    # Rate Limiting
    av_rate_limit_rpm: int = 75
    av_request_delay_seconds: float = 0.8  # ~75/min with buffer

    # Pre-filter Thresholds
    min_market_cap: int = 200_000_000  # $200M
    min_avg_volume: int = 500_000  # shares/day
    max_beta_for_shares: float = 3.0  # above this, prefer puts

    # Technical Indicator Parameters
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_extremely_overbought: int = 80
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_window: int = 20
    bollinger_std: float = 2.0
    atr_period: int = 14

    # Data Parameters
    lookback_days: int = 60
    intraday_interval: str = "15min"

    # Scoring Weights (sum to 1.0)
    weight_rsi: float = 0.20
    weight_bollinger: float = 0.20
    weight_macd: float = 0.15
    weight_volume: float = 0.15
    weight_momentum: float = 0.15
    weight_pattern: float = 0.15

    # Claude Sentiment
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 500


class Thresholds:
    """Named thresholds for readability in scoring logic."""

    # Risk flags
    MICROCAP_THRESHOLD = 200_000_000
    LOW_FLOAT_THRESHOLD = 10_000_000
    HIGH_BETA_THRESHOLD = 2.5

    # Technical scores (0-10 scale)
    RSI_SCORE_MAX = 2.0  # contribution when RSI > 80
    BOLLINGER_SCORE_MAX = 2.0  # contribution when price > upper band
    VOLUME_DIVERGENCE_BONUS = 1.5  # when price up but volume fading

    # Score adjustments
    FUNDAMENTAL_REPRICING_PENALTY = -3.0
    SPECULATIVE_CATALYST_BONUS = 1.5
    HIGH_SQUEEZE_PENALTY = -2.0


def get_settings() -> Settings:
    """Factory function to create settings instance."""
    return Settings()
