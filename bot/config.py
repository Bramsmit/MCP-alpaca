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
START_CAPITAL = 1000
CAPITAL_PER_ASSET = START_CAPITAL / SYMBOLS_ACTIVE  # verdeel over actieve symbolen

# Range niveaus (rolling 24h met daily bars)
# Gebruik gemiddelde van laatste 3 dagen i.p.v. 1 dag - minder gevoelig voor uitschieters
LEVELS_LOOKBACK_DAYS = 3
BUY_ABOVE_LOW_PCT = 0.005   # 0.5% boven de gem. low
SELL_BELOW_HIGH_PCT = 0.02  # 2% onder de gem. high
MIN_SPREAD_PCT = 0.02       # minimaal 2% spread tussen koop en verkoop

# Stop-loss: vast bedrag per eenheid onder koopniveau
# Backtest beste: $0.01/eenheid
STOP_LOSS_PER_UNIT = 0.01

# Alpaca crypto: slechts 1 exit order per positie (geen bracket orders).
# Plaats NOOIT limit sell + stop-loss tegelijk - 2e order faalt met "available: 0".
ALPACA_CRYPTO_SINGLE_EXIT_ORDER = True

# Dynamische order updates: herplaats order als prijs meer dan dit percentage afwijkt
ORDER_UPDATE_THRESHOLD = 0.01  # 1%

# Na 24 uur: order waarschijnlijk niet meer relevant (prijs bewogen), cancel en herplaats met verse 24h levels
ORDER_MAX_AGE_HOURS = 24

# Als huidige prijs >5% boven buy order: order vult waarschijnlijk niet, direct cancel+herplaats
ORDER_STALE_PRICE_THRESHOLD = 0.05
STOP_LOSS_VALUES_TO_TEST = [0.01, 0.02, 0.03, 0.05, 0.10]  # voor backtest

# Backtest
BACKTEST_MONTHS = 3
TIMEFRAME = "1Day"
