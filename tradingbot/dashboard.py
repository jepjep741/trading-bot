"""Web dashboard: Flask server exposing the paper account, signals with
reasoning, market pulse, and regime state as a single-page view."""
from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from . import config as config_mod
from . import regime as regime_mod
from .broker import PaperBroker
from .db import Store
from .market_data import MarketData

app = Flask(__name__)
_cfg = None
_md = None


def _deps():
    global _cfg, _md
    if _cfg is None:
        _cfg = config_mod.load()
        _md = MarketData(_cfg.exchange)
    # fresh Store per request: sqlite connections are not thread-safe across
    # Flask's worker threads, and opening the file is cheap
    store = Store(config_mod.DATA_DIR, _cfg.starting_cash)
    return _cfg, _md, store


@app.route("/")
def index():
    cfg, _, _ = _deps()
    return render_template("dashboard.html", quote=cfg.quote)


@app.route("/api/data")
def data():
    cfg, md, store = _deps()
    broker = PaperBroker(store, cfg.taker_pct, cfg.slippage_pct)

    all_symbols = sorted({s for t in cfg.tiers for s in t.symbols}
                         | (set(cfg.scanner.symbols) if cfg.scanner else set()))
    try:
        tickers = md.tickers(all_symbols)
    except Exception:
        tickers = {}

    prices = {s: t["last"] for s, t in tickers.items()}
    positions = []
    for p in store.open_positions():
        cur = prices.get(p["symbol"], p["entry_price"])
        positions.append({
            "id": p["id"],
            "symbol": p["symbol"], "tier": p["tier"], "qty": p["qty"],
            "entry": p["entry_price"], "current": cur,
            "pnl_pct": (cur - p["entry_price"]) / p["entry_price"] * 100,
            "pnl": (cur - p["entry_price"]) * p["qty"],
            "tp": p["take_profit"], "sl": p["stop_loss"],
            "opened_at": p["opened_at"],
        })

    closed = store.conn.execute(
        "SELECT * FROM positions WHERE status='closed' ORDER BY closed_at").fetchall()
    wins = sum(1 for c in closed if c["exit_price"] > c["entry_price"])
    realized = sum((c["exit_price"] - c["entry_price"]) * c["qty"] for c in closed)

    try:
        reg = regime_mod.detect(md, cfg.regime_proxies, cfg.regime_lookback_days,
                                cfg.regime_threshold_pct)
        regime = {"name": reg.name,
                  "proxies": {s.split("/")[0]: round(c, 2)
                              for s, c in reg.proxy_changes.items()}}
    except Exception:
        last = store.recent("regime_history", 1)
        regime = {"name": last[0]["regime"] if last else "UNKNOWN", "proxies": {}}

    equity = broker.equity(prices)
    equity_curve = [{"ts": r["ts"], "equity": r["equity"]}
                    for r in reversed(store.recent("equity_history", 500))]

    tier_info = [{"name": t.name, "threshold": t.confidence_threshold,
                  "symbols": t.symbols} for t in cfg.tiers]

    day_start = store.equity_day_start()
    return jsonify({
        "mode": cfg.mode,
        "testnet": cfg.testnet,
        "paused": store.get_control("trading_paused", "0") == "1",
        "pause_reason": store.get_control("pause_reason", ""),
        "max_daily_loss_pct": cfg.max_daily_loss_pct,
        "max_open_positions": cfg.max_open_positions,
        "day_change_pct": ((equity - day_start) / day_start * 100)
                          if day_start else None,
        "pending_requests": len(store.pending_requests()),
        "quote": cfg.quote,
        "starting_cash": cfg.starting_cash,
        "cash": store.cash,
        "equity": equity,
        "realized_pnl": realized,
        "win_rate": (wins / len(closed) * 100) if closed else None,
        "closed_trades": len(closed),
        "regime": regime,
        "positions": positions,
        "equity_curve": equity_curve,
        "market": [{"symbol": s, "last": t["last"], "pct_24h": t["pct_24h"]}
                   for s, t in sorted(tickers.items())],
        "signals": [dict(r) for r in store.recent("signals", 30)],
        "trades": [dict(r) for r in store.recent("trades", 30)],
        "tiers": tier_info,
        "analyst": cfg.analyst_enabled,
    })


@app.route("/api/pause", methods=["POST"])
def pause():
    """Pause/resume new entries. Open positions keep their TP/SL either way."""
    _, _, store = _deps()
    body = request.get_json(silent=True) or {}
    paused = bool(body.get("paused"))
    store.set_control("trading_paused", "1" if paused else "0")
    store.set_control("pause_reason", "paused from dashboard" if paused else "")
    return jsonify({"paused": paused})


@app.route("/api/close", methods=["POST"])
def close():
    """Queue a close request; the bot process executes it within ~30 s.
    The dashboard holds no exchange API keys by design."""
    _, _, store = _deps()
    body = request.get_json(silent=True) or {}
    target = body.get("position_id")
    if target == "all":
        store.add_request("close_all")
    else:
        try:
            pos_id = int(target)
        except (TypeError, ValueError):
            return jsonify({"error": "position_id must be an id or 'all'"}), 400
        if not any(p["id"] == pos_id for p in store.open_positions()):
            return jsonify({"error": "no such open position"}), 404
        store.add_request("close", pos_id)
    return jsonify({"queued": True})


def serve(host: str, port: int) -> None:
    app.run(host=host, port=port, threaded=True)
