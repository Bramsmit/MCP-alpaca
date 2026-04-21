"""
Telegram notificaties voor trades.
Stuur berichten via de Telegram Bot API.
"""

import os

from bot_live.config import BITVAVO_FEE_BUY_RATE

try:
    import requests
except ImportError:
    requests = None


def send_telegram(message: str) -> bool:
    """
    Stuur een bericht naar Telegram.
    Vereist: TELEGRAM_BOT_TOKEN en TELEGRAM_CHAT_ID in .env
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("⚠️ TELEGRAM_BOT_TOKEN of TELEGRAM_CHAT_ID niet gezet in .env")
        return False

    if chat_id == "VUL_HIER_JE_CHAT_ID_IN":
        print("⚠️ Vul TELEGRAM_CHAT_ID in .env in (zie bot_range_1000/README.md)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        if requests:
            r = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
            return r.status_code == 200
        import urllib.request
        import urllib.parse
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"❌ Telegram fout: {e}")
        return False


def _quote_for_symbol(symbol: str) -> str:
    """EUR-paren als €, USD (Alpaca) als $."""
    s = symbol.upper()
    if "/EUR" in s or s.endswith("EUR"):
        return "€"
    return "$"


def notify_trade(side: str, symbol: str, qty: float, price: float, order_id: str = "") -> bool:
    """Stuur een trade-notificatie naar Telegram."""
    q = _quote_for_symbol(symbol)
    emoji = "🟢" if side.lower() == "buy" else "🔴"
    msg = f"{emoji} {side.upper()}: {qty} {symbol} @ {q}{price:.4f}"
    if order_id:
        msg += f"\nOrder ID: {order_id}"
    return send_telegram(msg)


def notify_trade_filled(
    side: str,
    symbol: str,
    qty: float,
    price: float,
    profit: float | None,
    portfolio_value: float,
    entry_price: float | None = None,
) -> bool:
    """Stuur een notificatie bij een gevulde trade."""
    q = _quote_for_symbol(symbol)
    emoji = "🟢" if side.lower() == "buy" else "🔴"
    msg = f"{emoji} Trade: {side.upper()} {qty} {symbol} @ {q}{price:.4f}"
    if profit is not None and side.lower() == "sell":
        if entry_price and qty > 0:
            cost_basis = entry_price * qty * (1 + BITVAVO_FEE_BUY_RATE)
            pct = (profit / cost_basis * 100) if cost_basis else 0
        else:
            entry_val = price * qty - profit
            pct = (profit / entry_val * 100) if entry_val else 0
        msg += f"\n💰 Netto (Bitvavo fees): {q}{profit:.2f} ({pct:+.1f}%)"
    msg += f"\n📊 Totaal portfolio: {q}{portfolio_value:.2f}"
    return send_telegram(msg)


def notify_stop_loss(symbol: str, qty: float, price: float) -> bool:
    """Stuur een stop-loss notificatie."""
    q = _quote_for_symbol(symbol)
    msg = f"🛑 STOP-LOSS: {qty} {symbol} verkocht @ {q}{price:.4f}"
    return send_telegram(msg)
