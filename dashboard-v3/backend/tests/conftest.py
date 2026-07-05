import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO))

os.environ["BOT_DATA_DIR"] = tempfile.mkdtemp(prefix="dash-test-")
os.environ["BOT_CONFIG"] = str(REPO / "config.yaml")
os.environ["DASHBOARD_ADMIN_PASSWORD"] = "test-password-123"

from tradingbot.db import Store  # noqa: E402


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)) \
        .isoformat(timespec="seconds")


@pytest.fixture(scope="session")
def seeded_store():
    store = Store(Path(os.environ["BOT_DATA_DIR"]), 10000)
    c = store.conn
    # equity history over 5 days
    for i in range(5 * 12):
        c.execute("INSERT INTO equity_history (ts, equity, cash) VALUES (?,?,?)",
                  (_iso(5 - i / 12), 10000 + i * 3, 9000))
    # closed positions: technical + claude sources, wins and losses
    fixtures = [
        ("BTC/USDT", "stable-core", 0.01, 50000, 52000, 4.5, "SMA12 crossed above SMA26", 4.0),
        ("ETH/USDT", "stable-core", 0.5, 2500, 2400, 4.0, "[claude] strong setup", 3.5),
        ("SOL/USDT", "stable-core", 10, 150, 160, 3.0, "SMA12 crossed above SMA26", 2.5),
        ("AAVE/USDT", "momentum-midcap", 2, 250, 275, 2.0, "[claude] breakout", 1.5),
    ]
    for sym, tier, qty, entry, exitp, opened_days, reason, closed_days in fixtures:
        cur = c.execute(
            """INSERT INTO positions (symbol,tier,qty,entry_price,take_profit,
               stop_loss,opened_at,status,closed_at,exit_price,exit_reason,mode)
               VALUES (?,?,?,?,?,?,?,'closed',?,?,?,'paper')""",
            (sym, tier, qty, entry, entry * 1.06, entry * 0.96,
             _iso(opened_days), _iso(closed_days), exitp,
             "take-profit hit" if exitp > entry else "stop-loss hit"))
        pid = cur.lastrowid
        c.execute("INSERT INTO trades (ts,symbol,side,qty,price,fee,position_id,reason)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (_iso(opened_days), sym, "buy", qty, entry, 1.0, pid, reason))
        c.execute("INSERT INTO trades (ts,symbol,side,qty,price,fee,position_id,reason)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (_iso(closed_days), sym, "sell", qty, exitp, 1.0, pid, "exit"))
    # signals
    for i, (sym, act, conf, src) in enumerate([
            ("BTC/USDT", "buy", 0.74, "technical"),
            ("ETH/USDT", "hold", 0.0, "technical"),
            ("SOL/USDT", "buy", 0.55, "claude")]):
        c.execute("INSERT INTO signals (ts,symbol,tier,action,confidence,regime,"
                  "price,reasoning,source) VALUES (?,?,?,?,?,?,?,?,?)",
                  (_iso(0.1 * i), sym, "stable-core", act, conf, "BULL",
                   100.0, "test reasoning", src))
    c.execute("INSERT INTO control (key,value) VALUES ('heartbeat', ?)",
              (str(int(datetime.now(timezone.utc).timestamp())),))
    c.execute("INSERT INTO control (key,value) VALUES ('bot_mode','paper')")
    c.commit()
    return store


@pytest.fixture(scope="session")
def client(seeded_store):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as tc:
        yield tc


@pytest.fixture()
def admin_client(client):
    client.post("/api/admin/login", json={"password": "test-password-123"})
    yield client
