# AGENTS.md

本仓库的唯一交付物是一个自包含 Agent Skill：`skills/baozhangfang/`。它为 AI 提供一套保障性住房台账（项目 / 批次 / 公文 / 政策），让 AI 能直接写 SQL 回答用户问题，并按手册持续同步新公告。

## 权威来源

| 关注点 | 唯一权威 |
| :-- | :-- |
| 同步流程与判断准则 | `skills/baozhangfang/references/sync_playbook.md` |
| 表结构、枚举、状态机 | `skills/baozhangfang/references/database_schema.md` |
| 检索 SQL 模板 | `skills/baozhangfang/references/query_cheatsheet.md` |
| 新增城市 / 区县数据源 | `skills/baozhangfang/references/sources_guide.md` |
| 技能入口与工作流大纲 | `skills/baozhangfang/SKILL.md` |
| 数据源配置 | `skills/baozhangfang/config/sources.json` |

目录速览：`skills/baozhangfang/{config,data,scripts,references}`；根目录 `scripts/`、`config/` 是可选扩展工具，不属于 Skill 运行时。

## 设计原则（不可违背）

1. **Skill 自包含**：`skills/baozhangfang/` 必须能整目录拷走后独立运行，只依赖内部 `data/housing.db`（由 `data/seed.sql` 自举）；禁止依赖外部 MySQL / RDS / 目录外凭据。MySQL 桥接只存在于根目录 `scripts/sync_to_mysql.py`，Skill 内不得引用。
2. **脚本原子化，判断归 Agent**：脚本只做「抓列表 / 抓正文 / 读写一条记录」。不在脚本里写关键词白名单、正则推断、分类规则或状态机硬编码；相关性判断、字段抽取、批次归属、阶段推进全部由 Agent 按作业手册决定。
3. **唯一事实来源**：数据源只配 `config/sources.json`；同步脚本只在 `skills/baozhangfang/scripts/`；全项目只有一个数据库 `data/housing.db`。不得在根目录新增重复实现、配置或数据库副本。文档同理——细节只写在一处，其他位置用链接。
4. **多城市、无硬编码**：架构与表结构中禁止把深圳写死；`city` / `district` 为必备分区字段；新城市只加声明式配置。
5. **标准库优先、最小依赖**：优先 `sqlite3` / `json` / `pathlib` / `re` / `argparse` / `datetime`；抓取只用 `requests` + `beautifulsoup4`；PDF 解析按需用 `pypdf` / `pdfplumber`。拒绝过度封装。
6. **隐私与凭据红线**：不提交 `config/database.json`、任何密钥或 Token；不提交 `housing.db`；`seed.sql` 只能由 `export_seed.py` 生成（自动剔除 `households` / `members` / `applications` 数据行）；提交前用 `git status`、`git check-ignore` 复核。
7. **中文与提交规范**：文档、注释、提示一律中文；提交遵循 Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:`）。

## 数据模型要点

`schema.py` 定义 5 张表：`projects`（物理楼盘，按 `(city, project_name)` 唯一）、`batches`（推售批次，主键 `batch_id`）、`notices`（公文流水，`url` 唯一）、`policies`（政策法规）、`applications`（申购家庭，含 PII）。
`seed.sql` 另带历史表 `households` / `members`（PII，仅保留结构）与 `projects_pipeline`（历史管线数据，`schema.py` 未定义，改动前先确认影响面）。

批次阶段单向推进、不降级：

```text
认购中(subscribing) → 认购名单已出 → 选房签约中(selecting) → 常态化配售中(regular) / 已完成选房(completed)
```

新通告权重不高于当前阶段时，只追加时间线事件，不改 `current_stage`。

## 操作要点

- **运行库**：`data/housing.db` 被 Git 忽略；不存在时脚本会自动由 `seed.sql` 自举，也可显式运行 `python3 skills/baozhangfang/scripts/db.py`。
- **查询**：不封装查询脚本，按需求直接写 SQL（`db_io.py query "<SQL>"` 或 `sqlite3`），模板见 `query_cheatsheet.md`。
- **同步**：先读 `sync_playbook.md`，流程为 `fetch_list.py` → `db_io.py diff` → `fetch_detail.py` → Agent 判断 → `db_io.py upsert-*` / `append-timeline`。所有写入幂等（notice 按 `district+title+publish_date` → `url`，batch 按 `batch_id`，project 按 `(city, project_name)`），可放心重跑。
- **增量判定**：不引入水位线表，每次抓最近 1–2 页用 `diff` 判 new/known。
- **改动前后自检**：动 schema 或抓取规则前先跑 `db_io.py stats --city 深圳` 记录基线，改完复跑核对条数无异常下降；源配置调整后用 `audit_sources.py --city 深圳` 验收。
- **基线发布**：日常同步只写 `housing.db`；仅发版时运行 `export_seed.py` 刷新并提交 `seed.sql`。
- **临时产物**：PDF、表格、中间 JSON 一律放 `/tmp`，仓库根目录不留测试脚本或输出。

## 文档职责

| 文件 | 面向 | 写什么 |
| :-- | :-- | :-- |
| `README.md` | 用户 | 项目是什么、有什么数据、怎么用，保持简短 |
| `AGENTS.md` | AI 助手 | 事实、权威文档索引、设计原则与红线 |
| `SKILL.md` + `references/` | 运行时 Agent | 作业流程、表字典、SQL 模板、源接入 |
| 过程性文档（评审、整改方案、调研记录） | 临时 | 不写入上述文档，不作为常驻文档提交 |
