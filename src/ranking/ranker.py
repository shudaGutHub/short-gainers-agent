"""
Ranking module for short candidates.

Combines technical scores with sentiment adjustments and risk penalties
to produce final ranked candidates.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from src.filters.prefilter import has_dangerous_risk_profile
from src.models.candidate import (
    KeyLevels,
    RiskFlag,
    ShortCandidate,
    TechnicalState,
    TradeExpression,
)
from src.sentiment.catalyst import SentimentResult, get_risk_flag_from_sentiment


# -----------------------------------------------------------------------------
# Risk penalties applied to final score
# -----------------------------------------------------------------------------

RISK_PENALTIES: dict[RiskFlag, float] = {
    RiskFlag.MICROCAP: 1.0,
    RiskFlag.HIGH_SQUEEZE: 2.0,
    RiskFlag.LOW_LIQUIDITY: 0.5,
    RiskFlag.EXTREME_VOLATILITY: 1.5,
    RiskFlag.FUNDAMENTAL_REPRICING: 3.0,
    RiskFlag.NONE: 0.0,
}


@dataclass
class RankingInput:
    """Input data for ranking a single candidate."""
    
    ticker: str
    current_price: Decimal
    change_percent: Decimal
    tech_score: Decimal
    tech_state: TechnicalState
    sentiment_result: SentimentResult
    risk_flags: list[RiskFlag]
    key_levels: KeyLevels
    market_cap: Optional[int] = None
    avg_volume: Optional[int] = None
    beta: Optional[Decimal] = None


@dataclass 
class RankingResult:
    """Result of ranking calculation."""
    
    ticker: str
    final_score: Decimal
    tech_score: Decimal
    sentiment_adjustment: float
    risk_penalty: float
    expression: TradeExpression
    candidate: ShortCandidate


def compute_risk_penalty(risk_flags: list[RiskFlag]) -> float:
    """
    Compute total risk penalty from flags.
    
    Args:
        risk_flags: List of risk flags
        
    Returns:
        Total penalty (higher = worse for shorting)
    """
    penalty = 0.0
    seen = set()
    
    for flag in risk_flags:
        if flag not in seen:
            penalty += RISK_PENALTIES.get(flag, 0.0)
            seen.add(flag)
    
    return penalty


def determine_expression(
    final_score: float,
    risk_flags: list[RiskFlag],
    beta: Optional[Decimal],
    sentiment_result: SentimentResult,
    max_beta_for_shares: float = 3.0,
) -> TradeExpression:
    """
    Determine recommended trade expression.
    
    Args:
        final_score: Computed final score
        risk_flags: List of risk flags
        beta: Stock beta
        sentiment_result: Sentiment analysis result
        max_beta_for_shares: Max beta for direct shorting
        
    Returns:
        TradeExpression enum
    """
    flags_set = set(risk_flags)
    
    # Check for dangerous combinations
    if has_dangerous_risk_profile_from_flags(flags_set):
        return TradeExpression.AVOID
    
    # Check sentiment
    if sentiment_result.is_fundamental_repricing:
        if float(sentiment_result.assessment.confidence) >= 0.7:
            return TradeExpression.AVOID
    
    # Score too low
    if final_score < 3.0:
        return TradeExpression.AVOID
    
    # High squeeze risk - use options
    if RiskFlag.HIGH_SQUEEZE in flags_set:
        return TradeExpression.BUY_PUTS
    
    # High volatility - use options
    if RiskFlag.EXTREME_VOLATILITY in flags_set:
        return TradeExpression.PUT_SPREADS
    
    # Check beta
    if beta is not None:
        beta_val = float(beta)
        if beta_val > max_beta_for_shares * 1.5:
            return TradeExpression.AVOID
        elif beta_val > max_beta_for_shares:
            return TradeExpression.BUY_PUTS
    
    # Microcap - prefer defined risk
    if RiskFlag.MICROCAP in flags_set:
        return TradeExpression.PUT_SPREADS
    
    # Default to shares for clean setups
    return TradeExpression.SHORT_SHARES


def has_dangerous_risk_profile_from_flags(flags: set[RiskFlag]) -> bool:
    """Check if flag combination is dangerous."""
    dangerous_combos = [
        {RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE},
        {RiskFlag.HIGH_SQUEEZE, RiskFlag.EXTREME_VOLATILITY},
        {RiskFlag.MICROCAP, RiskFlag.HIGH_SQUEEZE, RiskFlag.LOW_LIQUIDITY},
    ]
    
    for combo in dangerous_combos:
        if combo.issubset(flags):
            return True
    
    return False


def rank_candidate(
    input_data: RankingInput,
    max_beta_for_shares: float = 3.0,
) -> RankingResult:
    """
    Rank a single candidate and produce ShortCandidate.
    
    Args:
        input_data: RankingInput with all analysis data
        max_beta_for_shares: Max beta for direct shorting
        
    Returns:
        RankingResult with final score and candidate
    """
    # Start with technical score
    tech_score = float(input_data.tech_score)
    
    # Add sentiment adjustment
    sentiment_adj = input_data.sentiment_result.score_adjustment
    
    # Compute risk penalty
    risk_flags = list(input_data.risk_flags)
    
    # Add sentiment-derived risk flag if applicable
    sentiment_flag = get_risk_flag_from_sentiment(input_data.sentiment_result)
    if sentiment_flag and sentiment_flag not in risk_flags:
        risk_flags.append(sentiment_flag)
    
    risk_penalty = compute_risk_penalty(risk_flags)
    
    # Final score calculation
    raw_final = tech_score + sentiment_adj - risk_penalty
    final_score = max(0.0, min(10.0, raw_final))
    
    # Determine expression
    expression = determine_expression(
        final_score=final_score,
        risk_flags=risk_flags,
        beta=input_data.beta,
        sentiment_result=input_data.sentiment_result,
        max_beta_for_shares=max_beta_for_shares,
    )
    
    # Build ShortCandidate
    candidate = ShortCandidate(
        ticker=input_data.ticker,
        current_price=input_data.current_price,
        change_percent=input_data.change_percent,
        final_score=Decimal(str(round(final_score, 1))),
        tech_score=input_data.tech_score,
        news_adjustment=Decimal(str(round(sentiment_adj, 2))),
        news_assessment=input_data.sentiment_result.assessment,
        technical_state=input_data.tech_state,
        risk_flags=risk_flags if risk_flags else [RiskFlag.NONE],
        preferred_expression=expression,
        key_levels=input_data.key_levels,
        market_cap=input_data.market_cap,
        avg_volume=input_data.avg_volume,
    )
    
    return RankingResult(
        ticker=input_data.ticker,
        final_score=Decimal(str(round(final_score, 1))),
        tech_score=input_data.tech_score,
        sentiment_adjustment=sentiment_adj,
        risk_penalty=risk_penalty,
        expression=expression,
        candidate=candidate,
    )


def rank_candidates_batch(
    inputs: list[RankingInput],
    max_beta_for_shares: float = 3.0,
) -> list[RankingResult]:
    """
    Rank multiple candidates and sort by final score.
    
    Args:
        inputs: List of RankingInput
        max_beta_for_shares: Max beta for direct shorting
        
    Returns:
        List of RankingResult, sorted descending by final_score
    """
    results = []
    
    for input_data in inputs:
        result = rank_candidate(input_data, max_beta_for_shares)
        results.append(result)
    
    # Sort by final score descending (best shorts first)
    results.sort(key=lambda r: float(r.final_score), reverse=True)
    
    return results


def get_top_candidates(
    results: list[RankingResult],
    min_score: float = 4.0,
    exclude_avoid: bool = True,
) -> list[ShortCandidate]:
    """
    Get top candidates above minimum score threshold.
    
    Args:
        results: Ranked results
        min_score: Minimum final score to include
        exclude_avoid: Whether to exclude AVOID expression
        
    Returns:
        List of ShortCandidate meeting criteria
    """
    candidates = []
    
    for result in results:
        if float(result.final_score) < min_score:
            continue
        
        if exclude_avoid and result.expression == TradeExpression.AVOID:
            continue
        
        candidates.append(result.candidate)
    
    return candidates


def summarize_rankings(results: list[RankingResult]) -> dict:
    """
    Produce summary statistics for rankings.
    
    Args:
        results: List of ranking results
        
    Returns:
        Dict with summary stats
    """
    if not results:
        return {
            "total": 0,
            "avg_score": 0.0,
            "actionable": 0,
            "avoid": 0,
            "by_expression": {},
        }
    
    scores = [float(r.final_score) for r in results]
    expressions = {}
    
    for r in results:
        exp = r.expression.value
        expressions[exp] = expressions.get(exp, 0) + 1
    
    actionable = sum(1 for r in results if r.expression != TradeExpression.AVOID)
    
    return {
        "total": len(results),
        "avg_score": sum(scores) / len(scores),
        "max_score": max(scores),
        "min_score": min(scores),
        "actionable": actionable,
        "avoid": expressions.get("AVOID", 0),
        "by_expression": expressions,
    }
