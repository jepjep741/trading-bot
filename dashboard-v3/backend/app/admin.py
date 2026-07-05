"""Admin router: every action is confirmed client-side, authenticated,
audit-logged, and structurally incapable of raising risk beyond the file
config (see tradingbot.config.apply_overrides) or enabling live mode."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import auth, deps

router = APIRouter(prefix="/api/admin")

RESET_PHRASE = "RESET PAPER ACCOUNT"


class LoginBody(BaseModel):
    password: str


class PauseBody(BaseModel):
    paused: bool


class KillBody(BaseModel):
    active: bool


class ResetBody(BaseModel):
    confirmation: str


class ConfigBody(BaseModel):
    overrides: dict


def _audit(conn, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO audit (ts, actor, action, detail) VALUES "
                 "(datetime('now'), 'admin', ?, ?)", (action, detail))
    conn.commit()


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    auth.login(request, response, body.password)
    with deps.connect() as conn:
        _audit(conn, "login", request.client.host if request.client else "")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@router.get("/session")
def session(request: Request):
    return {"enabled": auth.admin_password() is not None,
            "authed": auth.session_valid(request.cookies.get(auth.SESSION_COOKIE))}


@router.post("/pause", dependencies=[Depends(auth.require_admin)])
def pause(body: PauseBody):
    with deps.connect() as conn:
        deps.set_control(conn, "trading_paused", "1" if body.paused else "0")
        deps.set_control(conn, "pause_reason",
                         "paused from admin panel" if body.paused else "")
        _audit(conn, "pause" if body.paused else "resume")
    return {"paused": body.paused}


@router.post("/kill", dependencies=[Depends(auth.require_admin)])
def kill(body: KillBody):
    with deps.connect() as conn:
        deps.set_control(conn, "kill_switch", "1" if body.active else "0")
        _audit(conn, "kill_switch_on" if body.active else "kill_switch_cleared")
    return {"kill_switch": body.active}


@router.post("/flatten", dependencies=[Depends(auth.require_admin)])
def flatten():
    with deps.connect() as conn:
        conn.execute("INSERT INTO requests (ts, action) VALUES (datetime('now'),"
                     " 'close_all')")
        conn.commit()
        _audit(conn, "flatten_all", "close_all queued; bot executes within ~30s")
    return {"queued": True}


@router.post("/reset", dependencies=[Depends(auth.require_admin)])
def reset(body: ResetBody):
    if body.confirmation != RESET_PHRASE:
        raise HTTPException(400, f'type exactly "{RESET_PHRASE}" to confirm')
    with deps.connect() as conn:
        mode = deps.get_control(conn, "bot_mode", "paper")
        if mode == "live":
            raise HTTPException(403, "refusing to reset the journal in "
                                     "real-funds live mode")
        if conn.execute("SELECT 1 FROM positions WHERE status='open'").fetchone():
            raise HTTPException(409, "close all positions before resetting")
        for table in ("positions", "trades", "signals", "equity_history",
                      "regime_history", "requests"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE account SET cash = ? WHERE id = 1",
                     (deps.base_cfg().starting_cash,))
        conn.commit()
        _audit(conn, "paper_reset")
    return {"reset": True}


@router.get("/config", dependencies=[Depends(auth.require_admin)])
def get_config():
    with deps.connect() as conn:
        base = deps.base_cfg()
        eff = deps.effective_cfg(conn)
        raw = deps.get_control(conn, "config_overrides", "")

        def tier_view(t, b):
            return {"name": t.name, "symbols": t.symbols,
                    "position_pct": t.position_pct,
                    "position_pct_cap": b.position_pct,
                    "confidence_threshold": t.confidence_threshold,
                    "confidence_threshold_floor": b.confidence_threshold,
                    "take_profit_pct": t.take_profit_pct,
                    "stop_loss_pct": t.stop_loss_pct}

        return {
            "overrides": json.loads(raw) if raw else {},
            "effective": {
                "tiers": [tier_view(t, b) for t, b in zip(eff.tiers, base.tiers)],
                "scanner": tier_view(eff.scanner, base.scanner) if eff.scanner else None,
                "max_open_positions": eff.max_open_positions,
                "max_open_positions_cap": base.max_open_positions,
                "max_daily_loss_pct": eff.max_daily_loss_pct,
                "max_daily_loss_pct_cap": base.max_daily_loss_pct,
            },
            "immutable": {
                "mode": base.mode, "testnet": base.testnet,
                "note": "trading mode, TP/SL and the file-config risk ceilings "
                        "cannot be changed from this panel",
            },
        }


@router.put("/config", dependencies=[Depends(auth.require_admin)])
def put_config(body: ConfigBody):
    from tradingbot.config import apply_overrides
    base = deps.base_cfg()
    raw = json.dumps(body.overrides)
    effective = apply_overrides(base, raw)   # clamps everything to the caps
    with deps.connect() as conn:
        deps.set_control(conn, "config_overrides", raw)
        _audit(conn, "config_update", raw[:500])
    return {"saved": True,
            "effective_max_daily_loss_pct": effective.max_daily_loss_pct,
            "note": "values beyond the hard caps were clamped by the bot config"}


@router.get("/audit", dependencies=[Depends(auth.require_admin)])
def audit_log(limit: int = 50):
    with deps.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
