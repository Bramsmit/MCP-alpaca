# Alpaca paper vs Kraken live — vergelijking

_Gegenereerd: 22-05-2026_

---

## Gedeelde strategie (beide bots identiek)

| Parameter | Waarde |
|---|---|
| Type | Daily range-bot (limit buy + limit sell, GTC) |
| Symbool-pool | AVAX, UNI, AAVE, LINK, DOT, SOL, ADA, XRP, BCH, LTC, CRV, DOGE, ETH, BTC |
| Actief per run | top 3 op spread × range score |
| Level-berekening | gem. low/high laatste **3 dagbars** |
| Buy level | gem. low × 1,005 (+0,5%) |
| Sell level | gem. high × 0,980 (−2%) |
| Minimale spread | ≥ 2% (dynamisch hoger bij kleine orders) |
| Order vervangen | afwijking > 1% of ouder dan 24 uur |
| Run-interval | elk uur via GitHub Actions |

---

## Alpaca paper-bot (USD)

**Bron:** `metrics/alpaca_filled_orders_2026-02-05_2026-05-05.csv`
**Periode export:** 14 maart 2026 → 5 mei 2026 (91 rondtrips)

> Na 5 mei liep het portfolio door tot **$1.346,49** op 22-05-2026 (Telegram-dagrapport).

### Totaalresultaat (t/m 5 mei)

| Metric | Waarde |
|---|---|
| Rondtrips (FIFO) | 91 |
| Winnende trades | 74 (81%) |
| Verliezende trades | 17 (19%) |
| Bruto PnL | +$364,79 |
| Fictieve fees (0,15% maker + $0,25/zijde) | −$105,13 |
| **Netto PnL** | **+$259,60** |
| Gem. per trade | +$2,85 |
| Beste trade | +$19,00 (DOT 13 apr) |
| Slechtste trade | −$14,79 (AAVE 25 apr) |

### Per symbool (t/m 5 mei)

| Symbool | Trades | Win% | Bruto | Fees | **Netto** |
|---|---|---|---|---|---|
| DOT/USD | 23 | 83% | +$140,49 | $26,00 | **+$114,49** |
| CRV/USD | 15 | 93% | +$85,33 | $17,96 | **+$67,37** |
| UNI/USD | 24 | 88% | +$70,04 | $29,51 | **+$40,53** |
| AAVE/USD | 15 | 80% | +$33,38 | $16,32 | **+$17,05** |
| LINK/USD | 3 | 100% | +$14,37 | $3,37 | **+$11,00** |
| ADA/USD | 5 | 40% | +$10,53 | $5,70 | **+$4,82** |
| AVAX/USD | 2 | 50% | +$5,87 | $2,04 | **+$3,83** |
| ETH/USD | 1 | 100% | +$2,61 | $1,49 | **+$1,13** |
| SOL/USD | 1 | 100% | +$1,61 | $0,92 | **+$0,69** |
| XRP/USD | 1 | 0% | +$0,38 | $0,82 | **−$0,44** |
| BCH/USD | 1 | 0% | +$0,18 | $1,00 | **−$0,82** |

### Cumulatieve groei over tijd

| Periode | PnL die maand | Cum. PnL |
|---|---|---|
| Mrt 2026 (14–31) | +$21,29 | $21,29 |
| Apr 2026 | +$182,28 | $203,57 |
| Mei 2026 (1–5) | +$56,03 | $259,60 |
| Mei 2026 (6–22, schatting) | ±$87* | **±$346*** |

> *Schatting op basis van portfolio $1.346 vs startwaarde ~$1.000 begin mei. Werkelijk cijfer staat in de CI-artifact `trades.jsonl`.

### Top-3 meest actieve symbolen (Alpaca)

1. **DOT/USD** — 23 trades, grootste winstbron (+$114)
2. **UNI/USD** — 24 trades, consistent kleine winsten (+$41)
3. **CRV/USD** — 15 trades, hoogste win-rate 93% (+$67)

---

## Kraken live-bot (USD)

**Bron:** `kraken_trades.jsonl` (CI artifact) — onderstaande tabel invullen na download.

> Download het meest recente artifact via GitHub Actions → "Kraken Trading Bot" → meest recente run → artifact `kraken-journals-*`.

### Totaalresultaat (invullen)

| Metric | Alpaca paper | Kraken live |
|---|---|---|
| Periode | 14 mrt – 22 mei | _?_ |
| Startkapitaal | ~$1.000 | _?_ |
| Portfolio nu | $1.346 | _?_ |
| **Netto PnL** | **+$346 ±** | _?_ |
| Rondtrips | 91+ | _?_ |
| Win-rate | 81% | _?_ |
| Gem. per trade | +$2,85 | _?_ |

### Per symbool (invullen)

| Symbool | Kraken trades | Kraken netto |
|---|---|---|
| DOT/USD | _?_ | _?_ |
| CRV/USD | _?_ | _?_ |
| UNI/USD | _?_ | _?_ |
| AAVE/USD | _?_ | _?_ |

---

## Checklist bij vergelijking

- [ ] Zijn de **actieve symbolen** op dit moment gelijk? (Alpaca: AVAX, CRV, UNI op 22 mei)
- [ ] Liggen de **buy/sell levels** dicht bij elkaar? (zelfde 3-daags gem. → vrijwel identiek)
- [ ] Is de **win-rate** op Kraken vergelijkbaar met 81% paper?
- [ ] Zijn de **gemiddelde fees** op Kraken ≤ 0,15% maker? (anders fee-drempel aanpassen)
- [ ] Zijn er **openstaande posities** op Kraken die het paper-bot niet heeft (of vice versa)?
- [ ] Is er een groot verschil in **vullingen** (slippage Kraken vs Alpaca paper)?
- [ ] Klopt `.kraken_trade_state.json` `entries` met de werkelijke open posities op Kraken?
- [ ] Zijn er dubbele notificaties geweest vóór de dedupe-fix van 22 mei? (check `kraken_trades.jsonl` op dubbele order-IDs)

---

## Opmerkingen

- **Fee-model Kraken:** de bot rekent fictief 0,15% maker + $0,25 vaste kosten, maar Kraken rekent werkelijk per trade af. Bij hogere taker-fees loopt de netto PnL terug. Controleer je Kraken fee-tier.
- **USD vs USD:** beide bots quoten in USD, directe vergelijking mogelijk zonder wisselkoers.
- **Paper ≠ live:** Alpaca paper garandeert altijd vulling bij limietprijs; Kraken kan deels of niet vullen bij dun orderboek (vooral kleinere altcoins als CRV).
- **Meest winstgevend Alpaca:** DOT en CRV zijn de uitschieters. Check of Kraken dezelfde niveaus haalt.
