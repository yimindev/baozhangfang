#!/usr/bin/env python3
"""
query_housing.py - 自包含保障房业务检索与资产巡检命令行工具 (纯 SQLite 独立版)
支持:
  1. 按城市与楼盘名称模糊搜索项目物理大盘与所属批次
  2. 一键筛选 "常态化现场即时配售" 房源清单
  3. 按户型筛选 (两房 / 三房 / 四房在售套数)
  4. 展开指定批次的完整官方公文流水演进链 (notices_json)
  5. 数据库整体健康指标统计
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DB_SQLITE = SKILL_ROOT / "data" / "housing.db"

def get_connection():
    if not DB_SQLITE.exists():
        print(f"[ERROR] 数据库文件未找到: {DB_SQLITE}")
        sys.exit(1)
    return sqlite3.connect(DB_SQLITE)

def query_stats(city: str = None):
    conn = get_connection()
    cur = conn.cursor()
    print("================== 数据库健康巡检与资产总览 ==================")
    city_filter = "WHERE city = ?" if city else ""
    params = (city,) if city else ()

    for tbl in ["projects", "batches", "notices", "policies", "applications"]:
        if city and tbl != "policies":
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE city = ?", (city,))
        else:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        count = cur.fetchone()[0]
        print(f"表 {tbl: <15}: {count: <6} 行")

    # 批次状态分布
    print("\n------------------ 推售批次阶段分布 ------------------")
    sql = f"SELECT current_stage, COUNT(*), SUM(total_units) FROM batches {city_filter} GROUP BY current_stage ORDER BY COUNT(*) DESC"
    cur.execute(sql, params)
    for stg, cnt, units in cur.fetchall():
        units_str = f"{int(units)} 套" if units else "未公布"
        print(f"  * {stg or '未公告阶段': <12} : {cnt: <2} 批次 (房源累计: {units_str})")

    # 常态化配售大盘
    cur.execute(f"SELECT COUNT(*) FROM batches WHERE (has_regular_sales_exit = 1 OR current_stage = '常态化配售中') {'AND city = ?' if city else ''}", params)
    reg_cnt = cur.fetchone()[0]
    print(f"\n  ★ 具备常态化现场即时配售通道的批次: {reg_cnt} 个")
    print("======================================================")
    conn.close()

def query_batches(keyword: str = None, city: str = "深圳", regular_only: bool = False, stage: str = None, min_beds: int = None):
    conn = get_connection()
    cur = conn.cursor()

    conditions = ["b.city = ?"]
    params = [city]

    if keyword:
        conditions.append("(p.project_name LIKE ? OR b.batch_id LIKE ? OR b.reception_location LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    if regular_only:
        conditions.append("(b.has_regular_sales_exit = 1 OR b.current_stage = '常态化配售中')")

    if stage:
        conditions.append("b.current_stage LIKE ?")
        params.append(f"%{stage}%")

    if min_beds == 2:
        conditions.append("b.two_bedroom_units > 0")
    elif min_beds == 3:
        conditions.append("b.three_bedroom_units > 0")
    elif min_beds == 4:
        conditions.append("b.four_bedroom_units > 0")

    where_clause = " AND ".join(conditions)
    sql = f"""
    SELECT b.batch_id, p.project_name, p.district, b.housing_type,
           b.total_units, b.two_bedroom_units, b.three_bedroom_units, b.four_bedroom_units,
           b.average_price, b.sales_mode, b.has_regular_sales_exit, b.current_stage,
           b.consultation_phone, b.reception_location, b.notices_json
    FROM batches b
    JOIN projects p ON b.project_id = p.id
    WHERE {where_clause}
    ORDER BY b.batch_id DESC
    """
    cur.execute(sql, params)
    rows = cur.fetchall()

    if not rows:
        print(f"[提示] 未找到符合条件的保障房批次 (城市: {city}, 关键词: {keyword or '无'})")
        conn.close()
        return

    print(f"\n================== 检索结果 (共找到 {len(rows)} 个批次) ==================")
    for r in rows:
        bid, pname, dist, htype, tot, u2, u3, u4, price, smode, reg, stg, phone, loc, n_json = r
        print(f"\n【{pname}】({dist or '市辖'}) - 批次: {bid}")
        print(f"  • 当前阶段: {stg or '未更新'} | 销售模式: {smode or '集中摇号'} | 常态化出口: {'有 (即时选房)' if reg else '暂无'}")
        
        bed_info = []
        if u2: bed_info.append(f"两房: {u2}套")
        if u3: bed_info.append(f"三房: {u3}套")
        if u4: bed_info.append(f"四房: {u4}套")
        bed_str = " | ".join(bed_info) if bed_info else "户型明细以公文为准"
        tot_str = f"{tot} 套" if tot else "套数待查"
        price_str = f"{price} 元/㎡" if price else "价格待查"

        print(f"  • 房源概况: 总推售 {tot_str} ({bed_str})")
        print(f"  • 配售均价: {price_str}")
        if phone: print(f"  • 咨询电话: {phone}")
        if loc: print(f"  • 接待中心: {loc}")

        try:
            notices = json.loads(n_json) if n_json else []
            if notices:
                print(f"  • 公文演进链 ({len(notices)} 篇官方通告):")
                for n in notices[:4]:
                    print(f"    - [{n.get('date')}] ({n.get('stage')}) {n.get('title')[:36]}")
                if len(notices) > 4:
                    print(f"    - ... (共 {len(notices)} 篇，更多见 notices 表)")
        except Exception:
            pass
    print("========================================================================\n")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自包含保障房资产查询工具")
    parser.add_argument("keyword", nargs="?", default=None, help="楼盘名称或批次号关键词 (如: 华越龙苑、深铁熙府、083)")
    parser.add_argument("--city", default="深圳", help="目标城市名称，默认: 深圳")
    parser.add_argument("--regular", action="store_true", help="只看具备常态化现场即时配售的项目")
    parser.add_argument("--stage", help="按推售阶段过滤 (如: 选房签约中, 认购中, 常态化配售中)")
    parser.add_argument("--beds", type=int, choices=[2, 3, 4], help="按户型过滤 (2: 两房, 3: 三房, 4: 四房)")
    parser.add_argument("--stats", action="store_true", help="查看数据库全量统计与批次分布")
    args = parser.parse_args()

    if args.stats or (not args.keyword and not args.regular and not args.stage and not args.beds):
        query_stats(city=args.city)
    else:
        query_batches(keyword=args.keyword, city=args.city, regular_only=args.regular, stage=args.stage, min_beds=args.beds)
