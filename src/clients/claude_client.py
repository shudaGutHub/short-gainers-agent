"""
Claude API client for news sentiment analysis.

Uses httpx for direct API calls to Anthropic.
"""

import json
from decimal import Decimal
from typing import Optional

import httpx

from src.models.candidate import CatalystClassification, NewsAssessment, SentimentLevel
from src.models.ticker import NewsFeed


class ClaudeClientError(Exception):
    """Base exception for Claude API errors."""

    pass


CATALYST_ANALYSIS_PROMPT = """Analyze these news headlines for ticker {ticker} which gained {pct_change:.1f}% today.

Headlines (most recent first):
{headlines}

Your task: Determine what is driving this stock move and whether it justifies a permanent valuation change.

Respond ONLY with valid JSON (no markdown, no explanation):
{{
  "catalyst_type": "<one of: EARNINGS, FDA, MA, UPGRADE, DOWNGRADE, CONTRACT, PRODUCT_LAUNCH, SPECULATIVE, MEME_SOCIAL, UNKNOWN>",
  "sentiment": "<one of: strongly_positive, positive, mixed, negative, strongly_negative>",
  "summary": "<one sentence describing the catalyst, max 100 chars>",
  "justifies_repricing": <true if this news justifies a permanent valuation change, false if speculative/temporary>,
  "confidence": <0.0 to 1.0, your confidence in this assessment>
}}

Guidelines:
- EARNINGS: Quarterly results, revenue/profit beats or misses
- FDA: Drug approvals, clinical trial results, regulatory decisions
- MA: Merger, acquisition, buyout announcements
- UPGRADE/DOWNGRADE: Analyst rating changes
- CONTRACT: Major business wins, partnerships
- PRODUCT_LAUNCH: New product announcements
- SPECULATIVE: Vague PR, rumors, no clear fundamental driver
- MEME_SOCIAL: Social media driven, retail squeeze patterns
- UNKNOWN: Cannot determine catalyst

justifies_repricing should be TRUE for:
- Strong earnings beats with raised guidance
- FDA approvals for major drugs
- Confirmed M&A at premium
- Major contract wins that materially change revenue outlook

justifies_repricing should be FALSE for:
- Vague press releases without numbers
- Social media hype without fundamental news
- Minor partnerships or early-stage announcements
- Analyst upgrades without new information"""


class ClaudeClient:
    """
    Async client for Anthropic Claude API.

    Used specifically for news sentiment analysis.
    """

    BASE_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 500,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "ClaudeClient":
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()

    async def analyze_news(
        self,
        ticker: str,
        pct_change: Decimal,
        news_feed: NewsFeed,
    ) -> NewsAssessment:
        """
        Analyze news to classify catalyst and assess sentiment.

        Args:
            ticker: Stock symbol
            pct_change: Today's percentage change
            news_feed: NewsFeed with recent articles

        Returns:
            NewsAssessment with catalyst classification
        """
        if not news_feed.items:
            return NewsAssessment(
                catalyst_type=CatalystType.UNKNOWN,
                sentiment=SentimentLevel.MIXED,
                summary="No recent news found",
                justifies_repricing=False,
                confidence=Decimal("0.3"),
            )

        # Format headlines for prompt
        headlines = "\n".join(
            f"- [{item.source}] {item.title}"
            for item in news_feed.items[:10]  # Limit to 10 most recent
        )

        prompt = CATALYST_ANALYSIS_PROMPT.format(
            ticker=ticker,
            pct_change=float(pct_change),
            headlines=headlines,
        )

        try:
            response = await self._call_api(prompt)
            return self._parse_response(response)
        except Exception as e:
            # Return conservative default on any error
            return NewsAssessment(
                catalyst_type=CatalystType.UNKNOWN,
                sentiment=SentimentLevel.MIXED,
                summary=f"Analysis failed: {str(e)[:50]}",
                justifies_repricing=False,
                confidence=Decimal("0.1"),
            )

    async def _call_api(self, prompt: str) -> str:
        """Make API call to Claude."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        response = await self._client.post(
            self.BASE_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

        data = response.json()
        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0]["text"]

        raise ClaudeClientError("Unexpected response format")

    def _parse_response(self, response_text: str) -> NewsAssessment:
        """Parse Claude's JSON response into NewsAssessment."""
        # Clean potential markdown formatting
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ClaudeClientError(f"Invalid JSON response: {e}")

        # Map string values to enums
        catalyst_str = data.get("catalyst_type", "UNKNOWN").upper()
        try:
            catalyst = CatalystClassification(catalyst_str)
        except ValueError:
            catalyst = CatalystClassification.UNKNOWN

        sentiment_str = data.get("sentiment", "mixed").lower()
        try:
            sentiment = SentimentLevel(sentiment_str)
        except ValueError:
            sentiment = SentimentLevel.MIXED

        return NewsAssessment(
            catalyst_type=catalyst,
            sentiment=sentiment,
            summary=data.get("summary", "")[:100],
            justifies_repricing=bool(data.get("justifies_repricing", False)),
            confidence=Decimal(str(data.get("confidence", 0.5))),
        )
