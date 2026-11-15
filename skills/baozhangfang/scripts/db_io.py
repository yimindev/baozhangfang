#!/usr/bin/env python3
"""
db_io.py - 数据库读写原子操作（原子工具）

职责边界：
  只提供「一条记录级别」的读写原语，全部参数化、不带任何业务推断。
  批次阶段怎么推、通告归到哪个批次、项目怎么匹配，由 Agent 判断后显式传入。

子命令：
  query           执行只读 SQL（SELECT/WITH/PRAGMA），输出 table/json/tsv
  stats           各表行数与最新公文日期
  latest          库内最新公文日期（派生查询，可按 --district 过滤）
  known-urls      导出已入库 URL（lines/json，支持 notices/policies）
  diff            fetch_list 结果与库内记录做差集（new/known，支持 notices/policies）
  upsert-project  建/改项目（按 city + project_name 唯一）
  upsert-batch    建/改推售批次（按 batch_id 唯一）
  upsert-notice   建/改公文（按 district+归一化标题+publish_date → url 两级去重）
  upsert-policy   建/改政策法规规约（按 city+归一化标题+date → url 两级去重）
  append-timeline 给批次的 notices_json 追加一条事件

示例：
  python3 scripts/db_io.py stats
  python3 scripts/db_io.py latest --city 深圳
  python3 scripts/db_io.py latest --city 深圳 --district 盐田区
  python3 scripts/db_io.py query "SELECT project_name, district FROM projects LIMIT 5"
  python3 scripts/db_io.py known-urls --since 2026-10-01
  python3 scripts/db_io.py upsert-project --name 星河开市客环球商业中心 --district 龙华区
  python3 scripts/db_io.py upsert-batch --batch-id "住保售〔2026〕054号批次" --project-id 84 \\
      --current-stage 选房签约中 --total-units 300 --average-price 28000
  python3 scripts/db_io.py upsert-notice --url https://... --title "..." --date 2026-11-10 \\
      --district 光明区 --category 综合公告 --batch-id "" --content-file /tmp/body.txt
  python3 scripts/db_io.py upsert-policy --url https://... --title "..." --category 规章 \\
      --publisher 深圳市人民政府 --date 2026-08-01 --content-file /tmp/policy.txt
"""

import argparse
import json
import re
import signal
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import get_db_path

BATCH_FIELDS = ["project_id", "district", "batch_seq", "housing_type", "total_units",
                "one_bedroom_units", "two_bedroom_units", "three_bedroom_units",
                "four_bedroom_units", "other_units", "average_price", "deposit_amount",
                "sales_mode", "has_regular_sales_exit", "reception_location",
                "consultation_phone", "booking_channel", "sub_start_date",
                "sub_end_date", "current_stage", "notices_json"]

PROJECT_FIELDS = ["district", "subdistrict", "developer", "housing_type",
                  "total_planned_units", "planned_area", "address", "status",
                  "aliases"]

NOTICE_FIELDS = ["district", "project_id", "batch_id", "category", "title",
                 "publish_date", "summary", "content_text", "attachments_json"]

POLICY_FIELDS = ["category", "title", "document_number", "publisher", "publish_date",
                 "effective_date", "status", "summary", "content_text", "attachments_json"]


def connect(read_only: bool = False) -> sqlite3.Connection:
    db_p = get_db_path().resolve()
    if read_only:
        uri = f"file:{db_p}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_p)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_title(title: str) -> str:
    """标题同一化：全半角统一、中英文括号统一、去掉全部空白。

    仅用于去重比对，不改写库内保存的原始标题；不做模糊匹配或同义词映射。
    """
    s = unicodedata.normalize("NFKC", title or "")
    s = s.replace("[", "〔").replace("]", "〕")
    return re.sub(r"\s+", "", s)


def normalize_aliases(raw: str) -> str:
    """把逗号分隔或 JSON 数组的别名规范为 JSON 数组文本。"""
    s = (raw or "").strip()
    if not s:
        return "[]"
    if s.startswith("["):
        try:
            items = json.loads(s)
        except json.JSONDecodeError:
            raise ValueError(f"别名 JSON 非法：{raw!r}") from None
        if not isinstance(items, list):
            raise ValueError(f"别名 JSON 必须是数组：{raw!r}")
    else:
        items = re.split(r"[,，;；]", s)
    result: List[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"别名必须为字符串：{item!r}")
        v = item.strip()
        if v and v not in result:
            result.append(v)
    return json.dumps(result, ensure_ascii=False)


def alias_list(text: str) -> List[str]:
    """读取库内别名 JSON；非法内容按空列表处理，不让脏数据中断主流程。"""
    try:
        arr = json.loads(text or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(arr, list):
        return []
    return [str(a).strip() for a in arr if str(a).strip()]


def find_project(conn: sqlite3.Connection, city: str, name: str):
    """先按标准名精确匹配，再按别名精确匹配。

    返回 (row, "name"|"alias")；未命中返回 (None, None)；
    同名别名命中多个项目时抛 LookupError，由 Agent 决策，不做静默选取。
    """
    name = (name or "").strip()
    row = conn.execute(
        "SELECT id, project_name, aliases FROM projects WHERE city = ? AND project_name = ?",
        (city, name)).fetchone()
    if row:
        return row, "name"

    hits = []
    for r in conn.execute(
            "SELECT id, project_name, aliases FROM projects WHERE city = ? AND aliases IS NOT NULL AND aliases <> ''",
            (city,)):
        if name in alias_list(r["aliases"]):
            hits.append(r)
    if len(hits) == 1:
        return hits[0], "alias"
    if len(hits) > 1:
        detail = ", ".join(f"{r['id']}:{r['project_name']}" for r in hits)
        raise LookupError(f"名称 {name!r} 同时命中多个项目（{detail}），请确认归属后重试")
    return None, None


def normalize_date(value: str) -> str:
    """校验日期并规范为 YYYY-MM-DD；非法时抛 ValueError。"""
    v = (value or "").strip().replace("/", "-").replace(".", "-")
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", v)
    if m:
        v = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    try:
        return datetime.strptime(v, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"日期格式非法：{value!r}，应为 YYYY-MM-DD") from None


def dump(rows, fmt: str = "table") -> None:
    rows = [dict(r) for r in rows]
    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if fmt == "tsv":
        if not rows:
            return
        print("\t".join(rows[0].keys()))
        for r in rows:
            print("\t".join("" if v is None else str(v) for v in r.values()))
        return
    if not rows:
        print("(empty)")
        return

    def cell(v):
        return "" if v is None else str(v)

    cols = list(rows[0].keys())
    width = {c: max(len(c), *(len(cell(r.get(c))) for r in rows)) for c in cols}
    print("  ".join(c.ljust(width[c]) for c in cols))
    print("  ".join("-" * width[c] for c in cols))
    for r in rows:
        print("  ".join(cell(r.get(c)).ljust(width[c]) for c in cols))


# ---------------- 读 ----------------

def cmd_query(args) -> int:
    head = args.sql.strip().split()[0].lower() if args.sql.strip() else ""
    if head not in ("select", "with", "pragma", "explain") and not args.write:
        print("[拒绝] 只读子命令只允许 SELECT/WITH/PRAGMA；确需写入请加 --write", file=sys.stderr)
        return 2

    try:
        conn = connect(read_only=not args.write)
    except Exception as exc:
        print(f"[错误] 打开数据库失败: {exc}", file=sys.stderr)
        return 1

    try:
        cur = conn.execute(args.sql, args.param or [])
        if cur.description:
            dump(cur.fetchall(), args.format)
        else:
            if args.write:
                conn.commit()
            print(f"[ok] affected={cur.rowcount}")
    except sqlite3.OperationalError as exc:
        if "readonly" in str(exc).lower():
            print("[拒绝] 当前为只读模式，禁止写入操作（确需执行写 SQL 请添加 --write 参数）", file=sys.stderr)
            return 2
        print(f"[SQL 错误] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[执行错误] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


def cmd_stats(args) -> int:
    conn = connect(read_only=True)
    try:
        city_where = " WHERE city = ?" if args.city else ""
        params = [args.city] if args.city else []
        out = {}
        for tbl in ("projects", "batches", "notices", "policies", "households", "members", "applications"):
            try:
                cur = conn.execute(f"PRAGMA table_info({tbl})")
                cols = [r["name"] for r in cur.fetchall()]
                if not cols:
                    out[tbl] = None
                    continue
                if args.city and "city" in cols:
                    out[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}{city_where}", params).fetchone()[0]
                elif not args.city:
                    out[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                else:
                    out[tbl] = None
            except sqlite3.Error:
                out[tbl] = None
        out["latest_notice"] = conn.execute(
            f"SELECT MAX(publish_date) FROM notices{city_where}", params).fetchone()[0]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


def cmd_latest(args) -> int:
    """库内最新公文日期（派生查询）。不是同步游标，增量判断以 diff 为准。"""
    conn = connect(read_only=True)
    try:
        sql = "SELECT MAX(publish_date) FROM notices WHERE city = ?"
        params = [args.city]
        if getattr(args, "district", None):
            sql += " AND district = ?"
            params.append(args.district)
        row = conn.execute(sql, params).fetchone()
        print(row[0] or "")
    finally:
        conn.close()
    return 0


def cmd_known_urls(args) -> int:
    conn = connect(read_only=True)
    try:
        if args.channel == "policies":
            sql = "SELECT url, title, publish_date FROM policies WHERE city = ?"
        else:
            sql = "SELECT url, title, publish_date, district FROM notices WHERE city = ?"
        params = [args.city]
        if args.since:
            sql += " AND publish_date >= ?"
            params.append(args.since)
        rows = conn.execute(sql, params).fetchall()
        if args.format == "json":
            print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(r["url"])
    finally:
        conn.close()
    return 0


def cmd_diff(args) -> int:
    """把 fetch_list 的 JSON 与库内记录做差集。

    notices：按 URL 或 city+district+归一化标题+publish_date 判定；
    policies：按 URL 或 city+归一化标题+publish_date 判定（政策表无 district）。
    标题只做全半角/括号/空白同一化，日期按原始字符串精确比对，不做天数容差。
    """
    if args.input in (None, "-"):
        raw = sys.stdin.read()
    else:
        raw = Path(args.input).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f"[错误] 无法解析输入 JSON：{exc}", file=sys.stderr)
        return 2
    items = data.get("items", []) if isinstance(data, dict) else data
    channel = getattr(args, "channel", "notices")

    conn = connect(read_only=True)
    try:
        if channel == "policies":
            urls = {r["url"] for r in conn.execute(
                "SELECT url FROM policies WHERE city = ?", (args.city,))}
            keys = {(normalize_title(r["title"]), r["publish_date"] or "") for r in conn.execute(
                "SELECT title, publish_date FROM policies WHERE city = ?", (args.city,))}
        else:
            urls = {r["url"] for r in conn.execute(
                "SELECT url FROM notices WHERE city = ?", (args.city,))}
            keys = {(r["district"] or "", normalize_title(r["title"]), r["publish_date"] or "")
                    for r in conn.execute(
                        "SELECT district, title, publish_date FROM notices WHERE city = ?", (args.city,))}

        new_items, known_items = [], []
        invalid = []
        for it in items:
            url = it.get("url") or ""
            date = it.get("date") or it.get("publish_date") or ""
            title = it.get("title") or ""
            district = it.get("district") or ""
            if not (url and title and date and (channel == "policies" or district)):
                invalid.append(it)
            title_key = normalize_title(title)
            if channel == "policies":
                hit = url in urls or (title_key, date) in keys
            else:
                hit = url in urls or (district, title_key, date) in keys
            (known_items if hit else new_items).append(it)
        if invalid:
            print(f"[warn] {len(invalid)} 条缺少 url/title/date/district，无法稳定判重，已按 new 处理",
                  file=sys.stderr)
    finally:
        conn.close()

    if args.format == "lines":
        for it in new_items:
            print(f"{it.get('date', '')}\t{it.get('district', '')}\t{it.get('title', '')}\t{it.get('url', '')}")
        return 0
    print(json.dumps({"city": args.city, "channel": channel, "total": len(items),
                      "new_count": len(new_items), "known_count": len(known_items),
                      "new": new_items, "known": known_items},
                     ensure_ascii=False, indent=2))
    return 0


# ---------------- 写 ----------------

def cmd_upsert_project(args) -> int:
    conn = connect()
    try:
        values = {k: getattr(args, k) for k in PROJECT_FIELDS if getattr(args, k, None) is not None}
        try:
            if "aliases" in values:
                values["aliases"] = normalize_aliases(values["aliases"])
            row, matched_by = find_project(conn, args.city, args.name)
        except (ValueError, LookupError) as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 2

        if row:
            pid = row["id"]
            if matched_by == "alias":
                # 命中别名时把本次名称并入别名，避免同一实体再被建一次
                merged = alias_list(row["aliases"])
                if args.name.strip() not in merged:
                    merged.append(args.name.strip())
                if "aliases" in values:
                    merged += [a for a in alias_list(values["aliases"]) if a not in merged]
                values["aliases"] = json.dumps(merged, ensure_ascii=False)
            if values:
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(f"UPDATE projects SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             [*values.values(), pid])
            action = "updated" if matched_by == "name" else "matched-alias"
            project_name = row["project_name"]
        else:
            cols = ["city", "project_name", *values.keys()]
            conn.execute(f"INSERT INTO projects ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [args.city, args.name, *values.values()])
            pid = conn.execute("SELECT id FROM projects WHERE city = ? AND project_name = ?",
                               (args.city, args.name)).fetchone()[0]
            action = "created"
            project_name = args.name
        conn.commit()
        print(json.dumps({"project_id": pid, "project_name": project_name,
                          "matched_by": matched_by, "action": action}, ensure_ascii=False))
    finally:
        conn.close()
    return 0


def cmd_upsert_batch(args) -> int:
    conn = connect()
    try:
        pid = args.project_id
        if not pid and args.project_name:
            try:
                row, _ = find_project(conn, args.city, args.project_name)
            except LookupError as exc:
                print(f"[错误] {exc}", file=sys.stderr)
                return 2
            if not row:
                print(f"[错误] 项目不存在：{args.project_name}，请先用 upsert-project 建档", file=sys.stderr)
                return 2
            pid = row["id"]

        values = {}
        for f in BATCH_FIELDS:
            v = getattr(args, f, None)
            if v is not None:
                values[f] = v

        # 别名兼容
        if args.stage is not None and "current_stage" not in values:
            values["current_stage"] = args.stage
        if args.price is not None and "average_price" not in values:
            values["average_price"] = args.price

        if pid:
            values["project_id"] = pid

        exists = conn.execute("SELECT 1 FROM batches WHERE batch_id = ?", (args.batch_id,)).fetchone()
        if exists:
            if not values:
                print("[warn] 没有需要更新的字段", file=sys.stderr)
            else:
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(f"UPDATE batches SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE batch_id = ?",
                             [*values.values(), args.batch_id])
            action = "updated"
        else:
            if not pid:
                print("[错误] 新建批次必须提供 --project-id 或 --project-name", file=sys.stderr)
                return 2
            cols = ["batch_id", "city", *values.keys()]
            conn.execute(f"INSERT INTO batches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [args.batch_id, args.city, *values.values()])
            action = "created"
        conn.commit()
        print(json.dumps({"batch_id": args.batch_id, "project_id": pid, "action": action,
                          "fields": sorted(values)}, ensure_ascii=False))
    finally:
        conn.close()
    return 0


def cmd_upsert_notice(args) -> int:
    try:
        date = normalize_date(args.date)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    conn = connect()
    try:
        pid = args.project_id
        if not pid and args.project_name:
            row = conn.execute("SELECT id FROM projects WHERE city = ? AND project_name = ?",
                               (args.city, args.project_name)).fetchone()
            pid = row[0] if row else None

        content = ""
        if args.content_file:
            content = Path(args.content_file).read_text(encoding="utf-8")
        elif args.content:
            content = args.content

        updatable = {}
        if args.title is not None:
            updatable["title"] = args.title
        if args.district is not None:
            updatable["district"] = args.district
        updatable["publish_date"] = date
        if args.category is not None:
            updatable["category"] = args.category
        if args.batch_id is not None:
            updatable["batch_id"] = args.batch_id.strip() if args.batch_id.strip() else None
        if pid is not None:
            updatable["project_id"] = pid
        if args.summary is not None:
            updatable["summary"] = args.summary.strip() if args.summary.strip() else None
        if content:
            updatable["content_text"] = content
            if args.summary is None and not updatable.get("summary"):
                updatable["summary"] = content[:120].replace("\n", " ")
        if args.attachments_json is not None:
            updatable["attachments_json"] = args.attachments_json.strip() if args.attachments_json.strip() else None

        title_key = normalize_title(args.title)
        exists = None
        if args.district:
            for row in conn.execute(
                    "SELECT id, url, title FROM notices "
                    "WHERE city = ? AND district = ? AND publish_date = ?",
                    (args.city, args.district, date)):
                if normalize_title(row["title"]) == title_key:
                    exists = row
                    break
        matched_by = "district+title+date" if exists else None
        if not exists:
            exists = conn.execute("SELECT id, url, title FROM notices WHERE url = ?", (args.url,)).fetchone()
            if exists:
                matched_by = "url"

        url_replaced = False
        if exists:
            nid, old_url = exists["id"], exists["url"]
            # 同一公告换了 gkmlpt 直链（专题页 URL → gkmlpt URL）时，把旧 URL 升级为 gkmlpt URL
            if old_url != args.url and "gkmlpt" in args.url and "gkmlpt" not in old_url:
                clash = conn.execute("SELECT 1 FROM notices WHERE url = ? AND id <> ?",
                                     (args.url, nid)).fetchone()
                if not clash:
                    updatable["url"] = args.url
                    url_replaced = True
            if updatable:
                sets = ", ".join(f"{k} = ?" for k in updatable)
                conn.execute(f"UPDATE notices SET {sets} WHERE id = ?", [*updatable.values(), nid])
            action = "updated"
        else:
            insert_data = {
                "city": args.city,
                "url": args.url,
                "title": args.title,
                "district": args.district,
                "publish_date": date,
                "category": args.category,
                "batch_id": args.batch_id.strip() if (args.batch_id and args.batch_id.strip()) else None,
                "project_id": pid,
                "summary": args.summary if args.summary is not None else (content[:120].replace("\n", " ") or None),
                "content_text": content or None,
                "attachments_json": args.attachments_json or None,
            }
            cur = conn.execute(f"INSERT INTO notices ({', '.join(insert_data)}) VALUES ({', '.join('?' * len(insert_data))})",
                               list(insert_data.values()))
            nid = cur.lastrowid
            action = "created"
        conn.commit()
        print(json.dumps({"notice_id": nid, "action": action, "matched_by": matched_by,
                          "url_replaced": url_replaced}, ensure_ascii=False))
    finally:
        conn.close()
    return 0


def cmd_upsert_policy(args) -> int:
    conn = connect()
    try:
        content = ""
        if args.content_file:
            content = Path(args.content_file).read_text(encoding="utf-8")
        elif args.content:
            content = args.content

        doc_no = args.doc_no if args.doc_no is not None else args.document_number
        pub_date = args.date if args.date is not None else args.publish_date
        if pub_date is not None:
            try:
                pub_date = normalize_date(pub_date)
            except ValueError as exc:
                print(f"[错误] {exc}", file=sys.stderr)
                return 2

        updatable = {}
        if args.title is not None:
            updatable["title"] = args.title
        if args.category is not None:
            updatable["category"] = args.category
        if doc_no is not None:
            updatable["document_number"] = doc_no.strip() if doc_no.strip() else None
        if args.publisher is not None:
            updatable["publisher"] = args.publisher
        if pub_date is not None:
            updatable["publish_date"] = pub_date
        if args.effective_date is not None:
            updatable["effective_date"] = args.effective_date
        if args.status is not None:
            updatable["status"] = args.status
        if args.summary is not None:
            updatable["summary"] = args.summary.strip() if args.summary.strip() else None
        if content:
            updatable["content_text"] = content
            if args.summary is None and not updatable.get("summary"):
                updatable["summary"] = content[:150].replace("\n", " ")
        if args.attachments_json is not None:
            updatable["attachments_json"] = args.attachments_json.strip() if args.attachments_json.strip() else None

        exists = None
        if pub_date:
            title_key = normalize_title(args.title)
            for row in conn.execute(
                    "SELECT id, url, title FROM policies WHERE city = ? AND publish_date = ?",
                    (args.city, pub_date)):
                if normalize_title(row["title"]) == title_key:
                    exists = row
                    break
        matched_by = "city+title+date" if exists else None
        if not exists:
            exists = conn.execute("SELECT id, url, title FROM policies WHERE url = ?", (args.url,)).fetchone()
            if exists:
                matched_by = "url"

        url_replaced = False
        if exists:
            pid, old_url = exists["id"], exists["url"]
            if old_url != args.url and "gkmlpt" in args.url and "gkmlpt" not in old_url:
                clash = conn.execute("SELECT 1 FROM policies WHERE url = ? AND id <> ?",
                                     (args.url, pid)).fetchone()
                if not clash:
                    updatable["url"] = args.url
                    url_replaced = True
            if updatable:
                sets = ", ".join(f"{k} = ?" for k in updatable)
                conn.execute(f"UPDATE policies SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             [*updatable.values(), pid])
            action = "updated"
        else:
            insert_data = {
                "city": args.city,
                "url": args.url,
                "title": args.title,
                "category": args.category,
                "document_number": doc_no.strip() if (doc_no and doc_no.strip()) else None,
                "publisher": args.publisher,
                "publish_date": pub_date,
                "effective_date": args.effective_date,
                "status": args.status or "现行有效",
                "summary": args.summary if args.summary is not None else (content[:150].replace("\n", " ") or None),
                "content_text": content or None,
                "attachments_json": args.attachments_json or None,
            }
            cur = conn.execute(f"INSERT INTO policies ({', '.join(insert_data)}) VALUES ({', '.join('?' * len(insert_data))})",
                               list(insert_data.values()))
            pid = cur.lastrowid
            action = "created"
        conn.commit()
        print(json.dumps({"policy_id": pid, "action": action, "matched_by": matched_by,
                          "url_replaced": url_replaced}, ensure_ascii=False))
    finally:
        conn.close()
    return 0


def cmd_append_timeline(args) -> int:
    conn = connect()
    try:
        row = conn.execute("SELECT notices_json FROM batches WHERE batch_id = ?", (args.batch_id,)).fetchone()
        if not row:
            print(f"[错误] 批次不存在：{args.batch_id}", file=sys.stderr)
            return 2
        try:
            events = json.loads(row[0]) if row[0] else []
        except Exception:
            events = []
        if any(e.get("url") == args.url for e in events):
            print(json.dumps({"batch_id": args.batch_id, "action": "skipped(duplicate)"}, ensure_ascii=False))
            return 0
        events.append({"stage": args.stage, "title": args.title, "date": args.date, "url": args.url})
        events.sort(key=lambda e: e.get("date") or "")
        conn.execute("UPDATE batches SET notices_json = ?, updated_at = CURRENT_TIMESTAMP WHERE batch_id = ?",
                     (json.dumps(events, ensure_ascii=False), args.batch_id))
        conn.commit()
        print(json.dumps({"batch_id": args.batch_id, "action": "appended", "events": len(events)},
                         ensure_ascii=False))
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="保障房数据库读写原子操作")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # 1. query
    p = sub.add_parser("query", help="只读 SQL（SELECT/WITH/PRAGMA）")
    p.add_argument("sql")
    p.add_argument("--param", nargs="*", default=None)
    p.add_argument("--format", default="table", choices=["table", "json", "tsv"])
    p.add_argument("--write", action="store_true", help="允许执行写 SQL（INSERT/UPDATE/DELETE/DDL）")
    p.set_defaults(func=cmd_query)

    # 2. stats
    p = sub.add_parser("stats", help="各表行数与最新公告日期")
    p.add_argument("--city", default=None)
    p.set_defaults(func=cmd_stats)

    # 3. latest（库内最新日期；watermark 为兼容别名）
    p = sub.add_parser("latest", help="库内最新公文日期（派生查询）")
    p.add_argument("--city", default="深圳")
    p.add_argument("--district", default=None)
    p.set_defaults(func=cmd_latest)

    p = sub.add_parser("watermark", help="已弃用：等同 latest（库内最新日期，无状态）")
    p.add_argument("--city", default="深圳")
    p.add_argument("--district", default=None)
    p.set_defaults(func=cmd_latest)

    # 4. known-urls
    p = sub.add_parser("known-urls", help="导出已入库 URL（notices/policies）")
    p.add_argument("--city", default="深圳")
    p.add_argument("--channel", default="notices", choices=["notices", "policies"])
    p.add_argument("--since", default=None)
    p.add_argument("--format", default="lines", choices=["lines", "json"])
    p.set_defaults(func=cmd_known_urls)

    p = sub.add_parser("diff", help="fetch_list 结果与库内做差集（new/known）")
    p.add_argument("--city", default="深圳")
    p.add_argument("--channel", default="notices", choices=["notices", "policies"])
    p.add_argument("--input", default="-", help="fetch_list 的 JSON 文件，默认从标准输入读取")
    p.add_argument("--format", default="json", choices=["json", "lines"])
    p.set_defaults(func=cmd_diff)

    # 5. upsert-project
    p = sub.add_parser("upsert-project", help="建/改项目（按 city + project_name 唯一）")
    p.add_argument("--city", default="深圳")
    p.add_argument("--name", required=True)
    for f in PROJECT_FIELDS:
        p.add_argument(f"--{f.replace('_', '-')}", dest=f, default=None,
                       help="项目别名：逗号分隔或 JSON 数组，存为 JSON" if f == "aliases" else None,
                       type=int if f in ("total_planned_units",) else (
                           float if f == "planned_area" else str))
    p.set_defaults(func=cmd_upsert_project)

    # 6. upsert-batch
    p = sub.add_parser("upsert-batch", help="建/改推售批次（按 batch_id 唯一）")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--city", default="深圳")
    p.add_argument("--project-id", type=int, default=None)
    p.add_argument("--project-name", default=None)
    p.add_argument("--stage", default=None, help="别名：--current-stage")
    p.add_argument("--price", type=float, default=None, help="别名：--average-price")
    int_fields = {"project_id", "batch_seq", "total_units", "one_bedroom_units",
                  "two_bedroom_units", "three_bedroom_units", "four_bedroom_units",
                  "other_units", "has_regular_sales_exit"}
    float_fields = {"average_price", "deposit_amount"}
    for f in BATCH_FIELDS:
        if f in ("project_id", "notices_json"):
            continue
        p.add_argument(f"--{f.replace('_', '-')}", dest=f, default=None,
                       type=int if f in int_fields else (float if f in float_fields else str))
    p.set_defaults(func=cmd_upsert_batch)

    # 7. upsert-notice
    p = sub.add_parser("upsert-notice", help="建/改公文（按 district+归一化标题+publish_date → url 去重）")
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--city", default="深圳")
    p.add_argument("--district", default=None)
    p.add_argument("--date", required=True, help="发布日期 YYYY-MM-DD，一律取 fetch_list 返回的列表日期")
    p.add_argument("--category", default=None)
    p.add_argument("--batch-id", default=None, help="传空串表示清空归属批次")
    p.add_argument("--project-id", type=int, default=None)
    p.add_argument("--project-name", default=None)
    p.add_argument("--summary", default=None)
    p.add_argument("--content-file", default=None)
    p.add_argument("--content", default=None)
    p.add_argument("--attachments-json", default=None)
    p.set_defaults(func=cmd_upsert_notice)

    # 8. upsert-policy
    p = sub.add_parser("upsert-policy", help="建/改政策法规（按 title+date → url 两级去重，标题做同一化）")
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--city", default="深圳")
    p.add_argument("--category", default=None)
    p.add_argument("--doc-no", default=None, help="发文字号")
    p.add_argument("--document-number", default=None, help="发文字号")
    p.add_argument("--publisher", default=None)
    p.add_argument("--date", default=None, help="印发/发布日期 YYYY-MM-DD")
    p.add_argument("--publish-date", default=None, help="印发/发布日期 YYYY-MM-DD")
    p.add_argument("--effective-date", default=None, help="实施日期 YYYY-MM-DD")
    p.add_argument("--status", default="现行有效", help="现行有效/已废止")
    p.add_argument("--summary", default=None)
    p.add_argument("--content-file", default=None)
    p.add_argument("--content", default=None)
    p.add_argument("--attachments-json", default=None)
    p.set_defaults(func=cmd_upsert_policy)

    # 9. append-timeline
    p = sub.add_parser("append-timeline", help="批次时间线追加事件")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--url", required=True)
    p.set_defaults(func=cmd_append_timeline)

    return ap


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    args = build_parser().parse_args()
    sys.exit(args.func(args))
