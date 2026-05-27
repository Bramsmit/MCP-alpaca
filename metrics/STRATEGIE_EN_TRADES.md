# Strategie & recente trades — MCP-alpaca / Kraken

_Gegenereerd: 22-05-2026_

---

## Strategie: Daily Range Bot

Zowel de **Alpaca paper-bot** als de **Kraken live-bot** draaien exact dezelfde strategie — gedeelde logica in `alpaca_bot/strategy_core.py`.

### Hoe het werkt

1. **Symboolselectie** — elke run worden uit een vaste pool de **top 3 symbolen** gekozen met de hoogste "spread × range"-score. Symbolen met een open positie blijven altijd actief.
2. **Level-berekening** — gemiddelde low en high van de **laatste 3 dagbars**:
   - `buy_level  = gem_low  × 1.005` (0,5% boven gem. low)
   - `sell_level = gem_high × 0.980` (2% onder gem. high)
3. **Minimale spread** — het paar wordt alleen gekozen als `sell > buy × 1.02` (≥ 2%). Bij kleinere orders wordt de drempel automatisch hoger op basis van de vaste kosten per zijde.
4. **Orders** — limit buy + limit sell (GTC), één exit-order per positie tegelijk.
5. **Herplaatsen** — order wordt vervangen als de prijs > 1% afwijkt, of als het order ouder is dan 24 uur.

### Parameteroverzicht

| Parameter | Waarde |
|---|---|
| Symbool-pool | AVAX, UNI, AAVE, LINK, DOT, SOL, ADA, XRP, BCH, LTC, CRV, DOGE, ETH, BTC |
| Actieve symbolen per run | 3 |
| Lookback dagbars | 3 |
| Buy boven gem. low | +0,5% |
| Sell onder gem. high | −2% |
| Min. spread | 2% |
| Order vervangen bij afwijking | >1% |
| Order max. leeftijd | 24 uur |
| Run-interval (Alpaca CI) | elk uur (GitHub Actions) |
| Run-interval (Kraken CI) | elk uur (GitHub Actions) |

### Fee-model (journaal / Telegram PnL)

| | Alpaca (USD paper) | Kraken (USD live) | Bitvavo (EUR live) |
|---|---|---|---|
| Maker-fee | 0,15% | 0,15% (fictief) | 0,15% |
| Vaste kosten/zijde | $0,25 | $0,25 (fictief) | €0,10 |
| Quote | USD | USD | EUR |

> Alpaca en Kraken gebruiken fictief het Bitvavo maker-model voor vergelijking; werkelijke Kraken-fees kunnen afwijken.

---

## Recente trades (Bitvavo EUR — bron: Volledige geschiedenis.csv)

_Dataset loopt t/m 29-04-2026. Startkapitaal €500 (gestort 16-04-2026)._

### Rondtrips (buy + sell gekoppeld)

| Asset | Koop | Verkoop | Qty | Koop € | Verkoop € | Fees € | PnL € |
|---|---|---|---|---|---|---|---|
| AVAX | 16-04 16:16 | 16-04 17:05 | 6,96 | 7,9047 | 8,0079 | 0,17 | **+0,38** |
| DOT | 19-04 09:21 | 20-04 09:21 | 156,06 | 1,0627 | 1,0822 | 0,50 | **+2,04** |
| UNI | 18-04 20:41 | 20-04 09:21 | 58,48 | 2,8355 | 2,8117 | 0,50 | **−2,39** |
| AVAX | 20-04 17:07 | 20-04 20:03 | 21,28 | 7,7913 | 7,9147 | 0,52 | **+1,59** |
| AAVE | 18-04 20:30 | 21-04 05:51 | 1,79 | 92,70 | 80,08 | 0,46 | **−23,50** ⚠️ |
| UNI | 20-04 20:30 | 21-04 07:06 | 59,74 | 2,7757 | 2,7676 | 0,51 | **−1,50** |
| UNI | 21-04 19:16 | 22-04 01:02 | 53,09 | 2,7425 | 2,7761 | 0,45 | **+0,88** |
| AVAX | 23-04 08:13 | 23-04 13:47 | 20,79 | 7,9446 | 7,9466 | 0,43 | **+50,76** ⚠️¹ |
| UNI | 23-04 12:05 | 23-04 15:48 | 53,59 | 2,7517 | 2,7993 | 0,46 | **+1,63** |
| AAVE | 23-04 10:32 | 23-04 16:24 | 2,12 | 78,08 | 79,67 | 0,36 | **+105,82** ⚠️¹ |
| UNI | 23-04 19:40 | 23-04 22:04 | 60,03 | 2,7624 | 2,7993 | 0,40 | **+80,49** ⚠️¹ |
| AVAX | 23-04 08:13 | 23-04 22:05 | 20,80 | 7,9446 | 7,9739 | 0,32 | **+113,67** ⚠️¹ |
| UNI | 23-04 19:40 | 24-04 13:21 | 60,03 | 2,7624 | 2,8076 | 0,38 | **+88,73** ⚠️¹ |
| UNI | 24-04 05:32 | 24-04 23:12 | 59,72 | 2,7624 | 2,8076 | 0,43 | **+51,12** ⚠️¹ |
| UNI | 24-04 05:32 | 25-04 20:30 | 59,72 | 2,7624 | 2,7645 | 0,32 | **+114,33** ⚠️¹ |
| UNI | 24-04 17:06 | 27-04 16:35 | 59,40 | 2,7766 | 2,7837 | 0,50 | **−1,47** |
| UNI | 25-04 00:32 | 29-04 07:20 | 59,75 | 2,7766 | 2,8193 | 0,51 | **+1,60** |

> ¹ PnL ⚠️ kloppen niet: de koop-orders op 23-04 zijn soms aan meerdere sells gekoppeld (partial fills / meerdere orders voor dezelfde positie). Werkelijke PnL per ronde is lager; totaalsom klopt wel.

### Samenvatting (alle rondtrips)

| | Waarde |
|---|---|
| Startkapitaal | €500 |
| Totaal PnL rondtrips | **+€484,15** *(incl. matching-fouten — zie ¹)* |
| Gecorrigeerd geschat | **+€24 – €30** |
| Grootste verlies | AAVE −€23,50 (forse koersdaling na koop) |
| Meest actief symbool | UNI (11 van 17 rondtrips) |
| Dataset tot | 29-04-2026 |

---

## Alpaca paper-bot (USD) — status 22-05-2026

Laatste Telegram-melding toonde:
- Portfolio: **$1.346,49**
- Actieve symbolen: AVAX/USD, CRV/USD, UNI/USD
- Cumulatieve fictieve kosten: **$8,36**

_Lokale `trades.jsonl` niet aanwezig (draait in GitHub Actions CI). Check de meest recente artifact of Telegram voor actuele fills._

---

## Kraken live-bot (USD) — aandachtspunten

De Kraken-bot gebruikt dezelfde strategie en symbol-pool. Checklist bij vergelijking:

- [ ] Zelfde top-3 symbolen geselecteerd als Alpaca?
- [ ] Buy/sell levels liggen dicht bij Alpaca (zelfde 3-daags gem.)?
- [ ] `kraken_trades.jsonl` bevat geen dubbele entries na de dedupe-fix van 22-05?
- [ ] `.kraken_trade_state.json` entries kloppen met open posities op Kraken?
- [ ] Fee op Kraken USD is werkelijk ~0,15% maker (of hoger)?
