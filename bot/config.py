"""
Configuratie voor de Kraken range-trading bot.
"""

# Pool van crypto symbolen op Kraken (tegen EUR)
SYMBOL_POOL = [
    "AVAX/EUR", "UNI/EUR", "AAVE/EUR", "LINK/EUR", "DOT/EUR",
    "SOL/EUR", "ADA/EUR", "XRP/EUR", "LTC/EUR", "BCH/EUR",
    "DOGE/EUR", "ETH/EUR", "BTC/EUR",
]

# Hoeveel symbolen actief getrade worden (geselecteerd op winstgevendheid)
SYMBOLS_ACTIVE = 3

# Voor backtest: eerste N uit pool (zelfde subset als live)
SYMBOLS = SYMBOL_POOL[:SYMBOLS_ACTIVE]

# Maximaal kapitaal dat de bot mag inzetten (EUR)
# De rest van je account wordt NIET aangeraakt door de bot
MAX_CAPITAL_EUR = 500

# Kapitaal per asset (alleen voor backtest; live gebruikt MAX_CAPITAL_EUR / actieve symbolen)
CAPITAL_PER_ASSET = MAX_CAPITAL_EUR / SYMBOLS_ACTIVE

# Range niveaus (rolling lookback met daily bars)
# Gebruik gemiddelde van laatste 3 dagen i.p.v. 1 dag - minder gevoelig voor uitschieters
LEVELS_LOOKBACK_DAYS = 3
BUY_ABOVE_LOW_PCT = 0.005   # 0.5% boven de gem. low
SELL_BELOW_HIGH_PCT = 0.02  # 2% onder de gem. high
MIN_SPREAD_PCT = 0.02       # minimaal 2% spread tussen koop en verkoop

# Stop-loss: vast bedrag per eenheid onder koopniveau
STOP_LOSS_PER_UNIT = 0.01

# Na cancel: wacht even voordat nieuwe order geplaatst wordt (balance moet vrijkomen)
ORDER_REPLACE_DELAY_SEC = 3

# Dynamische order updates: herplaats order als prijs meer dan dit percentage afwijkt
ORDER_UPDATE_THRESHOLD = 0.01  # 1%

# Na 24 uur: order waarschijnlijk niet meer relevant (prijs bewogen), cancel en herplaats
ORDER_MAX_AGE_HOURS = 24

# Als huidige prijs >5% boven/onder order: order vult waarschijnlijk niet, direct vervangen
ORDER_STALE_PRICE_THRESHOLD = 0.05

STOP_LOSS_VALUES_TO_TEST = [0.01, 0.02, 0.03, 0.05, 0.10]  # voor backtest

# Backtest
BACKTEST_MONTHS = 3
TIMEFRAME = "1Day"
