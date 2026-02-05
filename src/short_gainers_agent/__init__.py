"""Short Gainers Agent - Autonomous trading research for short opportunities."""

from .agent import Agent, analyze_symbol
from .config import Config, get_config
from .data.models import (
    AnalysisResult,
    BatchResult,
    CatalystClassification,
    Quote,
    RiskFlag,
    TradeExpression,
)

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "analyze_symbol",
    "Config",
    "get_config",
    "AnalysisResult",
    "BatchResult",
    "Quote",
    "RiskFlag",
    "TradeExpression",
    "CatalystClassification",
]
