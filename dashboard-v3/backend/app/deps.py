"""Shared dependencies: DB access, bot config, market data cache."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

# the tradingbot package lives two levels up (repo root)
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tradingbot import config as bot_config          # noqa: E402
from tradingbot.config import apply_overrides        # noqa: E402

DATA_DIR = Path(os.environ.get("BOT_DATA_DIR", REPO_ROOT / "data"))
CONFIG_PATH = Path(os.environ.get("BOT_CONFIG", REPO_ROOT / "config.yaml"))

_base_cfg = None


def base_cfg():
    global _base_cfg
    if _base_cfg is None:
        _base_cfg = bot_config.load(CONFIG_PATH)
    return _base_cfg


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATA_DIR / "tradingbot.db", timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def get_control(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM control WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_control(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO control (key, value) VALUES (?,?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))
    conn.commit()


def effective_cfg(conn: sqlite3.Connection):
    return apply_overrides(base_cfg(), get_control(conn, "config_overrides", ""))


def bot_status(conn: sqlite3.Connection) -> dict:
    hb = get_control(conn, "heartbeat", "0")
    alive = (time.time() - int(hb or 0)) < 120
    kill = get_control(conn, "kill_switch", "0") == "1"
    paused = get_control(conn, "trading_paused", "0") == "1"
    if kill:
        state = "KILL_SWITCH"
    elif not alive:
        state = "BOT_OFFLINE"
    elif paused:
        state = "HALTED"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "reason": get_control(conn, "pause_reason", ""),
        "mode": get_control(conn, "bot_mode", "paper"),
        "bot_alive": alive,
    }


# ---- BTC benchmark candles (cached; the only network call in the backend) --
_btc_cache: dict = {"ts": 0.0, "since": None, "data": []}


def btc_hourly_closes(since_ms: int) -> list[tuple[int, float]]:
    now = time.time()
    covered = (_btc_cache["since"] is not None
               and since_ms >= _btc_cache["since"] - 3600_000)
    if now - _btc_cache["ts"] < 900 and _btc_cache["data"] and covered:
        return _btc_cache["data"]
    since_ms = min(since_ms, _btc_cache["since"] or since_ms)
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        candles = []
        cursor = since_ms
        while True:
            batch = ex.fetch_ohlcv("BTC/USDT", "1h", since=cursor, limit=1000)
            if not batch:
                break
            candles.extend(batch)
            if len(batch) < 1000:
                break
            cursor = batch[-1][0] + 1
        _btc_cache.update(ts=now, since=since_ms,
                          data=[(c[0], c[4]) for c in candles])
    except Exception:
        pass   # keep the stale cache (or empty) — the chart degrades gracefully
    return _btc_cache["data"]
