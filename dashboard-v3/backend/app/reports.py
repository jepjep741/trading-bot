"""Daily reports computed from the journal, including the mandated
plain-language line on whether the bot beats buy-and-hold after costs."""
from __future__ import annotations

import sqlite3

from . import deps


def available_days(conn: sqlite3.Connection) -> list[str]:
    return [r["d"] for r in conn.execute(
        "SELECT DISTINCT substr(ts,1,10) d FROM equity_history ORDER BY d DESC")]


def daily_report(conn: sqlite3.Connection, day: str) -> dict:
    eq = conn.execute(
        """SELECT ts, equity FROM equity_history
           WHERE ts >= ? AND ts < date(?, '+1 day') ORDER BY id""",
        (day, day)).fetchall()
    trades = conn.execute(
        "SELECT * FROM trades WHERE ts >= ? AND ts < date(?, '+1 day') ORDER BY id",
        (day, day)).fetchall()
    closed = conn.execute(
        """SELECT * FROM positions WHERE status='closed'
           AND closed_at >= ? AND closed_at < date(?, '+1 day')""",
        (day, day)).fetchall()

    fees = sum(t["fee"] for t in trades)
    realized = sum((p["exit_price"] - p["entry_price"]) * p["qty"] for p in closed)
    wins = sum(1 for p in closed if p["exit_price"] > p["entry_price"])
    eq_start = eq[0]["equity"] if eq else None
    eq_end = eq[-1]["equity"] if eq else None
    bot_ret = ((eq_end - eq_start) / eq_start * 100) if eq_start else None

    # benchmark: BTC over the same first->last snapshot window
    bench_ret = None
    if eq:
        import datetime as dt
        first = dt.datetime.fromisoformat(eq[0]["ts"])
        closes = deps.btc_hourly_closes(int(first.timestamp() * 1000) - 3600_000)
        from .stats import benchmark_curve
        curve = benchmark_curve([dict(r) for r in eq], closes)
        if curve and curve[0]["benchmark"] and curve[-1]["benchmark"]:
            bench_ret = ((curve[-1]["benchmark"] - curve[0]["benchmark"])
                         / curve[0]["benchmark"] * 100)

    if bot_ret is None or bench_ret is None:
        verdict = ("Not enough data yet to compare the bot against simply "
                   "holding Bitcoin for this day.")
    else:
        diff = bot_ret - bench_ret
        if abs(diff) < 0.05:
            verdict = (f"After all costs, the bot performed about the same as "
                       f"simply holding Bitcoin today ({bot_ret:+.2f}% vs "
                       f"{bench_ret:+.2f}%).")
        elif diff > 0:
            verdict = (f"After all costs, the bot BEAT simply holding Bitcoin "
                       f"today: {bot_ret:+.2f}% vs {bench_ret:+.2f}%.")
        else:
            verdict = (f"After all costs, the bot LOST to simply holding Bitcoin "
                       f"today: {bot_ret:+.2f}% vs {bench_ret:+.2f}%.")

    return {
        "date": day,
        "equity_start": eq_start,
        "equity_end": eq_end,
        "return_pct": bot_ret,
        "benchmark_return_pct": bench_ret,
        "trades": len(trades),
        "positions_closed": len(closed),
        "wins": wins,
        "realized_pnl": realized,
        "fees": fees,
        "verdict": verdict,
    }
