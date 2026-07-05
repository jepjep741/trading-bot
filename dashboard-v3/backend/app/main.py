"""FastAPI app: JSON API + WebSocket live feed + static frontend.

Separate process from the trading loop — reads the same SQLite journal; admin
actions go through control/requests tables, executed by the bot. Binds to
127.0.0.1 by default; any other host refuses to start without admin auth.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import admin, auth, deps, reports, stats

app = FastAPI(title="Trading Bot Dashboard v3")
app.include_router(admin.router)

if os.environ.get("DASH_DEV_CORS"):
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173",
                                                      "http://localhost:5173"],
                       allow_credentials=True, allow_methods=["*"],
                       allow_headers=["*"])


# ---------------------------------------------------------------- overview --
@app.get("/api/overview")
def overview():
    with deps.connect() as conn:
        cfg = deps.effective_cfg(conn)
        eq = [dict(r) for r in conn.execute(
            "SELECT ts, equity FROM equity_history ORDER BY id")]
        curve = []
        if eq:
            first = dt.datetime.fromisoformat(eq[0]["ts"])
            closes = deps.btc_hourly_closes(int(first.timestamp() * 1000) - 3600_000)
            curve = stats.benchmark_curve(eq, closes)
        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE status='open'")]
        return {
            "status": deps.bot_status(conn),
            "today": stats.today_stats(conn, cfg.max_daily_loss_pct),
            "curve": curve,
            "open_positions": positions,
            "starting_cash": deps.base_cfg().starting_cash,
            "quote": cfg.quote,
        }


# ----------------------------------------------------------------- sources --
@app.get("/api/sources")
def sources():
    with deps.connect() as conn:
        return {"sources": stats.source_stats(conn),
                "min_trades": stats.MIN_TRADES_FOR_ESTIMATE,
                "prior_n": stats.PRIOR_N}


@app.get("/api/sources/correlation")
def correlation():
    with deps.connect() as conn:
        return stats.source_correlation(conn)


@app.get("/api/sources/equity")
def sources_equity():
    with deps.connect() as conn:
        return stats.source_equity_curves(conn)


# --------------------------------------------------------- signals & trades --
@app.get("/api/signals")
def signals(symbol: str = "", source: str = "", limit: int = 100):
    q = "SELECT * FROM signals WHERE 1=1"
    args: list = []
    if symbol:
        q += " AND symbol = ?"; args.append(symbol)
    if source:
        q += " AND (tier || '/' || source) = ?"; args.append(source)
    q += " ORDER BY id DESC LIMIT ?"; args.append(min(limit, 500))
    with deps.connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


@app.get("/api/trades")
def trades(symbol: str = "", source: str = "", date_from: str = "",
           date_to: str = "", format: str = "json"):
    with deps.connect() as conn:
        rows = stats.closed_positions_with_source(conn)
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    if source:
        rows = [r for r in rows if r["source"] == source]
    if date_from:
        rows = [r for r in rows if r["closed_at"] >= date_from]
    if date_to:
        rows = [r for r in rows if r["closed_at"] <= date_to + "T23:59:59"]
    rows.reverse()
    if format == "csv":
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition":
                                 "attachment; filename=trades.csv"})
    return rows


# ----------------------------------------------------------------- reports --
@app.get("/api/reports")
def report_list(limit: int = 30):
    with deps.connect() as conn:
        days = reports.available_days(conn)[:limit]
        return [reports.daily_report(conn, d) for d in days]


# --------------------------------------------------------------- websocket --
class WSManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, message: dict):
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.add(ws)
        self.clients -= dead


manager = WSManager()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    manager.clients.add(ws)
    try:
        while True:
            await ws.receive_text()   # client pings keep the socket alive
    except WebSocketDisconnect:
        manager.clients.discard(ws)


async def _poller():
    """Watch the journal for new rows / status changes and push them out."""
    last_signal = last_trade = 0
    last_status = None
    while True:
        try:
            with deps.connect() as conn:
                if manager.clients:
                    for r in conn.execute(
                            "SELECT * FROM signals WHERE id > ? ORDER BY id",
                            (last_signal,)):
                        last_signal = r["id"]
                        await manager.broadcast({"type": "signal", "data": dict(r)})
                    for r in conn.execute(
                            "SELECT * FROM trades WHERE id > ? ORDER BY id",
                            (last_trade,)):
                        last_trade = r["id"]
                        await manager.broadcast({"type": "trade", "data": dict(r)})
                    status = deps.bot_status(conn)
                    if status != last_status:
                        last_status = status
                        await manager.broadcast({"type": "status", "data": status})
                else:
                    row = conn.execute("SELECT MAX(id) m FROM signals").fetchone()
                    last_signal = row["m"] or 0
                    row = conn.execute("SELECT MAX(id) m FROM trades").fetchone()
                    last_trade = row["m"] or 0
        except Exception:
            pass
        await asyncio.sleep(2)


@app.on_event("startup")
async def startup():
    host = os.environ.get("DASH_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost") and not auth.admin_password():
        raise SystemExit("refusing to bind to a non-localhost interface "
                         "without DASHBOARD_ADMIN_PASSWORD set")
    asyncio.create_task(_poller())


# ------------------------------------------------------------------ static --
# SPA serving: real files (assets) as-is, every other path falls back to
# index.html so client-side routes like /sources work on refresh.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(DIST):
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
