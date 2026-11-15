#!/usr/bin/env python3
"""
audit_sources.py - 数据源巡检（API / 库内 / 重复 / UI 四向对照）

职责边界：
  只做体检与告警，不改配置、不写库、不做相关性判断。
  本工具不属于每日同步主流程，建议在源切换、历史回填验收、每周/每月定期体检时运行。
  发现 FAIL/WARN 后，由 Agent 按 references/sources_guide.md 排查并按需回滚源配置。

检查项：
  1. API 是否可用、返回条数、栏目名（classify.name）；
  2. API 最新日期 vs 库内最新日期（超过 --max-lag 天告警）；
  3. 库内是否存在重复 district + title + publish_date；
  4. UI 入口页最新条目是否被 API 覆盖（ui_only 不进库，只报告）。

用法：
  python3 scripts/audit_sources.py --city 深圳
  python3 scripts/audit_sources.py --city 深圳 --source sz_baoan_jsj --format json
  python3 scripts/audit_sources.py --city 深圳 --channel policies
  python3 scripts/audit_sources.py --city 深圳 --include-disabled   # 巡检旧源，确认已无新增
"""

import argparse
import datetime
import json
import signal
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import get_db_path  # noqa: E402
from fetch_list import collect, fetch_url, load_sources, parse_topic_html  # noqa: E402

UI_LIMIT = 20


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def db_latest(conn: sqlite3.Connection, city: str, district: str, channel: str) -> str:
    try:
        if channel == "policies":
            row = conn.execute("SELECT MAX(publish_date) AS d FROM policies WHERE city = ?",
                               (city,)).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(publish_date) AS d FROM notices WHERE city = ? AND district = ?",
                (city, district)).fetchone()
        return (row["d"] if row else "") or ""
    except sqlite3.Error:
        return ""


def db_duplicates(conn: sqlite3.Connection, city: str, district: str, channel: str) -> List[Dict[str, Any]]:
    try:
        if channel == "policies":
            rows = conn.execute(
                "SELECT title, publish_date, COUNT(*) AS c FROM policies WHERE city = ? "
                "GROUP BY title, publish_date HAVING c > 1", (city,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT title, publish_date, COUNT(*) AS c FROM notices "
                "WHERE city = ? AND district = ? GROUP BY title, publish_date HAVING c > 1",
                (city, district)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def date_lag(newer: str, older: str) -> int:
    try:
        a = datetime.date.fromisoformat(newer)
        b = datetime.date.fromisoformat(older)
        return (a - b).days
    except (TypeError, ValueError):
        return -1


def audit_one(src: Dict[str, Any], city: str, channel: str, pages: int,
              conn: sqlite3.Connection, max_lag: int) -> Dict[str, Any]:
    sid = src.get("source_id", "")
    district = src.get("district") or ""
    items, meta = collect(src, 1, pages, channel)
    dates = [it.get("date") or "" for it in items if it.get("date")]
    api_newest = max(dates) if dates else ""
    db_newest = db_latest(conn, city, district, channel)
    dups = db_duplicates(conn, city, district, channel)

    warnings: List[str] = []
    fails: List[str] = []

    if not items:
        fails.append("API 无返回（栏目改版/接口参数失效/反爬）")

    classify_name = meta.get("classify_name") or ""
    if items and not classify_name:
        warnings.append("API 未返回栏目名 classify.name")

    lag = date_lag(api_newest, db_newest) if (api_newest and db_newest) else -1
    if lag > max_lag:
        warnings.append(f"库内落后 API {lag} 天（{db_newest} < {api_newest}）")

    if dups:
        warnings.append(f"库内重复 title+date {len(dups)} 组")

    ui_only: List[Dict[str, str]] = []
    ui_note = ""
    entry_url = src.get("entry_url") or src.get("url") or ""
    if channel == "notices" and entry_url:
        ui_items = parse_topic_html(fetch_url(entry_url), entry_url)[:UI_LIMIT]
        if not ui_items:
            # gkmlpt 的 UI 入口是 JS 动态渲染，静态 HTML 里没有条目，属于预期
            ui_note = ("gkmlpt UI 为动态渲染，以 API 为准"
                       if src.get("type") == "gkmlpt" else "UI 列表解析为空（可能为改版）")
            if src.get("type") != "gkmlpt":
                warnings.append(ui_note)
        else:
            api_titles = {(it.get("title") or "").strip() for it in items}
            ui_only = [{"date": it["date"], "title": it["title"]}
                       for it in ui_items if (it.get("title") or "").strip() not in api_titles][:10]
            if ui_only:
                warnings.append(f"UI 最新 {len(ui_items)} 条中有 {len(ui_only)} 条 API 未覆盖")
    elif channel == "policies":
        ui_note = "政策源跳过 UI 对比"

    status = "FAIL" if fails else ("WARN" if warnings else "PASS")

    return {
        "status": status,
        "source_id": sid,
        "district": district,
        "role": src.get("role") or "",
        "enabled": bool(src.get("enabled", True)),
        "classify_name": classify_name,
        "count": len(items),
        "api_newest": api_newest,
        "db_latest": db_newest,
        "lag_days": lag,
        "duplicates": len(dups),
        "ui_only": ui_only,
        "ui_note": ui_note,
        "messages": fails + warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="数据源巡检：API / 库内 / 重复 / UI 四向对照")
    ap.add_argument("--city", default="深圳")
    ap.add_argument("--channel", default="notices", choices=["notices", "policies"])
    ap.add_argument("--source", action="append", default=None, help="只巡检指定 source_id，可重复")
    ap.add_argument("--pages", type=int, default=2, help="每源抓取 API 页数（默认 2）")
    ap.add_argument("--max-lag", type=int, default=7, help="库内最新日期允许落后 API 的天数（默认 7）")
    ap.add_argument("--include-disabled", action="store_true", help="连同已禁用源一起巡检")
    ap.add_argument("--format", default="table", choices=["table", "json"])
    args = ap.parse_args()

    sources = load_sources(args.city, args.channel)
    if args.source:
        wanted = set(args.source)
        sources = [s for s in sources if s.get("source_id") in wanted]
    elif not args.include_disabled:
        sources = [s for s in sources if s.get("enabled", True)]
    if not sources:
        print(json.dumps({"error": "no source matched", "city": args.city}, ensure_ascii=False),
              file=sys.stderr)
        return 2

    conn = open_db()
    try:
        rows = [audit_one(src, args.city, args.channel, args.pages, conn, args.max_lag)
                for src in sources]
    finally:
        conn.close()

    rows.sort(key=lambda r: ({"FAIL": 0, "WARN": 1, "PASS": 2}[r["status"]], r["source_id"]))
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("PASS", "WARN", "FAIL")}

    if args.format == "json":
        print(json.dumps({"city": args.city, "channel": args.channel,
                          "summary": counts, "sources": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"{'状态':<5}{'源':<22}{'区域':<10}{'条数':>4}  {'API最新':<11}{'库内最新':<11}"
              f"{'栏目':<10}备注")
        for r in rows:
            note = "；".join(r["messages"]) if r["messages"] else "-"
            print(f"{r['status']:<5}{r['source_id']:<22}{r['district']:<10}{r['count']:>4}  "
                  f"{r['api_newest'] or '-':<11}{r['db_latest'] or '-':<11}"
                  f"{r['classify_name'][:8]:<10}{note}")
        print(f"\n合计：PASS {counts['PASS']} / WARN {counts['WARN']} / FAIL {counts['FAIL']}")

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
