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

# Alpaca range-bot draait op meer parallelle symbolen dan hybrid/Kraken: het
# risico per trade blijft 1% van de equity (safety.buy_cap), maar er staan meer
# limietorders in de markt, dus vaker een fill en minder cash die stilstaat.
import os as _os_range

ALPACA_RANGE_SYMBOLS_ACTIVE = int(
    _os_range.environ.get("ALPACA_RANGE_SYMBOLS_ACTIVE", "5")
)

# Plafond op de totale blootstelling. SAFETY_MAX_ALLOC_PCT begrenst alleen per
# symbool (20%), dus zonder deze grens kan de bot met meer parallelle symbolen
# volledig belegd raken.
ALPACA_RANGE_MAX_DEPLOYED_PCT = float(
    _os_range.environ.get("ALPACA_RANGE_MAX_DEPLOYED_PCT", "0.60")
)

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
# Onder dit bedrag eet de vaste round-trip-fee meer op dan de minimale spread die
# de bot eist: zulke restposities krijgen geen exit-order en bezetten geen
# kapitaalslot, maar mogen wel weer aangevuld worden tot een volwaardige positie.
ALPACA_MIN_POSITION_NOTIONAL_USD = ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD / MIN_SPREAD_PCT
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


# Journal/Telegram netto-PnL op Alpaca: vaste USD per fill (default = zijde hierboven).
import os as _os_journal_fees

_jf_default = str(ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD)
_jffe = _os_journal_fees.environ.get("JOURNAL_FIXED_FEE_PER_FILL_USD", _jf_default).strip()
JOURNAL_FIXED_FEE_PER_FILL_USD = float(_jffe) if _jffe else 0.0
# Telegram: geen bericht per koop-fill; alleen afgeronde verkoop met PnL (standaard).
TELEGRAM_NOTIFY_BUY_FILLS = _os_journal_fees.environ.get(
    "TELEGRAM_NOTIFY_BUY_FILLS", "false"
).strip().lower() in ("1", "true", "yes", "on")

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
# Bij gap/hysteresis blijft vorig regime; smalle drempels (25/28) hielden bots
# jaren op TRENDING_UP → trend-strategie blokkeerde entries bij chop.
HYBRID_ADX_RANGE_THRESHOLD = 30.0
HYBRID_ADX_TREND_THRESHOLD = 35.0
HYBRID_REGIME_CONFIRMATION_BARS = 1
HYBRID_RANGE_LOOKBACK_HOURS = 48
HYBRID_MIN_SPREAD_PCT = 0.012
HYBRID_UNCERTAINTY_MAX_ADX_FOR_RANGE = 34.5

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

# ---------------------------------------------------------------------------
# Safety guardrails voor de Alpaca range-bot (paper 1000 eu)
# ---------------------------------------------------------------------------

SAFETY_ENABLED = _os.environ.get("SAFETY_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
SAFETY_DRY_RUN = _os.environ.get("SAFETY_DRY_RUN", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
SAFETY_STATE_FILE = _os.environ.get("SAFETY_STATE_FILE", ".alpaca_safety_state.json")

# Portfolio circuit breaker. Bij pause worden open buy orders geannuleerd en
# nieuwe buys tijdelijk geblokkeerd. Liquidate triggert alleen exits die ook
# hun software-stop raken; geen blinde alles-verkoop.
SAFETY_PEAK_DRAWDOWN_PAUSE_PCT = float(
    _os.environ.get("SAFETY_PEAK_DRAWDOWN_PAUSE_PCT", "0.20")
)
SAFETY_PEAK_DRAWDOWN_LIQUIDATE_PCT = float(
    _os.environ.get("SAFETY_PEAK_DRAWDOWN_LIQUIDATE_PCT", "0.08")
)
SAFETY_COOLDOWN_HOURS = int(_os.environ.get("SAFETY_COOLDOWN_HOURS", "6"))
SAFETY_SYMBOL_COOLDOWN_HOURS = int(
    _os.environ.get("SAFETY_SYMBOL_COOLDOWN_HOURS", "24")
)

# Software-stop: per run gecontroleerd. Alpaca crypto ondersteunt geen
# bracket/OCO naast de take-profit limit, dus stop-exits zijn cancel+sell.
SAFETY_STOP_MIN_PCT = float(_os.environ.get("SAFETY_STOP_MIN_PCT", "0.06"))
SAFETY_STOP_MAX_PCT = float(_os.environ.get("SAFETY_STOP_MAX_PCT", "0.10"))
SAFETY_STOP_ATR_MULT = float(_os.environ.get("SAFETY_STOP_ATR_MULT", "2.0"))
SAFETY_AGGRESSIVE_SELL_DISCOUNT_PCT = float(
    _os.environ.get("SAFETY_AGGRESSIVE_SELL_DISCOUNT_PCT", "0.003")
)

# Entry gates: voorkom dip-buying in duidelijke neertrend.
SAFETY_SYMBOL_EMA_GATE = _os.environ.get(
    "SAFETY_SYMBOL_EMA_GATE", "false"
).strip().lower() in ("1", "true", "yes", "on")
SAFETY_MARKET_GATE = _os.environ.get(
    "SAFETY_MARKET_GATE", "false"
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
SAFETY_MARKET_DROP_7D_PCT = float(
    _os.environ.get("SAFETY_MARKET_DROP_7D_PCT", "0.05")
)
SAFETY_EMA_FAST_DAYS = int(_os.environ.get("SAFETY_EMA_FAST_DAYS", "20"))
SAFETY_EMA_SLOW_DAYS = int(_os.environ.get("SAFETY_EMA_SLOW_DAYS", "50"))

# Risk-based notional cap voor nieuwe buys.
SAFETY_MAX_ALLOC_PCT = float(_os.environ.get("SAFETY_MAX_ALLOC_PCT", "0.20"))
SAFETY_RISK_PER_TRADE_PCT = float(
    _os.environ.get("SAFETY_RISK_PER_TRADE_PCT", "0.01")
)
