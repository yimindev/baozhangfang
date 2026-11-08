#!/usr/bin/env python3
"""
sync_notices.py - 深圳保障房公告抓取与全文入库工具 (2026年全域数据)
支持:
  1. 市住建局主题专栏 (HTML 分页解析)
  2. 各区住建局公开目录 (gkmlpt REST API)
  3. 过滤 2026 年相关通告，解析批次、分类、正文全文、附件
  4. 存储至 SQLite `notices` 表
"""

import sys
import json
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "sources.json"
DB_PATH = PROJECT_ROOT / "data" / "housing.db"

HOUSING_KEYWORDS = [
    "人才", "安居", "共有产权", "公租房", "公共租赁", "保障性",
    "配售", "配租", "摇号", "选房", "认购", "合格名单", "终审",
    "初审", "退房", "房源", "住房保障"
]

BATCH_PATTERNS = [
    r"住保售〔(\d{4})〕(\d+)号(?:批次)?",
    r"〔(\d{4})〕(\d+)号",
    r"(\d{7,8}-\d+|\d{7,8})批次",
    r"(\d{4}\d{2,3})批次",
]

def fetch_url(url: str, timeout: int = 15) -> str:
    """使用 curl 安全抓取网页，避免国产 SM2/TLS 握手问题"""
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
    except Exception as e:
        return ""

def classify_notice(title: str) -> str:
    """根据标题自动识别公告类型"""
    if any(k in title for k in ["配售通告", "配售住房通告", "认购通告", "配租通告", "配售通知"]):
        return "认购通告"
    if any(k in title for k in ["初审", "初核", "认购申请家庭名单", "合格名单公示", "初审合格"]):
        return "初审名单"
    if any(k in title for k in ["终审", "复核", "资格审核合格", "终审合格", "终审结果"]):
        return "终审结果"
    if any(k in title for k in ["摇号", "抽签", "摇号结果"]):
        return "摇号结果"
    if any(k in title for k in ["选房通告", "选房通知", "选房有关事项", "选房结果", "选房签约", "销控"]):
        return "选房通知"
    if any(k in title for k in ["年度计划", "实施计划", "入市计划", "建设筹集"]):
        return "发展计划"
    if any(k in title for k in ["轮候", "日常轮候", "轮候申请"]):
        return "轮候公示"
    return "综合公告"

def extract_batch_id(title: str) -> str:
    """提取批次文号"""
    m = re.search(r"住保售〔(\d{4})〕(\d+)号(?:批次)?", title)
    if m:
        return f"住保售〔{m.group(1)}〕{m.group(2)}号批次"
    m = re.search(r"（(\d{7,8}-\d+|\d{7,8})批次）", title)
    if m:
        return f"{m.group(1)}批次"
    m = re.search(r"〔(\d{4})〕(\d+)号", title)
    if m:
        return f"〔{m.group(1)}〕{m.group(2)}号"
    return ""

def parse_notice_content(url: str) -> str:
    """抓取公告正文文本"""
    html = fetch_url(url)
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # 匹配常见政务网正文容器
    content_node = (
        soup.find("div", class_="article_content") or
        soup.find("div", class_="article-content") or
        soup.find("div", class_="news_cont_d_c") or
        soup.find("div", class_="TRS_Editor") or
        soup.find("div", id="article_content") or
        soup.find("div", class_="content")
    )
    if content_node:
        return content_node.get_text("\n", strip=True)
    return ""

def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT NOT NULL,
        batch_id TEXT,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        publish_date TEXT,
        url TEXT UNIQUE NOT NULL,
        summary TEXT,
        content_text TEXT,
        attachments_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS batches (
        batch_id TEXT PRIMARY KEY,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT NOT NULL,
        project_name TEXT NOT NULL,
        housing_type TEXT NOT NULL,
        two_bedroom_units INTEGER DEFAULT 0,
        three_bedroom_units INTEGER DEFAULT 0,
        total_units INTEGER DEFAULT 0,
        average_price REAL,
        sub_start_date TEXT,
        sub_end_date TEXT,
        current_stage TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    conn.commit()

def sync_municipal_notices(conn: sqlite3.Connection, max_pages: int = 15):
    """抓取市住房保障署（市住建局专栏）2026年公告"""
    print(">>> 开始抓取市住建局（市保障署）公告...")
    cur = conn.cursor()
    total_saved = 0
    base_url = "https://zjj.sz.gov.cn/ztfw/zfbz/tzgg2017/"

    for page in range(1, max_pages + 1):
        url = f"{base_url}index.html" if page == 1 else f"{base_url}index_{page}.html"
        html = fetch_url(url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        items = soup.find_all("li")
        page_2026_count = 0
        reached_earlier = False

        for li in items:
            a = li.find("a")
            span = li.find("span")
            if not a or not span:
                continue
            title = (a.get("title") or a.get_text(strip=True)).strip()
            date_raw = span.get_text(strip=True)
            href = a.get("href", "").strip()
            
            # 标准化日期格式
            # 格式常见为 26-10-29 或 2026-10-29
            if re.match(r"^26-\d{2}-\d{2}", date_raw):
                publish_date = f"20{date_raw}"
            elif re.match(r"^2026-\d{2}-\d{2}", date_raw):
                publish_date = date_raw
            elif "2026" in title or "〔2026〕" in title:
                publish_date = "2026-未知"
            else:
                if re.match(r"^(?:25|24|23)-\d{2}-\d{2}", date_raw):
                    reached_earlier = True
                continue

            page_2026_count += 1
            if not href.startswith("http"):
                full_url = f"{base_url}{href.lstrip('./')}"
            else:
                full_url = href

            category = classify_notice(title)
            batch_id = extract_batch_id(title)

            # 抓取重要通告的正文
            content_text = ""
            if category in ["认购通告", "选房通知", "摇号结果", "终审结果"]:
                content_text = parse_notice_content(full_url)

            try:
                cur.execute('''
                INSERT INTO notices (city, district, batch_id, category, title, publish_date, url, content_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    batch_id=excluded.batch_id,
                    category=excluded.category,
                    publish_date=excluded.publish_date,
                    content_text=CASE WHEN excluded.content_text != '' THEN excluded.content_text ELSE notices.content_text END
                ''', ('深圳', '市住建局', batch_id, category, title, publish_date, full_url, content_text))
                total_saved += 1
            except Exception as e:
                pass

        conn.commit()
        if reached_earlier or page_2026_count == 0:
            break

    print(f"市住建局 2026 年通告抓取完成，累计入库/更新: {total_saved} 条")

def sync_gkmlpt_district(conn: sqlite3.Connection, source: dict, max_pages: int = 5):
    """抓取各区 gkmlpt 平台的 2026 年公告"""
    district = source.get("district", "区住建局")
    api_pattern = source.get("api")
    if not api_pattern:
        return 0

    cur = conn.cursor()
    saved = 0
    print(f">>> 正在同步 [{district}] gkmlpt 数据...")

    for page in range(1, max_pages + 1):
        api_url = api_pattern.format(page=page)
        res_text = fetch_url(api_url)
        if not res_text:
            break
        try:
            data = json.loads(res_text)
        except Exception:
            break

        articles = data.get("articles", [])
        if not articles:
            break

        reached_earlier = False
        for art in articles:
            created_at = art.get("created_at") or ""
            # 判断是否为 2026 年
            if not created_at.startswith("2026"):
                if created_at and created_at < "2026-01-01":
                    reached_earlier = True
                continue

            title = (art.get("title") or "").strip()
            # 过滤保障房相关关键词
            is_housing = any(k in title for k in HOUSING_KEYWORDS)
            keywords = art.get("keywords") or ""
            if any(k in keywords for k in ["保障", "人才", "公租", "安居"]):
                is_housing = True
            
            if not is_housing:
                continue

            publish_date = created_at[:10]
            url = art.get("url") or ""
            summary = art.get("abstract") or ""
            category = classify_notice(title)
            batch_id = extract_batch_id(title)

            # 附件列表
            attachments = art.get("attachment") or []
            att_json = json.dumps(attachments, ensure_ascii=False) if attachments else None

            # 抓取重点通告的正文
            content_text = ""
            if category in ["认购通告", "选房通知", "摇号结果", "终审结果"] and url:
                content_text = parse_notice_content(url)

            try:
                cur.execute('''
                INSERT INTO notices (city, district, batch_id, category, title, publish_date, url, summary, content_text, attachments_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    batch_id=excluded.batch_id,
                    category=excluded.category,
                    publish_date=excluded.publish_date,
                    summary=excluded.summary,
                    attachments_json=excluded.attachments_json,
                    content_text=CASE WHEN excluded.content_text != '' THEN excluded.content_text ELSE notices.content_text END
                ''', ('深圳', district, batch_id, category, title, publish_date, url, summary, content_text, att_json))
                saved += 1
            except Exception:
                pass

        conn.commit()
        if reached_earlier:
            break

    return saved

def main():
    if not CONFIG_PATH.exists():
        print(f"配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # 1. 市住建局
    sync_municipal_notices(conn, max_pages=15)

    # 2. 各区住建局 (gkmlpt)
    city_cfg = config["cities"][0]
    total_district_saved = 0
    for src in city_cfg.get("sources", []):
        if src.get("type") == "gkmlpt" and src.get("enabled", True):
            count = sync_gkmlpt_district(conn, src, max_pages=5)
            total_district_saved += count

    print(f"全部区住建局 2026 数据抓取完成，累计入库: {total_district_saved} 条")

    # 统计展示
    cur = conn.cursor()
    cur.execute("SELECT district, category, COUNT(*) FROM notices WHERE publish_date LIKE '2026%' GROUP BY district, category ORDER BY district, COUNT(*) DESC")
    rows = cur.fetchall()
    print("\n================== 2026 年公告数据库统计 ==================")
    print(f"{'区域':<12} {'公告分类':<12} {'数量':<6}")
    print("-" * 35)
    for r in rows:
        print(f"{r[0]:<12} {r[1]:<12} {r[2]:<6}")

    cur.execute("SELECT COUNT(*), COUNT(DISTINCT batch_id) FROM notices WHERE publish_date LIKE '2026%'")
    tot_notices, tot_batches = cur.fetchone()
    print("-" * 35)
    print(f"2026年公告总计: {tot_notices} 条，涉及批次文号: {tot_batches} 个")

    conn.close()

if __name__ == "__main__":
    main()
