#!/usr/bin/env python3
"""
sync_historical.py - 自包含保障房历史基线数据与项目大盘建档工具 (纯 SQLite 独立版)
"""

import sys
import json
import re
import sqlite3
import subprocess
import argparse
from pathlib import Path
from bs4 import BeautifulSoup

SKILL_ROOT = Path(__file__).resolve().parent.parent
DB_SQLITE = SKILL_ROOT / "data" / "housing.db"
CONFIG_SOURCES = SKILL_ROOT / "config" / "sources.json"

CUTOFF_DATE = "2026-10-01"

HOUSING_KEYWORDS = [
    "人才", "安居", "共有产权", "公租房", "公共租赁", "保障性",
    "配售", "配租", "摇号", "选房", "认购", "合格名单", "终审",
    "初审", "退房", "房源", "住房保障"
]

def fetch_url(url: str, timeout: int = 8) -> str:
    cmd = [
        "curl", "-k", "-s", "-L",
        "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--connect-timeout", str(timeout),
        "--max-time", str(timeout + 4),
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, check=True)
        return res.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def classify_notice(title: str) -> str:
    if any(k in title for k in ["配售通告", "配售住房通告", "认购通告", "配租通告", "配售通知"]):
        return "认购通告"
    if any(k in title for k in ["初审", "初核", "认购申请家庭名单", "合格名单公示", "初审合格", "审核结果公示"]):
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

def extract_batch_id(title: str, text: str = "") -> str:
    combined = title + " " + text[:500]
    m = re.search(r"住保售〔(\d{4})〕(\d+)号(?:批次)?", combined)
    if m:
        return f"住保售〔{m.group(1)}〕{m.group(2)}号批次"
    m = re.search(r"（(\d{4})(\d{3,4})-\d+.*?）", combined)
    if m:
        return f"住保售〔{m.group(1)}〕{m.group(2)}号批次"
    m = re.search(r"（(\d{7,8}-\d+|\d{7,8})批次）", combined)
    if m:
        return f"{m.group(1)}批次"
    m = re.search(r"〔(\d{4})〕(\d+)号", combined)
    if m:
        return f"〔{m.group(1)}〕{m.group(2)}号"
    return None

def extract_project_name(title: str, text: str) -> str:
    patterns = [
        r'现就\s*([A-Za-z0-9\u4e00-\u9fa5]{2,15}(?:花园|园|苑|府|城|大厦|嘉园|家园|雅苑|名苑|华府|公寓|公馆))项目',
        r'开展\s*([A-Za-z0-9\u4e00-\u9fa5]{2,15}(?:花园|园|苑|府|城|大厦|嘉园|家园|雅苑|名苑|华府|公寓|公馆))项目',
        r'([A-Za-z0-9\u4e00-\u9fa5]{2,15}(?:花园|园|苑|府|城|大厦|嘉园|家园|雅苑|名苑|华府|公寓|公馆))项目(?:住房|安居型商品房|人才住房)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            clean = m.group(1).strip()
            clean = re.sub(r'^\d+年\d+月\d+日(?:上午|下午)?', '', clean)
            if not any(bad in clean for bad in ['深圳市', '商品房', '保障性', '住房保障', '安居型', '公证摇号']):
                return clean
    return None

def parse_notice_content(url: str) -> str:
    html = fetch_url(url)
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
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

def sync_projects_master(conn: sqlite3.Connection, city: str = "深圳"):
    print(f"[*] 正在初始化 {city} projects 物理资产台账...")
    cur = conn.cursor()
    cmd = 'curl -k -s -L -A "Mozilla/5.0" "https://zjj.sz.gov.cn/gkmlpt/content/12/12782/post_12782208.html"'
    res = subprocess.run(cmd, shell=True, capture_output=True)
    import io, pdfplumber
    inserted = 0

    try:
        with pdfplumber.open(io.BytesIO(res.stdout)) as pdf:
            # 储备计划表
            for row in pdf.pages[5].extract_tables()[0][1:]:
                if len(row) >= 5 and row[0] and row[0].isdigit():
                    seq, resp, name, loc, area, units = row[:6] if len(row)>=6 else (row[0], row[1], row[2], row[3], row[4], 0)
                    dist = resp.replace('政府', '').replace('管委会', '').strip()
                    try: area_val = float(area.replace(' ', ''))
                    except: area_val = None
                    try: units_val = int(units.replace(' ', ''))
                    except: units_val = None
                    clean_name = name.replace('\n', '').strip()

                    cur.execute("""
                    INSERT OR IGNORE INTO projects (city, district, project_name, developer, housing_type, total_planned_units, planned_area, address, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (city, dist, clean_name, resp.replace('\n', '').strip(), '保障性住房', units_val, area_val, loc.replace('\n', '').strip(), '规划储备'))
                    inserted += 1

            # 竣工/在建计划表
            for p_idx in [6, 7, 8]:
                for row in pdf.pages[p_idx].extract_tables()[0][1:]:
                    if len(row) >= 5 and row[0] and row[0].isdigit():
                        seq, resp, name, dev, area, units = row[:6]
                        dist = resp.replace('政府', '').replace('管委会', '').strip()
                        try: area_val = float(area.replace(' ', ''))
                        except: area_val = None
                        try: units_val = int(units.replace(' ', ''))
                        except: units_val = None
                        clean_name = name.replace('\n', '').strip()

                        cur.execute("""
                        INSERT OR IGNORE INTO projects (city, district, project_name, developer, housing_type, total_planned_units, planned_area, address, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (city, dist, clean_name, dev.replace('\n', '').strip(), '保障性住房', units_val, area_val, None, '计划竣工/在建'))
                        inserted += 1
    except Exception as e:
        print(f"解析年度计划 PDF 提示: {e}")

    classic_projects = [
        (city, '罗湖区', '畔溪悦府', '深圳市罗湖人才安居有限公司', '人才配售房', 306, 3.2, '罗湖区莲塘街道', '配售中'),
        (city, '龙华区', '安居华越龙苑', '深圳市安居集团有限公司', '人才配售房', 1350, 15.0, '龙华区民治街道新牛社区', '配售中'),
        (city, '南山区', '深铁熙府', '深圳市地铁集团有限公司', '人才配售房', 2100, 16.6, '南山区兴海大道5号', '配售中'),
        (city, '宝安区', '深铁璟城', '深圳市地铁集团有限公司', '人才配售房', 2480, 18.8, '宝安区松岗街道', '配售中'),
        (city, '光明区', '润珑苑', '深圳市润宏房地产有限公司', '人才配售房', 2705, 20.4, '光明区凤凰街道', '配售中'),
        (city, '南山区', '山樾湾花园', '深圳市新建投资发展有限公司', '共有产权住房', 4900, 36.7, '南山区前海前湾片区', '配售中')
    ]
    for p in classic_projects:
        cur.execute("""
        INSERT OR REPLACE INTO projects (city, district, project_name, developer, housing_type, total_planned_units, planned_area, address, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, p)

    conn.commit()
    print(f"[SUCCESS] 物理项目大盘初始化完成，当前库内项目数: {inserted + len(classic_projects)}")

def sync_historical(city: str = "深圳"):
    conn = sqlite3.connect(DB_SQLITE)
    sync_projects_master(conn, city)
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自包含历史大盘基线构建工具")
    parser.add_argument("--city", default="深圳", help="目标城市名称，默认: 深圳")
    args = parser.parse_args()
    sync_historical(city=args.city)
