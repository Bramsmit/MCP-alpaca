# Implementatieplan — Kraken live range-bot

_Datum: 22 augustus 2026_  
_Doelrepo: **`Kraken bot 500 eu 15 mei/`** (live, GitHub Actions hourly)_  
_Referentierepo: `MCP-alpaca v1 1000 eu/` (Alpaca paper + compare-tooling)_

Dit document is bedoeld om **1-op-1** aan de Kraken-codebase (of aan een agent die daarin werkt) te geven. Het beschrijft wat er misgaat, waarom, welke bestanden je aanpast, en in welke volgorde.

---

## Inhoudsopgave

1. [Context](#1-context)
2. [De zes suggestiepunten](#2-de-zes-suggestiepunten)
3. [Implementatie in vier fases](#3-implementatie-in-vier-fases)
4. [Bestandsoverzicht](#4-bestandsoverzicht)
5. [Commit-volgorde](#5-commit-volgorde)
6. [Verificatie-checklist](#6-verificatie-checklist)
7. [Referentie Alpaca-fixes](#7-referentie-alpaca-fixes)
8. [Agent-prompt (copy-paste)](#8-agent-prompt-copy-paste)

---

## 1. Context

### 1.1 Welke repo is live?

| Repo | Rol |
|---|---|
| **`Kraken bot 500 eu 15 mei/`** | **Draait live** via `.github/workflows/trade.yml` (elk uur UTC) |
| **`MCP-alpaca/kraken/`** | Oudere kopie in Alpaca-monorepo — **niet** wat nu live draait |

Telegram-berichten met prefix `[Kraken]` en meldingen `✅ Afgeronde trade` komen uit de **eerste repo** (`src/rangebot/main.py`).

Entrypoint live: `python -m kraken.live_trader` → `rangebot.main.run_once()`.

### 1.2 Gedeelde strategie (nu identiek aan Alpaca paper)

| Parameter | Waarde |
|---|---|
| Type | Daily range-bot (limit buy + limit sell, GTC) |
| Symbool-pool | AVAX, UNI, AAVE, LINK, DOT, SOL, ADA, XRP, BCH, LTC, CRV, DOGE, ETH, BTC |
| Actief per run | Top **3** op spread × range-score |
| Level-berekening | Gem. low/high laatste **3 dagbars** |
| Buy level | gem. low × 1,005 (+0,5%) |
| Sell level | gem. high × 0,980 (−2%) |
| Minimale spread | ≥ 2% (dynamisch hoger bij kleine orders) |
| Order vervangen | Afwijking > 1% of ouder dan 24 uur |

Config: `src/rangebot/config/settings.py`  
Strategie: `src/rangebot/strategy/range_strategy.py`

### 1.3 Wat ging er mis? (live, 22 aug 2026)

Voorbeelden uit Telegram (bot: `mcp_alpaca_day_trade_live_bot`):

| Trade | Verkoop | Instap (avg) | Bruto | Netto na fee |
|---|---|---|---|---|
| UNI/USD (2×) | $4.0694 | $4.1930 | −$3.53 | −$3.99 |
| DOGE/USD | $0.0911 | $0.0912 | −$0.02 | −$0.17 |

- Portfolio ~**$310** (start ~€500).
- Na de sells draaide de bot verder met **AAVE, XRP, CRV** — UNI/DOGE zaten niet meer in de top-3.

**Conclusie:** dit zijn **echte verliezen**, geen Telegram-bug. De bot volgt de code; het gedrag is op Kraken met echte fees destructief.

### 1.4 Diagnose uit eerdere data-analyse (juli–aug 2026)

- **50 fills** Kraken vs **246** Alpaca in overlapperiode → veel minder activiteit.
- **69%** van bruto PnL ging op aan fees (dunne marges + echte kosten).
- **~75%** van kapitaal stond idle (cash niet effectief ingezet).
- **Alle verlies-roundtrips** in het venster: verkocht **onder kostprijs** (vooral AAVE; later UNI).
- **Orphan-posities:** DOGE/AAVE weken vast — symbool in selectie (balance) maar **geen** sell-order (spread-filter).
- **AVAX:** grote winstbron op Alpaca, **nul** fills op Kraken in dezelfde periode.
- **KRAKEN_POST_ONLY:** lokaal `false`, CI default `true` (alle gemeten fills waren maker ~0,30%/kant).

### 1.5 Wat níet doen

De recente Alpaca-fix (commit `c273f0c` in MCP-alpaca) **niet 1-op-1 kopiëren**:

| Alpaca (paper) | Kraken (live) |
|---|---|
| 5 parallelle symbolen | **Blijf op 3** — meer trades = meer fee-druk |
| Max 60% ingezet | **Max ~40–45%** — conservatiever |
| Geen echte fees | ~0,60% roundtrip maker gemeten |

**Wel overnemen van Alpaca:** dust-drempel (notional) + buy-slots sizing (zie fase B).

---

## 2. De zes suggestiepunten

| # | Probleem | Verwachte impact | Primaire bestanden |
|---|---|---|---|
| **1** | Sell-level zakt onder kostprijs mee bij elke run | **Hoogst** — directe verliezen (UNI −3,3%) | `main.py`, `risk_manager.py` |
| **2** | Kapitaalformule deelt door alle geselecteerde symbolen | **Hoog** — ~75% cash idle, lage omzet | `position_manager.py`, `main.py` |
| **3** | Fee-model klopt niet (spook-$0,25/zijde + te lage %) | **Midden** — marginale trades doorgelaten | `settings.py`, buy-gate in `main.py` |
| **4** | Posities zonder exit als symbool spread-filter faalt | **Midden** — DOGE/AAVE weken vast | `main.py`, `signals.py` |
| **5** | Geen cap per symbool — concentratie (AAVE) | **Midden** | `settings.py`, buy-loop `main.py` |
| **6** | POST_ONLY lokaal ≠ CI; AVAX nooit geselecteerd | **Laag / observatie** | `.env`, `trade.yml`, run-logging |

---

## 3. Implementatie in vier fases

### Fase A — Veiligheid (direct, laag risico)

#### A1. Bodem onder sell-level (suggestie 1)

**Probleem**

In `src/rangebot/main.py` (~regel 231):

```python
limit_sell = sell_level
```

`sell_level` = `gem_high × (1 - SELL_BELOW_HIGH_PCT)` en wordt **elke run** opnieuw berekend. Daalt de markt → sell zakt **onder avg_entry**. Bestaande sell-orders worden vervangen door lagere prijzen (`ORDER_UPDATE_THRESHOLD`, `ORDER_MAX_AGE_HOURS`).

**Gevolg live:** UNI verkocht @ $4.07 na instap @ $4.19 (−3,3% netto).

**Fix**

1. Voeg helper toe in `src/rangebot/execution/risk_manager.py`:

```python
def minimum_profitable_sell_price(
    entry: float,
    *,
    maker_round_trip_pct: float,
    min_margin_pct: float = 0.003,
) -> float:
    """
    Minimale verkoopprijs: entry + roundtrip maker-fees + kleine marge.

    min_margin_pct default 0,3% buffer boven fee-model.
    """
    if entry <= 0:
        return 0.0
    return entry * (1 + maker_round_trip_pct + min_margin_pct)
```

2. In `main.py`, sell-tak:

```python
from rangebot.config.settings import RANGE_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT

entry = avg_entry if avg_entry > 0 else buy_level
fee_floor = minimum_profitable_sell_price(
    entry,
    maker_round_trip_pct=RANGE_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT,
)
limit_sell = max(sell_level, fee_floor)
```

3. **Bestaande sell-order niet verlagen** onder `fee_floor`:
   - Als `existing_sell` en `old_sell_price >= fee_floor` en berekend `limit_sell < fee_floor` → sell **ongewijzigd** (`needs_new_sell = False`).
   - Alleen vervangen/updaten als nieuw level **≥** oude prijs of **≥** fee_floor.

4. Log + optioneel Telegram:

```
UNI/USD: sell-floor $4.21 (entry $4.19), range-level $4.07 → floor actief
```

**Trade-off:** posities blijven langer open in dalende markt. Huidige `stop_price_below_entry()` is slechts `entry - STOP_LOSS_PER_UNIT` ($0.01) — geen echte stop-loss. Apart beslissen of `STOP_LOSS_PER_UNIT` herzien moet worden.

**Tests** (`tests/unit/test_risk_manager.py`):

- `minimum_profitable_sell_price(4.19, maker_round_trip_pct=0.003)` > 4.19
- Integratietest: `limit_sell = max(sell_level, fee_floor)` wanneer `sell_level < entry`

---

#### A2. Exit voor vastzittende posities (suggestie 4)

**Probleem**

In `main.py`:

```python
for symbol in symbols:
    if symbol not in levels:
        continue
```

Flow:

1. `select_top_symbols_for_range()` houdt symbolen met balance **altijd** in `selected`.
2. `levels` bevat alleen symbolen die de **spread-filter** halen.
3. Symbool kan dus in `symbols` zitten maar **niet** in `levels` → **geen sell-order**.

Dit verklaart DOGE ($28, 21+ dagen) en vergelijkbare orphans.

**Fix**

1. Verzamel alle symbolen die beheerd moeten worden:

```python
from rangebot.strategy.signals import symbols_with_balance

held = symbols_with_balance(client, kr_pool)
managed = list(dict.fromkeys(symbols + [s for s in held if s not in symbols]))
```

2. Loop over `managed` i.p.v. alleen `symbols`.

3. Voor symbolen **met positie maar zonder levels** (orphan exit mode):
   - Bereken ruwe levels **zonder spread-gate** (alleen voor exit):

```python
def levels_for_exit_only(rows: list[dict]) -> tuple[float, float] | None:
    t = levels_score_from_daily_rows(rows, min_spread_frac=0.0)
    if t is None:
        return None
    return t[0], t[1]
```

   - Pas sell-floor (A1) toe op `entry`.
   - **Geen nieuwe buys** voor orphan-symbolen.
   - Log: `[Kraken] {sym}: orphan exit mode (buiten spread-filter)`.

4. Optioneel in `select_top_symbols_for_range()`: fallback-levels voor held symbols toevoegen aan `levels` dict.

**Tests** (`tests/unit/test_signals.py` of nieuw `test_main_orphan_exit.py`):

- Symbool met balance, faalt spread → krijgt sell-logica
- Symbool zonder balance, faalt spread → geen sell

---

### Fase B — Kapitaal & dust (suggestie 2 + Alpaca-lessen)

#### B1. Notional dust-drempel

**Probleem**

`symbols_with_balance()` in `strategy/signals.py`:

```python
if qf > float(MIN_SELLABLE_CRYPTO_QTY):  # 0.0001 munt
    out.add(sym)
```

0,106 XRP ($0,16) telt als volwaardige positie → bezet slot, krijgt sell-order, verdeelt kapitaal.

**Fix**

1. In `settings.py`:

```python
# Onder dit bedrag eet roundtrip-fee de minimale spread op.
KRAKEN_MIN_POSITION_NOTIONAL_USD = (
    RANGE_CRYPTO_ROUND_TRIP_FIXED_USD / MIN_SPREAD_PCT
)  # = $25 bij huidige defaults ($0.50 / 0.02)
```

Na fee-model fix (fase C) eventueel afleiden van **percentage-only** drempel.

2. Helper (bijv. `execution/position_manager.py`):

```python
def is_tradable_position(qty: float, ref_price: float) -> bool:
    from decimal import Decimal
    from rangebot.config.settings import (
        MIN_SELLABLE_CRYPTO_QTY,
        KRAKEN_MIN_POSITION_NOTIONAL_USD,
    )
    if qty <= 0 or Decimal(str(qty)) < MIN_SELLABLE_CRYPTO_QTY:
        return False
    return qty * float(ref_price or 0) >= KRAKEN_MIN_POSITION_NOTIONAL_USD
```

3. Pas `symbols_with_balance()` aan: alleen `is_tradable_position(qty, entry_or_last_price)`.

4. In main-loop: restposities onder drempel → geen sell-order, geen slot; **wel** opnieuw kopen toestaan tot volwaardige positie (consolidatie).

---

#### B2. Buy-slots i.p.v. `len(symbols)` (suggestie 2)

**Probleem**

`capital_per_active_symbol_usd()` in `execution/position_manager.py`:

```python
def capital_per_active_symbol_usd(*, portfolio_equity_usd, free_quote_usd, n_symbols):
    n = float(n_symbols)
    slot = portfolio_equity_usd / n * BUYING_POWER_PER_SYMBOL_FRACTION
    cash_cap = free_quote_usd / n
    return min(slot, cash_cap)
```

In `main.py`: `n_symbols=len(symbols)` — inclusief symbolen **met open positie**.

Met 3 posities + weinig cash → elke buy ~$134 max terwijl maar 0–1 slot echt vrij is. Gemeten: ~75% portfolio idle, turnover 5,4× vs 25× Alpaca.

**Fix**

1. In `main.py` na `positions` ophalen:

```python
buy_slots = sum(
    1
    for sym in symbols
    if not is_tradable_position(*positions.get(sym, (0.0, 0.0)))
)
capital_per = capital_per_active_symbol_usd(
    portfolio_equity_usd=portfolio_equity,
    free_quote_usd=free_usd,
    n_symbols=max(1, buy_slots),
)
```

2. **Optioneel** totaal deploy-plafond (Kraken-specifiek, conservatief):

```python
# settings.py
KRAKEN_MAX_DEPLOYED_PCT = float(os.environ.get("KRAKEN_MAX_DEPLOYED_PCT", "0.45"))

# main.py
deployed = max(0.0, portfolio_equity - free_usd)
deploy_room = max(0.0, portfolio_equity * KRAKEN_MAX_DEPLOYED_PCT - deployed)
capital_per = min(capital_per, deploy_room / max(1, buy_slots))
```

3. **`SYMBOLS_ACTIVE` blijft 3** — niet verhogen naar 5.

4. Log per run:

```
Portfolio ~ $535 | Vrije USD $402 | Koopslots: 1 van 3 | Per slot $402.00
```

**Tests** (`tests/unit/test_position_manager.py`):

- `buy_slots=1`, cash=$400 → `capital_per≈400` (niet $133)
- Restpositie $0,16 → telt niet mee in `symbols_with_balance`
- `deploy_room=0` boven plafond → `capital_per=0`

---

#### B3. Run-audit velden

Voeg toe aan `kraken_runs.jsonl` payload in `main.py`:

```json
{
  "buy_slots": 2,
  "deployed_usd": 123.45,
  "deployed_pct": 0.23,
  "capital_per_usd": 178.5,
  "symbols_selected": ["AAVE/USD", "XRP/USD", "CRV/USD"],
  "symbols_held": ["UNI/USD"]
}
```

---

### Fase C — Fee-model (suggestie 3)

**Probleem**

Huidige `settings.py`:

- `BITVAVO_MAKER_FEE_RATE = 0.0015` (0,15%/kant) — te laag voor gemeten Kraken
- `RANGE_CRYPTO_FEE_FIXED_PER_SIDE_USD = 0.25` — **bestaat niet** op Kraken spot
- `required_min_spread_fraction_crypto_usd()` telt vaste fee mee → bestraft kleine orders dubbel

Gemeten op 44 fills met fee-data: **~0,30%/kant** (40× ~0,30%, 4× ~0,40%), gemiddeld **0,31%**, geen taker.

**Fix**

1. Kraken-specifieke constanten in `settings.py`:

```python
# Gemeten live (aug 2026); Tier ~2 maker. Pas aan na volume-tier wijziging.
KRAKEN_MAKER_FEE_RATE = float(os.environ.get("KRAKEN_MAKER_FEE_RATE", "0.0030"))
KRAKEN_TAKER_FEE_RATE = float(os.environ.get("KRAKEN_TAKER_FEE_RATE", "0.0040"))

# Geen vaste USD-fee in spread-gate voor Kraken live.
KRAKEN_USE_FIXED_FEE_IN_SPREAD_GATE = False

# Voor journal/telegram-schatting (percentage-only roundtrip):
RANGE_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT = KRAKEN_MAKER_FEE_RATE * 2
```

2. Pas `required_min_spread_fraction_crypto_usd()` aan:

```python
def required_min_spread_fraction_crypto_usd(ref_notional_usd: float) -> float:
    ref = max(RANGE_MIN_ORDER_REF_USD, float(ref_notional_usd or 0))
    pct = KRAKEN_MAKER_FEE_RATE * 2  # ~0,60% roundtrip
    extra_margin = 0.002  # 0,2% buffer boven fees
    if KRAKEN_USE_FIXED_FEE_IN_SPREAD_GATE:
        fixed = RANGE_CRYPTO_ROUND_TRIP_FIXED_USD / ref
        return max(MIN_SPREAD_PCT, fixed) + pct + extra_margin
    return max(MIN_SPREAD_PCT, pct + extra_margin)
```

3. Buy-gate in `main.py` (blok waar `gross_usd_est < fee_usd_est`): zelfde fee-model gebruiken, **zonder** vaste $0,50 roundtrip tenzij expliciet aan.

4. Telegram (`telegram/notifications.py` / `state_and_fills.py`):
   - Zorg dat `buy_fee_usd` uit state altijd mee gaat bij sells.
   - `$0.00` koopfee op oude posities: noteer in log `buy_fee unknown (legacy entry)`.

**Tests:**

- ref $100 → min spread ≥ ~0,8%
- Geschatte DOGE-trade ($37, 0,1% bruto marge) → buy overgeslagen

---

### Fase D — Risicobeheer & ops (suggesties 5 + 6)

#### D1. Positie-cap per symbool (suggestie 5)

**Probleem:** `KRAKEN_MAX_POSITION_VALUE_USD` bestaat in settings maar default leeg. AAVE kreeg disproportioneel veel buys t.o.v. portfolio (~$587 buys op ~$535 equity in analysevenster).

**Fix**

1. Default via env (documenteer in `.env.example`):

```env
# Max notional per symbool (USD). Leeg = geen cap. Aanbevolen: ~40% equity.
KRAKEN_MAX_POSITION_VALUE_USD=200
```

2. In buy-loop vóór order:

```python
mid = mid_prices.get(symbol) or buy_level
current_notional = pos_qty * mid
cap = KRAKEN_MAX_POSITION_VALUE_USD
if cap and current_notional >= cap:
    log.info("  %s: positie-cap ($%.2f >= $%.2f), geen buy", symbol, current_notional, cap)
    stats["skipped"] += 1
    continue
```

3. Optioneel: cap ook op **ordergrootte** zelf: `capital_for_order = min(capital_per, cap - current_notional)`.

---

#### D2. POST_ONLY gelijktrekken (suggestie 6)

**Situatie:**

- `post_only_from_env()` default **`true`** (`exchange/kraken/common.py`)
- CI (`trade.yml`) zet `KRAKEN_POST_ONLY` **niet** expliciet → CI = true
- Lokale `.env` had `KRAKEN_POST_ONLY=false` → lokale tests ≠ live gedrag

**Fix**

1. `.env.example`: `KRAKEN_POST_ONLY=true`
2. Lokale `.env` gelijk trekken.
3. Optioneel in `.github/workflows/trade.yml`:

```yaml
env:
  KRAKEN_POST_ONLY: ${{ vars.KRAKEN_POST_ONLY || 'true' }}
```

4. In fill-audit: log `fee_rate = fee_usd / notional`. Waarschuwing/Telegram als > 0,35% (taker-verdacht).

---

#### D3. Symbol-selectie debug — AVAX (suggestie 6)

Alpaca: AVAX grote winstbron. Kraken: **0 fills** in overlap.

Voeg per run logging toe (geen strategie-wijziging yet):

```python
for sym in kr_pool:
    if sym not in levels_scored:
        log.info("  %s: niet in levels_scored (data/spread)", sym)
    else:
        buy, sell, score = levels_scored[sym]
        log.info("  %s: score=%.4f spread=%.2f%%", sym, score, (sell/buy-1)*100)
```

Optioneel in run-audit: `selection_debug: {sym: {score, spread_pct, rejected_reason}}`.

---

## 4. Bestandsoverzicht

```
Kraken bot 500 eu 15 mei/
├── src/rangebot/
│   ├── main.py                          ← A1, A2, B1–B3, C buy-gate, D1
│   ├── config/settings.py               ← B1 drempels, C fee-model, D1 cap, D3
│   ├── strategy/
│   │   ├── signals.py                   ← A2, B1 symbols_with_balance
│   │   └── range_strategy.py            ← A2 levels_for_exit_only (optioneel)
│   ├── execution/
│   │   ├── position_manager.py          ← B1 is_tradable_position, B2 capital_per
│   │   └── risk_manager.py              ← A1 minimum_profitable_sell_price
│   ├── exchange/kraken/
│   │   ├── client.py                    ← D2 post_only
│   │   ├── common.py                    ← D2 post_only_from_env
│   │   └── state_and_fills.py           ← C fee logging, telegram buy_fee
│   └── telegram/notifications.py        ← C messaging
├── tests/unit/
│   ├── test_risk_manager.py             ← A1
│   ├── test_position_manager.py         ← B1, B2
│   ├── test_signals.py                  ← A2, B1
│   └── test_sell_floor.py               ← nieuw: A1 integratie
├── .env.example                         ← D1, D2
└── .github/workflows/trade.yml          ← D2 optioneel
```

---

## 5. Commit-volgorde

| Stap | Inhoud | Voorbeeld commit message |
|---|---|---|
| 1 | A1 sell-floor + tests | `fix: never replace Kraken sell below cost plus fees` |
| 2 | A2 orphan exit + tests | `fix: exit orders for held symbols outside spread filter` |
| 3 | B1 dust + buy-slots + deploy cap + tests | `fix: Kraken buy sizing by free slots and notional dust threshold` |
| 4 | C fee-model + buy-gate | `fix: use measured Kraken maker fees in spread gate` |
| 5 | D1 position cap | `feat: optional per-symbol notional cap for Kraken buys` |
| 6 | D2 POST_ONLY + fee logging | `chore: align KRAKEN_POST_ONLY defaults and log fee rates` |
| 7 | D3 selection debug | `chore: log symbol selection scores and reject reasons` |

**Tussen stappen:** `pytest -q` groen; minstens 24–48u live monitoren via Telegram + `data/kraken_trades.jsonl`.

**Eerst testen met** `KRAKEN_DRY_RUN=true` (default) — live pas na expliciet `KRAKEN_DRY_RUN=false` in repo variable.

---

## 6. Verificatie-checklist

### Direct na eerste live run (na DRY_RUN=false)

- [ ] Geen Telegram sell-replace met prijs **onder** `Referentie inkoop (avg)`
- [ ] Restposities <$25 krijgen geen sell-order en bezetten geen slot
- [ ] Orphan-symbolen (buiten top-3 / spread) krijgen exit-order of expliciete orphan-log
- [ ] Run-log toont `Koopslots: n van m` en `capital_per` > oude waarde bij vrije slots
- [ ] `KRAKEN_POST_ONLY=true` in `.env` en CI

### Na 1 week

- [ ] `deployed_pct` in audit stijgt (richting 30–45%, niet ~4–19%)
- [ ] Aandeel verlies-exits onder kostprijs → **0%**
- [ ] Gemiddelde bruto marge winnaars > **0,8%**
- [ ] Geen posities >7 dagen vast zonder sell-order (orphan-fix)
- [ ] Portfolio-trend stabiliseert of herstelt t.o.v. ~$310

### Telegram PnL

- [ ] Winnaars: `Bruto winst` positief, `Rendement na Kraken-kosten` positief
- [ ] Koopfee niet structureel `$0.00` op **nieuwe** roundtrips

### Commando's

```bash
cd "Kraken bot 500 eu 15 mei"
pip install -e ".[dev]"
pytest -q
KRAKEN_DRY_RUN=true python -m kraken.live_trader
```

Vergelijk later met Alpaca (vanuit MCP-alpaca repo):

```bash
python -m metrics.kraken_compare.cli \
  --kraken-journal "/path/to/Kraken bot/data/kraken_trades.jsonl" \
  --alpaca-journal "/path/to/MCP-alpaca/data/alpaca_trades.jsonl"
```

---

## 7. Referentie Alpaca-fixes

Commit **`c273f0c`** in MCP-alpaca: `fix: improve Alpaca range bot capital deployment`

| Alpaca-implementatie | Overnemen op Kraken? |
|---|---|
| `is_tradable_position()` — notional ≥ $25 | **Ja** (fase B1) |
| `buy_slots` i.p.v. `len(symbols)` | **Ja** (fase B2) |
| `ALPACA_RANGE_MAX_DEPLOYED_PCT=0.60` | **Nee** — gebruik ~0.45 |
| `ALPACA_RANGE_SYMBOLS_ACTIVE=5` | **Nee** — blijf 3 |
| Sell-floor onder kostprijs | **Ja** (fase A1) — **prioriteit 1** |

Inspiratie-bestanden in MCP-alpaca:

- `alpaca_bot/live_trader.py` — `is_tradable_position`, buy_slots, deploy cap
- `tests/test_position_slots.py` — testpatronen
- `bot_live/config.py` — `ALPACA_MIN_POSITION_NOTIONAL_USD` afleiding

---

## 8. Agent-prompt (copy-paste)

Gebruik onderstaande prompt wanneer je een agent in de Kraken-repo start:

---

**Taak:** Implementeer in repo `Kraken bot 500 eu 15 mei` alle verbeteringen uit `docs/KRAKEN_BOT_IMPLEMENTATIEPLAN.md` (of dit document).

**Prioriteit:** A1 (sell-floor) → A2 (orphan exit) → B1/B2 (dust + buy-slots) → C (fee-model) → D (cap, POST_ONLY, logging).

**Constraints:**

- `SYMBOLS_ACTIVE` blijft **3**
- Geen Alpaca 5-slot / 60%-deploy overnemen; Kraken max deploy ~**45%**
- Alle wijzigingen met **pytest**-tests
- Eerst testen met `KRAKEN_DRY_RUN=true`

**Kernbestanden:** `src/rangebot/main.py`, `execution/position_manager.py`, `execution/risk_manager.py`, `strategy/signals.py`, `config/settings.py`, `tests/unit/*`.

**Acceptatie:**

1. Geen sell-orders meer onder gemiddelde instap + fees
2. Orphan-posities krijgen altijd exit-beheer
3. Buy-sizing deelt door **vrije koopslots**, niet totaal geselecteerde symbolen
4. Spread-gate gebruikt gemeten Kraken maker-fees (~0,30%/kant), geen spook-vaste fee
5. Run-audit bevat `buy_slots`, `deployed_pct`, `capital_per_usd`
6. `pytest -q` groen

**Context live incident (22 aug 2026):** UNI verkocht @ $4.07 vs instap $4.19 (−3,3%); DOGE fee-dood; portfolio ~$310. Oorzaak: `limit_sell = sell_level` zonder floor + kapitaal verdeeld over alle slots inclusief restposities.

---

_Einde document._
