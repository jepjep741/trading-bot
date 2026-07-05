"""Scan-cycle orchestrator: regime -> exits -> tier signals -> entries -> scanner."""
from __future__ import annotations

import os
import time

from . import regime as regime_mod
from .analyst import Analyst
from .broker import LiveBroker, PaperBroker
from .config import Config, Tier, apply_overrides
from .db import Store
from .market_data import MarketData, make_exchange
from .strategy import Signal, evaluate, volume_spike_scan

LIVE_ACK = "I-ACCEPT-FULL-LOSS"


def build_broker(cfg: Config, store: Store):
    """Paper broker by default; live broker only behind explicit opt-ins."""
    if cfg.mode != "live":
        return PaperBroker(store, cfg.taker_pct, cfg.slippage_pct)
    key = os.environ.get("EXCHANGE_API_KEY", "")
    secret = os.environ.get("EXCHANGE_API_SECRET", "")
    if not key or not secret:
        raise SystemExit("live mode: set EXCHANGE_API_KEY and EXCHANGE_API_SECRET "
                         "in the environment (never in config files)")
    if not cfg.testnet and os.environ.get("LIVE_TRADING_ACK") != LIVE_ACK:
        raise SystemExit("live mode with real funds (testnet: false) requires the "
                         f"environment variable LIVE_TRADING_ACK={LIVE_ACK} — "
                         "this bot can lose all funds the API key can access")
    exchange = make_exchange(cfg.exchange, key, secret, cfg.testnet)
    print(f"LIVE trading enabled on {cfg.exchange}"
          f"{' (testnet)' if cfg.testnet else ' — REAL FUNDS'}")
    return LiveBroker(store, exchange, cfg.quote)


class Engine:
    def __init__(self, cfg: Config, store: Store, md: MarketData):
        self.base_cfg = cfg
        self.cfg = cfg
        self.store = store
        self.md = md
        store.mode = ("paper" if cfg.mode == "paper"
                      else ("live-testnet" if cfg.testnet else "live"))
        store.set_control("bot_mode", store.mode)
        self.broker = build_broker(cfg, store)
        if isinstance(self.broker, LiveBroker):
            free = self.broker.sync_cash()   # dashboard shows real balance at once
            print(f"exchange free balance: {free:.2f} {cfg.quote}")
        self.analyst = Analyst(cfg.analyst_model) if cfg.analyst_enabled else None

    def refresh_cfg(self) -> None:
        """Re-merge dashboard overrides (capped) at the start of every cycle."""
        self.cfg = apply_overrides(self.base_cfg,
                                   self.store.get_control("config_overrides", ""))

    # -- entry gating ------------------------------------------------------
    def entries_blocked(self) -> str | None:
        if self.store.get_control("kill_switch", "0") == "1":
            return "KILL SWITCH active"
        if self.store.get_control("trading_paused", "0") == "1":
            reason = self.store.get_control("pause_reason", "")
            return "trading paused" + (f" ({reason})" if reason else "")
        if len(self.store.open_positions()) >= self.cfg.max_open_positions:
            return f"max open positions ({self.cfg.max_open_positions}) reached"
        return None

    # -- exits -------------------------------------------------------------
    def open_position_prices(self) -> dict[str, float]:
        symbols = sorted({p["symbol"] for p in self.store.open_positions()})
        if not symbols:
            return {}
        try:
            return {s: t["last"] for s, t in self.md.tickers(symbols).items()}
        except Exception as exc:
            print(f"  ticker fetch failed: {exc}")
            return {}

    def check_exits(self, prices: dict[str, float] | None = None) -> None:
        positions = self.store.open_positions()
        if not positions:
            return
        if prices is None:
            prices = self.open_position_prices()
        for pos in positions:
            price = prices.get(pos["symbol"])
            if not price:
                continue
            if price >= pos["take_profit"]:
                pnl = self.broker.sell(pos, price, "take-profit hit")
                print(f"  EXIT {pos['symbol']} @ {price:.6g} take-profit, pnl {pnl:+.2f}")
            elif price <= pos["stop_loss"]:
                pnl = self.broker.sell(pos, price, "stop-loss hit")
                print(f"  EXIT {pos['symbol']} @ {price:.6g} stop-loss, pnl {pnl:+.2f}")

    # -- one symbol ----------------------------------------------------------
    def evaluate_symbol(self, symbol: str, tier: Tier, regime_name: str) -> Signal | None:
        try:
            candles = self.md.ohlcv(symbol, self.cfg.timeframe, self.cfg.candles)
        except Exception as exc:
            print(f"  data fetch failed for {symbol}: {exc}")
            return None

        sig = evaluate(candles, self.cfg.fast_ma, self.cfg.slow_ma)
        source = "technical"

        held = self.store.open_positions(symbol)
        position = None
        if held:
            p = held[0]
            position = {"qty": p["qty"], "entry_price": p["entry_price"],
                        "opened_at": p["opened_at"]}

        # ask Claude only when there is a decision to make
        if self.analyst and (sig.action != "hold" or held):
            sig = self.analyst.review(symbol, tier.name, regime_name, sig,
                                      candles, position)
            source = "claude" if sig.reasoning.startswith("[claude]") else "technical"

        adj_conf, block = regime_mod.adjust_confidence(sig.confidence, sig.action,
                                                       regime_name)
        if block:
            sig = Signal("hold", adj_conf, sig.price, f"{sig.reasoning} — {block}")
        else:
            sig = Signal(sig.action, adj_conf, sig.price, sig.reasoning)

        self.store.record_signal(symbol, tier.name, sig.action, sig.confidence,
                                 regime_name, sig.price, sig.reasoning, source)
        self.store.commit()

        # proactive exit on sell signal for a held asset
        if sig.action == "sell" and held:
            pnl = self.broker.sell(held[0], sig.price, f"sell signal: {sig.reasoning}")
            print(f"  EXIT {symbol} @ {sig.price:.6g} on signal, pnl {pnl:+.2f}")

        # entry
        if sig.action == "buy" and not held and sig.confidence >= tier.confidence_threshold:
            blocked = self.entries_blocked()
            if blocked:
                print(f"  skip {symbol} entry: {blocked}")
                return sig
            prices = {p["symbol"]: p["entry_price"] for p in self.store.open_positions()}
            notional = self.broker.equity(prices) * tier.position_pct / 100.0
            pos_id = self.broker.buy(symbol, tier.name, notional, sig.price,
                                     tier.take_profit_pct, tier.stop_loss_pct,
                                     sig.reasoning)
            if pos_id:
                print(f"  ENTER {symbol} [{tier.name}] {notional:.2f} {self.cfg.quote} "
                      f"@ {sig.price:.6g} (confidence {sig.confidence:.2f})")
            else:
                print(f"  skipped {symbol}: not enough cash")
        return sig

    # -- full cycle ----------------------------------------------------------
    def scan_cycle(self) -> None:
        self.refresh_cfg()
        reg = regime_mod.detect(self.md, self.cfg.regime_proxies,
                                self.cfg.regime_lookback_days,
                                self.cfg.regime_threshold_pct)
        changes = ", ".join(f"{s.split('/')[0]} {c:+.1f}%"
                            for s, c in reg.proxy_changes.items())
        print(f"regime: {reg.name} ({changes})")
        vals = list(reg.proxy_changes.values())
        self.store.record_regime(reg.name, vals[0] if vals else 0.0,
                                 vals[1] if len(vals) > 1 else 0.0)
        self.store.commit()

        self.check_exits()

        for tier in self.cfg.tiers:
            print(f"tier {tier.name} (threshold {tier.confidence_threshold}):")
            for symbol in tier.symbols:
                sig = self.evaluate_symbol(symbol, tier, reg.name)
                if sig and sig.action != "hold":
                    print(f"  {symbol}: {sig.action} conf {sig.confidence:.2f} — "
                          f"{sig.reasoning[:120]}")

        # equity snapshot for the dashboard's equity curve
        try:
            if isinstance(self.broker, LiveBroker):
                self.broker.sync_cash()
            prices = {p["symbol"]: self.md.last_price(p["symbol"])
                      for p in self.store.open_positions()}
            self.store.record_equity(self.broker.equity(prices), self.store.cash)
            self.store.commit()
        except Exception as exc:
            print(f"  equity snapshot failed: {exc}")

    def scanner_cycle(self) -> None:
        """Tier-3 unicorn hunter — runs on its own faster cadence, BULL only."""
        self.refresh_cfg()
        sc = self.cfg.scanner
        if not sc:
            return
        reg = regime_mod.detect(self.md, self.cfg.regime_proxies,
                                self.cfg.regime_lookback_days,
                                self.cfg.regime_threshold_pct)
        if reg.name != regime_mod.BULL:
            print(f"scanner idle: regime is {reg.name}, needs BULL")
            return
        self.check_exits()
        hits = 0
        for symbol in sc.symbols:
            if self.store.open_positions(symbol):
                continue
            try:
                c30 = self.md.ohlcv(symbol, "30m", sc.consecutive_green_30m + 4)
                c1d = self.md.ohlcv(symbol, "1d", 9)
            except Exception as exc:
                print(f"  scanner fetch failed for {symbol}: {exc}")
                continue
            hit, why = volume_spike_scan(c30, c1d, sc.volume_spike_ratio,
                                         sc.consecutive_green_30m)
            if not hit:
                continue
            hits += 1
            price = c30[-1][4]
            sig = Signal("buy", 0.80, price, f"unicorn scanner: {why}")
            if self.analyst:
                sig = self.analyst.review(symbol, sc.name, reg.name, sig, c30, None)
            self.store.record_signal(symbol, sc.name, sig.action, sig.confidence,
                                     reg.name, price, sig.reasoning,
                                     "claude" if self.analyst else "technical")
            self.store.commit()
            if sig.action == "buy" and sig.confidence >= sc.confidence_threshold:
                blocked = self.entries_blocked()
                if blocked:
                    print(f"  skip {symbol} entry: {blocked}")
                    continue
                prices = {p["symbol"]: p["entry_price"] for p in self.store.open_positions()}
                notional = self.broker.equity(prices) * sc.position_pct / 100.0
                if self.broker.buy(symbol, sc.name, notional, price,
                                   sc.take_profit_pct, sc.stop_loss_pct, sig.reasoning):
                    print(f"  ENTER {symbol} [unicorn] {notional:.2f} @ {price:.6g}")
        print(f"scanner: {reg.name}, {len(sc.symbols)} symbols checked, "
              f"{hits} spike(s)")

    # -- fast tick: GUI requests, TP/SL, circuit breaker (every ~30 s) ---------
    def process_requests(self) -> None:
        for req in self.store.pending_requests():
            try:
                targets = self.store.open_positions()
                if req["action"] == "close":
                    targets = [p for p in targets if p["id"] == req["position_id"]]
                elif req["action"] != "close_all":
                    self.store.finish_request(req["id"], "error", "unknown action")
                    continue
                closed = []
                for pos in targets:
                    price = self.md.last_price(pos["symbol"])
                    pnl = self.broker.sell(pos, price, "manual close (dashboard)")
                    closed.append(f"{pos['symbol']} pnl {pnl:+.2f}")
                    print(f"  MANUAL EXIT {pos['symbol']} @ {price:.6g}, pnl {pnl:+.2f}")
                self.store.finish_request(req["id"], "done",
                                          "; ".join(closed) or "nothing to close")
            except Exception as exc:
                self.store.finish_request(req["id"], "error", str(exc))
                print(f"  request {req['id']} failed: {exc}")
            self.store.commit()

    def check_circuit_breaker(self, equity: float) -> None:
        start = self.store.equity_day_start()
        if not start:
            return
        change_pct = (equity - start) / start * 100.0
        if (change_pct <= -self.cfg.max_daily_loss_pct
                and self.store.get_control("trading_paused", "0") != "1"):
            reason = (f"circuit breaker: {change_pct:.1f}% today, limit "
                      f"-{self.cfg.max_daily_loss_pct}%")
            self.store.set_control("trading_paused", "1")
            self.store.set_control("pause_reason", reason)
            print(f"CIRCUIT BREAKER TRIPPED — {reason}. New entries paused; "
                  f"open positions keep their TP/SL. Resume from the dashboard.")

    def tick(self) -> None:
        self.process_requests()
        if self.store.open_positions():
            prices = self.open_position_prices()
            if prices:
                self.check_exits(prices)
                self.check_circuit_breaker(self.broker.equity(prices))

    # -- long-running loop -----------------------------------------------------
    def run_forever(self) -> None:
        scan_s = self.cfg.scan_interval_minutes * 60
        scanner_s = self.cfg.scanner_interval_minutes * 60
        last_scan = float("-inf")   # both cycles fire immediately on startup
        last_scanner = float("-inf")
        mode = "PAPER" if self.cfg.mode == "paper" else (
            "LIVE-TESTNET" if self.cfg.testnet else "LIVE")
        print(f"bot running [{mode}]: scan every {self.cfg.scan_interval_minutes}m, "
              f"scanner every {self.cfg.scanner_interval_minutes}m, "
              f"exits/requests every 30s, analyst={'on' if self.analyst else 'off'}")
        while True:
            # wall clock, not monotonic: monotonic freezes during host suspend,
            # which silently postpones scans after the machine wakes up
            now = time.time()
            try:
                self.store.set_control("heartbeat", str(int(now)))
                if self.store.get_control("kill_switch", "0") == "1":
                    # halted: no scans, no entries — exits and dashboard
                    # requests keep running through tick()
                    self.tick()
                elif now - last_scan >= scan_s:
                    last_scan = now
                    self.scan_cycle()
                elif now - last_scanner >= scanner_s:
                    last_scanner = now
                    self.scanner_cycle()
                else:
                    self.tick()
            except Exception as exc:
                print(f"cycle error: {exc}")
            time.sleep(30)
