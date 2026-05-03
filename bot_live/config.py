"""
Configuratie voor de range-trading bot.
"""

# Pool van altcoins (SHIB/PEPE overgeslagen: Alpaca limit price issues)
SYMBOL_POOL = [
    "AVAX/USD", "UNI/USD", "AAVE/USD", "LINK/USD", "DOT/USD",
    "SOL/USD", "ADA/USD", "XRP/USD", "BCH/USD", "LTC/USD",
    "CRV/USD", "DOGE/USD", "ETH/USD", "BTC/USD",
]

# Hoeveel symbolen actief getrade worden (geselecteerd op winstgevendheid)
SYMBOLS_ACTIVE = 3

# Voor backtest: eerste N uit pool (zelfde subset als live)
SYMBOLS = SYMBOL_POOL[:SYMBOLS_ACTIVE]

# Kapitaal
START_CAPITAL = 500
# verdeel over actieve symbolen
CAPITAL_PER_ASSET = START_CAPITAL / SYMBOLS_ACTIVE

# Range niveaus (rolling 24h met daily bars)
# Gemiddelde laatste N dagen i.p.v. 1 dag — minder uitschieters
LEVELS_LOOKBACK_DAYS = 3
BUY_ABOVE_LOW_PCT = 0.005   # 0.5% boven de gem. low
SELL_BELOW_HIGH_PCT = 0.02  # 2% onder de gem. high
MIN_SPREAD_PCT = 0.02       # minimaal 2% spread tussen koop en verkoop

# Bitvavo spot (EUR-markten), laagste tier tot ~€100k volume / 30 dagen:
# maker vanaf 0,15%, taker vanaf 0,25%.
BITVAVO_MAKER_FEE_RATE = 0.0015
BITVAVO_TAKER_FEE_RATE = 0.0025
# Limietorders ≈ maker; stop/markt-exit ≈ taker (backtest).
# Niet in Alpaca-orders: alleen per trade handmatig doorrekenen (live/journal/telegram/backtest).
BITVAVO_FEE_BUY_RATE = BITVAVO_MAKER_FEE_RATE
BITVAVO_FEE_SELL_LIMIT_RATE = BITVAVO_MAKER_FEE_RATE
BITVAVO_FEE_SELL_TAKER_RATE = BITVAVO_TAKER_FEE_RATE

# Alpaca crypto: %-maker + vaste USD per zijde (kleine orders). Tier zelf afstemmen.
ALPACA_CRYPTO_MIN_ORDER_REF_USD = 5.0
ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD = 0.25
ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD = ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD * 2
ALPACA_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT = BITVAVO_MAKER_FEE_RATE * 2
# Journal/fills: uren terug naar closed orders (≥ interval Actions + marge).
ALPACA_FILLED_ORDERS_LOOKBACK_HOURS = 72


def required_min_spread_fraction_crypto_usd(ref_notional_usd: float) -> float:
    """Min. relatieve spread (sell vs buy); zelfde model als bitvavo_config."""
    ref = (
        float(ref_notional_usd)
        if ref_notional_usd and ref_notional_usd > 0
        else ALPACA_CRYPTO_MIN_ORDER_REF_USD
    )
    ref = max(ALPACA_CRYPTO_MIN_ORDER_REF_USD, ref)
    return (
        max(MIN_SPREAD_PCT, ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD / ref)
        + ALPACA_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT
    )


# Stop-loss: vast bedrag per eenheid onder koopniveau
# Backtest beste: $0.01/eenheid
STOP_LOSS_PER_UNIT = 0.01

# Alpaca crypto: max 1 exit order per positie (geen bracket orders).
# NOOIT limit sell + stop-loss tegelijk — 2e order faalt (available: 0).
ALPACA_CRYPTO_SINGLE_EXIT_ORDER = True

# Na cancel: korte pauze (balance moet vrijkomen)
ORDER_REPLACE_DELAY_SEC = 3

# Herplaats order als prijs meer dan dit % afwijkt
ORDER_UPDATE_THRESHOLD = 0.01  # 1%

# Na 24u: order minder relevant; herplaats met verse levels
ORDER_MAX_AGE_HOURS = 24

# Prijs >5% boven buy order: cancel + herplaats
ORDER_STALE_PRICE_THRESHOLD = 0.05
# voor backtest
STOP_LOSS_VALUES_TO_TEST = [0.01, 0.02, 0.03, 0.05, 0.10]

# Backtest
BACKTEST_MONTHS = 3
TIMEFRAME = "1Day"

# ---------------------------------------------------------------------------
# Hybrid regime-aware trader (additief; deelt Alpaca-runtime met range-bot)
# ---------------------------------------------------------------------------

# Master switch. Zolang False blijft gebruikt CI de bestaande range bot.
# Kan overschreven worden via env var HYBRID_ENABLED=true.
import os as _os_hybrid
HYBRID_ENABLED = _os_hybrid.environ.get("HYBRID_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

# Timeframe voor regime-detectie, trend- en range-strategieën in het hybrid model.
HYBRID_TIMEFRAME = "1Hour"

# ADX / regime-detectie (backtests / referentie; live hybrid gebruikt HYBRID_ADX_* hieronder)
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 25.0      # boven dit niveau = trending
ADX_RANGE_THRESHOLD = 20.0      # onder dit niveau = ranging
REGIME_CONFIRMATION_BARS = 2    # aantal candles bevestiging (hysteresis)

# Alleen `hybrid_trader` (v3 / trade_v2): losser dan ADX 20/25 zodat crypto-uurdata
# vaker als "chop/range" telt; UNCERTAIN met matige ADX mag nog range-entries proberen.
HYBRID_ADX_RANGE_THRESHOLD = 25.0
HYBRID_ADX_TREND_THRESHOLD = 28.0
HYBRID_REGIME_CONFIRMATION_BARS = 1
HYBRID_RANGE_LOOKBACK_HOURS = 48
HYBRID_MIN_SPREAD_PCT = 0.015
HYBRID_UNCERTAINTY_MAX_ADX_FOR_RANGE = 27.5

# Trend-strategy
EMA_FAST = 20
EMA_SLOW = 50
TREND_TRAILING_STOP_PCT = 0.05      # 5% trailing stop onder hoogste close sinds entry
TREND_STOP_ATR_MULT = 2.0           # initiële hard stop = entry - 2 * ATR
TREND_CROSSOVER_LOOKBACK_BARS = 3   # crossover mag max N bars oud zijn

# Range-strategy (hourly variant)
RANGE_LOOKBACK_HOURS = 72           # rolling window voor hourly range-levels
RANGE_STOP_ATR_MULT = 1.0

# Risk management (geldt voor beide strategieën)
RISK_PER_TRADE_PCT = 0.01           # 1% van equity per trade

# Safety: als True wordt geen order daadwerkelijk naar Alpaca gestuurd.
# Kan via env variable overschreven worden (DRY_RUN=true/false).
import os as _os
DRY_RUN = _os.environ.get("DRY_RUN", "false").strip().lower() in ("1", "true", "yes", "on")

