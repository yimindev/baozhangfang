#!/usr/bin/env python3
"""
db.py - 运行库路径解析与种子库自举工具

数据文件约定:
  - data/seed.sql   : 纳入 Git 版本管理的只读种子（已脱敏的 SQL 文本导出），仅在发版时通过 export_seed.py 刷新
  - data/housing.db : 运行时工作库（被 .gitignore 忽略），所有查询与增量同步均读写此文件

首次使用时若 housing.db 不存在，则自动由 seed.sql 导入生成，实现开箱即用。
"""

import sqlite3
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_ROOT / "data"
DB_PATH = DATA_DIR / "housing.db"
SEED_PATH = DATA_DIR / "seed.sql"


def bootstrap(force: bool = False) -> Path:
    """确保运行库存在；不存在（或 force=True）时由种子 SQL 导入重建。"""
    if DB_PATH.exists() and not force:
        return DB_PATH
    if not SEED_PATH.exists():
        # 无种子时交由调用方（如 schema.py）建空表
        return DB_PATH

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = DB_PATH.with_suffix(".db.tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    tmp_path.replace(DB_PATH)
    print(f"[*] 已由种子库初始化运行库: {DB_PATH}", file=sys.stderr)
    return DB_PATH


def get_db_path() -> Path:
    """返回可用的运行库路径（必要时自动自举）。"""
    return bootstrap()


def connect() -> sqlite3.Connection:
    """获取运行库连接（必要时自动自举）。"""
    return sqlite3.connect(get_db_path())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="由 seed.sql 初始化运行库 housing.db")
    parser.add_argument("--force", action="store_true", help="覆盖已有 housing.db，强制由种子重建")
    args = parser.parse_args()
    print(bootstrap(force=args.force))
