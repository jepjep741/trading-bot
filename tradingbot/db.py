"""SQLite persistence: account, positions, trades, signals, regime history."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    tier TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    take_profit REAL NOT NULL,
    stop_loss REAL NOT NULL,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',       -- open | closed
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,                        -- buy | sell
    qty REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL,
    position_id INTEGER,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    tier TEXT NOT NULL,
    action TEXT NOT NULL,                      -- buy | sell | hold
    confidence REAL NOT NULL,
    regime TEXT NOT NULL,
    price REAL NOT NULL,
    reasoning TEXT,
    source TEXT NOT NULL                       -- technical | claude
);
CREATE TABLE IF NOT EXISTS control (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,                      -- close | close_all
    position_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',    -- pending | done | error
    result TEXT
);
CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS regime_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    regime TEXT NOT NULL,
    btc_change_pct REAL,
    eth_change_pct REAL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: Path, starting_cash: float):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(data_dir / "tradingbot.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cur = self.conn.execute("SELECT cash FROM account WHERE id = 1")
        if cur.fetchone() is None:
            self.conn.execute("INSERT INTO account (id, cash) VALUES (1, ?)",
                              (starting_cash,))
            self.conn.commit()

    # -- account ---------------------------------------------------------
    @property
    def cash(self) -> float:
        return self.conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()["cash"]

    def adjust_cash(self, delta: float) -> None:
        self.conn.execute("UPDATE account SET cash = cash + ? WHERE id = 1", (delta,))

    def set_cash(self, value: float) -> None:
        self.conn.execute("UPDATE account SET cash = ? WHERE id = 1", (value,))

    # -- control flags & GUI requests -------------------------------------
    def get_control(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM control WHERE key = ?",
                                (key,)).fetchone()
        return row["value"] if row else default

    def set_control(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO control (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.conn.commit()

    def add_request(self, action: str, position_id: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO requests (ts, action, position_id) VALUES (?,?,?)",
            (now(), action, position_id))
        self.conn.commit()

    def pending_requests(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM requests WHERE status = 'pending' ORDER BY id").fetchall()

    def finish_request(self, request_id: int, status: str, result: str = "") -> None:
        self.conn.execute("UPDATE requests SET status = ?, result = ? WHERE id = ?",
                          (status, result, request_id))

    def equity_day_start(self) -> float | None:
        """First equity snapshot of the current UTC day (circuit-breaker baseline)."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT equity FROM equity_history WHERE ts >= ? ORDER BY id LIMIT 1",
            (day,)).fetchone()
        return row["equity"] if row else None

    # -- positions -------------------------------------------------------
    def open_positions(self, symbol: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM positions WHERE status = 'open'"
        args: tuple = ()
        if symbol:
            q += " AND symbol = ?"
            args = (symbol,)
        return self.conn.execute(q, args).fetchall()

    def open_position(self, symbol: str, tier: str, qty: float, price: float,
                      take_profit: float, stop_loss: float) -> int:
        cur = self.conn.execute(
            "INSERT INTO positions (symbol, tier, qty, entry_price, take_profit,"
            " stop_loss, opened_at) VALUES (?,?,?,?,?,?,?)",
            (symbol, tier, qty, price, take_profit, stop_loss, now()))
        return cur.lastrowid

    def close_position(self, position_id: int, exit_price: float, reason: str) -> None:
        self.conn.execute(
            "UPDATE positions SET status='closed', closed_at=?, exit_price=?,"
            " exit_reason=? WHERE id=?",
            (now(), exit_price, reason, position_id))

    # -- trades / signals / regime ----------------------------------------
    def record_trade(self, symbol: str, side: str, qty: float, price: float,
                     fee: float, position_id: int | None, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO trades (ts, symbol, side, qty, price, fee, position_id, reason)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now(), symbol, side, qty, price, fee, position_id, reason))

    def record_signal(self, symbol: str, tier: str, action: str, confidence: float,
                      regime: str, price: float, reasoning: str, source: str) -> None:
        self.conn.execute(
            "INSERT INTO signals (ts, symbol, tier, action, confidence, regime,"
            " price, reasoning, source) VALUES (?,?,?,?,?,?,?,?,?)",
            (now(), symbol, tier, action, confidence, regime, price, reasoning, source))

    def record_regime(self, regime: str, btc_pct: float, eth_pct: float) -> None:
        self.conn.execute(
            "INSERT INTO regime_history (ts, regime, btc_change_pct, eth_change_pct)"
            " VALUES (?,?,?,?)", (now(), regime, btc_pct, eth_pct))

    def record_equity(self, equity: float, cash: float) -> None:
        self.conn.execute(
            "INSERT INTO equity_history (ts, equity, cash) VALUES (?,?,?)",
            (now(), equity, cash))

    def recent(self, table: str, limit: int = 20) -> list[sqlite3.Row]:
        assert table in ("trades", "signals", "regime_history", "positions",
                         "equity_history")
        return self.conn.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def commit(self) -> None:
        self.conn.commit()
