# Plan: Alpaca-bot vs Bitvavo-bot eerlijk vergelijken

Dit document is een **uitgewerkt stappenplan** om resultaten naast elkaar te leggen. Voer de **zelfde** stappen voor **beide** bots uit (zelfde kalenderperiode, vergelijkbaar export-formaat).

Het beschrijft alleen de vergelijkingsmethode — **geen** wijzigingen aan bot-code of workflows zijn nodig om dit plan te volgen.

---

## 1. Doel en scope vastleggen

### 1.1 Vergelijkingsperiode

- Kies een **vaste start- en einddatum in UTC**, bijvoorbeeld `2026-03-01T00:00:00Z` t/m `2026-03-31T23:59:59Z`.
- Noteer deze **bovenaan** je worksheet of rapport — alle downstream-filtering gebruikt exact deze grenzen.

### 1.2 Wat je wel en niet combineert

| Wel vergelijkbaar (mits definities kloppen) | Pas op |
|--------------------------------------------|--------|
| Return **relatief** aan ingezet kapitaal (of aan nominale positiegrootte per ronde) | Absolute euro’s tussen USD- en EUR-setup alleen als je FX en timing expliciet meeneemt |
| Win rate op **afgeronde** rondes (zie §2) | “Totaal PnL €” tussen verschillende quoting currencies zonder omrekening |
| Gemiddelde PnL % per afgeronde ronde | Orders alleen uit repo-journal vs exchange-export zonder bron-afstemming |

### 1.3 Paper vs live

- **Alpaca:** in deze repo is de range-bot doorgaans **paper trading** (`ALPACA_PAPER_TRADE`); fills zijn gesimuleerd — niet 1-op-1 gelijk aan live liquiditeit en uitvoering.
- **Bitvavo:** via `bot_live/bitvavo_trader.py` is het **live** (tenzij `BITVAVO_DRY_RUN=true`).
- Vermeld dit **expliciet** in je conclusie: verschillen zijn verwacht en leggen veel uit, geen “fout” in één bot.

---

## 2. Definities afspreken (één keer, vasthouden)

| Onderwerp | Afspraak (aanbevolen) |
|-----------|----------------------|
| **Afgeronde trade / ronde** | Eén **buy gevuld** op symbool X gevolgd door een **sell gevuld** op hetzelfde symbool (of omgekeerde volgorde voor short-strategieën — hier niet van toepassing). Partial fills tellen als één leg tot het symbool gesloten is. |
| **Winst (PnL)** | Bruto `(exit − entry) × qty` minus fees volgens **één vaste methode** (bijv. exchange-fees uit export, of dezelfde fee-assumpties als in je journaal-code — maar niet methode A bij Alpaca en B bij Bitvavo). |
| **Symbool / markt** | Vergelijk **per basis-asset** (BTC, ETH, …). **USD-quote (Alpaca)** vs **EUR-quote (Bitvavo)** zijn **verschillende markten** — niet mengen in één “totaal BTC” zonder FX en tijdstempels. |

### 2.1 Match met deze repo

- **Alpaca range:** symbolen zoals `BTC/USD`, `ETH/USD` (zie [`bot_live/config.py`](../bot_live/config.py) — `SYMBOL_POOL`).
- **Bitvavo:** symbolen zoals `BTC/EUR`, `ETH/EUR` (zie [`bot_live/bitvavo_config.py`](../bot_live/bitvavo_config.py) — `SYMBOL_POOL`).
- Vergelijking “apples-to-apples”: **per coin** naast elkaar (BTC-USD-run vs BTC-EUR-run), niet één geaggregeerde bucket zonder label.

---

## 3. Data verzamelen — Alpaca

### 3.1 Primaire bron (aanbevolen)

Export van **Alpaca** voor alle **gevulde (closed/filled) orders** in de gekozen periode:

- Via **Alpaca Dashboard** (Paper of Live — het account dat je gebruikt) → Orders / Activity met datumbereik en CSV/export waar beschikbaar.
- Of via **Trading API**: orders filteren op status filled en tijdvenster (documenteer endpoint en filterlogica).

**Waarom niet alleen het journal?** Het journal in de repo (`trades.jsonl`, zie §3.2) wordt gevuld vanuit [`bot_live/alpaca_runtime.py`](../bot_live/alpaca_runtime.py): recent gesloten orders met een **beperkt tijdsvenster**. Als de bot lang niet draait of fills buiten het venster vallen, kan het journal **onvolledig** zijn ten opzichte van Alpaca als bron van waarheid.

### 3.2 Secundair / reconciliatie — deze repo

| Bestand | Rol |
|---------|-----|
| **`trades.jsonl`** (projectroot) | Append-door [`bot_live/journal.py`](../bot_live/journal.py): wat de runtime heeft gelogd na een nieuwe fill. JSON-lines met o.a. `timestamp`, `symbol`, `side`, `qty`, `price`, `entry_price`, `profit`. |
| **`.alpaca_trade_state.json`** (projectroot) | State voor entries / notified order-ids — handig voor context, niet primair voor alle fills. |

Gebruik `trades.jsonl` om te **cross-checken**: komt het ongeveer overeen met de Alpaca-export (aantal sells/buys per symbool in de periode)? Grote mismatch → eerst Alpaca-export als leidend beschouwen.

### 3.3 Optioneel — handoff-pakket (documentatie)

Vanaf **repository root**:

```bash
python -m bot_range_1000.export_handoff --output-dir exports
```

(Zie [`bot_range_1000/export_handoff.py`](../bot_range_1000/export_handoff.py): config-snapshot + trades uit journal waar aanwezig.)

Handig als **verslag bijlage**, niet als vervanging van een volledige Alpaca-export.

### 3.4 Velden om te exporteren (minimaal)

- **tijd** — UTC ISO8601  
- **symbool** — zoals `BTC/USD`  
- **side** — buy / sell  
- **hoeveelheid** — gevulde qty  
- **gemiddelde vulpijs** — waar beschikbaar  
- **order-id** — voor dedupe en matching met journal  

---

## 4. Data verzamelen — Bitvavo

### 4.1 Primaire bron

- Bitvavo **order- en tradehistorie** (app of API) over **exact hetzelfde UTC-interval** als bij Alpaca.

### 4.2 Secundair — deze repo

De Bitvavo-bot roept dezelfde `log_trade()` aan als de Alpaca-runtime; [`bot_live/journal.py`](../bot_live/journal.py) schrijft standaard naar **`trades.jsonl`** in de **projectroot**.  
De workflow [`.github/workflows/trade_bitvavo.yml`](../.github/workflows/trade_bitvavo.yml) cached ook **`bitvavo_trades.jsonl`** — als jouw runs alleen `trades.jsonl` vullen, gebruik dat bestand voor reconciliatie met Bitvavo-export.

Net als bij Alpaca: **journal = wat tijdens runs is gelogd**; voor volledige historie over **niet-draaiende perioden** heen: **Bitvavo als bron**.

### 4.3 Velden

Zelfde minimum als §3.4 (UTC, symbool met EUR-quote, side, qty, prijs, fees als Bitvavo ze teruggeeft).

---

## 5. Normaliseren en naast elkaar zetten

### 5.1 Eén formaat

- Twee tabbladen in één spreadsheet **of** twee CSV’s met **identieke kolomkoppen**.
- Alle tijdstippen **UTC** — geen mix met lokale tijd.

### 5.2 Pair-normalisatie

- Kolom **`base_asset`** (BTC, ETH, …) afgeleid uit het symbool.
- Kolom **`quote`** (`USD` vs `EUR`) expliciet — niet mergeren voor globale totalen zonder FX-strategie.

### 5.3 Kernberekeningen

Per symbool en **totaal over de periode** (los van quote waar nodig):

| Metriek | Notitie |
|---------|---------|
| Aantal afgeronde rondes | Na jouw definitie uit §2 |
| Win rate | Winnaars / rondes (als elke ronde één netto resultaat heeft) |
| Som / gemiddelde PnL | In **quote-valuta** per kolom (EUR-kolom niet bij USD optellen) |
| Return op gemiddeld ingezet kapitaal | Alleen als je ingezet kapitaal per periode redelijk kunt schatten (snapshot of gemiddelde exposure) |

### 5.4 Fees en spread

- Als de ene export **bruto** en de andere **netto** is, markeer dat of rek alles naar dezelfde kant bij (bij voorkeur **netto** na fees).

---

## 6. Caveats — afvinklijst

Gebruik dit als kwaliteitscheck vóór je conclusie:

- [ ] Zelfde kalenderperiode (**UTC**) voor beide bots.  
- [ ] Paper (Alpaca) vs live (Bitvavo) benoemd in het verslag.  
- [ ] USD- vs EUR-paren niet blind als “dezelfde trade” geteld.  
- [ ] Fees/spread expliciet meegenomen, of bewust weggelaten met reden.  
- [ ] Journal (`trades.jsonl` / eventueel `bitvavo_trades.jsonl`) alleen als **aanvulling** of reconciliatie, niet als enige bron voor volledige historie als de bot sporadisch draaide.  
- [ ] **Fill-venster:** Alpaca-side journal hangt aan polling-recent-closed orders; Bitvavo-side gebruikt `fetch_my_trades` met een **4-uur-venster** in [`bot_live/bitvavo_trader.py`](../bot_live/bitvavo_trader.py) — langere gaps → exchange-export essentieel.  
- [ ] **FX:** vergelijk je “totaal vermogen” over beide accounts in één munt, noteer koers en moment.

---

## 7. Wat je aan het eind vastlegt (conclusiepagina)

Eén korte pagina (half A4 volstaat):

1. **Periode** (UTC) en **bron per bot** (Alpaca dashboard/API export; Bitvavo export; eventueel journal-pad uit deze repo).  
2. **Kerngetallen** in één tabel (bijv. rondes, win rate, som PnL in eigen quote, eventueel return %).  
3. **2–3 zinnen** oordeel: wat verklaart het verschil waarschijnlijk (paper vs live, fees, andere universes/timing, EUR vs USD)?

Daarmee kun je **later dezelfde methode herhalen** zonder opnieuw te improviseren.

---

## 8. Tooling in deze repo — Bitvavo (operationeel)

Er staat een kleine CLI onder [`metrics/bitvavo_compare/`](../metrics/bitvavo_compare/README.md) voor **Bitvavo** (`*/EUR` in het journal), **zonder de bots aan te passen**:

| Stap | Command | Doel |
|------|---------|------|
| Journal → CSV | `python -m metrics.bitvavo_compare journal-export --start … --end … --output-dir metrics/output` | Leest `trades.jsonl` (en optioneel `bitvavo_trades.jsonl`), behoudt alleen EUR-rijen, schrijft o.a. `metrics/output/bitvavo_journal.csv`. |
| Metrics | `python -m metrics.bitvavo_compare metrics …` | Buys/sells en PnL-schatting op sells (journalvelden). |

Rijen met **niet-EUR** symbolen (bv. Alpaca `*/USD` in hetzelfde `trades.jsonl`) worden overgeslagen; het aantal staat op stderr.

Een volledige **Bitvavo exchange-export** voor dezelfde periode haal je nog uit de app/API; gebruik die naast deze CSV voor reconciliatie.

Uitvoer onder `metrics/output/` wordt standaard **niet gecommit** (`.gitignore`), behalve `metrics/output/.gitkeep`.

---

## Verwante documentatie in deze repo

- [`docs/VERIFICATION_ALPACA_VS_BITVAVO.md`](VERIFICATION_ALPACA_VS_BITVAVO.md) — wat er **feitelijk** in de codebase zit versus algemene Alpaca/Bitvavo-verhalen.  
- [`docs/CODEBASE_CONTEXT_FOR_V2.md`](CODEBASE_CONTEXT_FOR_V2.md) — journal vs logging vs state (Alpaca-kant).  
- [`metrics/bitvavo_compare/README.md`](../metrics/bitvavo_compare/README.md) — uitvoerbare voorbeelden voor §8 (Bitvavo).

---

*Vergelijkingsmethode + optionele tooling; geen wijziging aan bot-runtime-config tenzij je dat zelf doet.*
