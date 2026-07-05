"""Market data via ccxt public endpoints — no API keys required."""
from __future__ import annotations

import ccxt


def make_exchange(exchange_id: str, api_key: str = "", secret: str = "",
                  testnet: bool = False):
    """Authenticated ccxt exchange for live trading (sandbox when testnet)."""
    ex = getattr(ccxt, exchange_id)({
        "enableRateLimit": True,
        "apiKey": api_key,
        "secret": secret,
    })
    if testnet:
        ex.set_sandbox_mode(True)
    return ex


class MarketData:
    def __init__(self, exchange_id: str):
        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})

    def ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        """Returns [[ts_ms, open, high, low, close, volume], ...] oldest first."""
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def last_price(self, symbol: str) -> float:
        return float(self.exchange.fetch_ticker(symbol)["last"])

    def tickers(self, symbols: list[str]) -> dict[str, dict]:
        """Batched tickers: {symbol: {last, pct_24h}} for all requested symbols."""
        raw = self.exchange.fetch_tickers(symbols)
        out = {}
        for sym in symbols:
            t = raw.get(sym)
            if t:
                out[sym] = {"last": float(t["last"] or 0),
                            "pct_24h": float(t.get("percentage") or 0)}
        return out

    def change_pct(self, symbol: str, days: int) -> float:
        """Percent change of close over the last `days` daily candles."""
        candles = self.ohlcv(symbol, "1d", days + 1)
        if len(candles) < 2:
            raise RuntimeError(f"not enough daily candles for {symbol}")
        first, last = candles[0][4], candles[-1][4]
        return (last - first) / first * 100.0
