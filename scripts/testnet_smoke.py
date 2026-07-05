"""Binance testnet smoke test for LiveBroker — uses a throwaway database,
does not touch the paper-trading data or the running containers.

Usage:
    EXCHANGE_API_KEY=... EXCHANGE_API_SECRET=... \
        .venv/bin/python scripts/testnet_smoke.py

Exercises the full live order path: auth, balance sync, market buy with
exchange minimums/precision, position tracking, market sell, PnL.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingbot.broker import LiveBroker            # noqa: E402
from tradingbot.db import Store                     # noqa: E402
from tradingbot.market_data import make_exchange    # noqa: E402

SYMBOL = "BTC/USDT"
NOTIONAL = 50.0   # testnet USDT to spend; testnet grants ample play money


def main() -> int:
    key = os.environ.get("EXCHANGE_API_KEY", "")
    secret = os.environ.get("EXCHANGE_API_SECRET", "")
    if not key or not secret:
        print("set EXCHANGE_API_KEY and EXCHANGE_API_SECRET (testnet keys from "
              "https://testnet.binance.vision)")
        return 1

    print("1. connecting to Binance spot TESTNET ...")
    ex = make_exchange("binance", key, secret, testnet=True)
    store = Store(Path(tempfile.mkdtemp(prefix="testnet-smoke-")), 0)
    broker = LiveBroker(store, ex, "USDT")

    free = broker.sync_cash()
    print(f"   auth OK — free testnet balance: {free:.2f} USDT")
    if free < NOTIONAL:
        print("   not enough testnet USDT; get funds from the testnet faucet")
        return 1

    price = float(ex.fetch_ticker(SYMBOL)["last"])
    print(f"2. market BUY ~{NOTIONAL} USDT of {SYMBOL} @ ~{price:.2f} ...")
    pos_id = broker.buy(SYMBOL, "smoke-test", NOTIONAL, price,
                        take_profit_pct=6, stop_loss_pct=4, reason="smoke test")
    if not pos_id:
        print("   buy was skipped (see message above)")
        return 1
    pos = store.open_positions(SYMBOL)[0]
    print(f"   FILLED: qty {pos['qty']:.6f} @ {pos['entry_price']:.2f}, "
          f"tp {pos['take_profit']:.2f} sl {pos['stop_loss']:.2f}")
    print(f"   free balance after buy: {store.cash:.2f} USDT")

    print(f"3. market SELL (closing the position) ...")
    price = float(ex.fetch_ticker(SYMBOL)["last"])
    pnl = broker.sell(pos, price, "smoke test close")
    print(f"   CLOSED: pnl {pnl:+.4f} USDT (spread+fees on a round trip)")
    print(f"   free balance after sell: {store.cash:.2f} USDT")

    trades = store.recent("trades", 2)
    print("4. recorded trades:")
    for t in reversed(trades):
        print(f"   {t['ts']} {t['side']:<4} {t['symbol']} qty {t['qty']:.6f} "
              f"@ {t['price']:.2f} fee {t['fee']:.6f}")
    print("\nSMOKE TEST PASSED — live order path works against the testnet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
