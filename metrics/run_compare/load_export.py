"""JSONL inlezen, venster filteren, samenvatting, export naar metrics/output."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_row_ts(row: dict[str, Any]) -> datetime | None:
    raw = row.get("timestamp_utc") or row.get("timestamp")
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    s = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def filter_by_window(
    rows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = parse_row_ts(row)
        if ts is None:
            continue
        if start <= ts <= end:
            out.append(row)
    _min = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda r: parse_row_ts(r) or _min)
    return out


def _statsrollup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    placed = updated = unchanged = skipped = fills = 0
    sym_counter: Counter[str] = Counter()
    for row in rows:
        st = row.get("stats") or {}
        placed += int(st.get("placed", 0) or 0)
        updated += int(st.get("updated", 0) or 0)
        unchanged += int(st.get("unchanged", 0) or 0)
        skipped += int(st.get("skipped", 0) or 0)
        fills += int(row.get("fills_new_this_run", 0) or 0)
        for s in row.get("symbols") or []:
            base = str(s).split("/")[0]
            sym_counter[base] += 1
    return {
        "runs": len(rows),
        "stats_totals": {
            "placed": placed,
            "updated": updated,
            "unchanged": unchanged,
            "skipped": skipped,
        },
        "fills_new_total": fills,
        "symbol_run_counts_top": sym_counter.most_common(15),
    }


def build_report(
    alpaca_rows: list[dict[str, Any]],
    bitvavo_rows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "window_utc": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "alpaca": {
            "runs_in_window": len(alpaca_rows),
            "summary": _statsrollup(alpaca_rows),
            "runs": alpaca_rows,
        },
        "bitvavo": {
            "runs_in_window": len(bitvavo_rows),
            "summary": _statsrollup(bitvavo_rows),
            "runs": bitvavo_rows,
        },
    }


def format_markdown(report: dict[str, Any]) -> str:
    w = report["window_utc"]
    lines = [
        "# Run-audit vergelijking (Alpaca range vs Bitvavo)",
        "",
        f"- **Venster (UTC):** {w['start']} → {w['end']}",
        f"- **Gegenereerd:** {report['generated_utc']}",
        "",
        "## Alpaca (`alpaca_runs.jsonl`)",
        "",
    ]
    a = report["alpaca"]["summary"]
    lines.extend(
        [
            f"- Runs: **{a['runs']}**",
            f"- Totaal stats: geplaatst {a['stats_totals']['placed']}, "
            f"bijgewerkt {a['stats_totals']['updated']}, "
            f"ongewijzigd {a['stats_totals']['unchanged']}, "
            f"overgeslagen {a['stats_totals']['skipped']}",
            f"- Nieuwe fills gesignaleerd over runs: "
            f"**{a['fills_new_total']}**",
            "",
        ]
    )
    if a["symbol_run_counts_top"]:
        lines.append("| Base | Aantal runs (symbool actief) |")
        lines.append("|------|------------------------------|")
        for base, c in a["symbol_run_counts_top"]:
            lines.append(f"| {base} | {c} |")
        lines.append("")

    lines.extend(["## Bitvavo (`bitvavo_runs.jsonl`)", ""])
    b = report["bitvavo"]["summary"]
    lines.extend(
        [
            f"- Runs: **{b['runs']}**",
            f"- Totaal stats: geplaatst {b['stats_totals']['placed']}, "
            f"bijgewerkt {b['stats_totals']['updated']}, "
            f"ongewijzigd {b['stats_totals']['unchanged']}, "
            f"overgeslagen {b['stats_totals']['skipped']}",
            f"- Nieuwe fills gesignaleerd over runs: "
            f"**{b['fills_new_total']}**",
            "",
        ]
    )
    if b["symbol_run_counts_top"]:
        lines.append("| Base | Aantal runs (symbool actief) |")
        lines.append("|------|------------------------------|")
        for base, c in b["symbol_run_counts_top"]:
            lines.append(f"| {base} | {c} |")
        lines.append("")

    lines.extend(
        [
            "## Bestanden",
            "",
            "- Ruwe data: `metrics/output/run_compare_timeline.json` "
            "(alle runs in venster).",
            "- Fills: `bitvavo_trades.jsonl` / `trades.jsonl` (repo-root), "
            "export via `python -m metrics.export_all_trades`.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    report: dict[str, Any],
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "run_compare_summary.md"
    json_path = out_dir / "run_compare_timeline.json"
    # Volledige runs in JSON voor vergelijking; truncatie kan later bij grote logs.
    slim = {k: v for k, v in report.items() if k not in ("alpaca", "bitvavo")}
    slim["alpaca"] = {
        "runs_in_window": report["alpaca"]["runs_in_window"],
        "summary": report["alpaca"]["summary"],
        "runs": report["alpaca"]["runs"],
    }
    slim["bitvavo"] = {
        "runs_in_window": report["bitvavo"]["runs_in_window"],
        "summary": report["bitvavo"]["summary"],
        "runs": report["bitvavo"]["runs"],
    }
    json_path.write_text(
        json.dumps(slim, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    md_path.write_text(format_markdown(report), encoding="utf-8")
    return md_path, json_path
