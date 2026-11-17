---
name: baozhangfang
description: >-
  保障性住房（配售型、安居型、人才房、共有产权、公租房）全流程台账与政务数据同步助手。
  当用户查询保障房项目房源、户型套数、配售均价、常态化配售、申购资格政策、批次与申购家庭流转状态，
  或需要同步住建局公告与附件、接入新城市数据源时使用。
compatibility: >-
  Python 3.9+；纯查库与写库零第三方依赖。联网抓取与巡检需系统命令 curl 及 beautifulsoup4；
  解析 PDF/XLS 附件按需使用 pdfplumber/pypdf/xlrd（XLSX/DOCX 内置标准库兜底）。
---

# 保障房全流程台账与数据同步 (`baozhangfang`)

`baozhangfang` 是一个**自包含、零外部服务依赖**的保障性住房台账技能，使用嵌入式 SQLite 存储（首次运行自动由 `data/seed.sql` 自举），原生支持多城市扩展（现已深度适配深圳，可在 `config/sources.json` 按声明式配置接入广州、北京等城市）。

以官方政务公文为唯一事实来源，管理五大台账：**物理项目 (`projects`)**、**推售批次与楼盘房源 (`batches` / `batch_projects`)**、**公文流水 (`notices`)**、**政策法规 (`policies`)**、**申购家庭流转 (`applications`)**。

**核心原则：脚本原子化，流程 Agent 化。** 脚本只做「抓列表 / 抓正文与附件 / 参数化读写」；相关性判定、附件取舍、字段抽取、批次归属、阶段推进均由 Agent 依 [同步作业手册](references/sync_playbook.md) 决策，脚本内不写关键词白名单或状态机硬编码。

---

## 运行环境与依赖

| 场景 | 涉及脚本 | 依赖要求 |
| :--- | :--- | :--- |
| 查库、写库、种子自举/导出 | `db.py`、`db_io.py`、`schema.py`、`export_seed.py` | **零第三方依赖**（纯 Python 标准库） |
| 抓取列表、正文与巡检 | `fetch_list.py`、`fetch_detail.py`、`audit_sources.py` | 系统 `curl` + `beautifulsoup4` |
| 按需抽取附件内容 | `fetch_detail.py` | **PDF**：`pdfplumber`（优先，支持 `--tables`）或 `pypdf`<br>**XLSX**：`openpyxl`（未安装时自动走内置标准库兜底）<br>**DOCX**：纯标准库支持；**XLS**：需 `xlrd` |

依赖清单见 [requirements.txt](requirements.txt)（安装必需项：`pip install -r <SKILL_DIR>/requirements.txt`）。

---

## 目录结构

```text
skills/baozhangfang/
├── SKILL.md                     # 技能入口与工作流大纲（本文件）
├── requirements.txt             # Python 依赖声明
├── config/sources.json          # 多城市采集源（sources=通知公告，policy_sources=政策法规）
├── data/
│   ├── seed.sql                 # 脱敏种子基线（版本管理，仅发版时刷新）
│   └── housing.db               # 运行时工作库（由 seed.sql 自举，不入 Git）
├── scripts/                     # 原子工具脚本
│   ├── fetch_list.py            # 抓列表 → JSON（不做过滤与判断）
│   ├── fetch_detail.py          # 抓正文/附件（HTML/PDF/XLSX/DOCX）→ 文本/附件直链/表格
│   ├── db_io.py                 # 原子读写：query/stats/latest/known-urls/diff/
│   │                            #   upsert-project/upsert-batch/link-batch-project/
│   │                            #   upsert-notice/upsert-policy/upsert-application(s)/append-timeline
│   ├── audit_sources.py         # 定期巡检：API / 库内 / 重复 / UI 四向对照
│   ├── db.py                    # 运行库路径解析与种子自举
│   ├── schema.py                # DDL 建表与迁移
│   └── export_seed.py           # 导出脱敏 seed.sql（发版用）
└── references/
    ├── sync_playbook.md         # ★ 同步作业手册：判断准则与标准流程（同步前必读）
    ├── database_schema.md       # 表结构、枚举与状态机字典
    ├── query_cheatsheet.md      # 业务检索 SQL 模板速查
    └── sources_guide.md         # 多城市数据源接入规范
```

---

## 工作流 1：业务检索与问答（直接写 SQL）

直接编写 SQL 查询 `<SKILL_DIR>/data/housing.db`（不存在时先跑 `python3 <SKILL_DIR>/scripts/db.py` 自举）：

```bash
python3 <SKILL_DIR>/scripts/db_io.py query "<SQL>"
# 或：sqlite3 -header -column <SKILL_DIR>/data/housing.db "<SQL>"
```

- **查模板**：常见检索（单盘历次批次、常态化配售、户型/预算筛选、政策条款、申购名单）见 [references/query_cheatsheet.md](references/query_cheatsheet.md)，表字段与状态机见 [references/database_schema.md](references/database_schema.md)。
- **关键注意**：套数、户型、均价记在 `batch_projects`（一批次可能推售多个楼盘），不要只查 `batches`；查项目名称时同时匹配 `projects.aliases`；种子库不含 `applications` / `households` / `members`（含个人隐私信息），需本地同步解析导入。
- **回答规范**：明确区分「公证集中摇号」与「常态化现场即时选房」；给出全项目名、批次文号、当前阶段、户型套数、配售均价、咨询电话与接待中心，必要时附 `notices` 公文标题与直链溯源。

---

## 工作流 2：数据同步（Agent 主导）

**执行同步前先读 [references/sync_playbook.md](references/sync_playbook.md)**，核心骨架如下：

```bash
# 1) 查看库内最新日期（仅作参考，不是增量游标）
python3 <SKILL_DIR>/scripts/db_io.py latest --city 深圳

# 2) 宽松抓列表（不过滤关键词）并与库内做差集
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --pages 1 --out /tmp/todo.json --summary
python3 <SKILL_DIR>/scripts/db_io.py diff --city 深圳 --input /tmp/todo.json --format lines

# 3) Agent 判相关性并抓正文；对名单/摇号/选房或缺失要素的房源价格附件，按需加 --tables 抽取
python3 <SKILL_DIR>/scripts/fetch_detail.py --url-file /tmp/todo_urls.txt --save-dir /tmp/bf_html
python3 <SKILL_DIR>/scripts/fetch_detail.py <附件URL> --tables

# 4) 按外键顺序写入：project → batch → link-batch-project → notice → timeline → applications
python3 <SKILL_DIR>/scripts/db_io.py upsert-project --name <项目名> --district <区> --aliases "<异名>"
python3 <SKILL_DIR>/scripts/db_io.py upsert-batch --batch-id "住保售〔2026〕083号批次" --project-id <id> --current-stage 认购中
python3 <SKILL_DIR>/scripts/db_io.py link-batch-project --batch-id "住保售〔2026〕083号批次" --project-id <id> --units <套数> --average-price <均价>
python3 <SKILL_DIR>/scripts/db_io.py upsert-notice --url <url> --title "<标题>" --date YYYY-MM-DD --district <区> --batch-id "<批次>" --content-file /tmp/body.txt
python3 <SKILL_DIR>/scripts/db_io.py append-timeline --batch-id "<批次>" --stage <阶段> --title "<标题>" --date YYYY-MM-DD --url <url>
python3 <SKILL_DIR>/scripts/db_io.py upsert-applications --batch-id "<批次>" --input /tmp/apps.json --notice-url <附件URL> --notice-stage <阶段> --notice-date YYYY-MM-DD

# 5) 写入后自检；定期可用 audit_sources.py 做全源巡检
python3 <SKILL_DIR>/scripts/db_io.py stats --city 深圳
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳
```

所有写入均为幂等操作（`publish_date` 一律取 `fetch_list` 列表日期；阶段单向推进不降级）。日常增量只写 `data/housing.db`，仅发版刷新基线时运行 `export_seed.py`。

---

## 工作流 3：政策法规同步

```bash
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --channel policies --pages 1 --out /tmp/policies.json --summary
python3 <SKILL_DIR>/scripts/db_io.py diff --city 深圳 --channel policies --input /tmp/policies.json --format lines
python3 <SKILL_DIR>/scripts/fetch_detail.py <url> --text-only
python3 <SKILL_DIR>/scripts/db_io.py upsert-policy --url <url> --title "<政策标题>" --category <分类> --publisher <机关> --date YYYY-MM-DD --content-file /tmp/p1.txt
```

---

## 工作流 4：多城市扩展

1. 查阅 [references/sources_guide.md](references/sources_guide.md) 确认源协议与配置格式；
2. 在 [config/sources.json](config/sources.json) 的 `cities` 下追加目标城市的 `sources` 与 `policy_sources`；
3. 同步与写入时统一传入 `--city <城市名>`，数据天然按城市隔离。

---

## 详细参考索引

- ★ [同步作业手册（判断准则与完整流程）](references/sync_playbook.md)
- [数据表结构与状态机字典](references/database_schema.md)
- [业务检索 SQL 速查](references/query_cheatsheet.md)
- [多城市数据源接入规范](references/sources_guide.md)
