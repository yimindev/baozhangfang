#!/usr/bin/env python3
"""
fetch_detail.py - 公告正文与附件抽取器（原子工具）

职责边界：
  只负责「给 URL，返回干净的正文文本 + 附件直链 + 可选表格」。
  不做分类、不抽取业务字段（套数/价格/电话）、不写库。
  业务字段怎么读、要不要入库，由 Agent 拿到正文后自行判断。

用法：
  python3 scripts/fetch_detail.py https://example.gov.cn/post_123.html
  python3 scripts/fetch_detail.py --url-file /tmp/urls.txt --save-dir /tmp/html
  python3 scripts/fetch_detail.py --url-file - --tables < /tmp/urls.txt
  python3 scripts/fetch_detail.py <url> --text-only
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
ATTACH_RE = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar|7z)(\?|$)", re.I)

CONTENT_SELECTORS = [
    ("div", {"class": "article-content"}),
    ("div", {"class": "article_content"}),
    ("div", {"class": "news_cont_d_c"}),
    ("div", {"class": "TRS_Editor"}),
    ("div", {"id": "article_content"}),
    ("div", {"id": "main"}),
    ("article", {}),
    ("div", {"class": "content"}),
]

DATE_META_ATTRS = [
    {"name": "PubDate"},
    {"name": "pubdate"},
    {"name": "publishdate"},
    {"name": "ArticleDate"},
    {"name": "publish_date"},
    {"property": "article:published_time"},
    {"property": "og:release_date"},
]


def clean_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parts = list(urllib.parse.urlsplit(url))
    parts[2] = re.sub(r"/+", "/", parts[2])
    return urllib.parse.urlunsplit(parts)


def fetch_raw(url: str, timeout: int = 15) -> bytes:
    cmd = ["curl", "-k", "-s", "-L", "-A", UA,
           "--connect-timeout", str(timeout), "--max-time", str(timeout * 3), url]
    try:
        return subprocess.run(cmd, capture_output=True, check=True).stdout
    except Exception:
        return b""


def looks_like_pdf(url: str, blob: bytes) -> bool:
    return blob[:4] == b"%PDF" or url.lower().split("?")[0].endswith(".pdf")


def pdf_to_text(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    except Exception as exc:
        return f"[PDF 文本抽取失败: {exc}]"


def pick_content(soup: BeautifulSoup) -> Any:
    """按常见政务模板选择器取正文容器，取不到则退回「文本最长的 div」。"""
    for tag, attrs in CONTENT_SELECTORS:
        node = soup.find(tag, attrs=attrs) if attrs else soup.find(tag)
        if node and len(node.get_text(strip=True)) > 150:
            return node
    best, best_len = None, 0
    for div in soup.find_all("div"):
        length = len(div.get_text(strip=True))
        if length > best_len and length > 300:
            best, best_len = div, length
    return best


def clean_text(node: Any) -> str:
    if node is None:
        return ""
    for bad in node.find_all(["script", "style", "noscript"]):
        bad.decompose()
    lines = [ln.strip() for ln in node.get_text("\n", strip=True).split("\n")]
    return "\n".join(ln for ln in lines if ln)


def extract_tables(soup: BeautifulSoup) -> List[List[List[str]]]:
    tables = []
    for table in soup.find_all("table")[:10]:
        rows = []
        for tr in table.find_all("tr")[:200]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def normalize_meta_date(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def guess_meta(soup: BeautifulSoup, text: str) -> Dict[str, str]:
    title = ""
    for attrs in ({"property": "og:title"}, {"name": "ArticleTitle"}, {"name": "article-title"}):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content", "").strip():
            title = node["content"].strip()
            break
    if not title:
        for sel in ["h1", "h2"]:
            node = soup.find(sel)
            if node:
                candidate = node.get_text(strip=True)
                if len(candidate) > 8 and not re.search(r"政府信息公开|首页|政务公开", candidate):
                    title = candidate
                    break
    if not title and soup.title:
        title = re.split(r"[_|\-—]", soup.title.get_text(strip=True))[0].strip()

    date = ""
    # 1. 优先从 meta 标签中提取官方发布日期
    for attrs in DATE_META_ATTRS:
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content", "").strip():
            d = normalize_meta_date(node["content"])
            if d:
                date = d
                break

    # 2. 从页面 DOM 元素中查找包含明确“发布时间/发布日期”关键字的节点
    if not date:
        for pattern in [r"(?:发布时间|发布日期|成文日期|印发日期)[：:\s]*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})",
                        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})\s*(?:发布|印发)"]:
            nodes = soup.find_all(text=re.compile(pattern))
            for el in nodes:
                m = re.search(pattern, str(el))
                if m:
                    d = normalize_meta_date(m.group(1))
                    if d:
                        date = d
                        break
            if date:
                break

    # 3. 兜底从正文头部文本中提取附带发布关键字的日期
    if not date:
        m = re.search(r"(?:发布日期|发布时间|成文日期|印发日期)[：:\s]*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", text[:500])
        if m:
            date = normalize_meta_date(m.group(1))

    return {"title": title, "publish_date": date}


def process(url: str, save_dir: Path = None, want_tables: bool = False,
            max_chars: int = 0) -> Dict[str, Any]:
    blob = fetch_raw(url)
    if not blob:
        return {"url": url, "status": "fetch_failed", "text": ""}

    if looks_like_pdf(url, blob):
        out = {"url": url, "status": "ok", "content_type": "pdf",
               "title": "", "publish_date": "", "text": "", "attachments": []}
        filename = re.sub(r"[^\w.-]", "_", url.rsplit("/", 1)[-1])[:80] or "doc.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        out["title"] = filename

        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            p = save_dir / filename
            p.write_bytes(blob)
            out["local_path"] = str(p)
            out["text"] = pdf_to_text(p)
        else:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tf.write(blob)
                temp_p = Path(tf.name)
            try:
                out["text"] = pdf_to_text(temp_p)
            finally:
                if temp_p.exists():
                    temp_p.unlink()
        return out

    html = blob.decode("utf-8", errors="ignore")
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        p = save_dir / (re.sub(r"[^\w.-]", "_", url.rsplit("/", 1)[-1])[:80] or "page.html")
        p.write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(pick_content(soup))
    meta = guess_meta(soup, text)

    attachments = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ATTACH_RE.search(href):
            full = clean_url(urllib.parse.urljoin(url, href))
            if full:
                attachments.append({"name": a.get_text(" ", strip=True) or "附件", "url": full})

    result = {
        "url": clean_url(url),
        "status": "ok",
        "content_type": "html",
        "title": meta["title"],
        "publish_date": meta["publish_date"],
        "text": text[:max_chars] if max_chars else text,
        "text_len": len(text),
        "attachments": attachments,
    }
    if want_tables:
        result["tables"] = extract_tables(soup)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="公告正文与附件抽取器")
    ap.add_argument("urls", nargs="*", help="公告详情页 URL，可传多个")
    ap.add_argument("--url-file", default=None, help="URL 列表文件，每行一个；- 表示 stdin")
    ap.add_argument("--save-dir", default=None, help="同时把原始 html/pdf 落盘到该目录")
    ap.add_argument("--tables", action="action_true" if hasattr(argparse, "action_true") else "store_true",
                    help="额外抽取页面表格")
    ap.add_argument("--max-chars", type=int, default=0, help="正文截断长度，0=不截断")
    ap.add_argument("--text-only", action="store_true", help="只输出纯文本，便于人读")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.url_file:
        raw = sys.stdin.read() if args.url_file == "-" else Path(args.url_file).read_text(encoding="utf-8")
        urls += [u.strip() for u in raw.splitlines() if u.strip()]
    if not urls:
        ap.error("至少需要一个 URL 或 --url-file")

    save_dir = Path(args.save_dir) if args.save_dir else None
    results = [process(u, save_dir, args.tables, args.max_chars) for u in urls]

    if args.text_only:
        for r in results:
            print(f"### {r.get('title') or r['url']}\n{r['url']}\n")
            print(r.get("text", ""))
            if r.get("attachments"):
                print("\n附件：")
                for a in r["attachments"]:
                    print(f"- {a['name']}: {a['url']}")
            print("\n" + "=" * 70 + "\n")
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
