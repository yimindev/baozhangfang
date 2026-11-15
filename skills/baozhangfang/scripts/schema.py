#!/usr/bin/env python3
"""
schema.py - 自包含保障房 SQLite 数据库 DDL 建表与重置脚本
支持多城市 (city 作为联合主键与重要索引字段)
三层解耦：物理项目 (projects) / 批次过程 (batches) / 批次内单盘房源 (batch_projects)
"""

import sqlite3
import argparse
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
from db import DB_PATH  # 运行库路径（schema.py 不做种子自举，--reset 时得到空库）

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
        aliases TEXT,
        notices_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(city, project_name)
    );
    """,
    # 2. batches: 推售批次的过程台账（公告链、认购窗口、销售方式、阶段）
    #    房源量（套数/户型/均价）属于「批次 × 楼盘」，在 batch_projects
    """
    CREATE TABLE IF NOT EXISTS batches (
        batch_id TEXT PRIMARY KEY,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT,
        housing_type TEXT,
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
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 3. batch_projects: 批次内每个楼盘的推售房源（多对多 + 房源明细）
    """
    CREATE TABLE IF NOT EXISTS batch_projects (
        batch_id TEXT NOT NULL,
        project_id INTEGER NOT NULL,
        batch_seq INTEGER,
        units INTEGER,
        one_bedroom_units INTEGER,
        two_bedroom_units INTEGER,
        three_bedroom_units INTEGER,
        four_bedroom_units INTEGER,
        other_units INTEGER,
        average_price REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (batch_id, project_id),
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id),
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    """,
    # 4. notices: 官方公文与阶段事件流水台账
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
    # 5. applications: 申购家庭与状态机台账 (一家庭一记录就地更新)
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
    # 6. policies: 政策法规与规约台账
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
    """,
]

# 旧库补列（幂等，仅 ADD COLUMN，不改写数据）；新增字段时在此登记
COLUMN_MIGRATIONS = [
    ("projects", "aliases", "TEXT"),
    ("batch_projects", "units", "INTEGER"),
    ("batch_projects", "average_price", "REAL"),
    ("batch_projects", "batch_seq", "INTEGER"),
    ("batch_projects", "one_bedroom_units", "INTEGER"),
    ("batch_projects", "two_bedroom_units", "INTEGER"),
    ("batch_projects", "three_bedroom_units", "INTEGER"),
    ("batch_projects", "four_bedroom_units", "INTEGER"),
    ("batch_projects", "other_units", "INTEGER"),
]

BATCH_PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS batch_projects (
    batch_id TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    batch_seq INTEGER,
    units INTEGER,
    one_bedroom_units INTEGER,
    two_bedroom_units INTEGER,
    three_bedroom_units INTEGER,
    four_bedroom_units INTEGER,
    other_units INTEGER,
    average_price REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (batch_id, project_id),
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
"""

BATCHES_DDL = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    city TEXT NOT NULL DEFAULT '深圳',
    district TEXT,
    housing_type TEXT,
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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

BATCH_COLUMNS = ["batch_id", "city", "district", "housing_type", "deposit_amount", "sales_mode",
                 "has_regular_sales_exit", "reception_location", "consultation_phone",
                 "booking_channel", "sub_start_date", "sub_end_date", "current_stage",
                 "notices_json", "created_at", "updated_at"]
def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_columns(conn: sqlite3.Connection) -> list[str]:
    """为旧版本运行库补齐缺失列；表不存在时跳过（建表由 init_db 负责）。"""
    added = []
    for table, column, decl in COLUMN_MIGRATIONS:
        existing = _columns(conn, table)
        if not existing or column in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        added.append(f"{table}.{column}")
    if added:
        conn.commit()
    return added


def _demote_batch_units_to_links(conn: sqlite3.Connection) -> None:
    """把旧版 batches 上的套数/户型/均价/批次序号搬进 batch_projects。

    只对「单楼盘批次」做，避免把多楼盘批次的汇总值错误复制给某一个楼盘。
    """
    old = _columns(conn, "batches")
    if "total_units" not in old:
        return
    rows = conn.execute("""
        SELECT bp.batch_id, bp.project_id,
               b.batch_seq, b.total_units, b.one_bedroom_units, b.two_bedroom_units,
               b.three_bedroom_units, b.four_bedroom_units, b.other_units, b.average_price
        FROM batch_projects bp JOIN batches b ON b.batch_id = bp.batch_id
        WHERE (SELECT COUNT(*) FROM batch_projects x WHERE x.batch_id = bp.batch_id) = 1
    """).fetchall()
    for (batch_id, project_id, seq, total, one, two, three, four, other, price) in rows:
        conn.execute("""
            UPDATE batch_projects SET
                batch_seq = COALESCE(batch_seq, ?), units = COALESCE(units, ?),
                one_bedroom_units = COALESCE(one_bedroom_units, ?),
                two_bedroom_units = COALESCE(two_bedroom_units, ?),
                three_bedroom_units = COALESCE(three_bedroom_units, ?),
                four_bedroom_units = COALESCE(four_bedroom_units, ?),
                other_units = COALESCE(other_units, ?),
                average_price = COALESCE(average_price, ?)
            WHERE batch_id = ? AND project_id = ?
        """, (seq, total, one, two, three, four, other, price, batch_id, project_id))


def _rebuild_batches(conn: sqlite3.Connection) -> bool:
    """旧版 batches 去掉 project_id 与房源量列：重建表（SQLite 不能直接删带外键的列）。"""
    old = _columns(conn, "batches")
    if not old or "project_id" not in old:
        return False
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS batches__new")
        conn.execute(BATCHES_DDL.replace("CREATE TABLE IF NOT EXISTS batches",
                                         "CREATE TABLE batches__new"))
        keep = [c for c in BATCH_COLUMNS if c in old]
        cols = ", ".join(keep)
        conn.execute(f"INSERT INTO batches__new ({cols}) SELECT {cols} FROM batches")
        conn.execute("DROP TABLE batches")
        conn.execute("ALTER TABLE batches__new RENAME TO batches")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return True


def ensure_schema(conn: sqlite3.Connection) -> list[str]:
    """为旧版本运行库补齐表结构（幂等）：建表、回填关联、搬移房源量、重建 batches。

    db.py 每次打开运行库都会调用，因此只做 CREATE IF NOT EXISTS / INSERT OR IGNORE，
    以及一次性的（由列是否存在判定的）结构升级。
    """
    added = []
    if not _table_exists(conn, "batch_projects"):
        conn.execute(BATCH_PROJECTS_DDL)
        added.append("batch_projects")
    added += ensure_columns(conn)
    if _table_exists(conn, "batch_projects") and "is_primary" in _columns(conn, "batch_projects"):
        conn.execute("ALTER TABLE batch_projects DROP COLUMN is_primary")
        added.append("batch_projects(去 is_primary)")
    if _table_exists(conn, "batches"):
        # 回填：每个批次至少一条关联，指向旧版 batches.project_id
        if "project_id" in _columns(conn, "batches"):
            conn.execute("""
                INSERT OR IGNORE INTO batch_projects (batch_id, project_id)
                SELECT b.batch_id, b.project_id
                FROM batches b
                WHERE b.project_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM batch_projects bp WHERE bp.batch_id = b.batch_id)
            """)
        _demote_batch_units_to_links(conn)
        if _rebuild_batches(conn):
            added.append("batches(去 project_id/房源量列)")
    for idx_sql in INDEXES:
        conn.execute(idx_sql)
    conn.commit()
    if added:
        print(f"[*] 已迁移表结构: {', '.join(added)}", file=sys.stderr)
    return added


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_proj_city_dist ON projects (city, district);",
    "CREATE INDEX IF NOT EXISTS idx_batch_city_stage ON batches (city, current_stage);",
    "DROP INDEX IF EXISTS idx_batch_proj_id;",
    "CREATE INDEX IF NOT EXISTS idx_bp_project ON batch_projects (project_id);",
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
        for tbl in ["applications", "notices", "batch_projects", "batches", "projects", "policies"]:
            cur.execute(f"DROP TABLE IF EXISTS {tbl};")

    print(f"[*] 正在初始化 SQLite 数据表结构...")
    for sql in SQL_TABLES:
        cur.execute(sql)
    ensure_schema(conn)

    conn.commit()
    conn.close()
    print("[SUCCESS] SQLite 表结构初始化完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自包含 SQLite 数据库初始化工具")
    parser.add_argument("--reset", action="store_true", help="清空并重建所有数据表")
    args = parser.parse_args()
    init_db(reset=args.reset)
