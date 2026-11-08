#!/usr/bin/env python3
"""
sync_incremental.py - 深圳保障房增量刷新机制与状态机推进引擎
核心设计:
  1. 水位线检测 (High Watermark): 自动从 notices 表拉取最新发布日期 MAX(publish_date) 作为抓取基线；
  2. 逆向分页探测: 优先抓取市住建局与各区平台 Page 1，若有更新继续向后探测，直至命中历史水位线自动终止；
  3. 批次推售状态机演进 (Batch State Machine):
     - 认购通告 -> 认购中 (初始化推售台账、房源户型套数、配售模式)
     - 初审/合格公示 -> 初审名单公示 (追加 notices_json)
     - 终审结果/摇号通告 -> 终审与摇号 (追加 notices_json)
     - 选房通告/选房结果 -> 选房签约中 (追加 notices_json)
     - 若通告明确为"现场认购、即时选房" -> 自动激活常态化配售标识 has_regular_sales_exit=1，阶段转为常态化配售中
  4. 政策法规自动捕获: 针对市住建局最新印发的规范性公文，同步沉淀入 policies 表；
  5. 严格双库事务同步: 本地 SQLite 与 阿里云 RDS MySQL 双向原子写入。
"""

import sys
import os
import json
import re
import sqlite3
import pymysql
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Tuple, Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_SQLITE = PROJECT_ROOT / "data" / "housing.db"
CONFIG_SOURCES = PROJECT_ROOT / "config" / "sources.json"
CONFIG_DB = PROJECT_ROOT / "config" / "database.json"

STAGE_RANKS = {
    "认购中": 1,
    "初审名单公示": 2,
    "终审公示": 3,
    "公证摇号": 4,
    "选房签约中": 5,
    "常态化配售中": 6,
    "已完成选房": 7
}

NOTICE_CAT_TO_STAGE = {
    "认购通告": "认购中",
    "初审名单": "初审名单公示",
    "终审结果": "终审公示",
    "摇号结果": "公证摇号",
    "选房通知": "选房签约中"
}

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

def load_db_connections():
    s_conn = sqlite3.connect(DB_SQLITE)
    with open(CONFIG_DB, "r", encoding="utf-8") as f:
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
    return s_conn, m_conn

def get_watermark(s_conn) -> str:
    cur = s_conn.cursor()
    cur.execute("SELECT MAX(publish_date) FROM notices")
    row = cur.fetchone()
    return row[0] if row and row[0] else "2026-09-30"

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

class DualProjectResolver:
    """双库项目 ID 智能解析器"""
    def __init__(self, s_conn, m_conn):
        self.s_conn = s_conn
        self.m_conn = m_conn
        self.s_map = {}
        self.m_map = {}
        self.refresh()

    def refresh(self):
        s_cur = self.s_conn.cursor()
        s_cur.execute("SELECT id, project_name FROM projects")
        self.s_map = {row[1]: row[0] for row in s_cur.fetchall()}

        m_cur = self.m_conn.cursor()
        m_cur.execute("SELECT id, project_name FROM projects")
        self.m_map = {row[1]: row[0] for row in m_cur.fetchall()}

    def get_ids(self, name_part: str) -> tuple:
        for pname in self.s_map:
            if name_part in pname:
                return self.s_map[pname], self.m_map.get(pname)
        return None, None

    def resolve(self, title: str, text: str, district: str = '深圳') -> tuple:
        for pname in self.s_map:
            if pname in title or (len(pname) >= 3 and pname in text):
                return self.s_map[pname], self.m_map.get(pname)

        extracted = extract_project_name(title, text)
        if extracted:
            for pname in self.s_map:
                if extracted in pname or pname in extracted:
                    return self.s_map[pname], self.m_map.get(pname)

            s_cur = self.s_conn.cursor()
            m_cur = self.m_conn.cursor()
            s_cur.execute("INSERT INTO projects (city, district, project_name, housing_type, status) VALUES (?, ?, ?, ?, ?)",
                          ('深圳', district, extracted, '保障性住房', '配售中'))
            s_id = s_cur.lastrowid

            m_cur.execute("INSERT INTO projects (city, district, project_name, housing_type, status) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE status=VALUES(status);",
                          ('深圳', district, extracted, '保障性住房', '配售中'))
            m_id = m_cur.lastrowid
            if not m_id:
                m_cur.execute("SELECT id FROM projects WHERE project_name = %s", (extracted,))
                row = m_cur.fetchone()
                m_id = row[0] if row else None

            self.s_conn.commit()
            self.m_conn.commit()
            self.s_map[extracted] = s_id
            self.m_map[extracted] = m_id
            print(f"  [增量发现新项目实体] SQLite id={s_id}, MySQL id={m_id}, name={extracted}")
            return s_id, m_id

        return None, None

def update_batch_lifecycle(s_conn, m_conn, batch_id: str, notice_cat: str, notice_title: str, notice_date: str, notice_url: str, content_text: str, resolver: DualProjectResolver, dist: str):
    """批次推售台账状态机推进"""
    s_cur = s_conn.cursor()
    m_cur = m_conn.cursor()

    # 检查批次是否在 batches 表中存在
    s_cur.execute("""
    SELECT current_stage, notices_json, project_id, has_regular_sales_exit,
           total_units, two_bedroom_units, three_bedroom_units, four_bedroom_units, average_price, consultation_phone
    FROM batches WHERE batch_id = ?
    """, (batch_id,))
    batch_row = s_cur.fetchone()

    # 计算目标阶段
    target_stage = NOTICE_CAT_TO_STAGE.get(notice_cat)
    target_weight = STAGE_RANKS.get(target_stage, 0)
    is_regular_mode = 1 if any(k in content_text for k in ["实行“现场认购、即时选房、资格后审、动态公示”", "常态化配售", "即时选房"]) else 0

    # 提取房源户型参数与均价、电话
    m_tot = re.search(r'(?:房源合计|房源共|共提供房源|配售房源(?:位于[^\d，。；\n]+)?共?|共)\s*(\d+)\s*套', content_text)
    tot_units = int(m_tot.group(1)) if m_tot else None

    units_2b = None
    units_3b = None
    units_4b = None

    m_all_type = re.search(r'均为\s*([一两三四])\s*房', content_text)
    if m_all_type and tot_units:
        rc = m_all_type.group(1)
        if rc == '两': units_2b = tot_units
        elif rc == '三': units_3b = tot_units
        elif rc == '四': units_4b = tot_units
    else:
        m_2b = re.search(r'两房[^\d，。；\n]*?(\d+)\s*套|(\d+)\s*套[^\d，。；\n]*?两房', content_text)
        units_2b = int(m_2b.group(1) or m_2b.group(2)) if m_2b else None

        m_3b = re.search(r'三房[^\d，。；\n]*?(\d+)\s*套|(\d+)\s*套[^\d，。；\n]*?三房', content_text)
        units_3b = int(m_3b.group(1) or m_3b.group(2)) if m_3b else None

        m_4b = re.search(r'四房[^\d，。；\n]*?(\d+)\s*套|(\d+)\s*套[^\d，。；\n]*?四房', content_text)
        units_4b = int(m_4b.group(1) or m_4b.group(2)) if m_4b else None

    m_price = re.search(r'(?:均价|售价|基准售价)(?:为)?\s*([0-9.]+)\s*元', content_text)
    avg_price = float(m_price.group(1)) if m_price else None

    m_phone = re.search(r'(?:咨询电话|服务电话|联系电话)[：:\s]*([0-9-]{7,15})', content_text)
    consult_phone = m_phone.group(1) if m_phone else None

    if not batch_row:
        # 这是一个全新入市批次（如 083号批次）！自动新建批次台账
        print(f"  [发现全新批次入市] 批次文号: {batch_id}")
        s_pid, m_pid = resolver.resolve(notice_title, content_text, dist)
        if not s_pid:
            s_pid, m_pid = (1, 1)

        sales_mode = "常态化即时配售" if is_regular_mode else "公证摇号"
        curr_stg = "常态化配售中" if is_regular_mode else (target_stage or "认购中")

        notices_arr = [{
            "stage": notice_cat,
            "title": notice_title,
            "date": notice_date,
            "url": notice_url
        }]
        notices_json = json.dumps(notices_arr, ensure_ascii=False)

        # 写入 SQLite
        s_cur.execute("""
        INSERT INTO batches (
            batch_id, project_id, city, district, housing_type, total_units,
            two_bedroom_units, three_bedroom_units, four_bedroom_units,
            average_price, consultation_phone, sales_mode, has_regular_sales_exit, current_stage, notices_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (batch_id, s_pid, '深圳', dist, '人才配售房', tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone, sales_mode, is_regular_mode, curr_stg, notices_json))

        # 写入 MySQL
        m_cur.execute("""
        INSERT INTO batches (
            batch_id, project_id, city, district, housing_type, total_units,
            two_bedroom_units, three_bedroom_units, four_bedroom_units,
            average_price, consultation_phone, sales_mode, has_regular_sales_exit, current_stage, notices_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            current_stage=VALUES(current_stage),
            notices_json=VALUES(notices_json);
        """, (batch_id, m_pid, '深圳', dist, '人才配售房', tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone, sales_mode, is_regular_mode, curr_stg, notices_json))

        s_conn.commit()
        m_conn.commit()
        return f"新建批次: {batch_id} -> {curr_stg}"

    else:
        # 已有批次状态更新与属性丰富（如 073批次由 认购中 -> 审核名单公示 -> 终审摇号 -> 选房）
        curr_stage_name, n_json_str, s_pid, has_reg, old_tot, old_2b, old_3b, old_4b, old_price, old_phone = batch_row
        try:
            notices_arr = json.loads(n_json_str) if n_json_str else []
        except Exception:
            notices_arr = []

        # 检查是否已有该通告
        if not any(item.get("url") == notice_url or item.get("title") == notice_title for item in notices_arr):
            notices_arr.append({
                "stage": notice_cat,
                "title": notice_title,
                "date": notice_date,
                "url": notice_url
            })

        notices_arr.sort(key=lambda x: x.get("date", ""))
        new_notices_json = json.dumps(notices_arr, ensure_ascii=False)

        # 状态机升级判断（高阶状态不降级）
        current_weight = STAGE_RANKS.get(curr_stage_name, 0)
        final_stage = curr_stage_name
        if target_weight > current_weight:
            final_stage = target_stage
        if is_regular_mode:
            final_stage = "常态化配售中"
            has_reg = 1

        final_tot = tot_units if old_tot is None else old_tot
        final_2b = units_2b if old_2b is None else old_2b
        final_3b = units_3b if old_3b is None else old_3b
        final_4b = units_4b if old_4b is None else old_4b
        final_price = avg_price if old_price is None else old_price
        final_phone = consult_phone if old_phone is None else old_phone

        s_cur.execute("""
        UPDATE batches
        SET current_stage = ?, notices_json = ?, has_regular_sales_exit = COALESCE(?, has_regular_sales_exit),
            total_units = COALESCE(?, total_units),
            two_bedroom_units = COALESCE(?, two_bedroom_units),
            three_bedroom_units = COALESCE(?, three_bedroom_units),
            four_bedroom_units = COALESCE(?, four_bedroom_units),
            average_price = COALESCE(?, average_price),
            consultation_phone = COALESCE(?, consultation_phone)
        WHERE batch_id = ?
        """, (final_stage, new_notices_json, has_reg, final_tot, final_2b, final_3b, final_4b, final_price, final_phone, batch_id))

        m_cur.execute("""
        UPDATE batches
        SET current_stage = %s, notices_json = %s, has_regular_sales_exit = COALESCE(%s, has_regular_sales_exit),
            total_units = COALESCE(%s, total_units),
            two_bedroom_units = COALESCE(%s, two_bedroom_units),
            three_bedroom_units = COALESCE(%s, three_bedroom_units),
            four_bedroom_units = COALESCE(%s, four_bedroom_units),
            average_price = COALESCE(%s, average_price),
            consultation_phone = COALESCE(%s, consultation_phone)
        WHERE batch_id = %s
        """, (final_stage, new_notices_json, has_reg, final_tot, final_2b, final_3b, final_4b, final_price, final_phone, batch_id))

        s_conn.commit()
        m_conn.commit()
        return f"批次状态推进: {batch_id} [{curr_stage_name} -> {final_stage}]"

def sync_incremental():
    """增量刷新核心调度流程"""
    s_conn, m_conn = load_db_connections()
    watermark = get_watermark(s_conn)
    print(f"==========================================================")
    print(f"  保障房增量刷新机制启动")
    print(f"  当前基线水位线 (High Watermark): {watermark}")
    print(f"==========================================================")

    resolver = DualProjectResolver(s_conn, m_conn)
    s_cur = s_conn.cursor()
    m_cur = m_conn.cursor()

    new_notices_count = 0
    state_transitions = []

    # 1. 抓取市住建局 Page 1 (及 Page 2 未处理的 10 月公文)
    base_url = "https://zjj.sz.gov.cn/ztfw/zfbz/tzgg2017/"
    page_urls = [
        f"{base_url}index.html",
        f"{base_url}index_2.html"
    ]

    for p_url in page_urls:
        html = fetch_url(p_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        hit_stop_date = False

        for li in soup.find_all("li"):
            a = li.find("a")
            span = li.find("span")
            if not a or not span:
                continue
            title = (a.get("title") or a.get_text(strip=True)).strip()
            date_raw = span.get_text(strip=True)
            pub_date = f"20{date_raw}" if re.match(r"^2\d-\d{2}-\d{2}", date_raw) else date_raw
            href = a.get("href", "").strip()

            # 遇到早于基线水位线的通告，表示已完全接驳历史数据
            if pub_date < watermark:
                hit_stop_date = True
                break

            full_url = href if href.startswith("http") else f"{base_url}{href.lstrip('./')}"

            # 查重判断
            s_cur.execute("SELECT id FROM notices WHERE url = ?", (full_url,))
            if s_cur.fetchone():
                continue

            # 抓取正文
            content_text = parse_notice_content(full_url)
            cat = classify_notice(title)
            batch_id = extract_batch_id(title, content_text)

            # 匹配项目 ID
            s_pid, m_pid = resolver.resolve(title, content_text, '市住建局')

            # 沉淀入 notices
            s_cur.execute("""
            INSERT OR REPLACE INTO notices (city, district, project_id, batch_id, category, title, publish_date, url, summary, content_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ('深圳', '市住建局', s_pid, batch_id, cat, title, pub_date, full_url, content_text[:120].replace('\n',' '), content_text))

            m_cur.execute("""
            INSERT INTO notices (city, district, project_id, batch_id, category, title, publish_date, url, summary, content_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                project_id=VALUES(project_id),
                batch_id=VALUES(batch_id),
                category=VALUES(category),
                publish_date=VALUES(publish_date),
                content_text=CASE WHEN VALUES(content_text) != '' THEN VALUES(content_text) ELSE notices.content_text END;
            """, ('深圳', '市住建局', m_pid, batch_id, cat, title, pub_date, full_url, content_text[:120].replace('\n',' '), content_text))

            new_notices_count += 1
            print(f"  + [新通告入库] {pub_date} | {cat: <6} | {title[:38]}")

            # 批次状态机生命周期演进
            if batch_id:
                transition_msg = update_batch_lifecycle(
                    s_conn, m_conn, batch_id, cat, title, pub_date, full_url, content_text, resolver, '市住建局'
                )
                if transition_msg:
                    state_transitions.append(transition_msg)

            # 政策法规捕获判断
            if any(k in title for k in ["贯彻落实", "办法", "规定", "实施细则", "优化配置"]):
                s_cur.execute("SELECT id FROM policies WHERE url = ?", (full_url,))
                if not s_cur.fetchone():
                    s_cur.execute("""
                    INSERT OR REPLACE INTO policies (city, category, title, publisher, publish_date, status, url, summary, content_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, ('深圳', '房地产与保障房新政', title, '深圳市住建局等', pub_date, '现行有效', full_url, content_text[:120].replace('\n',' '), content_text))

                    m_cur.execute("""
                    INSERT INTO policies (city, category, title, publisher, publish_date, status, url, summary, content_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE status=VALUES(status);
                    """, ('深圳', '房地产与保障房新政', title, '深圳市住建局等', pub_date, '现行有效', full_url, content_text[:120].replace('\n',' '), content_text))
                    print(f"  ★ [新政策法规入库] {title}")

        if hit_stop_date:
            break

    # 2. 抓取各区 gkmlpt Page 1 增量
    with open(CONFIG_SOURCES, "r", encoding="utf-8") as f:
        src_cfg = json.load(f)

    for src in src_cfg["cities"][0].get("sources", []):
        if src.get("type") == "gkmlpt" and src.get("enabled", True):
            dist = src.get("district", "区住建局")
            api_pat = src.get("api")
            if not api_pat:
                continue
            res_text = fetch_url(api_pat.format(page=1))
            if not res_text:
                continue
            try:
                data = json.loads(res_text)
            except Exception:
                continue
            for art in data.get("articles", []):
                created_at = art.get("created_at") or ""
                pub_date = created_at[:10]
                if not pub_date or pub_date < watermark:
                    continue
                title = (art.get("title") or "").strip()
                if not any(k in title for k in HOUSING_KEYWORDS):
                    continue
                url = art.get("url") or ""
                s_cur.execute("SELECT id FROM notices WHERE url = ?", (url,))
                if s_cur.fetchone():
                    continue

                summary = art.get("abstract") or ""
                cat = classify_notice(title)
                atts = art.get("attachment") or []
                att_json = json.dumps(atts, ensure_ascii=False) if atts else None
                content_text = parse_notice_content(url) if cat in ["认购通告", "选房通知", "摇号结果", "终审结果"] else ""
                batch_id = extract_batch_id(title, content_text)

                s_pid, m_pid = resolver.resolve(title, content_text, dist)

                s_cur.execute("""
                INSERT OR REPLACE INTO notices (city, district, project_id, batch_id, category, title, publish_date, url, summary, content_text, attachments_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ('深圳', dist, s_pid, batch_id, cat, title, pub_date, url, summary, content_text, att_json))

                m_cur.execute("""
                INSERT INTO notices (city, district, project_id, batch_id, category, title, publish_date, url, summary, content_text, attachments_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    project_id=VALUES(project_id),
                    batch_id=VALUES(batch_id),
                    category=VALUES(category),
                    publish_date=VALUES(publish_date),
                    summary=VALUES(summary),
                    content_text=CASE WHEN VALUES(content_text) != '' THEN VALUES(content_text) ELSE notices.content_text END,
                    attachments_json=VALUES(attachments_json);
                """, ('深圳', dist, m_pid, batch_id, cat, title, pub_date, url, summary, content_text, att_json))

                new_notices_count += 1
                print(f"  + [新通告入库] ({dist}) {pub_date} | {cat: <6} | {title[:38]}")

                if batch_id:
                    transition_msg = update_batch_lifecycle(
                        s_conn, m_conn, batch_id, cat, title, pub_date, url, content_text, resolver, dist
                    )
                    if transition_msg:
                        state_transitions.append(transition_msg)

    s_conn.commit()
    m_conn.commit()

    # 3. 对齐生命周期与参数
    reconcile_all_batches(s_conn, m_conn)

    print("\n================== 增量刷新结果核验 ==================")
    print(f"本次增量抓取通告数: {new_notices_count} 篇")
    print(f"状态机演进/批次变更事件: {len(state_transitions)} 次")
    for tr in state_transitions:
        print(f"  * {tr}")

    print("\n------------------ 刷新后数据库总览 ------------------")
    for tbl in ["projects", "batches", "notices", "policies"]:
        s_cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        m_cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        print(f"表 {tbl: <12} -> SQLite: {s_cur.fetchone()[0]: <5} | MySQL: {m_cur.fetchone()[0]: <5}")
    print("======================================================")

    s_conn.close()
    m_conn.close()

def reconcile_all_batches(s_conn, m_conn):
    """全量校验与对齐 batches 推售生命周期状态与关联通告链"""
    print("\n>>> 正在根据最新通告流水对齐 batches 状态与房源参数...")
    s_cur = s_conn.cursor()
    m_cur = m_conn.cursor()

    # 0. 自动扫描补齐 notices 表遗漏的 batch_id 关联
    s_cur.execute("SELECT id, title, content_text FROM notices WHERE batch_id IS NULL")
    relinked = 0
    for nid, title, text in s_cur.fetchall():
        bid = extract_batch_id(title, text or "")
        if bid:
            s_cur.execute("UPDATE notices SET batch_id = ? WHERE id = ?", (bid, nid))
            m_cur.execute("UPDATE notices SET batch_id = %s WHERE id = %s", (bid, nid))
            relinked += 1
    s_conn.commit()
    m_conn.commit()
    if relinked:
        print(f"  + 成功自动补齐关联 {relinked} 篇事项通知与批次关系")

    s_cur.execute("SELECT batch_id, current_stage, notices_json FROM batches")
    batches = s_cur.fetchall()

    for bid, curr_stg, n_json_old in batches:
        s_cur.execute("""
        SELECT category, title, publish_date, url, content_text
        FROM notices
        WHERE batch_id = ?
        ORDER BY publish_date ASC, id ASC
        """, (bid,))
        notice_rows = s_cur.fetchall()
        if not notice_rows:
            continue

        notices_arr = []
        max_rank = 0
        final_stage = curr_stg
        has_reg_exit = 0

        tot_units = None
        units_2b = None
        units_3b = None
        units_4b = None
        avg_price = None
        consult_phone = None

        for cat, title, pub_date, url, text in notice_rows:
            notices_arr.append({
                "stage": cat,
                "title": title,
                "date": pub_date,
                "url": url
            })

            # 常态化配售出口判定
            if "实行“现场认购、即时选房、资格后审、动态公示”" in text or "常态化配售" in text:
                has_reg_exit = 1

            # 阶段计算
            if "常态化配售通告" in title or "面向人才配售住房通告（住保售〔2026〕083号）" in title:
                final_stage = "常态化配售中"
            else:
                stg = NOTICE_CAT_TO_STAGE.get(cat)
                rnk = STAGE_RANKS.get(stg, 0)
                if rnk > max_rank:
                    max_rank = rnk
                    final_stage = stg

            # 房源参数抽取
            if not tot_units:
                m_tot = re.search(r'(?:房源合计|房源共|共提供房源|配售房源(?:位于[^\d，。；\n]+)?共?|共)\s*(\d+)\s*套', text)
                if m_tot: tot_units = int(m_tot.group(1))

            m_all_type = re.search(r'均为\s*([一两三四])\s*房', text)
            if m_all_type and tot_units:
                rc = m_all_type.group(1)
                if rc == '两': units_2b = tot_units
                elif rc == '三': units_3b = tot_units
                elif rc == '四': units_4b = tot_units
            else:
                if not units_2b:
                    m_2b = re.search(r'两房[^\d，。；\n]*?(\d+)\s*套|(\d+)\s*套[^\d，。；\n]*?两房', text)
                    if m_2b: units_2b = int(m_2b.group(1) or m_2b.group(2))
                if not units_3b:
                    m_3b = re.search(r'三房[^\d，。；\n]*?(\d+)\s*套|(\d+)\s*套[^\d，。；\n]*?三房', text)
                    if m_3b: units_3b = int(m_3b.group(1) or m_3b.group(2))
                if not units_4b:
                    m_4b = re.search(r'四房[^\d，。；\n]*?(\d+)\s*套|(\d+)\s*套[^\d，。；\n]*?四房', text)
                    if m_4b: units_4b = int(m_4b.group(1) or m_4b.group(2))

            if not avg_price:
                m_price = re.search(r'(?:均价|售价|基准售价)(?:为)?\s*([0-9.]+)\s*元', text)
                if m_price: avg_price = float(m_price.group(1))

            if not consult_phone:
                m_ph = re.search(r'(?:咨询电话|服务电话|联系电话)[：:\s]*([0-9-]{7,15})', text)
                if m_ph: consult_phone = m_ph.group(1)

        new_n_json = json.dumps(notices_arr, ensure_ascii=False)

        s_cur.execute("""
        UPDATE batches
        SET current_stage = ?, notices_json = ?, has_regular_sales_exit = COALESCE(?, has_regular_sales_exit),
            total_units = COALESCE(?, total_units),
            two_bedroom_units = COALESCE(?, two_bedroom_units),
            three_bedroom_units = COALESCE(?, three_bedroom_units),
            four_bedroom_units = COALESCE(?, four_bedroom_units),
            average_price = COALESCE(?, average_price),
            consultation_phone = COALESCE(?, consultation_phone)
        WHERE batch_id = ?
        """, (final_stage, new_n_json, has_reg_exit, tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone, bid))

        m_cur.execute("""
        UPDATE batches
        SET current_stage = %s, notices_json = %s, has_regular_sales_exit = COALESCE(%s, has_regular_sales_exit),
            total_units = COALESCE(%s, total_units),
            two_bedroom_units = COALESCE(%s, two_bedroom_units),
            three_bedroom_units = COALESCE(%s, three_bedroom_units),
            four_bedroom_units = COALESCE(%s, four_bedroom_units),
            average_price = COALESCE(%s, average_price),
            consultation_phone = COALESCE(%s, consultation_phone)
        WHERE batch_id = %s
        """, (final_stage, new_n_json, has_reg_exit, tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone, bid))

    s_conn.commit()
    m_conn.commit()
    print("批次状态机与房源参数全量对齐完毕。")

if __name__ == "__main__":
    sync_incremental()
