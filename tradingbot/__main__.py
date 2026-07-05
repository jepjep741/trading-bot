"""CLI: python -m tradingbot {scan|scanner|run|status|signals|trades|reset}"""
from __future__ import annotations

import argparse
import sys

from . import config as config_mod
from .db import Store
from .engine import Engine
from .market_data import MarketData


def build_engine() -> tuple[Engine, Store]:
    cfg = config_mod.load()
    store = Store(config_mod.DATA_DIR, cfg.starting_cash)
    return Engine(cfg, store, MarketData(cfg.exchange)), store


def cmd_status() -> None:
    engine, store = build_engine()
    positions = store.open_positions()
    prices = {}
    for pos in positions:
        try:
            prices[pos["symbol"]] = engine.md.last_price(pos["symbol"])
        except Exception:
            prices[pos["symbol"]] = pos["entry_price"]
    print(f"cash:   {store.cash:.2f} {engine.cfg.quote}")
    print(f"equity: {engine.broker.equity(prices):.2f} {engine.cfg.quote}")
    if positions:
        print("open positions:")
        for pos in positions:
            cur = prices[pos["symbol"]]
            pnl_pct = (cur - pos["entry_price"]) / pos["entry_price"] * 100
            print(f"  {pos['symbol']:<12} [{pos['tier']}] qty {pos['qty']:.6g} "
                  f"entry {pos['entry_price']:.6g} now {cur:.6g} ({pnl_pct:+.2f}%) "
                  f"tp {pos['take_profit']:.6g} sl {pos['stop_loss']:.6g}")
    else:
        print("no open positions")


def cmd_table(table: str, limit: int) -> None:
    _, store = build_engine()
    rows = store.recent(table, limit)
    if not rows:
        print(f"no {table} yet")
        return
    for r in reversed(rows):
        d = dict(r)
        if table == "signals":
            print(f"{d['ts']} {d['symbol']:<12} {d['action']:<4} "
                  f"conf {d['confidence']:.2f} [{d['regime']}] ({d['source']}) "
                  f"{(d['reasoning'] or '')[:100]}")
        elif table == "trades":
            print(f"{d['ts']} {d['side']:<4} {d['symbol']:<12} qty {d['qty']:.6g} "
                  f"@ {d['price']:.6g} fee {d['fee']:.4f} — {(d['reason'] or '')[:80]}")
        else:
            print(d)


def cmd_reset() -> None:
    db = config_mod.DATA_DIR / "tradingbot.db"
    if db.exists():
        confirm = input(f"delete {db} and start over? [y/N] ")
        if confirm.strip().lower() == "y":
            db.unlink()
            print("reset done")
        else:
            print("aborted")
    else:
        print("nothing to reset")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tradingbot",
                                     description="Crypto paper-trading bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="run one tier-1/2 scan cycle")
    sub.add_parser("scanner", help="run one tier-3 unicorn scan")
    sub.add_parser("run", help="run continuously on the configured schedule")
    sub.add_parser("status", help="show cash, equity and open positions")
    for name in ("signals", "trades"):
        p = sub.add_parser(name, help=f"show recent {name}")
        p.add_argument("-n", type=int, default=20)
    sub.add_parser("reset", help="delete the paper-trading database")
    web = sub.add_parser("web", help="serve the web dashboard")
    web.add_argument("--host", default="0.0.0.0")
    web.add_argument("--port", type=int, default=8060)
    args = parser.parse_args()

    if args.cmd == "scan":
        engine, _ = build_engine()
        engine.scan_cycle()
    elif args.cmd == "scanner":
        engine, _ = build_engine()
        engine.scanner_cycle()
    elif args.cmd == "run":
        engine, _ = build_engine()
        try:
            engine.run_forever()
        except KeyboardInterrupt:
            sys.exit(0)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd in ("signals", "trades"):
        cmd_table(args.cmd, args.n)
    elif args.cmd == "reset":
        cmd_reset()
    elif args.cmd == "web":
        from .dashboard import serve
        serve(args.host, args.port)


if __name__ == "__main__":
    main()
