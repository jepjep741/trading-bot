# Trading Bot

> Suomenkieliset käyttöohjeet: [OHJEET.md](OHJEET.md)

Crypto **paper-trading** bot modeled on the tiered-architecture design from
[this article](https://medium.com/@augustozz/i-built-an-ai-crypto-trading-bot-with-claude-skills-here-is-how-it-works-f664b06d2fa6):
real market data, simulated money, no exchange account needed.

If you find this project useful, you can support it:

<a href="https://www.buymeacoffee.com/jepjep741"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" width="217" height="60"></a>

## How it works

Every scan cycle:

1. **Market regime** — BTC and ETH 7-day change classify the market:
   - `BULL` (both > +5%): all tiers active, buy confidence gets +0.05
   - `BEAR` (both < −5%): new buys blocked, capital protection
   - `RANGING` (±5%): buy confidence penalized −0.05
   - `DIVERGING` (opposite directions): confidence capped at 0.50 → holds
2. **Exits** — open positions checked against take-profit / stop-loss, plus
   proactive exits when the signal flips to sell on a held asset.
3. **Signals** — SMA(12/26) crossover on 4h candles per asset, with a
   heuristic confidence score (MA separation, trend slope, volume).
4. **Claude analyst (optional)** — if `ANTHROPIC_API_KEY` is set, Claude
   reviews each actionable signal against the raw candles and regime, and
   returns a refined action + confidence + plain-English reasoning. Every
   decision's reasoning is stored in SQLite for transparency.
5. **Entries** — buy only when confidence ≥ the tier's threshold.

Tiers (see `config.yaml`):

| Tier | Assets | Threshold | Position | TP / SL |
|---|---|---|---|---|
| stable-core | top-10 majors | 0.65 | 5% | +6% / −4% |
| momentum-midcap | mid caps | 0.72 | 3% | +10% / −6% |
| unicorn (scanner) | small caps | 0.78 | 1.5% | +15% / −8% |

The **unicorn scanner** runs every 30 minutes (tiers 1–2 every 2 h) and only
fires in a BULL regime, looking for a 3× volume spike over the 7-day average
plus three consecutive green 30-minute candles.

State lives in `data/tradingbot.db` (SQLite): account cash, positions,
trades, every signal with its reasoning, and regime history.

## Run locally

```bash
cd ~/work/trading-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m tradingbot scan      # one scan cycle
.venv/bin/python -m tradingbot status    # cash, equity, open positions
.venv/bin/python -m tradingbot signals   # recent decisions with reasoning
.venv/bin/python -m tradingbot trades
.venv/bin/python -m tradingbot run       # continuous, on the schedule
```

Enable the Claude analyst by exporting `ANTHROPIC_API_KEY` before running.

## Web dashboard

```bash
.venv/bin/python -m tradingbot web          # http://127.0.0.1:8060
```

Single-page view: equity KPI row (equity, cash, open positions, realized PnL,
win rate), regime badge with BTC/ETH 7-day proxies, an equity curve
(snapshotted every scan cycle), a 24h market-pulse chart across all tracked
assets, and tables for open positions, signals (with the stored reasoning)
and trades. Light/dark follows the browser's color scheme; refreshes every
60 s. In compose it runs as the `dashboard` service on port 8060 — with pasta
networking use `http://127.0.0.1:8060`, not `::1`.

## Dashboard v3 (monitoring & admin)

A React + FastAPI dashboard with statistics, live signal feed and an
authenticated admin panel lives in [dashboard-v3/](dashboard-v3/README.md).
Start: `podman-compose --env-file .env up -d --build dashboard-v3` →
http://127.0.0.1:8070. Admin requires `DASHBOARD_ADMIN_PASSWORD` in `.env`.

## Run in rootless Podman

```bash
podman-compose up -d --build
podman logs -f tradingbot
podman exec tradingbot python -m tradingbot status
```

The SQLite database is bind-mounted at `./data` (`:z` flag included for
SELinux hosts such as RHEL 8).

## Going live (real trading)

**Read this whole section first. A trading bot can lose money quickly — the
MA-crossover strategy here is a baseline, not a proven edge. Never trade
funds you cannot afford to lose entirely.**

The bot has three trading modes, gated so you can't reach real funds by
accident:

| Mode | `config.yaml` | Extra requirements |
|---|---|---|
| Paper (default) | `trading.mode: paper` | none |
| Live on testnet | `mode: live`, `testnet: true` | testnet API keys via env |
| Live, real funds | `mode: live`, `testnet: false` | real API keys **and** `LIVE_TRADING_ACK=I-ACCEPT-FULL-LOSS` |

### Step 1 — create exchange API keys safely

On Binance (or your ccxt-supported exchange):

1. Create a **new API key dedicated to the bot** — never reuse a key.
2. Permissions: **enable spot trading only**. **Disable withdrawals** and
   transfers — then a leaked key can trade but never move funds out.
3. **Restrict the key to your server's IP address.**
4. Fund a **sub-account** (Binance supports these) with only the amount the
   bot may manage, and create the key on that sub-account. The bot can lose
   at most what's there.

### Step 2 — dry-run on the exchange testnet

Binance Spot Testnet (https://testnet.binance.vision) gives free test funds.
Create testnet keys there, then:

```bash
# config.yaml:  trading: { mode: live, testnet: true }
cat > .env <<'EOF'
EXCHANGE_API_KEY=your-testnet-key
EXCHANGE_API_SECRET=your-testnet-secret
EOF
chmod 600 .env
```

Uncomment the `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` lines under the
**tradingbot** service in `compose.yaml` (never the dashboard service), then
`podman-compose up -d --build --force-recreate`. Run on testnet until you
have seen with your own eyes: an entry, a take-profit or stop-loss exit, a
manual close from the dashboard, and the circuit breaker or pause behaving
as expected.

### Step 3 — go live, small

1. Set `testnet: false` and add `LIVE_TRADING_ACK=I-ACCEPT-FULL-LOSS` to
   `.env` — the bot refuses to start on real funds without it.
2. **Lower the risk numbers first**: cut every tier's `position_pct` (e.g.
   5 → 1), set `max_open_positions: 2–3`, keep `max_daily_loss_pct` tight.
   Exchanges have minimum order sizes (~10 USDT on Binance); the bot skips
   orders below them, so the account needs enough balance for
   `position_pct` of equity to clear that minimum.
3. Recreate the containers and watch `podman logs -f tradingbot` — startup
   prints `LIVE trading enabled … REAL FUNDS`.

### What changes in live mode

- Orders are real **market orders** via ccxt; fills, fees and quantities are
  taken from the exchange's actual execution, and cash mirrors your free
  quote balance on the exchange.
- TP/SL and dashboard close-requests are checked **every 30 s** (paper mode
  too). Stops are bot-enforced, not exchange-side orders: if the bot is down,
  stops are not enforced — keep `restart: unless-stopped` on and monitor it.
- The **circuit breaker** auto-pauses new entries when the day's equity drop
  exceeds `max_daily_loss_pct`; open positions keep their TP/SL. Resume from
  the dashboard.

### Dashboard controls

- Header badge shows the mode: **PAPER** (blue) / **LIVE · testnet**
  (yellow) / **LIVE — real funds** (red).
- **Pause new entries / Resume** — stops opening positions; exits still run.
- **Close** per position and **Close all** — queued in SQLite and executed
  by the bot process within ~30 s (the dashboard container never holds API
  keys, so a compromised dashboard cannot place orders directly).
- Day-change vs. circuit-breaker limit and queued actions are shown in the
  Controls card.

### Security notes

- Keys live only in `.env` (mode 600, never committed) and only in the
  **tradingbot** container's environment.
- The dashboard has no authentication — it binds to localhost via the pasta
  port mapping. Do not expose port 8060 beyond localhost/LAN without putting
  a reverse proxy with auth in front, especially in live mode (the pause and
  close endpoints would be open to anyone who can reach the port).

## Notes

- Market data comes from Binance public endpoints via ccxt — no API keys.
- Fills are simulated with 0.1% fee and 0.05% slippage.
- This is paper trading only; there is deliberately no order-placement code.
- `python -m tradingbot reset` wipes the paper account and starts over.
