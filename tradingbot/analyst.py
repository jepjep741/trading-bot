"""Optional Claude analyst: reviews a technical signal against recent market
data and returns a refined action/confidence with plain-English reasoning.

Only used when an ANTHROPIC_API_KEY is available (or analyst.enabled: true).
The technical signal always remains the fallback if the API call fails.
"""
from __future__ import annotations

import json

import anthropic

from .strategy import Signal

SYSTEM = """You are the decision layer of a crypto paper-trading bot.
You receive one asset's technical signal (SMA crossover), recent OHLCV candles,
the current market regime, and the bot's open position in the asset if any.

Evaluate whether the proposed action is justified. Consider trend quality,
volume, recent volatility, and the regime. Be conservative: prefer hold over a
weak buy, and prefer closing early over riding deteriorating momentum.
Confidence is your probability that the action will be profitable within the
tier's take-profit horizon."""

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["action", "confidence", "reasoning"],
    "additionalProperties": False,
}


class Analyst:
    def __init__(self, model: str):
        self.client = anthropic.Anthropic()
        self.model = model

    def review(self, symbol: str, tier: str, regime: str, technical: Signal,
               candles: list[list[float]], position: dict | None) -> Signal:
        payload = {
            "symbol": symbol,
            "tier": tier,
            "market_regime": regime,
            "technical_signal": {
                "action": technical.action,
                "confidence": round(technical.confidence, 3),
                "reasoning": technical.reasoning,
            },
            "open_position": position,
            "recent_candles_ohlcv": [
                [round(v, 8) for v in c[1:]] for c in candles[-30:]
            ],
        }
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                thinking={"type": "adaptive"},
                system=SYSTEM,
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": json.dumps(payload)}],
            )
            if response.stop_reason == "refusal":
                return technical
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            conf = max(0.0, min(float(data["confidence"]), 1.0))
            return Signal(data["action"], conf, technical.price,
                          f"[claude] {data['reasoning']}")
        except Exception as exc:  # network/auth/parse — fall back to technicals
            print(f"  analyst unavailable for {symbol}: {exc}")
            return technical
