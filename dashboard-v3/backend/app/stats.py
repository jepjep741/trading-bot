"""All dashboard statistics live here — the frontend renders, never computes.

A "source" is a (tier, origin) pair, e.g. "stable-core/claude": the tier the
position belonged to plus whether the opening decision came from the Claude
analyst ("[claude] ..." reasoning prefix) or pure technicals.
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Beta-posterior shrinkage: prior Beta(a0, b0) centered on 50% with strength
# PRIOR_N pseudo-trades. With few trades the shrunk rate hugs 50%; the raw
# rate only earns credibility with volume. This is the point of the display.
PRIOR_N = 20
MIN_TRADES_FOR_ESTIMATE = 15   # UI shows "collecting data" below this
HALF_LIFE_DAYS = 14.0


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def closed_positions_with_source(conn: sqlite3.Connection) -> list[dict]:
    """Closed positions annotated with pnl and source (tier/origin)."""
    rows = conn.execute(
        """SELECT p.*, t.reason AS open_reason
           FROM positions p
           LEFT JOIN trades t ON t.position_id = p.id AND t.side = 'buy'
           WHERE p.status = 'closed' ORDER BY p.closed_at""").fetchall()
    out = []
    for r in rows:
        origin = "claude" if (r["open_reason"] or "").startswith("[claude]") else "technical"
        pnl = (r["exit_price"] - r["entry_price"]) * r["qty"]
        risk = (r["entry_price"] - r["stop_loss"]) * r["qty"]
        out.append({
            "id": r["id"], "symbol": r["symbol"], "tier": r["tier"],
            "source": f"{r['tier']}/{origin}",
            "opened_at": r["opened_at"], "closed_at": r["closed_at"],
            "entry": r["entry_price"], "exit": r["exit_price"], "qty": r["qty"],
            "pnl": pnl,
            "r_multiple": (pnl / risk) if risk > 0 else None,
            "holding_hours": round((_parse_ts(r["closed_at"]) -
                                    _parse_ts(r["opened_at"])).total_seconds() / 3600, 2),
            "exit_reason": r["exit_reason"],
            "mode": r["mode"] if "mode" in r.keys() else "",
        })
    return out


def shrunk_win_rate(wins: int, n: int) -> dict:
    """Posterior mean + ~90% credible interval (normal approx of the Beta)."""
    a = wins + PRIOR_N / 2
    b = (n - wins) + PRIOR_N / 2
    mean = a / (a + b)
    var = (a * b) / ((a + b) ** 2 * (a + b + 1))
    hw = 1.645 * math.sqrt(var)
    return {
        "raw": (wins / n) if n else None,
        "shrunk": mean,
        "ci_low": max(0.0, mean - hw),
        "ci_high": min(1.0, mean + hw),
    }


def max_drawdown(cum: list[float]) -> float:
    peak, dd = 0.0, 0.0
    for v in cum:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def source_stats(conn: sqlite3.Connection) -> list[dict]:
    positions = closed_positions_with_source(conn)
    by_source: dict[str, list[dict]] = defaultdict(list)
    for p in positions:
        by_source[p["source"]].append(p)

    last_signal = {
        f"{r['tier']}/{r['source']}": r["ts"]
        for r in conn.execute(
            """SELECT tier, source, MAX(ts) AS ts FROM signals
               GROUP BY tier, source""")
    }

    now = _now()
    out = []
    for source in sorted(set(by_source) | set(last_signal)):
        ps = by_source.get(source, [])
        n = len(ps)
        wins = sum(1 for p in ps if p["pnl"] > 0)
        gross_win = sum(p["pnl"] for p in ps if p["pnl"] > 0)
        gross_loss = -sum(p["pnl"] for p in ps if p["pnl"] < 0)
        cum, acc = [], 0.0
        w_sum = w_win = 0.0
        for p in ps:
            acc += p["pnl"]
            cum.append(acc)
            age_days = (now - _parse_ts(p["closed_at"])).total_seconds() / 86400
            w = 0.5 ** (age_days / HALF_LIFE_DAYS)
            w_sum += w
            if p["pnl"] > 0:
                w_win += w
        out.append({
            "source": source,
            "trades": n,
            "needed_for_estimate": max(0, MIN_TRADES_FOR_ESTIMATE - n),
            "win_rate": shrunk_win_rate(wins, n),
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
            "profit_factor_infinite": gross_loss == 0 and gross_win > 0,
            "total_pnl": acc if ps else 0.0,
            "max_drawdown": max_drawdown(cum),
            "recency_win_rate": (w_win / w_sum) if w_sum else None,
            "last_activity": last_signal.get(source),
        })
    return out


def source_equity_curves(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    curves: dict[str, list[dict]] = defaultdict(list)
    acc: dict[str, float] = defaultdict(float)
    for p in closed_positions_with_source(conn):
        acc[p["source"]] += p["pnl"]
        curves[p["source"]].append({"ts": p["closed_at"],
                                    "pnl": round(acc[p["source"]], 4)})
    return dict(curves)


def _daily_pnl_by_source(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in closed_positions_with_source(conn):
        day = p["closed_at"][:10]
        out[p["source"]][day] += p["pnl"]
    return out


def source_correlation(conn: sqlite3.Connection) -> dict:
    daily = _daily_pnl_by_source(conn)
    sources = sorted(daily)
    matrix = []
    for a in sources:
        row = []
        for b in sources:
            days = sorted(set(daily[a]) & set(daily[b]))
            if a == b:
                row.append(1.0)
            elif len(days) < 3:
                row.append(None)   # not enough overlap to say anything
            else:
                xa = [daily[a][d] for d in days]
                xb = [daily[b][d] for d in days]
                row.append(_pearson(xa, xb))
        matrix.append(row)
    return {"sources": sources, "matrix": matrix}


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def skipped_signal_reasons(conn: sqlite3.Connection, since: str) -> dict[str, int]:
    """Buy-intent signals that produced no trade, bucketed by why."""
    rows = conn.execute(
        "SELECT * FROM signals WHERE ts >= ? ORDER BY id", (since,)).fetchall()
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        reasoning = (r["reasoning"] or "").lower()
        if r["action"] == "buy":
            traded = conn.execute(
                """SELECT 1 FROM trades WHERE symbol = ? AND side = 'buy'
                   AND ts BETWEEN ? AND datetime(?, '+10 minutes')""",
                (r["symbol"], r["ts"], r["ts"])).fetchone()
            if not traded:
                counts["below threshold or blocked"] += 1
        elif r["action"] == "hold" and "blocked" in reasoning:
            counts["regime blocked (BEAR)"] += 1
    return dict(counts)


def today_stats(conn: sqlite3.Connection, max_daily_loss_pct: float) -> dict:
    day = _now().strftime("%Y-%m-%d")
    trades_today = conn.execute(
        "SELECT COUNT(*) c FROM trades WHERE ts >= ?", (day,)).fetchone()["c"]
    signals_today = conn.execute(
        "SELECT COUNT(*) c FROM signals WHERE ts >= ?", (day,)).fetchone()["c"]
    day_start = conn.execute(
        "SELECT equity FROM equity_history WHERE ts >= ? ORDER BY id LIMIT 1",
        (day,)).fetchone()
    latest = conn.execute(
        "SELECT equity FROM equity_history ORDER BY id DESC LIMIT 1").fetchone()
    day_pnl = (latest["equity"] - day_start["equity"]) if (day_start and latest) else None
    day_pnl_pct = (day_pnl / day_start["equity"] * 100) if day_pnl is not None else None
    remaining_budget = (max_daily_loss_pct + day_pnl_pct if day_pnl_pct is not None
                        else max_daily_loss_pct)

    consecutive_losses = 0
    for r in conn.execute(
            """SELECT exit_price > entry_price AS win FROM positions
               WHERE status='closed' ORDER BY closed_at DESC"""):
        if r["win"]:
            break
        consecutive_losses += 1

    return {
        "pnl": day_pnl,
        "pnl_pct": day_pnl_pct,
        "trades": trades_today,
        "signals": signals_today,
        "skipped": skipped_signal_reasons(conn, day),
        "remaining_loss_budget_pct": max(0.0, remaining_budget),
        "consecutive_losses": consecutive_losses,
    }


def benchmark_curve(equity_rows: list[dict], btc_closes: list[tuple[int, float]]) -> list[dict]:
    """Buy-and-hold BTC benchmark aligned to equity snapshots.

    btc_closes: [(ts_ms, close), ...] hourly candles covering the range.
    """
    if not equity_rows or not btc_closes:
        return []

    def btc_at(ts: datetime) -> float | None:
        target = ts.timestamp() * 1000
        best, bd = None, float("inf")
        for t, c in btc_closes:
            d = abs(t - target)
            if d < bd:
                bd, best = d, c
        return best if bd < 2 * 3600 * 1000 else None

    p0 = btc_at(_parse_ts(equity_rows[0]["ts"]))
    if not p0:
        return []
    e0 = equity_rows[0]["equity"]
    out = []
    for row in equity_rows:
        p = btc_at(_parse_ts(row["ts"]))
        out.append({"ts": row["ts"], "equity": row["equity"],
                    "benchmark": (e0 * p / p0) if p else None})
    return out
