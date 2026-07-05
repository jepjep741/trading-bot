# Dashboard v3 — monitoring & admin

> Suomeksi: [OHJEET.md](OHJEET.md)

A local web dashboard for the trading bot: FastAPI backend (JSON API +
WebSocket) and a React + Tailwind + Recharts frontend, dark-mode-first.
It runs as a **separate process** from the trading loop — if the UI crashes,
trading is unaffected, and vice versa.

## Starting

**Podman (recommended):**
```bash
podman-compose --env-file .env up -d --build dashboard-v3
# → http://127.0.0.1:8070
```

**Development:**
```bash
# backend (serves the built frontend if dashboard-v3/frontend/dist exists)
DASHBOARD_ADMIN_PASSWORD=... .venv/bin/python -m uvicorn app.main:app \
    --app-dir dashboard-v3/backend --port 8070
# frontend with hot reload (proxies /api and /ws to :8070)
cd dashboard-v3/frontend && npm install && npm run dev   # → :5173
```

**Tests:**
```bash
cd dashboard-v3/backend && ../../.venv/bin/python -m pytest tests/
```

## Admin password

Set `DASHBOARD_ADMIN_PASSWORD` in `.env` (compose passes it through). Without
it the admin panel is disabled — read-only pages still work. Login is
rate-limited (5 attempts/min), the session is an HMAC-signed cookie with a
per-boot secret, and the password is never written to code, logs, or the
database.

## Security model

- Binds to **127.0.0.1 only** (compose publishes `127.0.0.1:8070`).
  Binding any other interface requires an explicit config change **and**
  `DASHBOARD_ADMIN_PASSWORD` set — the server refuses to start otherwise.
- The dashboard **never holds exchange API keys.** Admin actions write to the
  shared SQLite journal (`control` / `requests` / `audit` tables); the bot
  process executes them within its 30-second tick.
- Every admin action requires a confirm dialog and is written to the audit log.

## What the admin panel deliberately CANNOT do

These are structural, enforced by `tradingbot.config.apply_overrides` on
every bot cycle — not UI politeness:

| Setting | Rule |
|---|---|
| Position size (per tier) | can be lowered freely; raising is clamped at the `config.yaml` value |
| Confidence thresholds | can be raised (more conservative); lowering is clamped at the file value |
| Max open positions | down only |
| Daily-loss circuit breaker | down only — the file value is the ceiling |
| Take-profit / stop-loss | not editable at all |
| Disabling stops | no such control exists |
| Leverage | the bot is spot-only, 1x by construction |
| **Live trading mode** | **never a button** — requires editing `config.yaml` *and* API keys *and* the `LIVE_TRADING_ACK` environment variable on the bot process |

## Pages

- **Overview** — status banner (RUNNING / HALTED / KILL SWITCH / BOT OFFLINE
  + PAPER/TESTNET/LIVE mode), today's P&L, skipped-signal reasons, remaining
  daily-loss budget, consecutive losses, equity vs buy-and-hold-BTC benchmark.
- **Sources** — per (tier × decision-origin) statistics: raw vs **shrunk**
  win rate side by side (Beta posterior, 20-trade prior toward 50%, ~90%
  credible interval as a bar), profit factor, max drawdown, recency-weighted
  win rate; correlation heatmap of daily P&L; per-source equity small
  multiples. All numbers computed in `backend/app/stats.py` — the frontend
  never recomputes.
- **Signals & Trades** — live WebSocket feed (auto-reconnect with backoff) of
  every decision with Claude's reasoning; trade journal with R multiple,
  holding time, execution path, filters and CSV export.
- **Reports** — daily reports, newest first, each with the plain-language
  line stating whether the bot beat buy-and-hold BTC after costs.
- **Admin** — pause/resume, kill switch (halts scanning and entries; TP/SL
  exits keep running), flatten all, capped config editor, paper reset behind
  the typed phrase `RESET PAPER ACCOUNT`, audit log.

## API

`GET /api/overview` · `/api/sources` · `/api/sources/correlation` ·
`/api/sources/equity` · `/api/signals` · `/api/trades[?format=csv]` ·
`/api/reports` · `WS /ws` · `POST /api/admin/{login,logout,pause,kill,flatten,reset}` ·
`GET|PUT /api/admin/config` · `GET /api/admin/audit`
