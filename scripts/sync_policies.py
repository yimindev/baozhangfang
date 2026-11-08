#!/usr/bin/env python3
"""
sync_policies.py - 深圳保障房法定政策法规抓取与入库工具
来源: 深圳市住房和建设局 - 政策法规专栏 (https://zjj.sz.gov.cn/ztfw/zfbz/zcfg2017/)
"""

import sys
import json
import sqlite3
import pymysql
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_SQLITE = PROJECT_ROOT / "data" / "housing.db"
CONFIG_FILE = PROJECT_ROOT / "config" / "database.json"

BASE_URL = "https://zjj.sz.gov.cn/ztfw/zfbz/zcfg2017/"

def fetch_url(url: str, timeout: int = 15) -> str:
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
    if "配售型" in title:
        return "配售型保障房"
    if "共有产权" in title:
        return "共有产权住房"
    if "租赁住房" in title or "租房" in title or "保租房" in title or "住房租赁" in title:
        return "保障性租赁住房"
    if "公共租赁" in title or "公租房" in title:
        return "公共租赁住房"
    if "人才" in title or "安居工程" in title:
        return "人才住房与安居"
    if "安居型商品房" in title:
        return "安居型商品房"
    if "城中村" in title or "棚户区" in title:
        return "城中村改造与棚改"
    return "综合保障法规"

def parse_policy_detail(url: str):
    """解析政策正文与公文字号"""
    html = fetch_url(url)
    if not html:
        return "", "", "", ""
    soup = BeautifulSoup(html, "html.parser")
    content_node = (
        soup.find("div", class_="article_content") or
        soup.find("div", class_="article-content") or
        soup.find("div", class_="news_cont_d_c") or
        soup.find("div", class_="TRS_Editor") or
        soup.find("div", class_="content")
    )
    full_text = content_node.get_text("\n", strip=True) if content_node else ""
    
    # 提取文号与发文机构
    doc_number = ""
    publisher = ""
    for line in full_text.split("\n")[:20]:
        if any(k in line for k in ["号", "令第", "〔20"]):
            if any(p in line for p in ["深府", "深住建", "规〔", "令"]):
                doc_number = line.strip()
                break
    
    # 提取发文单位 (末尾或抬头)
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    if lines:
        if len(lines) >= 3 and any(k in lines[-2] for k in ["局", "委", "政府", "办公室"]):
            publisher = lines[-2]
        elif any(k in lines[-1] for k in ["局", "委", "政府", "办公室"]):
            publisher = lines[-1]

    doc_number = doc_number[:200]
    publisher = publisher[:200]

    # 提取附件
    attachments = []
    if content_node:
        for a in content_node.find_all("a"):
            href = a.get("href", "")
            name = a.get_text(strip=True)
            if any(ext in href.lower() for ext in [".pdf", ".doc", ".docx", ".xlsx", ".xls"]):
                if not href.startswith("http"):
                    href = f"https://zjj.sz.gov.cn{href}" if href.startswith("/") else f"{url.rsplit('/', 1)[0]}/{href}"
                attachments.append({"name": name, "url": href})

    att_json = json.dumps(attachments, ensure_ascii=False) if attachments else None
    return full_text, doc_number, publisher, att_json

def sync_all_policies():
    print(">>> 正在抓取深圳市住建局全量政策法规...")
    policies = []
    for page in range(1, 3): # 官方政策法规共 2 页
        page_url = f"{BASE_URL}index.html" if page == 1 else f"{BASE_URL}index_{page}.html"
        html = fetch_url(page_url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        for li in soup.find_all("li"):
            a = li.find("a")
            span = li.find("span")
            if a and span and a.get("href"):
                href = a.get("href")
                if not href.startswith("http"):
                    href = f"{BASE_URL}{href.lstrip('./')}"
                title = (a.get("title") or a.get_text(strip=True)).strip()
                raw_date = span.get_text(strip=True)
                # 标准化 YYYY-MM-DD
                pub_date = f"20{raw_date}" if len(raw_date) == 8 and raw_date.count("-") == 2 else raw_date
                policies.append((pub_date, title, href))

    print(f"共发现 {len(policies)} 篇法定政策公文，开始深入抓取正文...")

    # 连接 SQLite
    s_conn = sqlite3.connect(DB_SQLITE)
    s_cur = s_conn.cursor()

    # 连接 MySQL
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    m_conn = pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["admin"]["user"],
        password=cfg["admin"]["password"],
        database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
        autocommit=False
    )
    m_cur = m_conn.cursor()

    saved_count = 0
    for pub_date, title, url in policies:
        cat = classify_policy(title)
        full_text, doc_number, publisher, att_json = parse_policy_detail(url)
        summary = full_text[:150].replace("\n", " ") if full_text else ""

        # 写入 SQLite
        s_cur.execute("""
        INSERT OR REPLACE INTO policies (city, category, title, document_number, publisher, publish_date, status, url, summary, content_text, attachments_json)
        VALUES (?, ?, ?, ?, ?, ?, '现行有效', ?, ?, ?, ?)
        """, ('深圳', cat, title, doc_number, publisher, pub_date, url, summary, full_text, att_json))

        # 写入 MySQL
        m_cur.execute("""
        INSERT INTO policies (city, category, title, document_number, publisher, publish_date, status, url, summary, content_text, attachments_json)
        VALUES (%s, %s, %s, %s, %s, %s, '现行有效', %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            category=VALUES(category),
            document_number=VALUES(document_number),
            publisher=VALUES(publisher),
            publish_date=VALUES(publish_date),
            summary=VALUES(summary),
            content_text=VALUES(content_text),
            attachments_json=VALUES(attachments_json);
        """, ('深圳', cat, title, doc_number, publisher, pub_date, url, summary, full_text, att_json))

        saved_count += 1
        print(f"[{saved_count}/{len(policies)}] 入库政策: [{pub_date}] {title[:30]}...")

    s_conn.commit()
    m_conn.commit()
    s_conn.close()
    m_cur.close()
    m_conn.close()
    print(f"\n[SUCCESS] 全部法定政策法规入库完成，累计: {saved_count} 篇！")

if __name__ == "__main__":
    sync_all_policies()
