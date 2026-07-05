"""Paper broker: simulated market fills with fee + slippage against the store."""
from __future__ import annotations

from .db import Store


class PaperBroker:
    def __init__(self, store: Store, taker_pct: float, slippage_pct: float):
        self.store = store
        self.taker = taker_pct / 100.0
        self.slippage = slippage_pct / 100.0

    def buy(self, symbol: str, tier: str, notional: float, price: float,
            take_profit_pct: float, stop_loss_pct: float, reason: str) -> int | None:
        fill = price * (1 + self.slippage)
        fee = notional * self.taker
        total = notional + fee
        if total > self.store.cash:
            return None
        qty = notional / fill
        tp = fill * (1 + take_profit_pct / 100.0)
        sl = fill * (1 - stop_loss_pct / 100.0)
        pos_id = self.store.open_position(symbol, tier, qty, fill, tp, sl)
        self.store.adjust_cash(-total)
        self.store.record_trade(symbol, "buy", qty, fill, fee, pos_id, reason)
        self.store.commit()
        return pos_id

    def sell(self, position, price: float, reason: str) -> float:
        """Close a position at market. Returns realized PnL in quote currency."""
        fill = price * (1 - self.slippage)
        proceeds = position["qty"] * fill
        fee = proceeds * self.taker
        self.store.close_position(position["id"], fill, reason)
        self.store.adjust_cash(proceeds - fee)
        self.store.record_trade(position["symbol"], "sell", position["qty"],
                                fill, fee, position["id"], reason)
        self.store.commit()
        cost = position["qty"] * position["entry_price"]
        return proceeds - fee - cost

    def equity(self, prices: dict[str, float]) -> float:
        total = self.store.cash
        for pos in self.store.open_positions():
            total += pos["qty"] * prices.get(pos["symbol"], pos["entry_price"])
        return total


class LiveBroker:
    """Real market orders through an authenticated ccxt exchange.

    Same interface as PaperBroker. Positions/trades are still tracked in
    SQLite; the store's cash mirrors the exchange's free quote balance so the
    dashboard (which has no API keys) can read it. Truth for balances is
    always the exchange.
    """

    def __init__(self, store: Store, exchange, quote: str):
        self.store = store
        self.ex = exchange
        self.quote = quote
        self.ex.load_markets()

    def sync_cash(self) -> float:
        bal = self.ex.fetch_balance()
        free = float((bal.get(self.quote) or {}).get("free") or 0.0)
        self.store.set_cash(free)
        self.store.commit()
        return free

    @staticmethod
    def _fill_of(order, fallback_price: float, fallback_qty: float):
        price = float(order.get("average") or order.get("price") or fallback_price)
        qty = float(order.get("filled") or fallback_qty)
        fee = 0.0
        for f in (order.get("fees") or ([order["fee"]] if order.get("fee") else [])):
            if f and f.get("cost"):
                fee += float(f["cost"])
        return price, qty, fee

    def buy(self, symbol: str, tier: str, notional: float, price: float,
            take_profit_pct: float, stop_loss_pct: float, reason: str) -> int | None:
        market = self.ex.market(symbol)
        limits = market.get("limits") or {}
        min_amount = (limits.get("amount") or {}).get("min")
        min_cost = (limits.get("cost") or {}).get("min")
        amount = float(self.ex.amount_to_precision(symbol, notional / price))
        if min_amount and amount < min_amount:
            print(f"  skip {symbol}: {amount} below exchange min amount {min_amount}")
            return None
        if min_cost and amount * price < min_cost:
            print(f"  skip {symbol}: notional below exchange min cost {min_cost}")
            return None
        if notional > self.sync_cash():
            print(f"  skip {symbol}: insufficient free {self.quote} on exchange")
            return None
        order = self.ex.create_market_buy_order(symbol, amount)
        fill, qty, fee = self._fill_of(order, price, amount)
        tp = fill * (1 + take_profit_pct / 100.0)
        sl = fill * (1 - stop_loss_pct / 100.0)
        pos_id = self.store.open_position(symbol, tier, qty, fill, tp, sl)
        self.store.record_trade(symbol, "buy", qty, fill, fee, pos_id, reason)
        self.sync_cash()
        return pos_id

    def sell(self, position, price: float, reason: str) -> float:
        symbol = position["symbol"]
        amount = float(self.ex.amount_to_precision(symbol, position["qty"]))
        order = self.ex.create_market_sell_order(symbol, amount)
        fill, qty, fee = self._fill_of(order, price, amount)
        self.store.close_position(position["id"], fill, reason)
        self.store.record_trade(symbol, "sell", qty, fill, fee, position["id"], reason)
        self.sync_cash()
        return (fill - position["entry_price"]) * qty - fee

    def equity(self, prices: dict[str, float]) -> float:
        total = self.store.cash
        for pos in self.store.open_positions():
            total += pos["qty"] * prices.get(pos["symbol"], pos["entry_price"])
        return total
