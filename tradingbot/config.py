"""Load and validate config.yaml into plain dataclasses."""
from __future__ import annotations

import copy
import json
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


def apply_overrides(base: Config, raw_json: str) -> Config:
    """Merge dashboard config overrides into a copy of the file config.

    Hard caps — an override can NEVER increase risk beyond the file config:
    position_pct / max_open_positions / max_daily_loss_pct only go DOWN,
    confidence thresholds only go UP, TP/SL and trading mode are untouchable.
    """
    cfg = copy.deepcopy(base)
    if not raw_json:
        return cfg
    try:
        ov = json.loads(raw_json)
    except ValueError:
        return cfg

    def clamp_tier(tier, base_tier, t_ov: dict):
        if "position_pct" in t_ov:
            tier.position_pct = min(float(t_ov["position_pct"]), base_tier.position_pct)
        if "confidence_threshold" in t_ov:
            tier.confidence_threshold = max(float(t_ov["confidence_threshold"]),
                                            base_tier.confidence_threshold)
        if "symbols" in t_ov and isinstance(t_ov["symbols"], list):
            symbols = [s for s in t_ov["symbols"]
                       if isinstance(s, str) and s.endswith("/" + base.quote)][:15]
            if symbols:
                tier.symbols = symbols

    tier_ov = ov.get("tiers", {})
    for tier, base_tier in zip(cfg.tiers, base.tiers):
        if tier.name in tier_ov:
            clamp_tier(tier, base_tier, tier_ov[tier.name])
    if cfg.scanner and base.scanner and "scanner" in ov:
        clamp_tier(cfg.scanner, base.scanner, ov["scanner"])
    if "max_open_positions" in ov:
        cfg.max_open_positions = min(int(ov["max_open_positions"]),
                                     base.max_open_positions)
    if "max_daily_loss_pct" in ov:
        cfg.max_daily_loss_pct = min(float(ov["max_daily_loss_pct"]),
                                     base.max_daily_loss_pct)
    return cfg


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
