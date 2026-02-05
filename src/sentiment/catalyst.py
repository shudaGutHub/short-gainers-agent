"""
Sentiment and catalyst analysis module.

Uses Claude to classify news catalysts and determine if price moves
are justified by fundamentals or speculative.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from src.clients.claude_client import ClaudeClient
from src.models.candidate import (
    CatalystClassification,
    NewsAssessment,
    RiskFlag,
    SentimentLevel,
)
from src.models.ticker import NewsFeed


# -----------------------------------------------------------------------------
# Score adjustments based on catalyst type
# -----------------------------------------------------------------------------

# Adjustments to technical score based on catalyst
# Positive = worse for shorting (penalize), Negative = better for shorting (boost)
CATALYST_SCORE_ADJUSTMENTS: dict[CatalystClassification, float] = {
    # Fundamental repricing - dangerous to short
    CatalystClassification.EARNINGS: -3.0,      # Strong earnings = don't short
    CatalystClassification.FDA: -4.0,           # FDA approval = regime change
    CatalystClassification.MA: -5.0,            # M&A = price floor established
    CatalystClassification.UPGRADE: -2.0,       # Analyst upgrade = institutional support
    CatalystClassification.CONTRACT: -1.5,      # Contract win = some fundamental support
    
    # Speculative - better short candidates
    CatalystClassification.SPECULATIVE: 1.5,    # Vague PR = good short
    CatalystClassification.MEME_SOCIAL: 2.0,    # Meme pump = excellent short (but risky)
    CatalystClassification.UNKNOWN: 0.5,        # No clear catalyst = slight boost
}

# Additional adjustment based on sentiment mismatch
# If sentiment doesn't match the move, it's suspicious
SENTIMENT_ADJUSTMENTS: dict[SentimentLevel, float] = {
    SentimentLevel.STRONGLY_POSITIVE: -1.0,  # Strong positive sentiment = caution
    SentimentLevel.POSITIVE: -0.5,
    SentimentLevel.MIXED: 0.5,               # Mixed sentiment on big up move = good
    SentimentLevel.NEGATIVE: 1.0,            # Negative sentiment on up move = very good
    SentimentLevel.STRONGLY_NEGATIVE: 1.5,
}


@dataclass
class SentimentResult:
    """Result of sentiment analysis for a ticker."""
    
    ticker: str
    assessment: Optional[NewsAssessment]
    score_adjustment: float
    raw_adjustment: float  # Before capping
    analysis_source: str  # "claude", "heuristic", or "none"
    error: Optional[str] = None
    
    @property
    def is_fundamental_repricing(self) -> bool:
        """Check if this appears to be fundamental repricing."""
        if self.assessment is None:
            return False
        return self.assessment.justifies_repricing
    
    @property
    def catalyst_type(self) -> Optional[CatalystClassification]:
        """Get catalyst type if available."""
        if self.assessment is None:
            return None
        return self.assessment.catalyst_type


def compute_score_adjustment(assessment: NewsAssessment) -> tuple[float, float]:
    """
    Compute score adjustment based on news assessment.
    
    Args:
        assessment: NewsAssessment from Claude or heuristics
        
    Returns:
        Tuple of (capped_adjustment, raw_adjustment)
    """
    raw = 0.0
    
    # Base adjustment from catalyst type
    catalyst_adj = CATALYST_SCORE_ADJUSTMENTS.get(assessment.catalyst_type, 0.0)
    raw += catalyst_adj
    
    # Adjustment from sentiment
    sentiment_adj = SENTIMENT_ADJUSTMENTS.get(assessment.sentiment, 0.0)
    raw += sentiment_adj
    
    # If justifies repricing, additional penalty
    if assessment.justifies_repricing:
        raw -= 2.0
    
    # Scale by confidence (already 0.0 to 1.0)
    confidence_scale = float(assessment.confidence)
    raw *= confidence_scale
    
    # Cap adjustment to [-5, +3] range
    capped = max(-5.0, min(3.0, raw))
    
    return capped, raw


# -----------------------------------------------------------------------------
# Heuristic fallback when Claude unavailable
# -----------------------------------------------------------------------------

def heuristic_catalyst_detection(
    headlines: list[str],
    change_percent: Decimal,
) -> NewsAssessment:
    """
    Simple keyword-based catalyst detection as fallback.
    
    Args:
        headlines: List of news headlines
        change_percent: Today's percentage change
        
    Returns:
        NewsAssessment with heuristic classification
    """
    text = " ".join(headlines).lower()
    
    # Check for fundamental catalysts
    earnings_keywords = ["earnings", "eps", "revenue", "profit", "beat", "miss", "guidance"]
    fda_keywords = ["fda", "approval", "approved", "clinical", "trial", "phase"]
    ma_keywords = ["merger", "acquisition", "acquire", "buyout", "takeover", "deal"]
    upgrade_keywords = ["upgrade", "price target", "outperform", "buy rating"]
    contract_keywords = ["contract", "award", "partnership", "agreement", "deal"]
    
    # Check for speculative catalysts
    meme_keywords = ["reddit", "wsb", "squeeze", "moon", "apes", "yolo"]
    speculative_keywords = ["potential", "could", "may", "exploring", "considering"]
    
    catalyst = CatalystClassification.UNKNOWN
    sentiment = SentimentLevel.MIXED
    justifies = False
    summary = "No clear catalyst identified"
    
    # Priority order for detection
    if any(kw in text for kw in fda_keywords):
        catalyst = CatalystClassification.FDA
        sentiment = SentimentLevel.STRONGLY_POSITIVE
        justifies = True
        summary = "FDA/clinical news detected"
    elif any(kw in text for kw in ma_keywords):
        catalyst = CatalystClassification.MA
        sentiment = SentimentLevel.STRONGLY_POSITIVE
        justifies = True
        summary = "M&A activity detected"
    elif any(kw in text for kw in earnings_keywords):
        catalyst = CatalystClassification.EARNINGS
        sentiment = SentimentLevel.POSITIVE
        justifies = True
        summary = "Earnings-related news detected"
    elif any(kw in text for kw in upgrade_keywords):
        catalyst = CatalystClassification.UPGRADE
        sentiment = SentimentLevel.POSITIVE
        justifies = False  # Upgrades don't always justify
        summary = "Analyst upgrade detected"
    elif any(kw in text for kw in contract_keywords):
        catalyst = CatalystClassification.CONTRACT
        sentiment = SentimentLevel.POSITIVE
        justifies = False  # Depends on contract size
        summary = "Contract/partnership news detected"
    elif any(kw in text for kw in meme_keywords):
        catalyst = CatalystClassification.MEME_SOCIAL
        sentiment = SentimentLevel.MIXED
        justifies = False
        summary = "Social/meme activity detected"
    elif any(kw in text for kw in speculative_keywords):
        catalyst = CatalystClassification.SPECULATIVE
        sentiment = SentimentLevel.MIXED
        justifies = False
        summary = "Speculative/vague PR detected"
    
    # Adjust sentiment based on move size
    if float(change_percent) > 50 and not justifies:
        sentiment = SentimentLevel.MIXED  # Big move without clear catalyst is suspicious
    
    return NewsAssessment(
        catalyst_type=catalyst,
        sentiment=sentiment,
        summary=summary,
        justifies_repricing=justifies,
        confidence=Decimal("0.5"),  # Heuristics are low confidence
    )


# -----------------------------------------------------------------------------
# Main analysis functions
# -----------------------------------------------------------------------------

async def analyze_catalyst(
    ticker: str,
    change_percent: Decimal,
    news_feed: Optional[NewsFeed],
    claude_client: Optional[ClaudeClient],
) -> SentimentResult:
    """
    Analyze news catalyst for a ticker.
    
    Uses Claude if available, falls back to heuristics.
    
    Args:
        ticker: Stock symbol
        change_percent: Today's percentage change
        news_feed: NewsFeed with headlines (may be None)
        claude_client: ClaudeClient instance (may be None)
        
    Returns:
        SentimentResult with assessment and score adjustment
    """
    # No news available
    if news_feed is None or len(news_feed.items) == 0:
        return SentimentResult(
            ticker=ticker,
            assessment=NewsAssessment(
                catalyst_type=CatalystClassification.UNKNOWN,
                sentiment=SentimentLevel.MIXED,
                summary="No news available",
                justifies_repricing=False,
                confidence=Decimal("0.2"),
            ),
            score_adjustment=0.5,  # Slight boost - no news on big move is suspicious
            raw_adjustment=0.5,
            analysis_source="none",
        )
    
    # Try Claude first
    if claude_client is not None:
        try:
            assessment = await claude_client.analyze_news(
                ticker=ticker,
                change_percent=change_percent,
                news_feed=news_feed,
            )
            
            capped_adj, raw_adj = compute_score_adjustment(assessment)
            
            return SentimentResult(
                ticker=ticker,
                assessment=assessment,
                score_adjustment=capped_adj,
                raw_adjustment=raw_adj,
                analysis_source="claude",
            )
        except Exception as e:
            # Fall through to heuristics
            pass
    
    # Fallback to heuristics
    headlines = [item.title for item in news_feed.items[:10]]
    assessment = heuristic_catalyst_detection(headlines, change_percent)
    
    capped_adj, raw_adj = compute_score_adjustment(assessment)
    
    return SentimentResult(
        ticker=ticker,
        assessment=assessment,
        score_adjustment=capped_adj,
        raw_adjustment=raw_adj,
        analysis_source="heuristic",
    )


async def analyze_catalysts_batch(
    tickers_with_news: list[tuple[str, Decimal, Optional[NewsFeed]]],
    claude_client: Optional[ClaudeClient],
) -> dict[str, SentimentResult]:
    """
    Analyze catalysts for multiple tickers.
    
    Args:
        tickers_with_news: List of (ticker, change_percent, news_feed) tuples
        claude_client: ClaudeClient instance
        
    Returns:
        Dict mapping ticker to SentimentResult
    """
    results = {}
    
    for ticker, change_pct, news_feed in tickers_with_news:
        result = await analyze_catalyst(
            ticker=ticker,
            change_percent=change_pct,
            news_feed=news_feed,
            claude_client=claude_client,
        )
        results[ticker] = result
    
    return results


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def should_avoid_short(result: SentimentResult) -> bool:
    """
    Determine if sentiment analysis suggests avoiding the short.
    
    Returns True if:
    - Fundamental repricing detected with high confidence
    - Score adjustment is very negative (< -3)
    """
    if result.assessment is None:
        return False
    
    # High-confidence fundamental repricing (0.7 = 70%)
    if result.is_fundamental_repricing and float(result.assessment.confidence) >= 0.7:
        return True
    
    # Very negative adjustment
    if result.score_adjustment <= -3.0:
        return True
    
    return False


def get_risk_flag_from_sentiment(result: SentimentResult) -> Optional[RiskFlag]:
    """
    Get risk flag based on sentiment analysis.
    
    Returns:
        RiskFlag.FUNDAMENTAL_REPRICING if applicable, else None
    """
    if result.is_fundamental_repricing:
        return RiskFlag.FUNDAMENTAL_REPRICING
    return None


def format_catalyst_summary(result: SentimentResult) -> str:
    """
    Format a concise catalyst summary for reports.
    
    Returns:
        String like "EARNINGS: Beat estimates [positive] (adj: -2.5)"
    """
    if result.assessment is None:
        return "No analysis available"
    
    a = result.assessment
    sentiment_str = a.sentiment.value.replace("_", " ")
    
    return (
        f"{a.catalyst_type.value}: {a.summary} "
        f"[{sentiment_str}] (adj: {result.score_adjustment:+.1f})"
    )
