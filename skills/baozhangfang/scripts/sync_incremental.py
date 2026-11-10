#!/usr/bin/env python3
"""
sync_incremental.py - 自包含保障房增量刷新机制与状态机推进引擎 (纯 SQLite 独立版)
核心流程:
  1. 水位线检测: 自动读取 notices 表最新发布日期 MAX(publish_date) 作为抓取分界；
  2. 逆向分页探测: 扫描市级与各辖区平台 Page 1，遇到水位线历史公文立即触发熔断；
  3. 批次推售状态机演进:
     - 认购通告 -> 认购中
     - 初审/核查名单 -> 初审名单公示
     - 终审结果/摇号通告 -> 终审与公证摇号
     - 选房通告/选房结果 -> 选房签约中
     - 现场认购/常态化即时配售 -> 常态化配售中 (标记 has_regular_sales_exit=1)
  4. 自动解析房源户型套数 (两房/三房/四房独立列)、配售均价、咨询电话、接待中心；
  5. 政策法规库自动捕获沉淀至 policies 表。
"""

import sys
import os
import json
import re
import sqlite3
import subprocess
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Tuple, Dict, Any, List

SKILL_ROOT = Path(__file__).resolve().parent.parent
from db import get_db_path  # 运行库路径（首次使用时自动由 seed.sql 自举）
CONFIG_SOURCES = SKILL_ROOT / "config" / "sources.json"

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

def get_watermark(conn: sqlite3.Connection, city: str = "深圳") -> str:
    cur = conn.cursor()
    cur.execute("SELECT MAX(publish_date) FROM notices WHERE city = ?", (city,))
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

class ProjectResolver:
    """本地项目 ID 智能解析器"""
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.p_map = {}
        self.refresh()

    def refresh(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, project_name FROM projects")
        self.p_map = {row[1]: row[0] for row in cur.fetchall()}

    def resolve(self, title: str, text: str, city: str = "深圳", district: str = None) -> int:
        for pname in self.p_map:
            if pname in title or (len(pname) >= 3 and pname in text):
                return self.p_map[pname]

        extracted = extract_project_name(title, text)
        if extracted:
            for pname in self.p_map:
                if extracted in pname or pname in extracted:
                    return self.p_map[pname]

            cur = self.conn.cursor()
            cur.execute("""
            INSERT INTO projects (city, district, project_name, housing_type, status)
            VALUES (?, ?, ?, ?, ?)
            """, (city, district, extracted, '保障性住房', '配售中'))
            self.conn.commit()
            new_id = cur.lastrowid
            self.p_map[extracted] = new_id
            print(f"  [发现新项目实体入库] ID={new_id}, 项目名称={extracted}")
            return new_id

        return None

def update_batch_lifecycle(conn: sqlite3.Connection, batch_id: str, notice_cat: str, notice_title: str, notice_date: str, notice_url: str, content_text: str, resolver: ProjectResolver, city: str, dist: str):
    """推售批次生命周期流转与属性丰富"""
    cur = conn.cursor()
    cur.execute("""
    SELECT current_stage, notices_json, project_id, has_regular_sales_exit,
           total_units, two_bedroom_units, three_bedroom_units, four_bedroom_units, average_price, consultation_phone
    FROM batches WHERE batch_id = ?
    """, (batch_id,))
    batch_row = cur.fetchone()

    target_stage = NOTICE_CAT_TO_STAGE.get(notice_cat)
    target_weight = STAGE_RANKS.get(target_stage, 0)
    is_regular_mode = 1 if any(k in content_text for k in ["实行“现场认购、即时选房、资格后审、动态公示”", "常态化配售", "即时选房"]) else 0

    # 提取房源属性
    m_tot = re.search(r'(?:房源合计|房源共|共提供房源|配售房源(?:位于[^\d，。；\n]+)?共?|共)\s*(\d+)\s*套', content_text)
    tot_units = int(m_tot.group(1)) if m_tot else None

    units_2b, units_3b, units_4b = None, None, None
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
        # 新批次建档
        pid = resolver.resolve(notice_title, content_text, city, dist) or 1
        sales_mode = "常态化即时配售" if is_regular_mode else "公证摇号"
        curr_stg = "常态化配售中" if is_regular_mode else (target_stage or "认购中")
        notices_arr = [{"stage": notice_cat, "title": notice_title, "date": notice_date, "url": notice_url}]
        notices_json = json.dumps(notices_arr, ensure_ascii=False)

        cur.execute("""
        INSERT INTO batches (
            batch_id, project_id, city, district, housing_type, total_units,
            two_bedroom_units, three_bedroom_units, four_bedroom_units,
            average_price, consultation_phone, sales_mode, has_regular_sales_exit, current_stage, notices_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (batch_id, pid, city, dist, '保障性住房', tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone, sales_mode, is_regular_mode, curr_stg, notices_json))
        conn.commit()
        return f"新建批次: {batch_id} -> {curr_stg}"

    else:
        # 已有批次升级
        curr_stage_name, n_json_str, pid, has_reg, old_tot, old_2b, old_3b, old_4b, old_price, old_phone = batch_row
        try:
            notices_arr = json.loads(n_json_str) if n_json_str else []
        except Exception:
            notices_arr = []

        if not any(item.get("url") == notice_url or item.get("title") == notice_title for item in notices_arr):
            notices_arr.append({"stage": notice_cat, "title": notice_title, "date": notice_date, "url": notice_url})

        notices_arr.sort(key=lambda x: x.get("date", ""))
        new_notices_json = json.dumps(notices_arr, ensure_ascii=False)

        current_weight = STAGE_RANKS.get(curr_stage_name, 0)
        final_stage = curr_stage_name
        if target_weight > current_weight:
            final_stage = target_stage
        if is_regular_mode:
            final_stage = "常态化配售中"
            has_reg = 1

        cur.execute("""
        UPDATE batches
        SET current_stage = ?, notices_json = ?, has_regular_sales_exit = COALESCE(?, has_regular_sales_exit),
            total_units = COALESCE(?, total_units),
            two_bedroom_units = COALESCE(?, two_bedroom_units),
            three_bedroom_units = COALESCE(?, three_bedroom_units),
            four_bedroom_units = COALESCE(?, four_bedroom_units),
            average_price = COALESCE(?, average_price),
            consultation_phone = COALESCE(?, consultation_phone)
        WHERE batch_id = ?
        """, (final_stage, new_notices_json, has_reg, tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone, batch_id))
        conn.commit()
        return f"批次状态推进: {batch_id} [{curr_stage_name} -> {final_stage}]"

def reconcile_all_batches(conn: sqlite3.Connection):
    """全局巡检对齐所有批次状态与关联公文链"""
    print("\n>>> 正在根据通告流水全量对齐批次生命周期与房源属性...")
    cur = conn.cursor()

    # 1. 扫描补全缺失 batch_id 的通知
    cur.execute("SELECT id, title, content_text FROM notices WHERE batch_id IS NULL")
    relinked = 0
    for nid, title, text in cur.fetchall():
        bid = extract_batch_id(title, text or "")
        if bid:
            cur.execute("UPDATE notices SET batch_id = ? WHERE id = ?", (bid, nid))
            relinked += 1
    conn.commit()
    if relinked:
        print(f"  + 成功自动挂载 {relinked} 篇事项通知与批次关联")

    # 2. 遍历所有批次重新校验阶段与户型套数
    cur.execute("SELECT batch_id, current_stage, notices_json FROM batches")
    batches = cur.fetchall()

    for bid, curr_stg, _ in batches:
        cur.execute("""
        SELECT category, title, publish_date, url, content_text
        FROM notices WHERE batch_id = ? ORDER BY publish_date ASC, id ASC
        """, (bid,))
        rows = cur.fetchall()
        if not rows: continue

        notices_arr = []
        max_rank = 0
        final_stage = curr_stg
        has_reg_exit = 0
        tot_units, units_2b, units_3b, units_4b, avg_price, consult_phone = None, None, None, None, None, None

        for cat, title, pub_date, url, text in rows:
            notices_arr.append({"stage": cat, "title": title, "date": pub_date, "url": url})
            if "实行“现场认购、即时选房、资格后审、动态公示”" in text or "常态化配售" in text:
                has_reg_exit = 1

            if "常态化配售通告" in title or "面向人才配售住房通告（住保售〔2026〕083号）" in title:
                final_stage = "常态化配售中"
            else:
                stg = NOTICE_CAT_TO_STAGE.get(cat)
                rnk = STAGE_RANKS.get(stg, 0)
                if rnk > max_rank:
                    max_rank = rnk
                    final_stage = stg

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
        cur.execute("""
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

    conn.commit()
    print("批次状态机与房源参数全量对齐完毕。")

def sync_incremental(target_city: str = "深圳"):
    """增量刷新调度核心"""
    conn = sqlite3.connect(get_db_path())
    watermark = get_watermark(conn, target_city)
    print(f"==========================================================")
    print(f"  保障房增量刷新机制启动 (城市: {target_city})")
    print(f"  当前基线水位线 (High Watermark): {watermark}")
    print(f"==========================================================")

    resolver = ProjectResolver(conn)
    cur = conn.cursor()
    new_notices_count = 0
    state_transitions = []

    # 1. 抓取市局专题页面
    base_url = "https://zjj.sz.gov.cn/ztfw/zfbz/tzgg2017/"
    page_urls = [f"{base_url}index.html", f"{base_url}index_2.html"]

    for p_url in page_urls:
        html = fetch_url(p_url)
        if not html: continue
        soup = BeautifulSoup(html, "html.parser")
        hit_stop_date = False

        for li in soup.find_all("li"):
            a = li.find("a")
            span = li.find("span")
            if not a or not span: continue

            title = (a.get("title") or a.get_text(strip=True)).strip()
            date_raw = span.get_text(strip=True)
            pub_date = f"20{date_raw}" if re.match(r"^2\d-\d{2}-\d{2}", date_raw) else date_raw
            href = a.get("href", "").strip()

            if pub_date < watermark:
                hit_stop_date = True
                break

            full_url = href if href.startswith("http") else f"{base_url}{href.lstrip('./')}"
            cur.execute("SELECT id FROM notices WHERE url = ?", (full_url,))
            if cur.fetchone(): continue

            content_text = parse_notice_content(full_url)
            cat = classify_notice(title)
            batch_id = extract_batch_id(title, content_text)
            pid = resolver.resolve(title, content_text, target_city, '市住建局')

            cur.execute("""
            INSERT OR REPLACE INTO notices (city, district, project_id, batch_id, category, title, publish_date, url, summary, content_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (target_city, '市住建局', pid, batch_id, cat, title, pub_date, full_url, content_text[:120].replace('\n',' '), content_text))
            new_notices_count += 1
            print(f"  + [新通告入库] {pub_date} | {cat: <6} | {title[:38]}")

            if batch_id:
                t_msg = update_batch_lifecycle(conn, batch_id, cat, title, pub_date, full_url, content_text, resolver, target_city, '市住建局')
                if t_msg: state_transitions.append(t_msg)

            if any(k in title for k in ["贯彻落实", "办法", "规定", "实施细则", "优化配置"]):
                cur.execute("SELECT id FROM policies WHERE url = ?", (full_url,))
                if not cur.fetchone():
                    cur.execute("""
                    INSERT OR REPLACE INTO policies (city, category, title, publisher, publish_date, status, url, summary, content_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (target_city, '房地产与保障房新政', title, '深圳市住建局等', pub_date, '现行有效', full_url, content_text[:120].replace('\n',' '), content_text))
                    print(f"  ★ [新政策法规入库] {title}")

        if hit_stop_date: break

    # 2. 抓取区级公开平台
    if CONFIG_SOURCES.exists():
        with open(CONFIG_SOURCES, "r", encoding="utf-8") as f:
            src_cfg = json.load(f)

        for c_data in src_cfg.get("cities", []):
            if c_data.get("city_name") == target_city or c_data.get("city_id") == target_city:
                for src in c_data.get("sources", []):
                    if src.get("type") == "gkmlpt" and src.get("enabled", True):
                        dist = src.get("district", "区住建局")
                        api_pat = src.get("api")
                        if not api_pat: continue
                        res_text = fetch_url(api_pat.format(page=1))
                        if not res_text: continue
                        try:
                            data = json.loads(res_text)
                        except Exception: continue

                        for art in data.get("articles", []):
                            pub_date = (art.get("created_at") or "")[:10]
                            if not pub_date or pub_date < watermark: continue
                            title = (art.get("title") or "").strip()
                            if not any(k in title for k in HOUSING_KEYWORDS): continue
                            url = art.get("url") or ""
                            cur.execute("SELECT id FROM notices WHERE url = ?", (url,))
                            if cur.fetchone(): continue

                            summary = art.get("abstract") or ""
                            cat = classify_notice(title)
                            atts = art.get("attachment") or []
                            att_json = json.dumps(atts, ensure_ascii=False) if atts else None
                            content_text = parse_notice_content(url) if cat in ["认购通告", "选房通知", "摇号结果", "终审结果"] else ""
                            batch_id = extract_batch_id(title, content_text)
                            pid = resolver.resolve(title, content_text, target_city, dist)

                            cur.execute("""
                            INSERT OR REPLACE INTO notices (city, district, project_id, batch_id, category, title, publish_date, url, summary, content_text, attachments_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (target_city, dist, pid, batch_id, cat, title, pub_date, url, summary, content_text, att_json))
                            new_notices_count += 1
                            print(f"  + [新通告入库] ({dist}) {pub_date} | {cat: <6} | {title[:38]}")

                            if batch_id:
                                t_msg = update_batch_lifecycle(conn, batch_id, cat, title, pub_date, url, content_text, resolver, target_city, dist)
                                if t_msg: state_transitions.append(t_msg)

    conn.commit()

    # 3. 执行对齐与总览
    reconcile_all_batches(conn)

    print("\n================== 增量刷新结果核验 ==================")
    print(f"本次增量抓取通告数: {new_notices_count} 篇")
    print(f"状态机演进/批次变更事件: {len(state_transitions)} 次")
    for tr in state_transitions:
        print(f"  * {tr}")

    print("\n------------------ 数据库当前总览 ------------------")
    for tbl in ["projects", "batches", "notices", "policies"]:
        cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE city = ?", (target_city,))
        print(f"表 {tbl: <12} (城市: {target_city}) -> {cur.fetchone()[0]: <5} 行")
    print("======================================================")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自包含保障房增量刷新引擎")
    parser.add_argument("--city", default="深圳", help="目标城市名称，默认: 深圳")
    args = parser.parse_args()
    sync_incremental(target_city=args.city)
