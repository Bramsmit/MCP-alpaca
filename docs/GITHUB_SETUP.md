# GitHub repo aanmaken en pushen

## 1. Repo op GitHub aanmaken

1. Ga naar [github.com/new](https://github.com/new)
2. **Repository name:** `MCP-alpaca`
3. **Public** of **Private** (private = minder gratis Actions-minuten)
4. **Niet** "Add a README" – de repo moet leeg zijn
5. Klik **Create repository**

## 2. Push (als je repo al hebt)

```bash
cd /Users/bramsmits/Documents/Cursor/Hobby/MCP-alpaca
git push -u origin main
```

Als je repo een andere naam heeft: pas de URL aan in `git remote -v`.

## 3. Eerste commit bevatte API keys

De allereerste commit bevatte `.cursor/mcp.json` met je Alpaca keys. Die staan nu in de git history.

**Advies:** Genereer nieuwe Alpaca API keys op [app.alpaca.markets](https://app.alpaca.markets) en gebruik die voor GitHub Actions.
