# Verificatie: algemene Alpaca/Bitvavo-tekst vs deze codebase

Dit document vat de verificatie samen: jouw uitleg over Alpaca paper trading, Bitvavo live API’s en praktische checklists, vergeleken met wat er **in deze repository** daadwerkelijk staat.

## 1. Wat in die tekst inhoudelijk klopt (algemeen)

- **Alpaca paper vs live:** Paper is gesimuleerd; fills en dynamiek kunnen afwijken van live — dat is consistent met hoe Alpaca paper positioneert. De kern (paper niet 1-op-1 live) is terecht.
- **Bitvavo:** Spreads, fees, minimums, rate limits, marktstatus, WebSocket als aanbevolen pad voor order tracking, EUR vs USD bij **absolute** drempels — dat zijn geldige punten voor **elke** Bitvavo-integratie, onafhankelijk van deze repo.
- **Een dergelijke checklist** (markets ophalen, afronden, fees meenemen, WebSocket, partial fills, throttling, API-key hygiene) is **best practice** voor productie; niets daarvan is “onjuist”.

## 2. Eerlijke nuance: dat verhaal vs *dit* project

In [`bot/live_trader.py`](../bot/live_trader.py) zit de **Alpaca**-bot (crypto tegen **USD**, `TradingClient`, `ALPACA_PAPER_TRADE`).

In [`bot/bitvavo_trader.py`](../bot/bitvavo_trader.py) zit een **aparte** Bitvavo-bot via **ccxt** (EUR-paren), met eigen config [`bot/bitvavo_config.py`](../bot/bitvavo_config.py) en eigen state (`.bitvavo_trade_state.json`, `bitvavo_trades.jsonl`).

Dat betekent: je beschrijft geen “één bot die van endpoint is gewisseld”, maar **twee implementaties naast elkaar** met vergelijkbare range-logica. Strategie-parameterpercentages zijn in beide configs **relatief** (%, spread, lookback) — dat sluit aan bij het punt dat **EUR vs USD** vooral pijn doet bij vaste dollarbedragen; hier zijn de drempels grotendeels **niet** in dollars gehard.

## 3. Waar de checklist wél / niet in de Bitvavo-code terugziet

| Thema | In de algemene tekst | In [`bot/bitvavo_trader.py`](../bot/bitvavo_trader.py) (eerlijk) |
|--------|----------------------|------------------------------------------------------------------|
| EUR vs USD | Quote-currency en minimums verschillen | **EUR**-pool en `MAX_CAPITAL_EUR` in config; geen USD-quote in deze bot. |
| Afronding / precisie | tickSize, decimals, minima | **ccxt** `amount_to_precision` / `price_to_precision` + `load_markets()` — geen handmatige GET /markets-cache, maar wel exchange-precision via ccxt. |
| Fees in strategie | Entry+exit meenemen | **Geen** expliciet fee-model in drempels/PnL-berekening; PnL op sell is grof `(price - entry) * qty` zonder fee-regel (zie [`bot/bitvavo_trader.py`](../bot/bitvavo_trader.py) rond regels 347–352). |
| Uitvoering | WebSocket voor orders | **REST** (`fetch_my_trades`, orders plaatsen via ccxt). `enableRateLimit: True` helpt met limits; **geen** WebSocket order stream in deze bot. |
| Partial fills / market quirks | Belangrijk voor live | Bot gebruikt **vooral limit** orders; `fetch_my_trades` per fill — geen aparte WebSocket partial-fill state machine. |
| Rate limits | Throttling, geen spam | ccxt rate limit aan; geen extra backoff-layer in code als verplicht — **gedeeltelijk** gedekt. |
| Balans available vs in orders | `available` vs `inOrder` | Er is o.a. `get_balance` op **free** EUR en logica rond orders/vervanging; volledige “fee buffer”-story niet als apart hoofdstuk uitgewerkt. |
| DRY_RUN | — | Parallel aan “paper”: `BITVAVO_DRY_RUN` — geen echte orders als True (`get_exchange` in [`bot/bitvavo_trader.py`](../bot/bitvavo_trader.py)). |

## 4. Conclusie

- **De uitleg over Alpaca paper en Bitvavo live API’s is als algemene kennis goed bruikbaar** en de risico’s (optimisme paper, fees, minimums, limits) zijn reëel.
- **Voor deze repo moet je het kader aanpassen:** het is **niet** “dezelfde bot is verhuisd”, maar **Alpaca-bot** en **Bitvavo-bot** naast elkaar; [`.github/workflows/trade.yml`](../.github/workflows/trade.yml) / [`.github/workflows/trade_v2.yml`](../.github/workflows/trade_v2.yml) vs [`.github/workflows/trade_bitvavo.yml`](../.github/workflows/trade_bitvavo.yml) zijn verschillende entrypoints en secrets.
- **Een strenge praktische checklist is strenger dan wat de Bitvavo-bot nu overal expliciet doet** (vooral: fees in strategie, WebSocket-ordertracking, uitgebreide market-status handling). Wat er wél zit (EUR-config, ccxt-precision, balance-aware flows, trade journaling, rate limit via ccxt) sluit **deels** aan.

Geen codewijzigingen in deze verificatie; alleen dit kaderdocument.
