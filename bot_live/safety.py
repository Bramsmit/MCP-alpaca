"""
Safety guardrails voor de Alpaca range-bot.

Doel: range-trading mag doorgaan in choppy markten, maar niet blijven dip-buyen
of grote posities vasthouden tijdens brede neertrends. Alpaca crypto heeft geen
bruikbare bracket/OCO naast de bestaande take-profit limit, dus stops worden
softwarematig per run uitgevoerd: bestaande sell annuleren en daarna één
agressieve limit-sell plaatsen.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import OrderSide

from bot_live.config import (
    SAFETY_AGGRESSIVE_SELL_DISCOUNT_PCT,
    SAFETY_COOLDOWN_HOURS,
    SAFETY_DRY_RUN,
    SAFETY_EMA_FAST_DAYS,
    SAFETY_EMA_SLOW_DAYS,
    SAFETY_ENABLED,
    SAFETY_MARKET_DROP_7D_PCT,
    SAFETY_MARKET_GATE,
    SAFETY_MAX_ALLOC_PCT,
    SAFETY_PEAK_DRAWDOWN_LIQUIDATE_PCT,
    SAFETY_PEAK_DRAWDOWN_PAUSE_PCT,
    SAFETY_RISK_PER_TRADE_PCT,
    SAFETY_STATE_FILE,
    SAFETY_STOP_ATR_MULT,
    SAFETY_STOP_MAX_PCT,
    SAFETY_STOP_MIN_PCT,
    SAFETY_SYMBOL_COOLDOWN_HOURS,
    SAFETY_SYMBOL_EMA_GATE,
    SYMBOL_POOL,
)
from bot_live.alpaca_runtime import (
    _find_position,
    _submit_crypto_sell,
    get_current_prices,
    get_open_orders,
    get_positions,
)
from bot_live.telegram import send_telegram

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_HISTORY_FILES = (
    "alpaca_runs.jsonl",
    "trades.jsonl",
    "data/alpaca_trades.jsonl",
)
_HISTORY_EQUITY_KEYS = (
    "portfolio_value",
    "portfolio_value_usd",
    "portfolio_equity",
    "equity",
)


@dataclass
class SafetyDecision:
    """Resultaat van de safety-pass voor één run."""

    enabled: bool = True
    portfolio_equity: float = 0.0
    peak_equity: float = 0.0
    drawdown_pct: float = 0.0
    block_new_buys: bool = False
    reason: str = ""
    allowed_symbols: set[str] = field(default_factory=set)
    blocked_symbols: dict[str, str] = field(default_factory=dict)
    stop_distances: dict[str, float] = field(default_factory=dict)
    exit_symbols: set[str] = field(default_factory=set)
    actions: list[str] = field(default_factory=list)

    def allow_buy(self, symbol: str) -> bool:
        return self.enabled and not self.block_new_buys and symbol in self.allowed_symbols

    def buy_cap(self, symbol: str, equity: float, default_cap: float) -> float:
        """Risk-aware cap voor nieuwe orders."""
        stop_dist = self.stop_distances.get(symbol, SAFETY_STOP_MIN_PCT)
        risk_cap = equity * SAFETY_RISK_PER_TRADE_PCT / max(stop_dist, 0.0001)
        alloc_cap = equity * SAFETY_MAX_ALLOC_PCT
        return max(0.0, min(default_cap, risk_cap, alloc_cap))


def _state_path() -> Path:
    return _REPO_ROOT / SAFETY_STATE_FILE


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def _history_peak_equity() -> float:
    """Beste lokale peak uit eerder gelogde bot-runs/fills."""
    peak = 0.0
    for rel_path in _LOCAL_HISTORY_FILES:
        path = _REPO_ROOT / rel_path
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    for key in _HISTORY_EQUITY_KEYS:
                        raw = row.get(key)
                        if raw is None:
                            continue
                        try:
                            peak = max(peak, float(raw))
                        except (TypeError, ValueError):
                            continue
        except OSError:
            continue
    return peak


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if symbol.endswith("USD"):
        return f"{symbol[:-3]}/USD"
    return symbol


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].astype(float).shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def stop_distance_fraction(daily: pd.DataFrame | None, entry: float) -> float:
    """ATR-gebaseerde stopafstand, begrensd tussen min en max percentage."""
    if entry <= 0:
        return SAFETY_STOP_MAX_PCT
    atr_frac = 0.0
    if daily is not None and len(daily) >= 15:
        atr_val = float(_atr(daily).iloc[-1])
        atr_frac = SAFETY_STOP_ATR_MULT * atr_val / entry if atr_val > 0 else 0.0
    return min(max(atr_frac, SAFETY_STOP_MIN_PCT), SAFETY_STOP_MAX_PCT)


def _fetch_daily_bars(data_client, symbols: list[str], days: int = 90) -> dict[str, pd.DataFrame]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    request = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = data_client.get_crypto_bars(request)
    out: dict[str, pd.DataFrame] = {}
    if bars.df is None or bars.df.empty:
        return out
    for symbol in symbols:
        if symbol not in bars.df.index.get_level_values(0):
            continue
        df = bars.df.loc[symbol].copy()
        df = df[["open", "high", "low", "close", "volume"]].sort_index()
        out[symbol] = df
    return out


def _symbol_gate(symbol: str, daily: pd.DataFrame | None) -> tuple[bool, str]:
    if not SAFETY_SYMBOL_EMA_GATE:
        return True, "symbol EMA gate disabled"
    if daily is None or len(daily) < SAFETY_EMA_SLOW_DAYS:
        return False, f"te weinig daily bars voor EMA{SAFETY_EMA_SLOW_DAYS}"
    close = daily["close"].astype(float)
    ema_fast = float(_ema(close, SAFETY_EMA_FAST_DAYS).iloc[-1])
    ema_slow = float(_ema(close, SAFETY_EMA_SLOW_DAYS).iloc[-1])
    last = float(close.iloc[-1])
    if last < ema_fast and ema_fast < ema_slow:
        return False, (
            f"downtrend: close {last:.4f} < EMA{SAFETY_EMA_FAST_DAYS} "
            f"{ema_fast:.4f} < EMA{SAFETY_EMA_SLOW_DAYS} {ema_slow:.4f}"
        )
    return True, "symbol trend ok"


def _market_gate(daily_map: dict[str, pd.DataFrame]) -> tuple[bool, str]:
    if not SAFETY_MARKET_GATE:
        return True, "market gate disabled"
    btc = daily_map.get("BTC/USD")
    eth = daily_map.get("ETH/USD")
    if btc is None or eth is None or len(btc) < SAFETY_EMA_SLOW_DAYS or len(eth) < SAFETY_EMA_FAST_DAYS:
        return True, "market gate inconclusive"

    btc_close = btc["close"].astype(float)
    eth_close = eth["close"].astype(float)
    btc_last = float(btc_close.iloc[-1])
    eth_last = float(eth_close.iloc[-1])
    btc_ema = float(_ema(btc_close, SAFETY_EMA_FAST_DAYS).iloc[-1])
    eth_ema = float(_ema(eth_close, SAFETY_EMA_FAST_DAYS).iloc[-1])
    btc_ret7 = btc_last / float(btc_close.iloc[-8]) - 1.0 if len(btc_close) >= 8 else 0.0

    if btc_last < btc_ema and eth_last < eth_ema and btc_ret7 <= -SAFETY_MARKET_DROP_7D_PCT:
        return False, (
            f"market risk-off: BTC 7d {btc_ret7*100:.1f}%, "
            f"BTC/ETH onder EMA{SAFETY_EMA_FAST_DAYS}"
        )
    return True, "market trend ok"


def _cancel_buy_orders(
    trading_client,
    dry_run: bool,
    symbols: list[str],
) -> list[str]:
    actions: list[str] = []
    allowed = {_norm_symbol(s) for s in symbols}
    for order in get_open_orders(trading_client):
        order_symbol = _norm_symbol(str(order.symbol))
        if order.side == OrderSide.BUY and order_symbol in allowed:
            msg = f"cancel buy {order.symbol} @{getattr(order, 'limit_price', '?')}"
            actions.append(msg)
            if not dry_run:
                trading_client.cancel_order_by_id(order.id)
    return actions


def _exit_position(trading_client, symbol: str, current_price: float, dry_run: bool) -> str:
    for order in get_open_orders(trading_client, symbol):
        if order.side == OrderSide.SELL and not dry_run:
            trading_client.cancel_order_by_id(order.id)
    limit_price = current_price * (1.0 - SAFETY_AGGRESSIVE_SELL_DISCOUNT_PCT)
    if not dry_run:
        pos_live = _find_position(trading_client, symbol)
        _submit_crypto_sell(trading_client, symbol, pos_live, limit_price)
    return f"software-stop exit {symbol} aggressive limit @{limit_price:.4f}"


def apply_safety_guardrails(
    trading_client,
    data_client,
    *,
    portfolio_equity: float,
    symbols: list[str] | None = None,
) -> SafetyDecision:
    """Voer safety-pass uit voordat nieuwe range-orders worden beheerd."""
    symbols = symbols or SYMBOL_POOL
    if not SAFETY_ENABLED:
        return SafetyDecision(enabled=False, reason="SAFETY_ENABLED=false")

    now = datetime.now(timezone.utc)
    state = _load_state()
    prev_peak = float(state.get("peak_equity", 0) or 0)
    if prev_peak <= 0:
        prev_peak = _history_peak_equity()
    peak = max(prev_peak, float(portfolio_equity or 0))
    drawdown = 0.0 if peak <= 0 else portfolio_equity / peak - 1.0

    cooldown_until = _parse_dt(state.get("cooldown_until"))
    in_cooldown = bool(cooldown_until and cooldown_until > now)

    daily_symbols = sorted(set(symbols) | {"BTC/USD", "ETH/USD"})
    daily_map = _fetch_daily_bars(data_client, daily_symbols)
    market_ok, market_reason = _market_gate(daily_map)

    decision = SafetyDecision(
        enabled=True,
        portfolio_equity=portfolio_equity,
        peak_equity=peak,
        drawdown_pct=drawdown * 100,
        block_new_buys=in_cooldown or not market_ok,
        reason=(
            f"cooldown tot {cooldown_until.isoformat()}"
            if in_cooldown and cooldown_until
            else market_reason
        ),
    )

    if drawdown <= -SAFETY_PEAK_DRAWDOWN_PAUSE_PCT:
        decision.block_new_buys = True
        until = now + timedelta(hours=SAFETY_COOLDOWN_HOURS)
        state["cooldown_until"] = until.isoformat()
        decision.reason = (
            f"portfolio drawdown {drawdown*100:.1f}% <= "
            f"-{SAFETY_PEAK_DRAWDOWN_PAUSE_PCT*100:.1f}%"
        )

    for symbol in symbols:
        ok, reason = _symbol_gate(symbol, daily_map.get(symbol))
        if ok:
            decision.allowed_symbols.add(symbol)
        else:
            decision.blocked_symbols[symbol] = reason
        decision.stop_distances[symbol] = stop_distance_fraction(daily_map.get(symbol), 1.0)

    if decision.block_new_buys:
        actions = _cancel_buy_orders(trading_client, SAFETY_DRY_RUN, symbols)
        decision.actions.extend(actions)

    prices = get_current_prices(data_client, symbols)
    positions = get_positions(trading_client, symbols=symbols)
    symbol_cooldowns = state.get("symbol_cooldowns", {})
    if not isinstance(symbol_cooldowns, dict):
        symbol_cooldowns = {}

    for symbol, (_qty, entry) in positions.items():
        if entry <= 0:
            continue
        daily = daily_map.get(symbol)
        stop_dist = stop_distance_fraction(daily, entry)
        decision.stop_distances[symbol] = stop_dist
        current = prices.get(symbol)
        if not current:
            continue
        stop_price = entry * (1.0 - stop_dist)
        liquidation_mode = drawdown <= -SAFETY_PEAK_DRAWDOWN_LIQUIDATE_PCT
        if current <= stop_price:
            action = _exit_position(trading_client, symbol, current, SAFETY_DRY_RUN)
            decision.actions.append(action)
            decision.exit_symbols.add(symbol)
            symbol_cooldowns[symbol] = (
                now + timedelta(hours=SAFETY_SYMBOL_COOLDOWN_HOURS)
            ).isoformat()
        elif liquidation_mode:
            decision.actions.append(
                f"risk-off active for {symbol}, no stop hit yet "
                f"(price {current:.4f} > stop {stop_price:.4f})"
            )

    for symbol, raw_until in list(symbol_cooldowns.items()):
        until = _parse_dt(raw_until)
        if until and until > now:
            decision.blocked_symbols[symbol] = f"symbol cooldown tot {until.isoformat()}"
            decision.allowed_symbols.discard(symbol)
        else:
            symbol_cooldowns.pop(symbol, None)

    state["peak_equity"] = peak
    state["last_equity"] = portfolio_equity
    state["last_drawdown_pct"] = drawdown * 100
    state["last_checked_at"] = now.isoformat()
    state["symbol_cooldowns"] = symbol_cooldowns
    _save_state(state)

    if decision.actions or decision.block_new_buys:
        _notify_safety(decision)
    return decision


def _notify_safety(decision: SafetyDecision) -> None:
    blocked = list(decision.blocked_symbols.items())[:6]
    lines = [
        "🛡️ Alpaca safety update",
        f"Equity: ${decision.portfolio_equity:.2f}",
        f"Peak: ${decision.peak_equity:.2f}",
        f"Drawdown: {decision.drawdown_pct:.1f}%",
        f"Nieuwe buys: {'gepauzeerd' if decision.block_new_buys else 'toegestaan'}",
        f"Reden: {decision.reason or 'n/a'}",
    ]
    if decision.actions:
        lines.append("Acties:")
        lines.extend(f"- {a}" for a in decision.actions[:8])
    if blocked:
        lines.append("Geblokkeerde symbols:")
        lines.extend(f"- {s}: {r}" for s, r in blocked)
    if SAFETY_DRY_RUN:
        lines.append("SAFETY_DRY_RUN=true: geen orders aangepast.")
    send_telegram("\n".join(lines))


def format_safety_status(current_equity: float | None = None) -> str:
    """Compacte statusregel voor dagrapporten zonder API/bars calls."""
    state = _load_state()
    peak = float(state.get("peak_equity", 0) or 0)
    last_equity = (
        float(current_equity)
        if current_equity is not None
        else float(state.get("last_equity", 0) or 0)
    )
    dd = (last_equity / peak - 1.0) * 100 if peak > 0 and last_equity > 0 else 0.0
    cooldown_until = state.get("cooldown_until")
    symbol_cooldowns = state.get("symbol_cooldowns", {})
    active_symbol_cooldowns = 0
    now = datetime.now(timezone.utc)
    if isinstance(symbol_cooldowns, dict):
        for raw in symbol_cooldowns.values():
            until = _parse_dt(raw)
            if until and until > now:
                active_symbol_cooldowns += 1

    status = "actief"
    until = _parse_dt(cooldown_until)
    if until and until > now:
        status = f"buy-pauze tot {until.strftime('%d-%m %H:%M UTC')}"

    return (
        "\n\n🛡️ Safety"
        f"\nStatus: {status}"
        f"\nPeak equity: ${peak:.2f}"
        f"\nDrawdown: {dd:+.1f}%"
        f"\nSymbol cooldowns: {active_symbol_cooldowns}"
    )
