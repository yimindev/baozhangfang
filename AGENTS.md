# AGENTS.md

本文件为在此 **baozhangfang（保障房助手）** 代码库上工作的 AI 编程助手（Agent）提供操作与协作规范指引。

---

## 项目概述

**baozhangfang（保障房助手）** 是一个专注于政府保障性住房（人才配售房、安居型商品房、共有产权房、配售型保障房、公共租赁住房）的全流程数据同步、批次生命周期状态追踪、政策法规库管理与智能交互查询平台。

- **核心资产**：位于 `skills/baozhangfang/` 目录下的独立、自包含 Agent Skill。
- **核心能力**：
  1. 多源增量爬取：覆盖市级住建局及各区级住建局政务公开通告。
  2. 批次生命周期状态机追踪：自动推进 `认购中` -> `认购名单已出` -> `选房中` -> `已选房/已完结` 全流程流转。
  3. 结构化政策法规库：归档配租配售、申请门槛、补贴标准等核心政策规约。
  4. 纯 SQLite 开箱即用检索：内置嵌入式 SQLite 数据库，支持毫秒级 CLI 与大模型自然语言交互查询。
  5. 多城市扩展架构：通过声明式 JSON 配置（`sources.json`）实现零代码侵入扩展新城市。

---

## 通用开发原则

1. **Skill 自包含原则（核心绝对原则）**：
   - 位于 `skills/baozhangfang/` 的技能**必须保持 100% 自包含与可移植**。
   - 所有 Skill 内的脚本和逻辑必须使用内部纯嵌入式 SQLite 数据库（`skills/baozhangfang/data/housing.db`）。
   - Skill **严禁**依赖外部 MySQL 数据库、云端 RDS 或 Skill 目录之外的私有凭据。
   - 外部 MySQL 同步脚本（如用于 BI / 阿里云 RDS 的数据桥接）仅作为根目录 `scripts/sync_to_mysql.py` 的可选扩展工具，绝不属于 Skill 运行时的依赖项。

2. **凭据安全与隐私保护（绝对红线）**：
   - **严禁**提交 `config/database.json` 或任何包含真实数据库密码、API 密钥、Token 凭证的文件到 Git。
   - 仓库仅允许提交脱敏配置模版（如 `config/database.json.example`）。
   - 在暂存或提交任何配置之前，务必使用 `git status` 和 `git check-ignore` 严格复核。

3. **极简主义与最小依赖原则**：
   - 优先采用 Python 标准库（`sqlite3`、`json`、`pathlib`、`re`、`argparse`、`datetime`）。
   - 外部依赖保持最少：网络抓取仅依赖 `requests` 和 `beautifulsoup4`，PDF 名单解析仅在需要时选用 `pypdf` 或 `pdfplumber`。
   - 杜绝过度封装与复杂抽象。

4. **原生支持多城市扩展**：
   - 架构与数据模型中禁止对深圳进行硬编码。
   - 数据源统一在 `config/sources.json` 中声明式定义（包含城市代码、区县划分、数据源 URL、CSS 选择器、分类规则等）。
   - 确保数据表结构中包含 `city` 和 `district` 分区字段。

5. **保持干净的工作区**：
   - 临时下载的 PDF 文件、测试表格（`*.xlsx`、`*.xls`、`*.csv`）以及中间 JSON 缓存必须在 `.gitignore` 中被忽略。
   - 不要在仓库根目录下残留临时测试脚本或临时输出产物。

---

## 仓库目录结构

```text
baozhangfang/
├── AGENTS.md                     # Agent 协作指南与操作规约（本文件）
├── README.md                     # 项目介绍与快速入门文档
├── .gitignore                    # Git 忽略规则（敏感配置、临时文件）
├── skills/
│   └── baozhangfang/             # 自包含 Agent Skill（可独立分发与运行）
│       ├── SKILL.md              # Skill 规范说明与大模型调度指引
│       ├── config/
│       │   └── sources.json      # 多城市数据源与抓取规则配置
│       ├── data/
│       │   └── housing.db        # 嵌入式 SQLite 数据库（项目、批次、通告、政策台账）
│       ├── scripts/
│       │   ├── schema.py         # SQLite 表结构初始化与重置脚本
│       │   ├── sync_incremental.py # 增量通告抓取与状态机流转引擎
│       │   ├── sync_policies.py  # 政策法规库全量/增量同步脚本
│       │   └── sync_historical.py# 历史通告与批次数据基准建档脚本
│       └── references/
│           ├── database_schema.md# 完整数据库表字典与枚举定义
│           ├── query_cheatsheet.md# 常用 SQL 与业务巡检速查手册
│           └── sources_guide.md  # 新增城市与区县数据源接入指南
├── config/                       # 根目录全局配置
│   ├── database.json.example     # 阿里云 RDS MySQL 配置脱敏模版（可选）
│   └── sources.json              # 官方数据源配置
├── scripts/                      # 根目录开发者数据处理与管道脚本
│   ├── build_dashboard.py        # 数据看板生成脚本
│   ├── parse_pdf.py              # PDF 申购人员资格名单解析工具
│   ├── sync_to_mysql.py          # 阿里云 RDS MySQL 同步桥接工具（可选）
│   └── ...
└── data/
    └── housing.db                # 本地工作 SQLite 数据库副本
```

---

## 数据库架构与核心数据表

`skills/baozhangfang/data/housing.db` 包含以下 5 大核心业务表与 1 张同步水位线表：

| 数据表名 | 用途说明 | 核心字段 |
|---|---|---|
| `projects` | 物理项目大盘基础台账 | `id`, `project_name`, `city`, `district`, `housing_type`, `total_planned_units`, `address`, `status` |
| `batches` | 房源推售与认购批次生命周期台账 | `batch_id`, `project_id`, `housing_type`, `total_units`, `two_bedroom_units`, `three_bedroom_units`, `average_price`, `current_stage`, `has_regular_sales_exit` |
| `notices` | 抓取的政务公开通告事件流水 | `id`, `city`, `district`, `batch_id`, `category`, `title`, `publish_date`, `url`, `content_text` |
| `policies` | 住房政策、法规与办事指南库 | `id`, `city`, `category`, `title`, `publisher`, `publish_date`, `status`, `url`, `content_text` |
| `households` | 认购公示合格家庭清单 (PDF解析导入) | `code`, `batch`, `house_type`, `queue`, `main_applicant`, `family_size` |
| `sync_watermark` | 增量采集水位线记录表 | `city`, `source_id`, `last_sync_time`, `last_notice_date`, `total_synced` |

### 批次生命周期状态机流转
```text
[认购通告发布] -> 认购中 (subscribing)
     ↓
[认购名单公布] -> 认购名单已出 / 初审终审公示
     ↓
[选房通告发布] -> 选房签约中 (selecting)
     ↓
[常态化通告/选房结束] -> 常态化配售中 (regular) / 已完成选房 (completed)
```

---

## 常用命令与工作流

### 1. 业务数据检索（SQL 直接探索，无脚本限制）
系统**不封装固定脚本**，Agent 应依据用户需求直接对 SQLite 数据库编写 SQL 查询（参考 `references/query_cheatsheet.md`）：

```bash
# 1. 查看全库资产健康指标与批次阶段分布
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT 'projects', count(*) FROM projects UNION ALL
SELECT 'batches', count(*) FROM batches UNION ALL
SELECT 'notices', count(*) FROM notices UNION ALL
SELECT 'policies', count(*) FROM policies;
"

# 2. 模糊查询具体楼盘（如：华越龙苑、深铁熙府、缙熙园）
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT p.project_name, p.district, b.batch_id, b.total_units, b.average_price, b.current_stage
FROM projects p LEFT JOIN batches b ON p.id = b.project_id
WHERE p.project_name LIKE '%华越龙苑%';
"

# 3. 筛选所有“常态化现场即时配售”房源（现场可直接认购）
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT p.project_name, p.district, b.total_units, b.average_price, b.current_stage, b.reception_location
FROM batches b JOIN projects p ON b.project_id = p.id
WHERE b.has_regular_sales_exit = 1 OR b.current_stage = '常态化配售中';
"

# 4. 全文检索政策法规（如：单身年龄限制、本科申请门槛）
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT title, publisher, publish_date, url
FROM policies
WHERE content_text LIKE '%全日制本科%' OR content_text LIKE '%单身%'
LIMIT 5;
"
```

### 2. 增量数据同步
```bash
# 执行多源增量通告抓取与批次状态自动流转
python3 skills/baozhangfang/scripts/sync_incremental.py

# 同步与更新政策法规库
python3 skills/baozhangfang/scripts/sync_policies.py
```

### 3. 新增城市或区县数据源
1. 打开 `skills/baozhangfang/config/sources.json`。
2. 在目标城市节点下新增数据源条目，配置以下要素：
   - `id`：全局唯一数据源标识符。
   - `name`：政务部门全称（如 `深圳市龙华区住房和建设局`）。
   - `city` / `district`：对应行政区划代码及名称。
   - `list_url`：政务通告列表页入口 URL。
   - `selectors`：标题、链接、发布日期和分页的 CSS 提取规则。
3. 执行 `python3 skills/baozhangfang/scripts/sync_incremental.py` 验证抓取解析是否正常。

---

## Agent 操作规范与守则

1. **修改前必验证**：
   - 凡涉及爬虫规则调整或数据库表结构变更，应先在本地执行测试或运行 `sqlite3 skills/baozhangfang/data/housing.db "SELECT count(*) FROM projects;"` 确保历史数据无损坏。
2. **保持 Skill 与根目录配置同步**：
   - 若对 `skills/baozhangfang/config/sources.json` 进行了更新，需同步检查并维护根目录 `config/sources.json`（若存在对应文件）。
3. **内容一律使用中文**：
   - 本项目的所有文档、注释说明、提示信息统一使用规范中文编写。
4. **规范提交 Git 记录**：
   - 遵循清晰的 Conventional Commits 规范（`feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`）。
   - 每次提交前运行 `git status` 确保没有任何密码凭证或临时测试文件被误暂存。
