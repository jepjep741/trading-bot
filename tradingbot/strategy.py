"""SMA-crossover signal with a heuristic confidence score.

The confidence score (0..1) starts at 0.5 on a fresh crossover and is nudged
by trend slope, MA separation, and volume vs. its recent average. The regime
layer then adjusts it further before it is compared to the tier threshold.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Signal:
    action: str          # buy | sell | hold
    confidence: float
    price: float
    reasoning: str


def sma(values: list[float], period: int) -> list[float]:
    out = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(float("nan"))
        else:
            out.append(sum(values[i + 1 - period:i + 1]) / period)
    return out


def evaluate(candles: list[list[float]], fast_period: int, slow_period: int) -> Signal:
    closes = [c[4] for c in candles]
    volumes = [c[5] for c in candles]
    if len(closes) < slow_period + 2:
        return Signal("hold", 0.0, closes[-1] if closes else 0.0,
                      "not enough history to compute moving averages")

    fast = sma(closes, fast_period)
    slow = sma(closes, slow_period)
    price = closes[-1]

    prev_diff = fast[-2] - slow[-2]
    curr_diff = fast[-1] - slow[-1]

    crossed_up = prev_diff <= 0 and curr_diff > 0
    crossed_down = prev_diff >= 0 and curr_diff < 0

    # supporting evidence
    separation = abs(curr_diff) / price                       # MA gap, fraction of price
    slope = (fast[-1] - fast[-3]) / fast[-3] if fast[-3] else 0.0
    vol_avg = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else (sum(volumes) / len(volumes))
    vol_ratio = volumes[-1] / vol_avg if vol_avg else 1.0

    def score(direction: int) -> float:
        s = 0.5
        s += min(separation * 40, 0.15)                       # up to +0.15
        s += max(min(slope * direction * 20, 0.15), -0.10)    # trend agrees / disagrees
        if vol_ratio > 1.2:
            s += 0.10                                         # volume confirmation
        return max(0.0, min(s, 1.0))

    if crossed_up:
        conf = score(+1)
        return Signal("buy", conf, price,
                      f"SMA{fast_period} crossed above SMA{slow_period} "
                      f"(gap {separation:.3%}, fast-MA slope {slope:+.3%}, "
                      f"volume {vol_ratio:.1f}x its 20-candle average)")
    if crossed_down:
        conf = score(-1)
        return Signal("sell", conf, price,
                      f"SMA{fast_period} crossed below SMA{slow_period} "
                      f"(gap {separation:.3%}, fast-MA slope {slope:+.3%}, "
                      f"volume {vol_ratio:.1f}x its 20-candle average)")

    trend = "above" if curr_diff > 0 else "below"
    return Signal("hold", 0.0, price,
                  f"no crossover; SMA{fast_period} is {trend} SMA{slow_period}")


def volume_spike_scan(candles_30m: list[list[float]], daily_candles: list[list[float]],
                      spike_ratio: float, green_needed: int) -> tuple[bool, str]:
    """Tier-3 scanner: 24h volume spike vs 7d average + N consecutive green 30m candles."""
    if len(daily_candles) < 8 or len(candles_30m) < green_needed + 1:
        return False, "not enough history"
    week = daily_candles[-8:-1]
    avg_daily_vol = sum(c[5] for c in week) / len(week)
    today_vol = daily_candles[-1][5]
    ratio = today_vol / avg_daily_vol if avg_daily_vol else 0.0

    # ignore the still-forming last candle, check the N before it
    recent = candles_30m[-(green_needed + 1):-1]
    greens = all(c[4] > c[1] for c in recent)

    if ratio >= spike_ratio and greens:
        return True, (f"volume {ratio:.1f}x 7-day average with "
                      f"{green_needed} consecutive green 30m candles")
    return False, f"volume {ratio:.1f}x avg, consecutive greens: {greens}"
