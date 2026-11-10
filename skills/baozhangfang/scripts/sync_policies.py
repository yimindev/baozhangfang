#!/usr/bin/env python3
"""
sync_policies.py - 自包含法定政策法规库抓取与全文入库工具 (纯 SQLite 独立版)
来源: 住房和建设局 - 政策法规专栏
"""

import sys
import json
import sqlite3
import subprocess
import argparse
from pathlib import Path
from bs4 import BeautifulSoup

SKILL_ROOT = Path(__file__).resolve().parent.parent
from db import get_db_path  # 运行库路径（首次使用时自动由 seed.sql 自举）

BASE_URL = "https://zjj.sz.gov.cn/ztfw/zfbz/zcfg2017/"

def fetch_url(url: str, timeout: int = 10) -> str:
    cmd = [
        "curl", "-k", "-s", "-L",
        "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--connect-timeout", str(timeout),
        "--max-time", str(timeout * 2),
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, check=True)
        return res.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def classify_policy(title: str) -> str:
    if "配售型" in title: return "配售型保障房"
    if "共有产权" in title: return "共有产权住房"
    if "租赁住房" in title or "租房" in title or "保租房" in title or "住房租赁" in title: return "保障性租赁住房"
    if "公共租赁" in title or "公租房" in title: return "公共租赁住房"
    if "人才" in title or "安居工程" in title: return "人才住房与安居"
    if "安居型商品房" in title: return "安居型商品房"
    if "城中村" in title or "棚户区" in title: return "城中村改造与棚改"
    return "综合保障法规"

def parse_policy_detail(url: str):
    html = fetch_url(url)
    if not html: return "", "", "", ""
    soup = BeautifulSoup(html, "html.parser")
    content_node = (
        soup.find("div", class_="article_content") or
        soup.find("div", class_="article-content") or
        soup.find("div", class_="news_cont_d_c") or
        soup.find("div", class_="TRS_Editor") or
        soup.find("div", id="article_content") or
        soup.find("div", class_="content")
    )
    content_text = content_node.get_text("\n", strip=True) if content_node else ""

    doc_number = ""
    publisher = ""
    effective_date = ""

    for line in content_text.split("\n")[:15]:
        line_s = line.strip()
        if any(k in line_s for k in ["〔", "号", "字"]):
            if len(line_s) < 50: doc_number = line_s
        if any(k in line_s for k in ["深圳市人民政府", "深圳市住房和建设局", "建设局", "住保署"]):
            if len(line_s) < 60: publisher = line_s

    atts = []
    if content_node:
        for a in content_node.find_all("a", href=True):
            href = a.get("href")
            txt = a.get_text(strip=True)
            if any(ext in href.lower() for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx"]):
                f_url = href if href.startswith("http") else f"{BASE_URL}{href.lstrip('./')}"
                atts.append({"name": txt or "政策附件", "url": f_url})

    return content_text, doc_number, publisher, json.dumps(atts, ensure_ascii=False) if atts else None

def sync_policies(city: str = "深圳"):
    print(f"[*] 正在拉取政策法规库 ({city})...")
    conn = sqlite3.connect(get_db_path())
    cur = conn.cursor()

    pages = [f"{BASE_URL}index.html", f"{BASE_URL}index_2.html"]
    saved = 0

    for p_url in pages:
        html = fetch_url(p_url)
        if not html: continue
        soup = BeautifulSoup(html, "html.parser")

        for li in soup.find_all("li"):
            a = li.find("a")
            span = li.find("span")
            if not a or not span: continue

            title = (a.get("title") or a.get_text(strip=True)).strip()
            date_raw = span.get_text(strip=True)
            pub_date = f"20{date_raw}" if len(date_raw) == 8 else date_raw
            href = a.get("href", "").strip()
            full_url = href if href.startswith("http") else f"{BASE_URL}{href.lstrip('./')}"

            cur.execute("SELECT id FROM policies WHERE url = ?", (full_url,))
            if cur.fetchone(): continue

            cat = classify_policy(title)
            content, doc_num, publisher, att_json = parse_policy_detail(full_url)
            summary = content[:150].replace("\n", " ") if content else ""

            cur.execute("""
            INSERT OR REPLACE INTO policies (city, category, title, document_number, publisher, publish_date, status, url, summary, content_text, attachments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (city, cat, title, doc_num[:200] if doc_num else None, publisher[:200] if publisher else None, pub_date, '现行有效', full_url, summary, content, att_json))
            saved += 1
            print(f"  + [新政策法规入库] {pub_date} | {cat: <10} | {title[:40]}")

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM policies WHERE city = ?", (city,))
    total = cur.fetchone()[0]
    conn.close()
    print(f"[SUCCESS] 政策法规同步完成，本次新增 {saved} 部，当前库内存量: {total} 部。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自包含政策法规库同步工具")
    parser.add_argument("--city", default="深圳", help="目标城市名称，默认: 深圳")
    args = parser.parse_args()
    sync_policies(city=args.city)
