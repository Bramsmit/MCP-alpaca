"""
Configuratie voor de range-trading bot.
"""

# Assets (SHIB/PEPE: Alpaca geeft "limit price must be > 0" - gebruik AVAX ipv SHIB)
SYMBOLS = ["AVAX/USD", "UNI/USD", "AAVE/USD"]

# Kapitaal
START_CAPITAL = 1000
CAPITAL_PER_ASSET = START_CAPITAL / 3  # 1/3 per crypto

# Range niveaus (rolling 24h met daily bars)
BUY_ABOVE_LOW_PCT = 0.005   # 0.5% boven de low
SELL_BELOW_HIGH_PCT = 0.02  # 2% onder de high
MIN_SPREAD_PCT = 0.02       # minimaal 2% spread tussen koop en verkoop

# Stop-loss: vast bedrag per eenheid onder koopniveau
# Backtest beste: $0.01/eenheid
STOP_LOSS_PER_UNIT = 0.01

# Dynamische order updates: herplaats order als prijs meer dan dit percentage afwijkt
ORDER_UPDATE_THRESHOLD = 0.01  # 1%

# Na 30 uur: order waarschijnlijk niet meer relevant (prijs bewogen), cancel en herplaats met verse 24h levels
ORDER_MAX_AGE_HOURS = 30
STOP_LOSS_VALUES_TO_TEST = [0.01, 0.02, 0.03, 0.05, 0.10]  # voor backtest

# Backtest
BACKTEST_MONTHS = 3
TIMEFRAME = "1Day"
