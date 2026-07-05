"""Load and validate config.yaml into plain dataclasses."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(os.environ.get("BOT_CONFIG", "config.yaml"))
DATA_DIR = Path(os.environ.get("BOT_DATA_DIR", "data"))


@dataclass
class Tier:
    name: str
    symbols: list[str]
    confidence_threshold: float
    position_pct: float
    take_profit_pct: float
    stop_loss_pct: float


@dataclass
class Scanner(Tier):
    volume_spike_ratio: float = 3.0
    consecutive_green_30m: int = 3


@dataclass
class Config:
    exchange: str
    quote: str
    starting_cash: float
    taker_pct: float
    slippage_pct: float
    regime_proxies: list[str]
    regime_lookback_days: int
    regime_threshold_pct: float
    timeframe: str
    fast_ma: int
    slow_ma: int
    candles: int
    scan_interval_minutes: int
    scanner_interval_minutes: int
    analyst_enabled: bool
    analyst_model: str
    mode: str = "paper"              # paper | live
    testnet: bool = True
    max_open_positions: int = 6
    max_daily_loss_pct: float = 5.0
    tiers: list[Tier] = field(default_factory=list)
    scanner: Scanner | None = None


def load(path: Path = DEFAULT_CONFIG) -> Config:
    raw = yaml.safe_load(path.read_text())

    analyst = raw.get("analyst", {})
    enabled = analyst.get("enabled", "auto")
    if enabled == "auto":
        enabled = bool(os.environ.get("ANTHROPIC_API_KEY"))

    tiers = [Tier(**t) for t in raw["tiers"]]

    scanner = None
    if "scanner" in raw:
        scanner = Scanner(**raw["scanner"])

    trading = raw.get("trading", {})
    mode = trading.get("mode", "paper")
    if mode not in ("paper", "live"):
        raise ValueError(f"trading.mode must be 'paper' or 'live', got {mode!r}")

    return Config(
        exchange=raw["exchange"],
        quote=raw["quote"],
        starting_cash=float(raw["starting_cash"]),
        taker_pct=float(raw["fees"]["taker_pct"]),
        slippage_pct=float(raw["fees"]["slippage_pct"]),
        regime_proxies=raw["regime"]["proxies"],
        regime_lookback_days=int(raw["regime"]["lookback_days"]),
        regime_threshold_pct=float(raw["regime"]["threshold_pct"]),
        timeframe=raw["strategy"]["timeframe"],
        fast_ma=int(raw["strategy"]["fast_ma"]),
        slow_ma=int(raw["strategy"]["slow_ma"]),
        candles=int(raw["strategy"]["candles"]),
        scan_interval_minutes=int(raw["schedule"]["scan_interval_minutes"]),
        scanner_interval_minutes=int(raw["schedule"]["scanner_interval_minutes"]),
        analyst_enabled=bool(enabled),
        analyst_model=analyst.get("model", "claude-opus-4-8"),
        mode=mode,
        testnet=bool(trading.get("testnet", True)),
        max_open_positions=int(trading.get("max_open_positions", 6)),
        max_daily_loss_pct=float(trading.get("max_daily_loss_pct", 5)),
        tiers=tiers,
        scanner=scanner,
    )
