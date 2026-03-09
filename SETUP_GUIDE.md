# Alpaca MCP – Stap-voor-stap handleiding

Deze handleiding neemt je mee van nul naar een werkende Alpaca MCP-server in Cursor. Geen voorkennis van MCP nodig.

---

## Wat is dit?

**Alpaca** is een broker-API waarmee je kunt handelen in aandelen, ETF’s, crypto en opties.  
**MCP (Model Context Protocol)** is een standaard waarmee AI-assistenten (zoals Cursor) tools kunnen aanroepen.  
De **Alpaca MCP-server** verbindt Cursor met je Alpaca-account, zodat je in gewone taal kunt handelen.

---

## Stap 1: Vereisten installeren

### 1.1 Python (3.10+)

Controleer of Python geïnstalleerd is:

```bash
python3 --version
```

Als je Python 3.10 of hoger ziet, ben je klaar. Anders: [python.org/downloads](https://www.python.org/downloads/).

### 1.2 uv (Python package manager)

`uv` wordt gebruikt om de Alpaca MCP-server te draaien.

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Daarna je terminal herstarten, of:
```bash
source $HOME/.local/bin/env
```

**Windows:** zie [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)

Controleer:
```bash
uvx --version
```

---

## Stap 2: Alpaca API-keys ophalen

1. Ga naar [app.alpaca.markets](https://app.alpaca.markets/paper/dashboard/overview)
2. Maak een **paper trading** account (gratis, geen echt geld)
3. Ga naar **API Keys** en genereer een key-paar
4. Bewaar je **API Key** en **Secret Key** veilig

---

## Stap 3: MCP-server configureren

### Optie A: Via Cursor Directory (makkelijkst)

1. Ga naar [cursor.directory/mcp/alpaca](https://cursor.directory/mcp/alpaca)
2. Klik op **Add to Cursor**
3. Vul je API Key en Secret Key in
4. Herstart Cursor

### Optie B: Handmatig via `mcp.json`

1. Open `~/.cursor/mcp.json` (Mac/Linux) of `%USERPROFILE%\.cursor\mcp.json` (Windows)
2. Plak dit en vervang de placeholders door je echte keys:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "jouw_api_key_hier",
        "ALPACA_SECRET_KEY": "jouw_secret_key_hier"
      }
    }
  }
}
```

3. Sla op en herstart Cursor volledig (Cmd+Q, daarna opnieuw openen)

---

## Stap 4: Controleren of het werkt

1. Open Cursor en dit project
2. Ga naar **View → Output** (Cmd+Shift+U)
3. Kies in het dropdown-menu **MCP**
4. Als er geen fouten staan, is de server gestart

Test in de chat:
> "Wat is mijn Alpaca account saldo?"

Als Cursor de Alpaca-tools gebruikt en een antwoord geeft, werkt alles.

---

## Voorbeelden van wat je kunt vragen

| Vraag | Wat gebeurt er |
|-------|----------------|
| "Wat is mijn account saldo?" | Toont balance en buying power |
| "Toon mijn posities" | Lijst van je aandelen/crypto |
| "Koop 5 AAPL aan de markt" | Plaatst een market order |
| "Verkoop 10 TSLA met limit $300" | Plaatst een limit order |
| "Wat kost AAPL nu?" | Haalt de laatste koers op |
| "Annuleer alle open orders" | Annuleert alle pending orders |

---

## Paper vs live trading

- **Paper trading** (standaard): virtueel geld, veilig om te testen
- **Live trading**: echt geld, alleen gebruiken als je zeker weet wat je doet

Om naar live te gaan, zet `ALPACA_PAPER_TRADE` op `false` in je `env`-config en gebruik live API-keys.

---

## Problemen oplossen

| Probleem | Oplossing |
|----------|-----------|
| `uvx` niet gevonden | Herstart je terminal na installatie van uv. Voeg `~/.local/bin` toe aan je PATH (bijv. in `~/.zshrc`): `export PATH="$HOME/.local/bin:$PATH"`. **Tip:** Start Cursor vanuit de terminal (`cursor .`) zodat het je PATH overneemt. |
| MCP-server start niet | Bekijk **View → Output → MCP** voor foutmeldingen |
| "Credentials missing" | Controleer of je API keys correct in `mcp.json` staan |
| Geen tools zichtbaar | Herstart Cursor volledig na wijzigingen in `mcp.json` |

---

## Projectstructuur

```
MCP-alpaca/
├── alpaca-server/     ← Broncode van de Alpaca MCP-server (van GitHub)
├── .cursor/mcp.json   ← Cursor MCP-configuratie
├── SETUP_GUIDE.md     ← Deze handleiding
└── README.md
```

De `alpaca-server/` map bevat de gekloonde repo. Je kunt `install.py` daar gebruiken voor een lokale installatie, maar `uvx` (zoals hierboven) is meestal het makkelijkst.
