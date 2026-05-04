"""
Telegram notificaties voor trades.
Stuur berichten via de Telegram Bot API.
"""

import os

from bot_live.config import (
    BITVAVO_FEE_BUY_RATE,
    BITVAVO_FEE_SELL_LIMIT_RATE,
    JOURNAL_FIXED_FEE_PER_FILL_USD,
    TELEGRAM_NOTIFY_BUY_FILLS,
)

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


def _currency_prefix(currency_label: str) -> str:
    return "€" if currency_label.upper() == "EUR" else "$"


def notify_trade_filled(
    side: str,
    symbol: str,
    qty: float,
    price: float,
    profit: float | None,
    portfolio_value: float,
    entry_price: float | None = None,
    *,
    fee_buy_rate: float | None = None,
    fee_sell_rate: float | None = None,
    fixed_fee_per_fill: float | None = None,
    currency_label: str = "USD",
    fee_eur: float | None = None,
    fee_estimated: bool = False,
    send_telegram_message: bool | None = None,
) -> bool:
    """Stuur een notificatie bij een gevulde trade.

    send_telegram_message: None = standaard (koop alleen als TELEGRAM_NOTIFY_BUY_FILLS).
    """
    r_buy = BITVAVO_FEE_BUY_RATE if fee_buy_rate is None else fee_buy_rate
    r_sell = BITVAVO_FEE_SELL_LIMIT_RATE if fee_sell_rate is None else fee_sell_rate
    fixed = (
        JOURNAL_FIXED_FEE_PER_FILL_USD
        if fixed_fee_per_fill is None
        else fixed_fee_per_fill
    )
    cur = _currency_prefix(currency_label)
    side_l = side.lower()
    if send_telegram_message is None:
        send_tg = TELEGRAM_NOTIFY_BUY_FILLS or side_l != "buy"
    else:
        send_tg = send_telegram_message
    if not send_tg:
        return True

    # Afgeronde ronde-trip: één duidelijk verkoopbericht
    if (
        side_l == "sell"
        and qty > 0
        and entry_price
        and entry_price > 0
    ):
        gross = (price - entry_price) * qty
        fee_buy = entry_price * qty * r_buy + fixed
        fee_sell = price * qty * r_sell + fixed
        fees_total = fee_buy + fee_sell
        net = gross - fee_buy - fee_sell
        cost_basis = entry_price * qty * (1 + r_buy) + fixed
        pct = (net / cost_basis * 100) if cost_basis else 0.0
        notional = qty * price
        msg = (
            f"✅ Afgeronde trade: {symbol}\n"
            f"Verkoop: {qty:.6f} @ {cur}{price:.4f} "
            f"(nominaal ≈ {cur}{notional:.2f})"
        )
        msg += f"\nReferentie inkoop (avg): {cur}{entry_price:.4f}"
        msg += f"\n📈 Bruto winst: {cur}{gross:.2f}"
        msg += f"\n📉 Transactiekosten (kopen): {cur}{fee_buy:.2f}"
        msg += f"\n📉 Transactiekosten (verkoop): {cur}{fee_sell:.2f}"
        msg += f"\n💸 Totaal fictieve kosten (model): {cur}{fees_total:.2f}"
        msg += f"\n📊 Rendement na kosten: {cur}{net:.2f} ({pct:+.1f}% t.o.v. kostbasis)"
    else:
        emoji = "🟢" if side_l == "buy" else "🔴"
        msg = f"{emoji} Trade: {side.upper()} {qty} {symbol} @ {cur}{price:.4f}"
        if side_l == "buy" and qty > 0 and price > 0:
            fee_pct_leg = price * qty * r_buy
            fee_buy_total = fee_pct_leg + fixed
            msg += f"\n📉 Transactiekosten (kopen): {cur}{fee_buy_total:.2f}"
            detail = f"maker {r_buy * 100:.2f}%: {cur}{fee_pct_leg:.2f}"
            if fixed > 0:
                detail += f", vast: {cur}{fixed:.2f}"
            msg += f"\n   ({detail})"
        elif side_l == "sell" and profit is not None:
            msg += f"\n✅ Netto (alleen bekend): {cur}{profit:.2f}"

    if fee_eur is not None:
        tag = " (≈ geschat)" if fee_estimated else ""
        msg += f"\n💡 Deze fill volgens exchange: {cur}{fee_eur:.2f}{tag}"

    msg += f"\n📊 Totaal portfolio: {cur}{portfolio_value:.2f}"
    return send_telegram(msg)


def notify_stop_loss(symbol: str, qty: float, price: float) -> bool:
    """Stuur een stop-loss notificatie."""
    q = _quote_for_symbol(symbol)
    msg = f"🛑 STOP-LOSS: {qty} {symbol} verkocht @ {q}{price:.4f}"
    return send_telegram(msg)
