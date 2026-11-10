#!/usr/bin/env python3
"""
export_seed.py - 由运行库 housing.db 导出脱敏种子 seed.sql（发版时手动执行）

- 输出为确定性的 SQL 文本（sqlite3 iterdump），便于 Git diff 与审计
- 含个人信息的表仅保留表结构、不导出任何数据行（见 PII_TABLES）
- 日常增量同步只写 housing.db，不会改动 seed.sql；仅当需要发布新基线时运行本脚本并提交
"""

import argparse
import sqlite3
import sys

from db import DB_PATH, SEED_PATH

# 含个人姓名/证件号等隐私字段的表：种子中只保留结构
PII_TABLES = ["households", "members", "applications"]


def export_seed() -> None:
    if not DB_PATH.exists():
        print(f"[ERROR] 运行库不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    src = sqlite3.connect(DB_PATH)
    mem = sqlite3.connect(":memory:")
    src.backup(mem)
    src.close()

    cur = mem.cursor()
    existing = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for tbl in PII_TABLES:
        if tbl in existing:
            cur.execute(f"DELETE FROM {tbl}")
    if "sqlite_sequence" in existing:
        cur.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({','.join('?' * len(PII_TABLES))})",
            PII_TABLES,
        )
    mem.commit()

    with open(SEED_PATH, "w", encoding="utf-8", newline="\n") as f:
        for line in mem.iterdump():
            f.write(line + "\n")

    stats = []
    for tbl in ["projects", "batches", "notices", "policies"]:
        if tbl in existing:
            stats.append(f"{tbl}={cur.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]}")
    mem.close()
    print(f"[SUCCESS] 种子已导出: {SEED_PATH} ({', '.join(stats)}；已剔除 {', '.join(PII_TABLES)} 数据)")


if __name__ == "__main__":
    argparse.ArgumentParser(description="导出脱敏种子 seed.sql").parse_args()
    export_seed()
