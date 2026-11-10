# 保障房数据同步与分析助手 (Baozhangfang)

深圳市保障性住房数据同步、生命周期状态追踪、政策法规库管理与 AI 交互查询助手。

本项目提供了一整套保障性住房公告数据的抓取、解析、状态机流转维护机制，并封装了符合 Antigravity 规范的独立 Agent Skill (`skills/baozhangfang`)，支持纯 SQLite 离线运行与多城市数据源扩展。

---

## 核心特性

- 🏛️ **多级公告增量抓取**：覆盖深圳市住建局及福田、南山、罗湖、宝安、龙岗、龙华、光明、坪山、盐田、大鹏等全区住建局公告源。
- 🔄 **生命周期状态机追踪**：自动追踪认购批次从「认购通告 -> 认购名单 -> 选房通告 -> 选房结果」的全生命周期流转。
- 📚 **政策法规库管理**：结构化抓取并归档配租配售、申请门槛、补贴标准等核心政策文件。
- 🔍 **开箱即用 SQLite 数据集**：内置纯 SQLite 嵌入式数据库，免外部数据库依赖，包含 83+ 房源项目、19+ 认购批次、1200+ 公告索引与最新政策法规。
- 🤖 **自包含 Antigravity Skill**：位于 `skills/baozhangfang/`，具备独立的配置、数据、脚本与参考文档，支持作为大模型工具即插即用。

---

## 目录结构

```text
baozhangfang/
├── skills/
│   └── baozhangfang/             # 自包含 Antigravity Skill
│       ├── SKILL.md              # Skill 规范说明与大模型指引
│       ├── config/
│       │   └── sources.json      # 多城市数据源与抓取规则配置
│       ├── data/
│       │   ├── seed.sql          # 脱敏种子基线 (SQL 文本，纳入版本管理)
│       │   └── housing.db        # 运行时工作库 (由 seed.sql 自举，Git 忽略)
│       ├── scripts/
│       │   ├── db.py             # 运行库路径解析与种子自举
│       │   ├── export_seed.py    # 导出脱敏种子 (发版时使用)
│       │   ├── schema.py         # SQLite 数据库表结构初始化
│       │   ├── sync_incremental.py # 增量数据抓取与状态机引擎
│       │   ├── sync_policies.py  # 政策法规抓取
│       │   └── sync_historical.py# 历史公告基线抓取
│       └── references/           # 数据库设计、数据源与查询文档
├── config/                       # 项目级全局配置
│   └── database.json.example     # 外部 MySQL 配置模版 (可选)
├── scripts/                      # 开发者扩展工具 (统一读写 Skill 运行库)
│   ├── build_dashboard.py        # 可视化大屏构建脚本
│   ├── parse_pdf.py              # PDF 名单结构化提取
│   └── sync_to_mysql.py          # 阿里云 RDS MySQL 同步工具 (可选)
└── README.md
```

---

## 快速上手

### 1. 安装依赖

```bash
pip install requests beautifulsoup4
```

*(如需使用 PDF 名单解析功能，可按需安装 `pypdf` 或 `pdfplumber`)*

### 2. 初始化运行库

```bash
# 由脱敏种子 seed.sql 生成 skills/baozhangfang/data/housing.db（同步脚本首次运行时也会自动执行）
python3 skills/baozhangfang/scripts/db.py
```

> 种子库不含 `households` / `members` / `applications` 的数据行（含个人信息），需要时请用 `scripts/parse_pdf.py --sqlite skills/baozhangfang/data/housing.db` 在本地导入。

### 3. 数据库检索与查询

数据库采用纯 SQLite 存储，结构简洁透明。Agent 或开发者可直接执行 SQL，无固定参数约束（详细 SQL 模板见 `skills/baozhangfang/references/query_cheatsheet.md`）：

```bash
# 查看数据库整体统计看板
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT 'projects', count(*) FROM projects UNION ALL
SELECT 'batches', count(*) FROM batches UNION ALL
SELECT 'notices', count(*) FROM notices UNION ALL
SELECT 'policies', count(*) FROM policies;
"

# 按项目名称模糊搜索（如：华越龙苑）
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT p.project_name, p.district, b.batch_id, b.total_units, b.average_price, b.current_stage
FROM projects p LEFT JOIN batches b ON p.id = b.project_id
WHERE p.project_name LIKE '%华越龙苑%';
"

# 查询常态化申购（现场即时配售）项目
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT p.project_name, p.district, b.total_units, b.average_price, b.current_stage, b.reception_location
FROM batches b JOIN projects p ON b.project_id = p.id
WHERE b.has_regular_sales_exit = 1 OR b.current_stage = '常态化配售中';
"
```

### 4. 数据增量同步

执行增量同步，自动比对水位线（Watermark）并抓取最新公告：

```bash
# 增量抓取最新公告与批次状态
python3 skills/baozhangfang/scripts/sync_incremental.py

# 更新政策法规库
python3 skills/baozhangfang/scripts/sync_policies.py
```

增量同步只写 `housing.db`（Git 忽略），工作区保持干净。需要发布新数据基线时再执行：

```bash
python3 skills/baozhangfang/scripts/export_seed.py   # 刷新 seed.sql（自动剔除个人信息）后提交
```

---

## 作为 Skill 使用

本项目的 `skills/baozhangfang` 符合标准 Agent Skill 协议，可通过 Antigravity 或大模型框架加载：
1. 拷贝或链接 `skills/baozhangfang` 到 Agent 技能目录。
2. 技能内置纯 SQLite 数据与查询工具，无需配置数据库账号即可回答用户关于保障房批次、项目进度、政策要求的各种提问。

---

## 开源协议

MIT 协议
