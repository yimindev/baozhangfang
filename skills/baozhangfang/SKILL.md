---
name: baozhangfang
description: >-
  保障性住房（人才配售房、安居型商品房、共有产权房、配售型保障房、公共租赁住房）全流程数据同步与资产台账专家。
  采用自包含架构与纯嵌入式 SQLite 存储，原生支持多城市水平扩展（现已深度适配深圳，预留广州、北京等城市接口）。
  当用户询问保障房楼盘房源（如华越龙苑、深铁熙府、深铁璟城、缙熙园等）、查询常态化即时配售房源、两房/三房/四房套数与配售均价、
  追踪住建局公文生命周期演进（认购/审核/摇号/选房）、执行数据同步刷新、或接入新城市保障房数据源时，务必使用此技能。
---

# 保障房全流程数据同步与资产台账专家 (`baozhangfang`)

`baozhangfang` 是一个**自包含、零外部服务依赖**的保障性住房数据工具集。它以官方政务公开公文为基准，
解耦物理资产与业务推售，管理五大核心台账：**物理项目大盘 (`projects`)**、**推售批次台账 (`batches`)**、
**公文事件流水 (`notices`)**、**政策法规规约 (`policies`)**、**申购名册与家庭审核 (`households` / `members` / `applications`)**。

**设计原则：脚本原子化，流程 Agent 化。** 脚本只做三件小事——抓列表、抓正文、读写一条记录；
「哪些公文相关、要不要抓全文、字段怎么读、批次怎么挂、阶段怎么推」全部由 Agent 依
[同步作业手册](references/sync_playbook.md) 判断。**不要在脚本里加关键词白名单、正则推断或状态机硬编码。**

---

## 架构

```
skills/baozhangfang/
├── SKILL.md                     # 入口说明书（当前文件）
├── config/sources.json          # 多城市采集源（sources=通知公告，policy_sources=政策法规）
├── data/
│   ├── seed.sql                 # 脱敏种子基线（版本管理，仅发版时刷新）
│   └── housing.db               # 运行时工作库（由 seed.sql 自举，不入库）
├── scripts/                     # 全部为原子工具
│   ├── fetch_list.py            # 抓列表 → JSON（不做任何判断）
│   ├── fetch_detail.py          # 抓正文 → 文本/附件/表格（不抽业务字段）
│   ├── db_io.py                 # 单记录读写：query/stats/watermark/known-urls/
│   │                            #   upsert-project/upsert-batch/upsert-notice/upsert-policy/append-timeline
│   ├── db.py                    # 运行库路径解析与种子自举
│   ├── schema.py                # DDL 建表与重置
│   └── export_seed.py           # 由运行库导出脱敏 seed.sql（发版用）
├── references/
│   ├── sync_playbook.md         # ★ 同步作业手册：判断准则与标准流程（Agent 必读）
│   ├── database_schema.md       # 表结构与状态机字典
│   ├── query_cheatsheet.md      # 业务检索 SQL 速查
│   └── sources_guide.md         # 多城市数据源接入规范
```

---

## 工作流 1：业务检索与问答（直接写 SQL）

数据库结构清晰规范。**不调用封装死板的固定脚本，直接探索表并编写 SQL**。

- **库路径**：`<SKILL_DIR>/data/housing.db`（全局技能路径为 `~/.agents/skills/baozhangfang/data/housing.db` 或工作区内 `skills/baozhangfang/data/housing.db`；不存在时先跑 `python3 <SKILL_DIR>/scripts/db.py` 由 seed 自举）
- **查询方式**：`python3 <SKILL_DIR>/scripts/db_io.py query "<SQL>"`，或 `sqlite3 -header -column <db> "<SQL>"`
- **隐私**：种子库不含 `households` / `members` / `applications` 数据行（含个人信息），需本地解析 PDF 名单导入

常用查询：

```sql
-- 某项目所有批次
SELECT p.project_name, p.district, b.batch_id, b.total_units, b.two_bedroom_units,
       b.three_bedroom_units, b.average_price, b.current_stage, b.sales_mode, b.consultation_phone
FROM projects p LEFT JOIN batches b ON p.id = b.project_id
WHERE p.project_name LIKE '%华越龙苑%' ORDER BY b.batch_id DESC;

-- 常态化即时配售（可现场交定金）
SELECT p.project_name, p.district, b.batch_id, b.total_units, b.average_price,
       b.current_stage, b.reception_location, b.consultation_phone
FROM batches b JOIN projects p ON b.project_id = p.id
WHERE b.has_regular_sales_exit = 1 OR b.current_stage = '常态化配售中'
ORDER BY p.district, b.average_price;

-- 户型与预算筛选
SELECT p.project_name, p.district, b.three_bedroom_units, b.average_price, b.current_stage, p.address
FROM batches b JOIN projects p ON b.project_id = p.id
WHERE p.district IN ('南山区','宝安区') AND b.three_bedroom_units > 0 AND b.average_price <= 40000
ORDER BY b.average_price;
```

回答规范：区分「公证集中摇号」与「常态化现场即时选房」；给全项目名、批次文号、阶段、户型套数、
配售均价、咨询电话、接待中心；必要时用 `notices` 里的公文标题与直链溯源。

---

## 工作流 2：数据同步（Agent 主导，脚本只做原子动作）

**完整规程见 [references/sync_playbook.md](references/sync_playbook.md)，执行前必读。** 核心骨架：

```bash
# 1) 水位线（参考起点，不是硬边界）
python3 <SKILL_DIR>/scripts/db_io.py watermark --city 深圳

# 2) 宽松抓列表：所有源第1页，不过滤关键词
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --pages 1 --format json

# 3) 与库内做差集
python3 <SKILL_DIR>/scripts/db_io.py known-urls --city 深圳 --since 2026-10-01

# 4) Agent 判断：哪些相关 / 哪些需要全文 → 列出待抓 URL

# 5) 抓正文（批量）
python3 <SKILL_DIR>/scripts/fetch_detail.py --url-file /tmp/todo_urls.txt --save-dir /tmp/bf_html

# 6) Agent 读正文抽要素，按 project → batch → notice → timeline 顺序写入
python3 <SKILL_DIR>/scripts/db_io.py upsert-project --name <项目名> --district <区>
python3 <SKILL_DIR>/scripts/db_io.py upsert-batch --batch-id "住保售〔2026〕083号批次" --project-id <id> --current-stage 认购中
python3 <SKILL_DIR>/scripts/db_io.py upsert-notice --url <url> --title "<标题>" --date 2026-11-09 \
        --district 市直属 --category 初审名单 --batch-id "住保售〔2026〕083号批次" --content-file /tmp/b1.txt
python3 <SKILL_DIR>/scripts/db_io.py append-timeline --batch-id "住保售〔2026〕083号批次" --stage 初审名单 \
        --title "<标题>" --date 2026-11-09 --url <url>

# 7) 自检
python3 <SKILL_DIR>/scripts/db_io.py stats --city 深圳
```

关键约定（细节见手册）：

- **列表不做关键词过滤**：脚本抓全，Agent 判相关性；模糊标题先抓正文再定。
- **套数/价格/电话以正文为准**，附件表格可用 `--tables` 辅助核对；找不到就留空，不凑数。
- **批次文号规范化** `住保售〔YYYY〕NNN号批次`（序号补零三位）；`住保租〔…〕` 是配租，不进 `batches`。
- **状态机单向不降级**：新通告权重 ≤ 当前权重时只追加时间线事件，不改 `current_stage`。
- **全部写入幂等**：按 URL / batch_id / (city, project_name) 去重，可放心重跑。

增量同步只写 `data/housing.db`，不改版本管理的 `seed.sql`；需要发布新基线时才跑
`python3 <SKILL_DIR>/scripts/export_seed.py`。

---

## 工作流 3：政策法规同步与查询

```bash
# 1) 抓取政策列表
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --channel policies --format table

# 2) 抓取政策正文
python3 <SKILL_DIR>/scripts/fetch_detail.py <url> --text-only

# 3) 写入政策法规库
python3 <SKILL_DIR>/scripts/db_io.py upsert-policy --url <url> --title "<政策标题>" \
        --category 地方性法规 --publisher 深圳市住房和建设局 --date 2026-08-01 --content-file /tmp/p1.txt
```

- 现行库内 35 部法规全文，含《深圳市保障性住房条例》《配售型保障性住房管理办法》等。
- 检索条款：`SELECT title, publisher, publish_date, document_number, url FROM policies WHERE content_text LIKE '%全日制本科%' OR content_text LIKE '%单身%' ORDER BY publish_date DESC;`
- 政策分类（`policies.category`）由 Agent 依据文件内容填写，脚本不再自动分类。

---

## 工作流 4：多城市扩展

1. 读 [references/sources_guide.md](references/sources_guide.md) 确认接入协议；
2. 在 `config/sources.json` 的 `cities` 下追加该城市的 `sources`（通知公告）与 `policy_sources`（政策）；
3. 直接执行 `python3 <SKILL_DIR>/scripts/fetch_list.py --city 广州`，写入时 `db_io.py` 一律带 `--city 广州`，
   数据天然按城市隔离。

---

## 详细参考索引

- ★ [同步作业手册（判断准则 + 标准流程）](references/sync_playbook.md) `sync_playbook.md`
- [数据表结构与状态机字典](references/database_schema.md) `database_schema.md`
- [业务检索 SQL 速查](references/query_cheatsheet.md) `query_cheatsheet.md`
- [多城市数据源接入规范](references/sources_guide.md) `sources_guide.md`
