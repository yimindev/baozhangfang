#!/usr/bin/env python3
"""
sync_to_mysql.py - 将本地保障房数据同步至阿里云 RDS MySQL
"""

import sys
import json
import sqlite3
import pymysql
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_SQLITE = PROJECT_ROOT / "skills" / "baozhangfang" / "data" / "housing.db"  # 统一使用 Skill 运行库
CONFIG_FILE = PROJECT_ROOT / "config" / "database.json"

def get_db_config(role="admin"):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return {
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg[role]["user"],
        "password": cfg[role]["password"],
        "database": cfg["database"],
        "charset": cfg.get("charset", "utf8mb4"),
        "autocommit": False
    }

def create_mysql_tables(m_cur):
    """创建 MySQL 表结构"""
    print(">>> 正在初始化 MySQL 表结构...")

    # 1. 公告表
    m_cur.execute("""
    CREATE TABLE IF NOT EXISTS notices (
        id INT AUTO_INCREMENT PRIMARY KEY,
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        district VARCHAR(64) NOT NULL COMMENT '区域/部门',
        batch_id VARCHAR(64) COMMENT '关联批次文号',
        category VARCHAR(64) NOT NULL COMMENT '分类',
        title VARCHAR(512) NOT NULL COMMENT '公告标题',
        publish_date VARCHAR(32) COMMENT '发布日期',
        url VARCHAR(512) NOT NULL UNIQUE COMMENT '原文链接',
        summary TEXT COMMENT '摘要',
        content_text MEDIUMTEXT COMMENT '正文纯文本',
        attachments_json TEXT COMMENT '附件JSON',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_city_district (city, district),
        INDEX idx_publish_date (publish_date),
        INDEX idx_category (category),
        INDEX idx_batch_id (batch_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='保障房公告台账表';
    """)

    # 2. 待入市与在建房源储备库
    m_cur.execute("""
    CREATE TABLE IF NOT EXISTS projects_pipeline (
        id INT AUTO_INCREMENT PRIMARY KEY,
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        district VARCHAR(64) NOT NULL COMMENT '区域',
        subdistrict VARCHAR(64) COMMENT '街道',
        project_name VARCHAR(128) NOT NULL COMMENT '项目名称',
        developer VARCHAR(255) COMMENT '建设/开发单位',
        housing_type VARCHAR(64) COMMENT '保障房类型',
        planned_units INT COMMENT '计划建设/竣工套数',
        planned_area DECIMAL(10,2) COMMENT '建筑面积(万平方米)',
        address VARCHAR(512) COMMENT '具体位置/地块',
        source_type VARCHAR(64) NOT NULL COMMENT '数据来源类型',
        source_document VARCHAR(255) COMMENT '来源文件',
        expected_timeline VARCHAR(64) COMMENT '预期入市时间',
        status VARCHAR(64) DEFAULT '待入市' COMMENT '当前状态',
        notes TEXT COMMENT '备注',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_city_district (city, district),
        INDEX idx_project_name (project_name),
        INDEX idx_expected_timeline (expected_timeline),
        INDEX idx_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='待入市与在建房源储备库';
    """)

    # 3. 认购家庭信息表
    m_cur.execute("""
    CREATE TABLE IF NOT EXISTS households (
        code VARCHAR(64) PRIMARY KEY COMMENT '认购申请编号',
        batch VARCHAR(64) COMMENT '批次',
        source_file VARCHAR(255) COMMENT '来源文件',
        seq INT COMMENT '队列序号',
        house_type VARCHAR(32) COMMENT '认购户型(两房/三房)',
        queue VARCHAR(32) COMMENT '队列(第一队列/第二队列等)',
        main_applicant VARCHAR(64) COMMENT '主申请人姓名',
        main_id_card VARCHAR(32) COMMENT '主申请人证件号(脱敏)',
        talent_type VARCHAR(255) COMMENT '人才类型',
        intention VARCHAR(255) COMMENT '意向房源/项目',
        family_size INT COMMENT '共同申请人数/家庭总人数',
        member_names VARCHAR(512) COMMENT '共同申请人姓名列表',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_batch (batch),
        INDEX idx_house_type (house_type),
        INDEX idx_queue (queue),
        INDEX idx_main_name (main_applicant)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='认购家庭信息表';
    """)

    # 4. 家庭成员明细表
    m_cur.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INT AUTO_INCREMENT PRIMARY KEY,
        code VARCHAR(64) NOT NULL COMMENT '申请编号',
        name VARCHAR(64) NOT NULL COMMENT '姓名',
        id_card VARCHAR(32) COMMENT '证件号(脱敏)',
        role VARCHAR(32) COMMENT '角色(主申请人/配偶/子女等)',
        is_main TINYINT(1) DEFAULT 0 COMMENT '是否为主申请人(1是,0否)',
        house_type VARCHAR(32) COMMENT '认购户型',
        queue VARCHAR(32) COMMENT '队列',
        talent_type VARCHAR(255) COMMENT '人才类型',
        source_file VARCHAR(255) COMMENT '来源文件',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_code (code),
        INDEX idx_name (name),
        INDEX idx_role (role)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='家庭成员明细表';
    """)

    # 5. 批次表
    m_cur.execute("""
    CREATE TABLE IF NOT EXISTS batches (
        batch_id VARCHAR(64) PRIMARY KEY COMMENT '批次文号',
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        district VARCHAR(64) NOT NULL COMMENT '区域/部门',
        project_name VARCHAR(128) NOT NULL COMMENT '项目名称',
        housing_type VARCHAR(64) NOT NULL COMMENT '房源类型',
        two_bedroom_units INT DEFAULT 0 COMMENT '两房套数',
        three_bedroom_units INT DEFAULT 0 COMMENT '三房套数',
        total_units INT DEFAULT 0 COMMENT '总套数',
        average_price DECIMAL(10,2) COMMENT '均价(元/㎡)',
        sub_start_date VARCHAR(32) COMMENT '认购开始时间',
        sub_end_date VARCHAR(32) COMMENT '认购截止时间',
        current_stage VARCHAR(64) COMMENT '当前阶段',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_city_district (city, district),
        INDEX idx_current_stage (current_stage)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='批次台账表';
    """)

def sync_notices(s_cur, m_cur, m_conn):
    print(">>> 同步 notices 表...")
    s_cur.execute("SELECT city, district, batch_id, category, title, publish_date, url, summary, content_text, attachments_json FROM notices")
    rows = s_cur.fetchall()
    insert_sql = """
    INSERT INTO notices (city, district, batch_id, category, title, publish_date, url, summary, content_text, attachments_json)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        batch_id=VALUES(batch_id),
        category=VALUES(category),
        title=VALUES(title),
        publish_date=VALUES(publish_date),
        summary=VALUES(summary),
        content_text=CASE WHEN VALUES(content_text) IS NOT NULL AND VALUES(content_text) != '' THEN VALUES(content_text) ELSE notices.content_text END,
        attachments_json=VALUES(attachments_json);
    """
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        m_cur.executemany(insert_sql, chunk)
    m_conn.commit()
    print(f"notices 同步完成: {len(rows)} 条")

def sync_projects_pipeline(s_cur, m_cur, m_conn):
    print(">>> 同步 projects_pipeline 表...")
    s_cur.execute("""
    SELECT city, district, subdistrict, project_name, developer, housing_type, planned_units, planned_area, address, source_type, source_document, expected_timeline, status, notes
    FROM projects_pipeline
    """)
    rows = s_cur.fetchall()
    # 清理后插入或直接插入
    m_cur.execute("TRUNCATE TABLE projects_pipeline")
    insert_sql = """
    INSERT INTO projects_pipeline (city, district, subdistrict, project_name, developer, housing_type, planned_units, planned_area, address, source_type, source_document, expected_timeline, status, notes)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        m_cur.executemany(insert_sql, chunk)
    m_conn.commit()
    print(f"projects_pipeline 同步完成: {len(rows)} 条")

def sync_households(s_cur, m_cur, m_conn):
    print(">>> 同步 households 表...")
    s_cur.execute("SELECT code, batch, source_file, seq, house_type, queue, main_applicant, main_id_card, talent_type, intention, family_size, member_names FROM households")
    rows = s_cur.fetchall()
    insert_sql = """
    INSERT INTO households (code, batch, source_file, seq, house_type, queue, main_applicant, main_id_card, talent_type, intention, family_size, member_names)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        batch=VALUES(batch),
        source_file=VALUES(source_file),
        seq=VALUES(seq),
        house_type=VALUES(house_type),
        queue=VALUES(queue),
        main_applicant=VALUES(main_applicant),
        main_id_card=VALUES(main_id_card),
        talent_type=VALUES(talent_type),
        intention=VALUES(intention),
        family_size=VALUES(family_size),
        member_names=VALUES(member_names);
    """
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        m_cur.executemany(insert_sql, chunk)
    m_conn.commit()
    print(f"households 同步完成: {len(rows)} 条")

def sync_members(s_cur, m_cur, m_conn):
    print(">>> 同步 members 表...")
    s_cur.execute("SELECT code, name, id_card, role, is_main, house_type, queue, talent_type, source_file FROM members")
    rows = s_cur.fetchall()
    m_cur.execute("TRUNCATE TABLE members")
    insert_sql = """
    INSERT INTO members (code, name, id_card, role, is_main, house_type, queue, talent_type, source_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        m_cur.executemany(insert_sql, chunk)
    m_conn.commit()
    print(f"members 同步完成: {len(rows)} 条")

def sync_batches(s_cur, m_cur, m_conn):
    print(">>> 同步 batches 表...")
    # 注入已知核心批次
    default_batches = [
        ('住保售〔2026〕081号批次', '深圳', '罗湖区', '畔溪悦府', '面向人才配售住房', 204, 102, 306, 39600.00, '2026-09-30', '2026-10-10', '选房签约'),
        ('住保售〔2026〕083号批次', '深圳', '市住建局', '安居华越龙苑', '面向人才配售住房', 0, 0, 0, 0.0, '2026-10-21', '2026-11-05', '常态化配售'),
        ('住保售〔2026〕073号批次', '深圳', '市住建局', '人才配售住房', '面向人才配售住房', 0, 0, 0, 0.0, '2026-09-28', '2026-10-08', '选房签约'),
        ('住保售〔2026〕077号批次', '深圳', '市住建局', '安居型商品房', '安居型商品房', 0, 0, 0, 0.0, '2026-09-29', '2026-10-09', '选房签约')
    ]
    insert_sql = """
    INSERT INTO batches (batch_id, city, district, project_name, housing_type, two_bedroom_units, three_bedroom_units, total_units, average_price, sub_start_date, sub_end_date, current_stage)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        project_name=VALUES(project_name),
        housing_type=VALUES(housing_type),
        current_stage=VALUES(current_stage);
    """
    m_cur.executemany(insert_sql, default_batches)
    m_conn.commit()
    print(f"batches 同步完成: {len(default_batches)} 条")

def verify_sync(m_cur):
    print("\n================== 线上 MySQL 数据库核验 ==================")
    for tbl in ["notices", "projects_pipeline", "households", "members", "batches"]:
        m_cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        cnt = m_cur.fetchone()[0]
        print(f"表 {tbl: <20}: {cnt: <6} 行")
    print("===========================================================")

def main():
    if not DB_SQLITE.exists():
        print(f"本地 SQLite 数据库不存在: {DB_SQLITE}")
        sys.exit(1)

    print(">>> 正在连接本地 SQLite 与 阿里云 MySQL RDS...")
    s_conn = sqlite3.connect(DB_SQLITE)
    s_cur = s_conn.cursor()

    admin_cfg = get_db_config("admin")
    try:
        m_conn = pymysql.connect(
            host=admin_cfg["host"],
            port=admin_cfg["port"],
            user=admin_cfg["user"],
            password=admin_cfg["password"],
            database=admin_cfg["database"],
            charset=admin_cfg["charset"],
            autocommit=False
        )
        m_cur = m_conn.cursor()
    except Exception as e:
        print(f"MySQL 连接失败: {e}")
        sys.exit(1)

    # 1. 创建表结构
    create_mysql_tables(m_cur)
    m_conn.commit()

    # 2. 同步数据
    sync_notices(s_cur, m_cur, m_conn)
    sync_projects_pipeline(s_cur, m_cur, m_conn)
    sync_households(s_cur, m_cur, m_conn)
    sync_members(s_cur, m_cur, m_conn)
    sync_batches(s_cur, m_cur, m_conn)

    # 3. 验证统计
    verify_sync(m_cur)

    m_cur.close()
    m_conn.close()
    s_conn.close()
    print("\n[SUCCESS] 全部数据同步至线上 MySQL 完毕！")

if __name__ == "__main__":
    main()
