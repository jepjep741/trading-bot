"""Market regime detection using BTC and ETH as proxies.

BULL      — both proxies up more than threshold over the lookback window
BEAR      — both down more than threshold; new buys are blocked
DIVERGING — proxies moving in opposite directions beyond threshold;
            confidence is capped so the bot defaults to holding
RANGING   — everything else; confidence thresholds are raised
"""
from __future__ import annotations

from dataclasses import dataclass

from .market_data import MarketData

BULL = "BULL"
BEAR = "BEAR"
RANGING = "RANGING"
DIVERGING = "DIVERGING"


@dataclass
class Regime:
    name: str
    proxy_changes: dict[str, float]


def classify_changes(changes: list[float], threshold: float) -> str:
    if all(c > threshold for c in changes):
        return BULL
    if all(c < -threshold for c in changes):
        return BEAR
    if (max(changes) > threshold and min(changes) < -threshold):
        return DIVERGING
    return RANGING


def detect(md: MarketData, proxies: list[str], lookback_days: int,
           threshold_pct: float) -> Regime:
    changes = {p: md.change_pct(p, lookback_days) for p in proxies}
    name = classify_changes(list(changes.values()), threshold_pct)
    return Regime(name=name, proxy_changes=changes)


def adjust_confidence(confidence: float, action: str, regime: str) -> tuple[float, str | None]:
    """Apply regime rules. Returns (adjusted_confidence, block_reason_or_None)."""
    if regime == BEAR and action == "buy":
        return confidence, "BEAR regime: new buys blocked (capital protection)"
    if regime == DIVERGING:
        return min(confidence, 0.50), None
    if regime == RANGING and action == "buy":
        return confidence - 0.05, None
    if regime == BULL and action == "buy":
        return min(confidence + 0.05, 1.0), None
    return confidence, None
