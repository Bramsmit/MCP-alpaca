"""
Configuratie voor de Bitvavo range-trading bot (EUR pairs).
"""

# Pool van crypto symbolen op Bitvavo (tegen EUR)
SYMBOL_POOL = [
    "AVAX/EUR", "UNI/EUR", "AAVE/EUR", "LINK/EUR", "DOT/EUR",
    "SOL/EUR", "ADA/EUR", "XRP/EUR", "LTC/EUR", "BCH/EUR",
    "DOGE/EUR", "ETH/EUR", "BTC/EUR",
]

# Hoeveel symbolen actief getrade worden (geselecteerd op winstgevendheid)
SYMBOLS_ACTIVE = 3

# Maximaal kapitaal dat de bot mag inzetten (EUR)
MAX_CAPITAL_EUR = 500

# Kapitaal per asset (alleen voor backtest)
CAPITAL_PER_ASSET = MAX_CAPITAL_EUR / SYMBOLS_ACTIVE

# Range niveaus (rolling lookback met daily bars)
LEVELS_LOOKBACK_DAYS = 3
BUY_ABOVE_LOW_PCT = 0.005   # 0.5% boven de gem. low
SELL_BELOW_HIGH_PCT = 0.02  # 2% onder de gem. high
MIN_SPREAD_PCT = 0.02       # minimaal 2% spread tussen koop en verkoop

STOP_LOSS_PER_UNIT = 0.01

# Na cancel: wacht even voordat nieuwe order geplaatst wordt
ORDER_REPLACE_DELAY_SEC = 3

# Dynamische order updates
ORDER_UPDATE_THRESHOLD = 0.01  # 1%
ORDER_MAX_AGE_HOURS = 24
ORDER_STALE_PRICE_THRESHOLD = 0.05
