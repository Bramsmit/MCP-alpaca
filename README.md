# Alpaca MCP in Cursor

Handel in aandelen, ETF's, crypto en opties via natuurlijke taal in Cursor, met de [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server).

## Snel starten

1. **Lees de handleiding:** [SETUP_GUIDE.md](./SETUP_GUIDE.md) – stap-voor-stap uitleg voor beginners
2. **API keys:** Maak een [gratis paper trading account](https://app.alpaca.markets/paper/dashboard/overview) en genereer keys
3. **Configuratie:** Vul je keys in bij `.cursor/mcp.json` (zie handleiding)
4. **Herstart Cursor** en vraag bijvoorbeeld: *"Wat is mijn Alpaca account saldo?"*

## Projectstructuur

| Map/ bestand | Beschrijving |
|--------------|--------------|
| `alpaca-server/` | Gekloonde [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server) broncode |
| `.cursor/mcp.json` | Cursor MCP-configuratie (voeg hier je API keys toe) |
| `SETUP_GUIDE.md` | Uitgebreide setup-handleiding |

## Voorbeelden

- "Toon mijn posities"
- "Koop 5 AAPL aan de markt"
- "Wat kost TSLA nu?"
- "Annuleer alle open orders"

## Links

- [Alpaca MCP Server op GitHub](https://github.com/alpacahq/alpaca-mcp-server)
- [Alpaca Paper Trading](https://app.alpaca.markets/paper/dashboard/overview)
- [Cursor MCP documentatie](https://docs.cursor.com/context/mcp)
