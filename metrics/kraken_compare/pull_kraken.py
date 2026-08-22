"""
Pull Kraken trade history into metrics/output/kraken_fills_api.jsonl.

Uses the sibling Kraken-bot checkout + its .env (keys never printed).

  python -m metrics.kraken_compare.pull_kraken \\
    --kraken-repo "../Kraken bot 500 eu 15 mei" \\
    --since 2026-05-01
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    p = argparse.ArgumentParser(description="Pull Kraken fills via sibling bot .env")
    p.add_argument(
        "--kraken-repo",
        default=str(root.parent / "Kraken bot 500 eu 15 mei"),
        help="Pad naar Kraken-bot repo",
    )
    p.add_argument("--since", default="2026-05-01")
    p.add_argument(
        "--output",
        default=str(root / "metrics" / "output" / "kraken_fills_api.jsonl"),
    )
    args = p.parse_args(argv)

    kraken_repo = Path(args.kraken_repo).expanduser().resolve()
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not (kraken_repo / ".env").exists():
        print(f"Geen .env in {kraken_repo}", file=sys.stderr)
        return 1

    py = kraken_repo / ".venv-ci" / "bin" / "python"
    if not py.exists():
        py = Path(sys.executable)

    script = r'''
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

env_path = Path(".env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    k, v = k.strip(), v.strip().strip('"').strip("'")
    if k and k not in os.environ:
        os.environ[k] = v

from rangebot.config.settings import SYMBOL_POOL
from rangebot.exchange.kraken.client import make_exchange
from rangebot.exchange.kraken.common import norm_symbol, trade_fee_usd_from_ccxt

OUT = Path(os.environ["COMPARE_OUT"])
SINCE = datetime.fromisoformat(os.environ["COMPARE_SINCE"] + "T00:00:00+00:00")
since_ms = int(SINCE.timestamp() * 1000)

client = make_exchange(dry_run=True)
pool = client.filter_tradable_symbol_pool(list(SYMBOL_POOL))
print(f"pool={len(pool)} since={SINCE.date()}", flush=True)

all_trades = {}
for sym in pool:
    cursor = since_ms
    fetched = 0
    while True:
        batch = client.fetch_my_trades(sym, since_ms=cursor, limit=50) or []
        if not batch:
            break
        fetched += len(batch)
        max_ts = cursor
        for tr in batch:
            tid = str(tr.get("id") or "").strip()
            if not tid:
                ts = tr.get("timestamp") or 0
                tid = f"noid:{sym}:{ts}:{tr.get('side')}:{tr.get('amount')}:{tr.get('price')}"
            all_trades[tid] = tr
            ts = tr.get("timestamp") or 0
            if ts > max_ts:
                max_ts = ts
        if len(batch) < 50 or max_ts <= cursor:
            break
        cursor = max_ts + 1
        time.sleep(0.35)
    print(f"  {sym}: {fetched}", flush=True)
    time.sleep(0.25)

rows = []
for tid, tr in sorted(all_trades.items(), key=lambda kv: kv[1].get("timestamp") or 0):
    sym = norm_symbol(tr.get("symbol") or "")
    qty = float(tr.get("amount") or 0)
    price = float(tr.get("price") or 0)
    side = str(tr.get("side") or "").lower()
    ts_ms = tr.get("timestamp")
    if qty <= 0 or price <= 0 or side not in ("buy", "sell"):
        continue
    fee = trade_fee_usd_from_ccxt(tr, symbol=sym, price=price)
    ts_iso = (
        datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
        if ts_ms else None
    )
    rows.append({
        "trade_id": tid,
        "timestamp": ts_iso,
        "symbol": sym,
        "side": side,
        "qty": qty,
        "price": price,
        "fee_usd": fee,
        "notional_usd": round(qty * price, 8),
        "source": "kraken_api_pull",
    })

OUT.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
print(f"Wrote {len(rows)} → {OUT}", flush=True)
'''
    env = os.environ.copy()
    env["COMPARE_OUT"] = str(out)
    env["COMPARE_SINCE"] = args.since
    proc = subprocess.run(
        [str(py), "-c", script],
        cwd=str(kraken_repo),
        env=env,
        check=False,
    )
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
