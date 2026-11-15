#!/usr/bin/env python3
"""
fetch_list.py - 政务公告列表抓取器（原子工具）

职责边界：
  只负责「把列表页的条目原样抓下来」，输出结构化 JSON。
  不做相关性判断、不做分类、不判批次、不写数据库。
  哪些条目值得抓正文、如何解析、如何入库，全部由 Agent 按 references/sync_playbook.md 决策。

用法：
  python3 scripts/fetch_list.py --city 深圳
  python3 scripts/fetch_list.py --city 深圳 --pages 1-3 --since 2026-11-01
  python3 scripts/fetch_list.py --city 深圳 --source sz_futian --source sz_guangming
  python3 scripts/fetch_list.py --city 深圳 --pages 1 --summary
  python3 scripts/fetch_list.py --city 深圳 --pages 1 --out /tmp/todo.json
  python3 scripts/fetch_list.py --city 深圳 --channel policies --summary
  python3 scripts/fetch_list.py --city 深圳 --source sz_longgang   # 显式指定时含已禁用旧源
"""

import argparse
import datetime
import json
import re
import signal
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "config" / "sources.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def fetch_url(url: str, timeout: int = 12) -> str:
    cmd = ["curl", "-k", "-s", "-L", "-A", UA,
           "--connect-timeout", str(timeout), "--max-time", str(timeout * 2), url]
    try:
        res = subprocess.run(cmd, capture_output=True, check=True)
        return res.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def normalize_date(raw: str) -> str:
    """把 26-11-09 / 2026-11-09 / 20261109 统一成 YYYY-MM-DD，无法识别则原样返回。"""
    raw = (raw or "").strip()
    m = re.match(r"^(\d{2})-(\d{2})-(\d{2})$", raw)
    if m:
        return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})[-/.]?(\d{2})[-/.]?(\d{2})$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw


def clean_url(url: str) -> str:
    """清理 URL 路径中多余的重复斜杠（保留协议头）。"""
    url = (url or "").strip()
    if not url:
        return ""
    parts = list(urllib.parse.urlsplit(url))
    parts[2] = re.sub(r"/+", "/", parts[2])
    return urllib.parse.urlunsplit(parts)


def absolute(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith("javascript:") or href.startswith("#"):
        return ""
    return clean_url(urllib.parse.urljoin(base, href))


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_nav_href(href: str) -> bool:
    """是否是栏目导航链接（下划线指到目录 / index 页），而非具体条目正文页。"""
    href = (href or "").strip()
    if not href:
        return True
    path = urllib.parse.urlsplit(href).path.rstrip("/")
    base = path.rsplit("/", 1)[-1].lower()
    return base in ("", "index.html", "index.htm", "index.shtml")


def _title_of(a) -> str:
    return (a.get("title") or a.get_text(" ", strip=True) or "").strip()


def parse_topic_html(html: str, base_url: str) -> List[Dict[str, Any]]:
    """解析专题列表页（兼容 <li><a><span> / 日期与链接同级 / <a> 内含日期 span 三类结构）。"""
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    def push(date: str, title: str, href: str) -> None:
        if not title or not DATE_RE.match(date):
            return
        full_url = absolute(base_url, href)
        if not full_url or is_nav_href(href):
            return
        items.append({"date": date, "title": title, "url": full_url})

    # 1. 常见 <li><a><span>（排除栏目导航，避免把侧栏归档日期当条目）
    for li in soup.find_all("li"):
        a, span = li.find("a"), li.find("span")
        if not a or not span:
            continue
        push(normalize_date(span.get_text(strip=True)), _title_of(a), a.get("href", ""))
    if items:
        return items

    # 1.5 日期与链接同级，如 <div class="ListconC"><span>2026-10-30</span><a title=...>
    for span in soup.find_all("span"):
        if not DATE_RE.match(normalize_date(span.get_text(strip=True))):
            continue
        parent = span.parent
        if parent is None:
            continue
        a = parent.find("a", href=True)
        if a is None:
            continue
        push(normalize_date(span.get_text(strip=True)), _title_of(a), a.get("href", ""))
    if items:
        return items

    # 2. 尝试无 li 包裹的 <a class="news-item"> 或包含日期 span 的 <a> 链接（如深汕）
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue
        time_span = a.find(lambda t: t.name == "span" and any(c in t.get("class", []) for c in ["time", "date"]))
        if not time_span:
            for s in a.find_all("span"):
                if re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", s.get_text(strip=True)):
                    time_span = s
                    break
        if not time_span:
            continue
        date = normalize_date(time_span.get_text(strip=True))
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue

        text_span = a.find(lambda t: t.name == "span" and any(c in t.get("class", []) for c in ["text", "title"]))
        if text_span:
            title = text_span.get_text(strip=True)
        else:
            title = a.get("title") or ""
            if not title:
                title = a.get_text(" ", strip=True).replace(time_span.get_text(strip=True), "").strip()
        if not title:
            continue
        push(date, title, href)

    return items


CST = datetime.timezone(datetime.timedelta(hours=8))


def epoch_to_date(raw: Any) -> str:
    """把 gkmlpt 的 epoch 时间戳（秒/毫秒）转成北京时间的 YYYY-MM-DD。"""
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if ts > 10 ** 11:  # 毫秒时间戳
        ts //= 1000
    try:
        return datetime.datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def gkmlpt_date(art: Dict[str, Any]) -> str:
    """官方发布日期优先级：date → display_publish_time → first_publish_time → created_at。

    created_at 是入库时间，不能直接当官方发布日期（大鹏 078：created_at=2026-10-28，
    官方 date=2026-10-30）。
    """
    for field in ("date", "display_publish_time", "first_publish_time"):
        d = epoch_to_date(art.get(field))
        if d:
            return d
    return normalize_date((art.get("created_at") or "")[:10])


def parse_gkmlpt(api_text: str) -> Tuple[List[Dict[str, Any]], str]:
    """解析广东省 gkmlpt 信息公开目录 JSON 接口，返回 (条目列表, 栏目名称)。"""
    try:
        data = json.loads(api_text)
    except Exception:
        return [], ""
    classify = ((data.get("classify") or {}).get("name") or "").strip()
    items = []
    for art in data.get("articles", []):
        title = (art.get("title") or "").strip()
        url = clean_url(art.get("url") or "")
        if not title or not url:
            continue
        items.append({
            "date": gkmlpt_date(art),
            "title": title,
            "url": url,
            "summary": art.get("abstract") or "",
            "attachments": art.get("attachment") or [],
            "document_number": art.get("document_number") or "",
            "classify": (art.get("classify_main_name") or classify or "").strip(),
        })
    return items, classify


def load_sources(city: str, channel: str) -> List[Dict[str, Any]]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = "sources" if channel == "notices" else "policy_sources"
    for c in cfg.get("cities", []):
        if str(c.get("city_name", "")).replace("市", "") == city.replace("市", "") \
                or c.get("city_id") == city:
            return c.get(key, [])
    return []


def collect(src: Dict[str, Any], start_page: int, end_page: int,
            channel: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """抓取单个源，返回 (条目, 源元信息)。元信息含 gkmlpt 栏目名，供 --summary / audit 使用。"""
    sid = src.get("source_id", "")
    district = src.get("district") or ""
    level = src.get("level") or ""
    entry_url = src.get("entry_url") or src.get("url") or ""
    out: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"source_id": sid, "district": district, "level": level,
                            "role": src.get("role") or "", "classify_name": "",
                            "entry_url": entry_url}

    for page in range(start_page, end_page + 1):
        if src.get("type") == "gkmlpt" and src.get("api"):
            text = fetch_url(src["api"].format(page=page))
            batch, classify = parse_gkmlpt(text)
            if classify and not meta["classify_name"]:
                meta["classify_name"] = classify
        elif src.get("type") == "topic_html" and entry_url:
            url = entry_url if page == 1 else (src.get("page_pattern") or "").format(page=page)
            if not url:
                break
            html = fetch_url(url)
            batch = parse_topic_html(html, url)
        else:
            break

        if not batch:
            break
        for it in batch:
            it.update({"source_id": sid, "district": district, "level": level, "channel": channel})
            out.append(it)

    return out, meta


def main() -> int:
    ap = argparse.ArgumentParser(description="政务公告列表抓取器（宽松抓取，不做相关性判断）")
    ap.add_argument("--city", default="深圳")
    ap.add_argument("--channel", default="notices", choices=["notices", "policies"])
    ap.add_argument("--source", action="append", default=None,
                    help="只抓指定 source_id（显式指定时包含已禁用源，便于回滚对比），可重复")
    ap.add_argument("--include-disabled", action="store_true", help="连同 enabled:false 的旧源一起抓取")
    ap.add_argument("--pages", default="1", help="抓取页数，支持 1 或 1-3")
    ap.add_argument("--since", default=None, help="只保留该日期及之后的条目 YYYY-MM-DD")
    ap.add_argument("--until", default=None, help="只保留该日期及之前的条目 YYYY-MM-DD")
    ap.add_argument("--match", default=None, help="可选：标题正则过滤（默认不过滤）")
    ap.add_argument("--limit", type=int, default=0, help="每个源最多返回条数，0=不限")
    ap.add_argument("--summary", action="store_true", help="只输出每个源的条数/最新/最旧/栏目名/前 3 条")
    ap.add_argument("--out", default=None, help="把 JSON 结果另存到指定文件")
    ap.add_argument("--format", default="json", choices=["json", "table", "lines"])
    args = ap.parse_args()

    m = re.match(r"^(\d+)(?:-(\d+))?$", str(args.pages).strip())
    if not m:
        print(f"[错误] 无效的页码范围格式: {args.pages}，请使用 1 或 1-3 格式", file=sys.stderr)
        return 2
    p_start = int(m.group(1))
    p_end = int(m.group(2) or m.group(1))
    if p_start < 1 or p_end < p_start:
        print(f"[错误] 非法页码范围: {args.pages}", file=sys.stderr)
        return 2

    sources = load_sources(args.city, args.channel)
    if args.source:
        wanted = set(args.source)
        sources = [s for s in sources if s.get("source_id") in wanted]
    elif not args.include_disabled:
        sources = [s for s in sources if s.get("enabled", True)]
    if not sources:
        print(json.dumps({"error": "no source matched", "city": args.city,
                          "channel": args.channel}, ensure_ascii=False), file=sys.stderr)
        return 2

    pattern = re.compile(args.match) if args.match else None
    all_items: List[Dict[str, Any]] = []
    errors = []
    summary_rows: List[Dict[str, Any]] = []

    for src in sources:
        items, meta = collect(src, p_start, p_end, args.channel)
        if not items:
            errors.append(src.get("source_id"))
        dates = [it["date"] for it in items if it.get("date")]
        summary_rows.append({
            "source_id": meta["source_id"],
            "district": meta["district"],
            "role": meta["role"],
            "enabled": bool(src.get("enabled", True)),
            "classify_name": meta["classify_name"],
            "count": len(items),
            "newest": max(dates) if dates else "",
            "oldest": min(dates) if dates else "",
            "top3": [{"date": it.get("date"), "title": it.get("title")}
                     for it in sorted(items, key=lambda x: x.get("date") or "", reverse=True)[:3]],
        })
        kept = []
        for it in items:
            d = it.get("date") or ""
            if args.since and d and d < args.since:
                continue
            if args.until and d and d > args.until:
                continue
            if pattern and not pattern.search(it.get("title", "")):
                continue
            kept.append(it)
        kept.sort(key=lambda x: x.get("date", ""), reverse=True)
        if args.limit:
            kept = kept[: args.limit]
        all_items.extend(kept)

    all_items.sort(key=lambda x: (x.get("date", ""), x.get("source_id", "")), reverse=True)

    payload = {
        "city": args.city,
        "channel": args.channel,
        "source_count": len(sources),
        "empty_sources": errors,
        "count": len(all_items),
        "summary": summary_rows,
        "items": all_items,
    }
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] 已写入 {out_path}", file=sys.stderr)

    if args.summary:
        if args.format == "json":
            print(json.dumps({k: payload[k] for k in ("city", "channel", "source_count",
                                                      "empty_sources", "summary")},
                             ensure_ascii=False, indent=2))
        else:
            print(f"{'源':<22}{'区域':<10}{'状态':<8}{'条数':>4}  {'最新':<11}{'最旧':<11}{'栏目':<12}前 3 条")
            for r in summary_rows:
                state = "启用" if r["enabled"] else "禁用"
                top3 = " | ".join(f"{x['date']} {x['title'][:18]}" for x in r["top3"])
                print(f"{r['source_id']:<22}{r['district']:<10}{state:<8}{r['count']:>4}  "
                      f"{r['newest']:<11}{r['oldest']:<11}{r['classify_name'][:10]:<12}{top3}")
            if errors:
                print(f"\n[空源] {', '.join(errors)}", file=sys.stderr)
    elif args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "lines":
        for it in all_items:
            print(f"{it['date']}\t{it['district']}\t{it['title']}\t{it['url']}")
    else:
        print(f"{'日期':<12}{'区域':<10}{'标题':<60}URL")
        for it in all_items:
            print(f"{it['date']:<12}{it['district']:<10}{it['title'][:58]:<60}{it['url']}")
        if errors:
            print(f"\n[空源] {', '.join(errors)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
