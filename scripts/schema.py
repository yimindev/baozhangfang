#!/usr/bin/env python3
"""
schema.py - 数据库表结构定义与初始化工具 (支持 SQLite 与 MySQL)
包含 5 张核心业务表:
  1. projects: 项目资产与规划台账表
  2. batches: 推售/配租批次业务主表 (外键关联 projects.id)
  3. notices: 官方公文流水表 (反向外键关联 projects.id 与 batches.batch_id)
  4. applications: 申购家庭记录表 (单批次单主键，原地状态机回填)
  5. policies: 政策法规库表 (收录最新与历史法定政策全文)
"""

import sqlite3
import pymysql

# ==================== SQLite DDL ====================
SQLITE_TABLES = [
    # 1. projects
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL DEFAULT '深圳',
        district TEXT NOT NULL,
        subdistrict TEXT,
        project_name TEXT NOT NULL UNIQUE,
        developer TEXT,
        housing_type TEXT,
        total_planned_units INTEGER,
        planned_area REAL,
        address TEXT,
        status TEXT,
        notices_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 2. batches
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
    # 3. notices
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
    # 4. applications
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
        UNIQUE (batch_id, applicant_code),
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
    );
    """,
    # 5. policies
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
]

# ==================== MySQL DDL ====================
MYSQL_TABLES = [
    # 1. projects
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INT AUTO_INCREMENT PRIMARY KEY,
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        district VARCHAR(64) NOT NULL COMMENT '行政区',
        subdistrict VARCHAR(64) COMMENT '街道/片区',
        project_name VARCHAR(128) NOT NULL UNIQUE COMMENT '项目标准名称',
        developer VARCHAR(255) COMMENT '建设开发单位',
        housing_type VARCHAR(64) COMMENT '保障房类别',
        total_planned_units INT COMMENT '规划总套数 (未公布为 NULL)',
        planned_area DECIMAL(10, 2) COMMENT '规划总建面/万㎡',
        address VARCHAR(512) COMMENT '具体地址/地块号',
        status VARCHAR(64) COMMENT '工程状态 (未公布为 NULL)',
        notices_json TEXT COMMENT '项目关键里程碑通告 JSON 数组',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_city_dist (city, district),
        INDEX idx_proj_name (project_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='项目资产表';
    """,
    # 2. batches
    """
    CREATE TABLE IF NOT EXISTS batches (
        batch_id VARCHAR(64) PRIMARY KEY COMMENT '批次文号',
        project_id INT NOT NULL COMMENT '外键关联 projects.id',
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        district VARCHAR(64) COMMENT '主管辖区',
        batch_seq INT COMMENT '该项目的第几次推售 (1, 2, 3...)',
        housing_type VARCHAR(64) COMMENT '房源类别',
        total_units INT COMMENT '本次推售总套数 (未公布为 NULL)',
        one_bedroom_units INT COMMENT '一房套数',
        two_bedroom_units INT COMMENT '两房套数',
        three_bedroom_units INT COMMENT '三房套数',
        four_bedroom_units INT COMMENT '四房套数',
        other_units INT COMMENT '其他户型套数',
        average_price DECIMAL(10, 2) COMMENT '配售均价/元/㎡',
        deposit_amount DECIMAL(10, 2) COMMENT '认购订金/元',
        sales_mode VARCHAR(64) COMMENT '销售模式 (未公告为 NULL)',
        has_regular_sales_exit TINYINT(1) COMMENT '是否允许常态化 (1是,0否,NULL未提及)',
        reception_location VARCHAR(512) COMMENT '常态化配售接待中心地址',
        consultation_phone VARCHAR(64) COMMENT '项目咨询服务热线',
        booking_channel VARCHAR(255) COMMENT '预约与销控渠道说明',
        sub_start_date VARCHAR(32) COMMENT '认购开始时间',
        sub_end_date VARCHAR(32) COMMENT '认购截止时间',
        current_stage VARCHAR(64) COMMENT '当前阶段 (未公告为 NULL)',
        notices_json TEXT COMMENT '生命周期通告 JSON 数组',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id),
        INDEX idx_proj_id (project_id),
        INDEX idx_stage (current_stage)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='批次推售表';
    """,
    # 3. notices
    """
    CREATE TABLE IF NOT EXISTS notices (
        id INT AUTO_INCREMENT PRIMARY KEY,
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        district VARCHAR(64) COMMENT '发布机构辖区',
        project_id INT COMMENT '外键反向关联 projects.id',
        batch_id VARCHAR(64) COMMENT '关联 batches.batch_id',
        category VARCHAR(64) COMMENT '通告类型',
        title VARCHAR(512) NOT NULL COMMENT '公告标题',
        publish_date VARCHAR(32) COMMENT '发布日期 YYYY-MM-DD',
        url VARCHAR(512) NOT NULL UNIQUE COMMENT '原文直链',
        summary TEXT COMMENT '简报摘要',
        content_text MEDIUMTEXT COMMENT '正文纯文本 (支撑问答与全文检索)',
        attachments_json TEXT COMMENT '附件数组 JSON',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id),
        INDEX idx_proj_id (project_id),
        INDEX idx_batch (batch_id),
        INDEX idx_category (category),
        INDEX idx_pub_date (publish_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='官方通告与阶段事件流水表';
    """,
    # 4. applications
    """
    CREATE TABLE IF NOT EXISTS applications (
        id INT AUTO_INCREMENT PRIMARY KEY,
        batch_id VARCHAR(64) NOT NULL COMMENT '关联 batches.batch_id',
        applicant_code VARCHAR(64) NOT NULL COMMENT '申请唯一编号',
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        main_applicant VARCHAR(64) NOT NULL COMMENT '主申请人姓名',
        id_card VARCHAR(32) COMMENT '脱敏证件号',
        house_type VARCHAR(32) COMMENT '意向户型',
        queue VARCHAR(64) COMMENT '所属队列/组别',
        talent_type VARCHAR(255) COMMENT '资质认定/人才类型',
        family_size INT COMMENT '家庭总人数',
        member_names VARCHAR(512) COMMENT '共同申请人家属摘要',
        verify_status VARCHAR(64) COMMENT '资格审核状态 (未公示为 NULL)',
        ballot_seq INT COMMENT '公证摇号顺位号 (未摇号为 NULL)',
        selection_result VARCHAR(64) COMMENT '选房结果 (未选房为 NULL)',
        selected_unit VARCHAR(128) COMMENT '最终认购房号 (未选定为 NULL)',
        notices_json TEXT COMMENT '经历通告与来源 PDF 附件 JSON',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_batch_code (batch_id, applicant_code),
        INDEX idx_batch_status (batch_id, verify_status),
        INDEX idx_ballot_seq (batch_id, ballot_seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='申购家庭记录表';
    """,
    # 5. policies
    """
    CREATE TABLE IF NOT EXISTS policies (
        id INT AUTO_INCREMENT PRIMARY KEY,
        city VARCHAR(32) NOT NULL DEFAULT '深圳' COMMENT '城市',
        category VARCHAR(64) COMMENT '政策类别',
        title VARCHAR(512) NOT NULL COMMENT '政策法规标题',
        document_number VARCHAR(255) COMMENT '发文字号',
        publisher VARCHAR(255) COMMENT '发文机关',
        publish_date VARCHAR(32) COMMENT '印发日期',
        effective_date VARCHAR(32) COMMENT '实施日期',
        status VARCHAR(32) DEFAULT '现行有效' COMMENT '现行有效/已废止',
        url VARCHAR(512) NOT NULL UNIQUE COMMENT '官方原文直链',
        summary TEXT COMMENT '核心要点摘要',
        content_text MEDIUMTEXT COMMENT '政策正文纯文本',
        attachments_json TEXT COMMENT '相关附件/政策解读公文',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_category (category),
        INDEX idx_pub_date (publish_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='政策法规库表';
    """
]

def init_sqlite(db_path, reset=False):
    """初始化或重置 SQLite 数据库"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if reset:
        for t in ["applications", "notices", "batches", "projects", "policies"]:
            cur.execute(f"DROP TABLE IF EXISTS {t};")
    for ddl in SQLITE_TABLES:
        cur.execute(ddl)
    conn.commit()
    conn.close()
    print(f"[SQLite] 初始化完成: {db_path} (reset={reset})")

def init_mysql(mysql_cfg, reset=False):
    """初始化或重置 MySQL 数据库"""
    conn = pymysql.connect(
        host=mysql_cfg["host"],
        port=mysql_cfg["port"],
        user=mysql_cfg["user"],
        password=mysql_cfg["password"],
        database=mysql_cfg["database"],
        charset=mysql_cfg.get("charset", "utf8mb4"),
        autocommit=False
    )
    cur = conn.cursor()
    if reset:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
        for t in ["applications", "notices", "batches", "projects", "policies"]:
            cur.execute(f"DROP TABLE IF EXISTS {t};")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
    for ddl in MYSQL_TABLES:
        cur.execute(ddl)
    conn.commit()
    cur.close()
    conn.close()
    print(f"[MySQL] 初始化完成: {mysql_cfg['database']} (reset={reset})")

if __name__ == "__main__":
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sqlite_path = root / "data" / "housing.db"
    cfg_path = root / "config" / "database.json"

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    admin_cfg = {
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg["admin"]["user"],
        "password": cfg["admin"]["password"],
        "database": cfg["database"],
        "charset": cfg.get("charset", "utf8mb4")
    }

    # 执行重置与全新建表
    init_sqlite(sqlite_path, reset=True)
    init_mysql(admin_cfg, reset=True)
