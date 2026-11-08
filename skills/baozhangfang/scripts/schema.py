#!/usr/bin/env python3
"""
schema.py - 自包含保障房 SQLite 数据库 DDL 建表与重置脚本
支持多城市 (city 作为联合主键与重要索引字段)
解耦物理项目 (projects) 与业务推售批次 (batches)
"""

import sqlite3
import argparse
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = SKILL_ROOT / "data" / "housing.db"

SQL_TABLES = [
    # 1. projects: 物理资产大盘台账 (一个实际地理建筑实体)
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT,
        subdistrict TEXT,
        project_name TEXT NOT NULL,
        developer TEXT,
        housing_type TEXT,
        total_planned_units INTEGER,
        planned_area REAL,
        address TEXT,
        status TEXT,
        notices_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(city, project_name)
    );
    """,
    # 2. batches: 业务推售批次台账 (按批次推售，关联 projects.id)
    """
    CREATE TABLE IF NOT EXISTS batches (
        batch_id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT,
        batch_seq INTEGER,
        housing_type TEXT,
        total_units INTEGER,
        one_bedroom_units INTEGER,
        two_bedroom_units INTEGER,
        three_bedroom_units INTEGER,
        four_bedroom_units INTEGER,
        other_units INTEGER,
        average_price REAL,
        deposit_amount REAL,
        sales_mode TEXT,
        has_regular_sales_exit INTEGER,
        reception_location TEXT,
        consultation_phone TEXT,
        booking_channel TEXT,
        sub_start_date TEXT,
        sub_end_date TEXT,
        current_stage TEXT,
        notices_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    """,
    # 3. notices: 官方公文与阶段事件流水台账
    """
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT,
        project_id INTEGER,
        batch_id TEXT,
        category TEXT,
        title TEXT NOT NULL,
        publish_date TEXT,
        url TEXT NOT NULL UNIQUE,
        summary TEXT,
        content_text TEXT,
        attachments_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    """,
    # 4. applications: 申购家庭与状态机台账 (一家庭一记录就地更新)
    """
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        applicant_code TEXT NOT NULL,
        city TEXT NOT NULL DEFAULT '深圳',
        main_applicant TEXT NOT NULL,
        id_card TEXT,
        house_type TEXT,
        queue TEXT,
        talent_type TEXT,
        family_size INTEGER,
        member_names TEXT,
        verify_status TEXT,
        ballot_seq INTEGER,
        selection_result TEXT,
        selected_unit TEXT,
        notices_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id),
        UNIQUE(batch_id, applicant_code)
    );
    """,
    # 5. policies: 政策法规与规约台账
    """
    CREATE TABLE IF NOT EXISTS policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL DEFAULT '深圳',
        category TEXT,
        title TEXT NOT NULL,
        document_number TEXT,
        publisher TEXT,
        publish_date TEXT,
        effective_date TEXT,
        status TEXT DEFAULT '现行有效',
        url TEXT NOT NULL UNIQUE,
        summary TEXT,
        content_text TEXT,
        attachments_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_proj_city_dist ON projects (city, district);",
    "CREATE INDEX IF NOT EXISTS idx_batch_proj_id ON batches (project_id);",
    "CREATE INDEX IF NOT EXISTS idx_batch_city_stage ON batches (city, current_stage);",
    "CREATE INDEX IF NOT EXISTS idx_notice_pub_date ON notices (city, publish_date);",
    "CREATE INDEX IF NOT EXISTS idx_notice_batch ON notices (batch_id);",
    "CREATE INDEX IF NOT EXISTS idx_app_batch_code ON applications (batch_id, applicant_code);",
    "CREATE INDEX IF NOT EXISTS idx_policy_city_cat ON policies (city, category);"
]

def init_db(reset: bool = False):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if reset:
        print(f"[*] 正在重置 SQLite 数据库: {DB_PATH}")
        for tbl in ["applications", "notices", "batches", "projects", "policies"]:
            cur.execute(f"DROP TABLE IF EXISTS {tbl};")

    print(f"[*] 正在初始化 SQLite 数据表结构...")
    for sql in SQL_TABLES:
        cur.execute(sql)
    for idx_sql in INDEXES:
        cur.execute(idx_sql)

    conn.commit()
    conn.close()
    print("[SUCCESS] SQLite 表结构初始化完成。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自包含 SQLite 数据库初始化工具")
    parser.add_argument("--reset", action="store_true", help="清空并重建所有数据表")
    args = parser.parse_args()
    init_db(reset=args.reset)
