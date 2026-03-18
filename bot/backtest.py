#!/usr/bin/env python3
"""
Range-trading backtest voor DOT, XLM, UNI.
- Koop: 0.5% boven 24h low
- Verkoop: 2% onder 24h high (min 2% spread)
- Stop-loss: vast bedrag per eenheid (meerdere waarden getest)
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

# Laad .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

import pandas as pd
from bot.config import (
    SYMBOLS,
    START_CAPITAL,
    CAPITAL_PER_ASSET,
    LEVELS_LOOKBACK_DAYS,
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    MIN_SPREAD_PCT,
    STOP_LOSS_VALUES_TO_TEST,
    BACKTEST_MONTHS,
)


def fetch_data(symbols: list[str], months: int = 3) -> dict[str, pd.DataFrame]:
    """Haal historische daily bars op van Alpaca."""
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        print("Installeer alpaca-py: pip install alpaca-py")
        raise

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")

    client = CryptoHistoricalDataClient(api_key, secret) if api_key else CryptoHistoricalDataClient()

    end = datetime.utcnow()
    start = end - timedelta(days=months * 31)

    request = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )

    bars = client.get_crypto_bars(request)
    result = {}

    for symbol in symbols:
        if symbol in bars.df.index.get_level_values(0):
            df = bars.df.loc[symbol].copy()
            df = df[["open", "high", "low", "close", "volume"]]
            df.index = pd.to_datetime(df.index)
            result[symbol] = df.sort_index()
        else:
            result[symbol] = pd.DataFrame()

    return result


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    capital: float,
    stop_loss_per_unit: float,
) -> dict:
    """
    Run backtest voor één asset.
    Gebruikt VORIGE dag high/low voor niveaus (geen look-ahead bias).
    """
    cash = capital
    position = 0.0
    buy_price = 0.0
    stop_price = 0.0
    trades = []
    equity_curve = []

    for i, (ts, row) in enumerate(df.iterrows()):
        high, low, close = row["high"], row["low"], row["close"]

        # Gebruik gem. van laatste N dagen voor niveaus (geen look-ahead, minder uitschieters)
        start_idx = max(0, i - LEVELS_LOOKBACK_DAYS)
        window = df.iloc[start_idx:i]
        if len(window) == 0:
            prev_high, prev_low = high, low
        else:
            prev_high = window["high"].mean()
            prev_low = window["low"].mean()

        buy_level = prev_low * (1 + BUY_ABOVE_LOW_PCT)
        sell_level = prev_high * (1 - SELL_BELOW_HIGH_PCT)

        # Min 2% spread
        if sell_level < buy_level * (1 + MIN_SPREAD_PCT):
            equity_curve.append({"date": ts, "cash": cash, "position": position, "value": cash + position * close})
            continue

        if position > 0:
            # We hebben een positie: check stop-loss eerst, dan take-profit
            if stop_loss_per_unit > 0 and low <= stop_price:
                # Stop-loss geraakt
                cash += position * stop_price
                trades.append({"date": ts, "side": "sell", "qty": position, "price": stop_price, "type": "stop_loss"})
                position = 0
            elif high >= sell_level:
                # Take-profit
                cash += position * sell_level
                trades.append({"date": ts, "side": "sell", "qty": position, "price": sell_level, "type": "take_profit"})
                position = 0
        else:
            # Geen positie: check of we kunnen kopen
            if low <= buy_level and cash > 0:
                qty = cash / buy_level
                position = qty
                cash = 0
                buy_price = buy_level
                stop_price = buy_price - stop_loss_per_unit
                trades.append({"date": ts, "side": "buy", "qty": qty, "price": buy_level})

        equity_curve.append({"date": ts, "cash": cash, "position": position, "value": cash + position * close})

    final_value = cash + position * df.iloc[-1]["close"]
    return {
        "symbol": symbol,
        "start_capital": capital,
        "final_value": final_value,
        "return_pct": (final_value - capital) / capital * 100,
        "trades": trades,
        "n_trades": len(trades),
        "stop_loss_used": stop_loss_per_unit,
    }


def main():
    print("=" * 60)
    print("Range-trading backtest: AVAX, UNI, AAVE")
    print("=" * 60)
    print(f"Koop: {BUY_ABOVE_LOW_PCT*100}% boven low | Verkoop: {SELL_BELOW_HIGH_PCT*100}% onder high")
    print(f"Min spread: {MIN_SPREAD_PCT*100}% | Kapitaal per asset: ${CAPITAL_PER_ASSET:.0f}")
    print()

    print("Ophalen data van Alpaca...")
    try:
        data = fetch_data(SYMBOLS, BACKTEST_MONTHS)
    except Exception as e:
        print(f"Fout bij ophalen data: {e}")
        return

    for sym in SYMBOLS:
        print(f"  {sym}: {len(data[sym])} bars")

    print()
    print("Backtesten met verschillende stop-loss waarden...")
    print()

    all_results = []

    for stop_val in STOP_LOSS_VALUES_TO_TEST:
        total_start = START_CAPITAL
        total_end = 0
        symbol_results = []

        for symbol in SYMBOLS:
            df = data[symbol]
            if df.empty:
                continue
            res = run_backtest(df, symbol, CAPITAL_PER_ASSET, stop_val)
            total_end += res["final_value"]
            symbol_results.append(res)

        total_return = (total_end - total_start) / total_start * 100
        all_results.append(
            {
                "stop_loss": stop_val,
                "total_return_pct": total_return,
                "final_value": total_end,
                "symbol_results": symbol_results,
            }
        )

    # Sorteer op return (beste eerst)
    all_results.sort(key=lambda x: x["total_return_pct"], reverse=True)

    print("Resultaten (beste stop-loss eerst):")
    print("-" * 60)
    for r in all_results:
        print(f"\nStop-loss ${r['stop_loss']:.2f}/eenheid:")
        print(f"  Totaal return: {r['total_return_pct']:+.2f}% | Eindwaarde: ${r['final_value']:.2f}")
        for sr in r["symbol_results"]:
            print(f"    {sr['symbol']}: {sr['return_pct']:+.2f}% ({sr['n_trades']} trades)")

    best = all_results[0]
    print()
    print("=" * 60)
    print(f"Beste stop-loss: ${best['stop_loss']:.2f}/eenheid (return: {best['total_return_pct']:+.2f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
