# Alpaca Crypto beperkingen

## 1 exit order per positie

**Alpaca crypto ondersteunt geen bracket orders.** Je kunt niet tegelijk een limit sell én een stop-loss op dezelfde positie hebben.

- De eerste sell order reserveert de positie
- Een tweede sell order voor dezelfde hoeveelheid faalt met: `"insufficient balance (requested: X, available: 0)"`

### Implementatie

- `config.py`: `ALPACA_CRYPTO_SINGLE_EXIT_ORDER = True` – nooit op False zetten
- `live_trader.py`: Plaats slechts 1 sell order per positie (limit sell = take-profit)
- Geen aparte stop-loss order – zou de 2e order zijn en falen

### Bij toekomstige wijzigingen

**Plaats NOOIT twee `submit_order` calls voor sell op dezelfde positie.** De tweede faalt altijd.
