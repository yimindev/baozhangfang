#!/usr/bin/env python3
"""
fetch_detail.py - 公告正文与附件抽取器（原子工具）

职责边界：
  只负责「给 URL，返回干净的正文文本 + 附件直链 + 可选表格」。
  支持 HTML 详情页以及 PDF / XLSX / DOCX（及可选 XLS）附件链接的通用文本与表格抽取。
  不做分类、不抽取业务字段（套数/价格/电话/名单字段映射）、不写库。
  是否抓取附件、业务字段怎么读、要不要入库，由 Agent 拿到抽取结果后自行判断。

用法：
  python3 scripts/fetch_detail.py https://example.gov.cn/post_123.html
  python3 scripts/fetch_detail.py https://example.gov.cn/price_table.xlsx --tables
  python3 scripts/fetch_detail.py https://example.gov.cn/list.pdf --tables
  python3 scripts/fetch_detail.py --url-file /tmp/urls.txt --save-dir /tmp/html
  python3 scripts/fetch_detail.py --url-file - --tables < /tmp/urls.txt
  python3 scripts/fetch_detail.py <url> --text-only
"""

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def detect_binary_type(url: str, blob: bytes) -> Optional[str]:
    """根据魔数与扩展名识别二进制附件格式，返回 pdf/xlsx/docx/xls 或 None（按 HTML 处理）。"""
    path = url.lower().split("?")[0]
    if blob[:4] == b"%PDF" or path.endswith(".pdf"):
        return "pdf"
    if blob[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = set(zf.namelist())
                if "xl/workbook.xml" in names or path.endswith(".xlsx"):
                    return "xlsx"
                if "word/document.xml" in names or path.endswith(".docx"):
                    return "docx"
        except zipfile.BadZipFile:
            pass
    if path.endswith(".xlsx"):
        return "xlsx"
    if path.endswith(".docx"):
        return "docx"
    if blob[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or path.endswith(".xls"):
        # OLE2 复合文档：老式 .xls 或 .doc
        if path.endswith(".doc"):
            return "doc"
        return "xls"
    return None


def _clean_cell(val: Any) -> str:
    if val is None:
        return ""
    return re.sub(r"\s+", " ", str(val)).strip()


def _rows_to_text(tables: List[List[List[str]]], headers: Optional[List[str]] = None) -> str:
    lines: List[str] = []
    for idx, rows in enumerate(tables):
        if headers and idx < len(headers) and headers[idx]:
            lines.append(f"[{headers[idx]}]")
        for row in rows:
            if any(c for c in row):
                lines.append("\t".join(row))
    return "\n".join(lines)


def extract_pdf(blob: bytes, want_tables: bool = False) -> Tuple[str, List[List[List[str]]]]:
    """抽取 PDF 文本及可选表格；优先 pdfplumber，其次 pypdf。"""
    tables: List[List[List[str]]] = []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(blob)
        temp_p = Path(tf.name)
    try:
        try:
            import pdfplumber
            with pdfplumber.open(temp_p) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
                if want_tables:
                    for page in pdf.pages:
                        for tbl in page.extract_tables() or []:
                            cleaned = [[_clean_cell(c) for c in row] for row in tbl if row]
                            if cleaned:
                                tables.append(cleaned)
                return text, tables
        except Exception:
            pass
        try:
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(str(temp_p)).pages)
            return text, tables
        except Exception as exc:
            return f"[PDF 文本抽取失败: {exc}]", tables
    finally:
        if temp_p.exists():
            temp_p.unlink()


def _col_ref_to_idx(ref: str) -> Optional[int]:
    m = re.match(r"^([A-Za-z]+)", ref or "")
    if not m:
        return None
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _extract_xlsx_stdlib(blob: bytes) -> Tuple[List[str], List[List[List[str]]]]:
    """纯标准库读取 .xlsx（zipfile + ElementTree），作为未装 openpyxl 时的兜底。"""
    ns_main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    ns_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    sheet_names: List[str] = []
    tables: List[List[List[str]]] = []

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall(f"{ns_main}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns_main}t")))

        rel_map: Dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rel_root:
                rid = rel.get("Id")
                target = rel.get("Target", "").lstrip("/")
                if rid and target:
                    if not target.startswith("xl/"):
                        target = "xl/" + target
                    rel_map[rid] = target

        targets: List[Tuple[str, str]] = []
        if "xl/workbook.xml" in names:
            wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
            for sh in wb_root.findall(f".//{ns_main}sheet"):
                sname = sh.get("name") or "Sheet"
                rid = sh.get(f"{ns_rel}id")
                target = rel_map.get(rid, "") if rid else ""
                if target in names:
                    targets.append((sname, target))
        if not targets:
            for p in sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")):
                targets.append((Path(p).stem, p))

        for sname, spath in targets:
            sh_root = ET.fromstring(zf.read(spath))
            rows: List[List[str]] = []
            for r in sh_root.findall(f".//{ns_main}row"):
                row_vals: List[str] = []
                for c in r.findall(f"{ns_main}c"):
                    col_idx = _col_ref_to_idx(c.get("r", ""))
                    if col_idx is None:
                        col_idx = len(row_vals)
                    while len(row_vals) <= col_idx:
                        row_vals.append("")
                    ctype = c.get("t")
                    if ctype == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(f"{ns_main}t"))
                    else:
                        v = c.find(f"{ns_main}v")
                        if v is None or v.text is None:
                            val = ""
                        elif ctype == "s":
                            idx = int(v.text)
                            val = shared[idx] if 0 <= idx < len(shared) else ""
                        elif ctype == "b":
                            val = "TRUE" if v.text == "1" else "FALSE"
                        else:
                            val = v.text
                    row_vals[col_idx] = _clean_cell(val)
                while row_vals and row_vals[-1] == "":
                    row_vals.pop()
                if any(row_vals):
                    rows.append(row_vals)
            sheet_names.append(sname)
            tables.append(rows)
    return sheet_names, tables


def extract_xlsx(blob: bytes) -> Tuple[str, List[str], List[List[List[str]]]]:
    """抽取 .xlsx 各工作表；优先 openpyxl，其次纯标准库兜底。"""
    sheet_names: List[str] = []
    tables: List[List[List[str]]] = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        try:
            for sname in wb.sheetnames:
                ws = wb[sname]
                rows: List[List[str]] = []
                for raw_row in ws.iter_rows(values_only=True):
                    cells = [_clean_cell(v) for v in raw_row]
                    while cells and cells[-1] == "":
                        cells.pop()
                    if any(cells):
                        rows.append(cells)
                sheet_names.append(sname)
                tables.append(rows)
        finally:
            wb.close()
    except ImportError:
        sheet_names, tables = _extract_xlsx_stdlib(blob)
    except Exception as exc:
        return f"[XLSX 解析失败: {exc}]", sheet_names, tables
    return _rows_to_text(tables, sheet_names), sheet_names, tables


def extract_docx(blob: bytes) -> Tuple[str, List[List[List[str]]]]:
    """纯标准库抽取 .docx 段落与表格。"""
    ns_w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            doc_root = ET.fromstring(zf.read("word/document.xml"))
            body = doc_root.find(f"{ns_w}body")
            if body is None:
                return "", tables
            for child in body:
                if child.tag == f"{ns_w}p":
                    txt = "".join(t.text or "" for t in child.iter(f"{ns_w}t")).strip()
                    if txt:
                        paragraphs.append(txt)
                elif child.tag == f"{ns_w}tbl":
                    rows: List[List[str]] = []
                    for tr in child.findall(f"{ns_w}tr"):
                        cells = []
                        for tc in tr.findall(f"{ns_w}tc"):
                            cell_txt = " ".join(
                                "".join(t.text or "" for t in p.iter(f"{ns_w}t")).strip()
                                for p in tc.findall(f".//{ns_w}p")
                            )
                            cells.append(_clean_cell(cell_txt))
                        if any(cells):
                            rows.append(cells)
                    if rows:
                        tables.append(rows)
                        paragraphs.extend("\t".join(r) for r in rows)
    except Exception as exc:
        return f"[DOCX 解析失败: {exc}]", tables
    return "\n".join(paragraphs), tables


def extract_xls(blob: bytes) -> Tuple[str, List[str], List[List[List[str]]]]:
    """抽取老式 .xls（需 xlrd）。"""
    try:
        import xlrd
    except ImportError:
        return "[XLS 解析失败: 当前环境未安装 xlrd，无法读取老式 .xls 二进制表格]", [], []
    try:
        wb = xlrd.open_workbook(file_contents=blob)
        sheet_names = list(wb.sheet_names())
        tables: List[List[List[str]]] = []
        for sname in sheet_names:
            sh = wb.sheet_by_name(sname)
            rows: List[List[str]] = []
            for r in range(sh.nrows):
                cells = [_clean_cell(sh.cell_value(r, c)) for c in range(sh.ncols)]
                while cells and cells[-1] == "":
                    cells.pop()
                if any(cells):
                    rows.append(cells)
            tables.append(rows)
        return _rows_to_text(tables, sheet_names), sheet_names, tables
    except Exception as exc:
        return f"[XLS 解析失败: {exc}]", [], []


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


def _safe_filename(url: str, ext: str) -> str:
    base = url.split("?")[0].rsplit("/", 1)[-1]
    name = re.sub(r"[^\w.-]", "_", base)[:80] or f"doc.{ext}"
    if not name.lower().endswith(f".{ext}"):
        name += f".{ext}"
    return name


def _process_binary(url: str, blob: bytes, ftype: str, save_dir: Optional[Path],
                    want_tables: bool, max_chars: int) -> Dict[str, Any]:
    filename = _safe_filename(url, ftype)
    out: Dict[str, Any] = {
        "url": clean_url(url),
        "status": "ok",
        "content_type": ftype,
        "title": filename,
        "publish_date": "",
        "text": "",
        "text_len": 0,
        "attachments": [],
    }
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        p = save_dir / filename
        p.write_bytes(blob)
        out["local_path"] = str(p)

    tables: List[List[List[str]]] = []
    if ftype == "pdf":
        text, tables = extract_pdf(blob, want_tables=want_tables)
    elif ftype == "xlsx":
        text, sheets, tables = extract_xlsx(blob)
        out["sheets"] = sheets
    elif ftype == "docx":
        text, tables = extract_docx(blob)
    elif ftype == "xls":
        text, sheets, tables = extract_xls(blob)
        out["sheets"] = sheets
    else:
        out["status"] = "unsupported_format"
        text = f"[暂不支持自动抽取该二进制格式: .{ftype}，请下载后人工查看]"

    out["text_len"] = len(text)
    out["text"] = text[:max_chars] if max_chars else text
    if want_tables:
        out["tables"] = tables
    return out


def process(url: str, save_dir: Optional[Path] = None, want_tables: bool = False,
            max_chars: int = 0) -> Dict[str, Any]:
    blob = fetch_raw(url)
    if not blob:
        return {"url": url, "status": "fetch_failed", "text": ""}

    ftype = detect_binary_type(url, blob)
    if ftype:
        return _process_binary(url, blob, ftype, save_dir, want_tables, max_chars)

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
    ap.add_argument("urls", nargs="*", help="公告详情页或附件 URL（支持 html/pdf/xlsx/docx），可传多个")
    ap.add_argument("--url-file", default=None, help="URL 列表文件，每行一个；- 表示 stdin")
    ap.add_argument("--save-dir", default=None, help="同时把原始 html/pdf/xlsx/docx 落盘到该目录")
    ap.add_argument("--tables", action="store_true", help="额外抽取页面/PDF/Excel/Word 表格")
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
