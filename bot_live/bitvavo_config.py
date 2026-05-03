"""
Configuratie voor de Bitvavo range-trading bot (EUR pairs).
"""

# Breedere pool: meer kandidaten voor select_top_symbols (score + spread-check).
# Hoeveel tegelijk live is SYMBOLS_ACTIVE — niet gelijk aan pool-grootte.
SYMBOL_POOL = [
    "BTC/EUR",
    "ETH/EUR",
    "SOL/EUR",
    "XRP/EUR",
    "LINK/EUR",
    "ADA/EUR",
    "AVAX/EUR",
    "DOT/EUR",
    "UNI/EUR",
    "AAVE/EUR",
    "DOGE/EUR",
    "LTC/EUR",
    "CRV/EUR",
    "BCH/EUR",
]

SYMBOLS_ACTIVE = 3

# Maximaal kapitaal dat de bot mag inzetten (EUR)
MAX_CAPITAL_EUR = 500

# Kapitaal per asset (alleen voor backtest)
CAPITAL_PER_ASSET = MAX_CAPITAL_EUR / SYMBOLS_ACTIVE

# Range niveaus (rolling lookback met daily bars)
LEVELS_LOOKBACK_DAYS = 3
BUY_ABOVE_LOW_PCT = 0.005   # 0.5% boven de gem. low
SELL_BELOW_HIGH_PCT = 0.02  # 2% onder de gem. high
# Bruto ruimte tussen buy-/sell-level (hoger = minder marginale setups, minder overtrade).
MIN_SPREAD_PCT = 0.024

# Bitvavo fees (pas aan naar je tier op bitvavo.com/fees). Gebruikt voor:
# - strengere pair-selectie: bruto-spread moet ook fees dekken
# - Telegram/journal PnL-schatting op sell (maker beide zijden)
FEE_MAKER_PCT = 0.0015      # 0,15% — typische startfee EUR-markten cat. A
FEE_TAKER_PCT = 0.0025      # 0,25% — alleen ter referentie / logging
# Round-trip bij passieve limits: koop + verkoop als maker (~0,3% totaal)
ESTIMATED_ROUND_TRIP_FEE_PCT = FEE_MAKER_PCT * 2

# Verwachte netto winstmarge op de trade (geen micro-scalps): richting 1,5–2%.
# Limit-sell floor: sell_price >= entry * (1 + ESTIMATED_ROUND_TRIP_FEE_PCT + TARGET_MIN_NET_PROFIT_PCT)
# (fee-aware; nooit verkopen onder alleen-fees-break-even: mult > 1 + fee%).
TARGET_MIN_NET_PROFIT_PCT = 0.02
MIN_LIMIT_SELL_PRICE_MULT = 1 + ESTIMATED_ROUND_TRIP_FEE_PCT + TARGET_MIN_NET_PROFIT_PCT

# Vaste fee per zijde (EUR): bij kleine notionals domineert dit boven %-tarief.
# Spread-check gebruikt max(strategie-%, vaste€/notional) + %-round-trip zodat
# je niet verkoopt als bruto-marge onder circa €0,50 blijft (pas aan naar jouw tier).
FEE_FIXED_PER_SIDE_EUR = 0.25
ROUND_TRIP_FIXED_FEE_EUR = FEE_FIXED_PER_SIDE_EUR * 2

# Conservatieve ondergrens voor spread-check bij lage balance (Bitvavo minimum-ordergebied).
MIN_ORDER_REF_EUR = 5.0

# Fills journal: fetch_my_trades sinds N uur (≥ uurlijkse Actions + uitloop).
FILLS_LOOKBACK_HOURS = 72


def required_min_spread_fraction(ref_notional_eur: float) -> float:
    """
    Minimale relatieve spread (sell vs buy level) zodat geschatte bruto winst in EUR
    de maker-%-fees én vaste round-trip € dekt.
    ref_notional_eur ≈ verwachte ordergrootte (kleinste order = strengste eis).
    """
    ref = float(ref_notional_eur) if ref_notional_eur and ref_notional_eur > 0 else MIN_ORDER_REF_EUR
    ref = max(MIN_ORDER_REF_EUR, ref)
    return max(MIN_SPREAD_PCT, ROUND_TRIP_FIXED_FEE_EUR / ref) + ESTIMATED_ROUND_TRIP_FEE_PCT


# postOnly op Bitvavo: bij True annuleert/wijst de exchange orders af die direct
# taker zouden zijn → vaker maker-fee, maar minder vulling (anders dan Alpaca GTC).
# False ≈ soepelere limits, dichter bij Alpaca; je kunt vaker taker-fee betalen.
# Overschrijven per run: env BITVAVO_POST_ONLY=true of false (override deze default).
POST_ONLY_LIMIT_ORDERS = False

STOP_LOSS_PER_UNIT = 0.01

# Na cancel: wacht even voordat nieuwe order geplaatst wordt
ORDER_REPLACE_DELAY_SEC = 3

# Dynamische order updates
ORDER_UPDATE_THRESHOLD = 0.015  # 1.5%
ORDER_MAX_AGE_HOURS = 24
ORDER_STALE_PRICE_THRESHOLD = 0.05
