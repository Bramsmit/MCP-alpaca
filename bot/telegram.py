"""
Telegram notificaties voor trades.
Stuur berichten via de Telegram Bot API.
"""

import os

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
        print("⚠️ Vul TELEGRAM_CHAT_ID in .env in (zie bot/README.md)")
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


def notify_trade(side: str, symbol: str, qty: float, price: float, order_id: str = "") -> bool:
    """Stuur een trade-notificatie naar Telegram."""
    emoji = "🟢" if side.lower() == "buy" else "🔴"
    msg = f"{emoji} {side.upper()}: {qty} {symbol} @ ${price:.4f}"
    if order_id:
        msg += f"\nOrder ID: {order_id}"
    return send_telegram(msg)


def notify_stop_loss(symbol: str, qty: float, price: float) -> bool:
    """Stuur een stop-loss notificatie."""
    msg = f"🛑 STOP-LOSS: {qty} {symbol} verkocht @ ${price:.4f}"
    return send_telegram(msg)
