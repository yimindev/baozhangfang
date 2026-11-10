#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保障房认购名单 PDF 结构化解析工具
支持单文件/多文件/目录批量解析，输出格式支持 CSV、Excel (.xlsx)、JSON 及 SQLite 数据库。
"""

import os
import re
import sys
import json
import glob
import sqlite3
import argparse
from typing import List, Dict, Any, Optional

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


ROLES = ['主申请人', '配偶', '未成年子女', '父母', '成年子女']
ROLE_PATTERN = '|'.join(ROLES)

# 正则匹配成员行: (seq)? (code)? 姓名 证件号 人员类别 剩余内容
MEMBER_RE = re.compile(
    r'^(?:(?P<seq>\d+)\s+)?(?:(?P<code>SQ\d+)\s+)?(?P<name>[A-Za-z\u4e00-\u9fa5*·]+)\s+(?P<id_card>[A-Za-z0-9*·]{8,24})\s+(?P<role>'
    + ROLE_PATTERN
    + r')\s*(?P<rest>.*)$'
)

# 剩余内容拆解: 意向 队列 人才类型 备注
REST_RE = re.compile(r'^(.*?)\s+(第[一二三四]队列)(?:\s+(.*))?$')


def extract_batch_and_type(filename: str) -> Dict[str, str]:
    """从文件名或通告标题推测批次、户型和队列"""
    basename = os.path.basename(filename)
    batch_match = re.search(r'〔?(\d{4})〕?(\d+)号批次', basename)
    batch = f"{batch_match.group(1)}年第{batch_match.group(2)}批次" if batch_match else "未知批次"

    house_type = "两房" if "两房" in basename else ("三房" if "三房" in basename else "未知户型")
    queue_match = re.search(r'(第[一二三四]队列)', basename)
    queue = queue_match.group(1) if queue_match else ""

    return {
        "batch": batch,
        "house_type": house_type,
        "queue": queue,
        "source_file": basename
    }


def parse_pdf_file(filepath: str) -> List[Dict[str, Any]]:
    """
    解析单个 PDF 文件，提取全部家庭成员及家庭维度的完整信息
    返回结构化的成员记录列表（含家庭与队列信息）
    """
    if not pypdf:
        raise RuntimeError("pypdf 未安装，请先执行: pip install pypdf")

    file_meta = extract_batch_and_type(filepath)
    reader = pypdf.PdfReader(filepath)

    cur_seq: Optional[int] = None
    cur_code: Optional[str] = None
    records: List[Dict[str, Any]] = []

    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        for line in lines:
            # 过滤页眉页脚
            if re.search(r'第\s*\d+\s*页[，,]\s*共\s*\d+\s*页', line):
                continue
            if '序号' in line and '认购编号' in line:
                continue
            if line.startswith('附件') or ('批次' in line and '名单' in line and '队列' not in line):
                continue

            # 处理独立成行的 序号 + 认购编号 (例如跨页或多人员首行)
            m_code = re.match(r'^(\d+)\s+(SQ\d+)$', line)
            if m_code:
                cur_seq = int(m_code.group(1))
                cur_code = m_code.group(2)
                continue

            # 处理成员数据行
            m_member = MEMBER_RE.search(line)
            if m_member:
                d = m_member.groupdict()
                if d['seq']:
                    cur_seq = int(d['seq'])
                if d['code']:
                    cur_code = d['code']

                rest = (d['rest'] or '').strip()
                m_rest = REST_RE.match(rest)
                if m_rest:
                    intention = m_rest.group(1).strip()
                    queue = m_rest.group(2).strip()
                    talent = (m_rest.group(3) or '').strip()
                else:
                    intention = rest
                    queue = file_meta['queue']
                    talent = ""

                # 清理意向中多余的重复前缀（如畔溪悦府项目畔溪悦府项目）
                intention = re.sub(r'(畔溪悦府项目)+', '畔溪悦府项目', intention)

                records.append({
                    "batch": file_meta['batch'],
                    "source_file": file_meta['source_file'],
                    "seq": cur_seq,
                    "code": cur_code,
                    "house_type": file_meta['house_type'],
                    "queue": queue or file_meta['queue'],
                    "name": d['name'],
                    "id_card": d['id_card'],
                    "role": d['role'],
                    "is_main": (d['role'] == '主申请人'),
                    "intention": intention,
                    "talent_type": talent,
                    "notes": ""
                })
            else:
                # 跨行文本追加 (如过长意向描述)
                if records and not line.startswith('第') and not line.startswith('序号'):
                    records[-1]['intention'] += ' ' + line

    return records


def aggregate_households(member_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按认购编号将成员记录聚合为家庭维度记录"""
    hh_dict: Dict[str, Dict[str, Any]] = {}

    for r in member_records:
        code = r['code']
        if not code:
            continue
        if code not in hh_dict:
            hh_dict[code] = {
                "batch": r['batch'],
                "source_file": r['source_file'],
                "seq": r['seq'],
                "code": code,
                "house_type": r['house_type'],
                "queue": r['queue'],
                "main_applicant": "",
                "main_id_card": "",
                "talent_type": "",
                "intention": r['intention'],
                "members": [],
                "member_names": [],
                "family_size": 0,
                "notes": r['notes']
            }

        hh = hh_dict[code]
        hh['members'].append({
            "name": r['name'],
            "id_card": r['id_card'],
            "role": r['role']
        })
        hh['member_names'].append(f"{r['name']}({r['role']})")
        hh['family_size'] += 1

        if r['is_main'] or not hh['main_applicant']:
            hh['main_applicant'] = r['name']
            hh['main_id_card'] = r['id_card']
            if r['talent_type']:
                hh['talent_type'] = r['talent_type']

    return list(hh_dict.values())


def save_to_sqlite(member_records: List[Dict[str, Any]], db_path: str):
    """保存到 SQLite 数据库并创建索引"""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS households (
        code TEXT PRIMARY KEY,
        batch TEXT,
        source_file TEXT,
        seq INTEGER,
        house_type TEXT,
        queue TEXT,
        main_applicant TEXT,
        main_id_card TEXT,
        talent_type TEXT,
        intention TEXT,
        family_size INTEGER,
        member_names TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        name TEXT,
        id_card TEXT,
        role TEXT,
        is_main INTEGER,
        house_type TEXT,
        queue TEXT,
        talent_type TEXT,
        source_file TEXT,
        FOREIGN KEY(code) REFERENCES households(code)
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_members_name ON members(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_members_code ON members(code)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_members_id_card ON members(id_card)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hh_queue ON households(house_type, queue)")

    households = aggregate_households(member_records)

    for hh in households:
        cur.execute("""
        INSERT OR REPLACE INTO households 
        (code, batch, source_file, seq, house_type, queue, main_applicant, main_id_card, talent_type, intention, family_size, member_names)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hh['code'], hh['batch'], hh['source_file'], hh['seq'], hh['house_type'], hh['queue'],
            hh['main_applicant'], hh['main_id_card'], hh['talent_type'], hh['intention'],
            hh['family_size'], ', '.join(hh['member_names'])
        ))

    # 清空重入 members
    codes = set(hh['code'] for hh in households)
    if codes:
        placeholders = ','.join('?' * len(codes))
        cur.execute(f"DELETE FROM members WHERE code IN ({placeholders})", list(codes))

    for r in member_records:
        cur.execute("""
        INSERT INTO members (code, name, id_card, role, is_main, house_type, queue, talent_type, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r['code'], r['name'], r['id_card'], r['role'], 1 if r['is_main'] else 0,
            r['house_type'], r['queue'], r['talent_type'], r['source_file']
        ))

    conn.commit()
    conn.close()


def save_to_excel(member_records: List[Dict[str, Any]], excel_path: str):
    """将数据导出为 Excel 表格（包含家庭汇总 Sheet 和成员明细 Sheet）"""
    if not openpyxl:
        raise RuntimeError("openpyxl 未安装，请执行 pip install openpyxl")

    wb = openpyxl.Workbook()

    # Sheet 1: 家庭汇总表
    ws_hh = wb.active
    ws_hh.title = "认购家庭汇总"
    hh_headers = ["序号", "认购编号", "户型", "队列", "主申请人", "证件号", "家庭人数", "家庭成员", "人才类型", "认购意向", "来源文件"]
    ws_hh.append(hh_headers)

    households = aggregate_households(member_records)
    for hh in households:
        ws_hh.append([
            hh['seq'],
            hh['code'],
            hh['house_type'],
            hh['queue'],
            hh['main_applicant'],
            hh['main_id_card'],
            hh['family_size'],
            ', '.join(hh['member_names']),
            hh['talent_type'],
            hh['intention'],
            hh['source_file']
        ])

    # Sheet 2: 人员明细表
    ws_mem = wb.create_sheet(title="家庭成员明细")
    mem_headers = ["序号", "认购编号", "户型", "队列", "姓名", "证件号", "人员类别", "人才类型", "认购意向", "来源文件"]
    ws_mem.append(mem_headers)

    for r in member_records:
        ws_mem.append([
            r['seq'],
            r['code'],
            r['house_type'],
            r['queue'],
            r['name'],
            r['id_card'],
            r['role'],
            r['talent_type'],
            r['intention'],
            r['source_file']
        ])

    wb.save(excel_path)


def print_summary(member_records: List[Dict[str, Any]]):
    """打印解析统计结果"""
    households = aggregate_households(member_records)
    print("=" * 60)
    print(f"📊 解析完成统计：共 {len(households)} 户家庭，{len(member_records)} 位人员")
    print("=" * 60)

    # 按户型和队列统计
    queue_stats: Dict[str, Dict[str, int]] = {}
    for hh in households:
        key = f"{hh['house_type']} - {hh['queue']}"
        if key not in queue_stats:
            queue_stats[key] = {"households": 0, "members": 0}
        queue_stats[key]["households"] += 1
        queue_stats[key]["members"] += hh['family_size']

    for q, stat in sorted(queue_stats.items()):
        print(f"  • {q:<16}: {stat['households']:>4} 户 / {stat['members']:>4} 人")

    print("-" * 60)


def main():
    parser = argparse.ArgumentParser(description="保障房认购公示名单 PDF 结构化解析工具")
    parser.add_argument("input", nargs="*", help="PDF 文件路径或通配符（默认当前目录下所有 .pdf）")
    parser.add_argument("-o", "--output", help="导出文件路径 (支持 .xlsx, .csv, .json)")
    parser.add_argument("--sqlite", help="存储到 SQLite 数据库文件路径 (如: skills/baozhangfang/data/housing.db)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出至标准输出")
    parser.add_argument("--summary", action="store_true", default=True, help="打印统计摘要 (默认开启)")

    args = parser.parse_args()

    # 收集待解析的文件
    input_files = []
    if args.input:
        for item in args.input:
            matched = glob.glob(item)
            if matched:
                input_files.extend(matched)
            elif os.path.exists(item):
                input_files.append(item)
    else:
        input_files = sorted(glob.glob("*.pdf"))

    if not input_files:
        print("未找到任何待解析的 PDF 文件！", file=sys.stderr)
        sys.exit(1)

    all_records: List[Dict[str, Any]] = []
    for f in sorted(input_files):
        records = parse_pdf_file(f)
        all_records.extend(records)

    # 打印统计摘要
    if not args.json and args.summary:
        print_summary(all_records)

    # 导出到 SQLite
    if args.sqlite:
        save_to_sqlite(all_records, args.sqlite)
        print(f"💾 数据已成功存入 SQLite 数据库: {args.sqlite}")

    # 导出到指定文件格式
    if args.output:
        out = args.output
        if out.endswith(".xlsx"):
            save_to_excel(all_records, out)
            print(f"📁 已成功导出 Excel 文件: {out}")
        elif out.endswith(".json"):
            households = aggregate_households(all_records)
            with open(out, "w", encoding="utf-8") as fp:
                json.dump({"households": households, "members": all_records}, fp, ensure_ascii=False, indent=2)
            print(f"📁 已成功导出 JSON 文件: {out}")
        elif out.endswith(".csv"):
            import csv
            with open(out, "w", encoding="utf-8-sig", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(["序号", "认购编号", "户型", "队列", "姓名", "证件号", "人员类别", "人才类型", "认购意向", "来源文件"])
                for r in all_records:
                    writer.writerow([
                        r['seq'], r['code'], r['house_type'], r['queue'],
                        r['name'], r['id_card'], r['role'], r['talent_type'], r['intention'], r['source_file']
                    ])
            print(f"📁 已成功导出 CSV 文件: {out}")
        else:
            print(f"不支持的文件格式: {out}，请使用 .xlsx, .csv 或 .json", file=sys.stderr)

    # JSON 输出至标准输出
    if args.json:
        households = aggregate_households(all_records)
        print(json.dumps({"households": households, "members": all_records}, ensure_ascii=False))


if __name__ == "__main__":
    main()
