---
name: baozhangfang
description: >-
  保障性住房（人才配售房、安居型商品房、共有产权房、配售型保障房、公共租赁住房）全流程数据同步与资产台账专家。
  采用自包含架构与纯嵌入式 SQLite 存储，原生支持多城市水平扩展（现已深度适配深圳，预留广州、北京等城市接口）。
  当用户询问保障房楼盘房源（如华越龙苑、深铁熙府、深铁璟城、缙熙园等）、查询常态化即时配售房源、两房/三房/四房套数与配售均价、
  追踪住建局公文生命周期演进（认购/审核/摇号/选房）、执行数据库增量同步刷新、或接入新城市保障房数据源时，务必使用此技能。
---

# 保障房全流程数据同步与资产台账专家 (`baozhangfang`)

`baozhangfang` 是一个**自包含、零外部服务依赖**的保障性住房数据同步与资产台账工具。它以官方政务公开公文为基准，解耦物理资产与业务推售，管理着五大核心台账：**物理项目大盘 (`projects`)**、**推售批次台账 (`batches`)**、**公文事件流水 (`notices`)**、**政策法规规约 (`policies`)**、**申购名册与家庭审核 (`households` / `applications`)**。

---

## 核心能力与架构

```
skills/baozhangfang/
├── SKILL.md                  # 核心技能说明书（当前文件）
├── config/sources.json       # 多城市政务采集源配置（预设深圳12个源，支持扩展）
├── data/housing.db           # 嵌入式 SQLite 数据库（自带全量历史基线）
├── scripts/                  # 纯 SQLite 驱动的数据维护脚本
│   ├── sync_incremental.py   # 增量刷新引擎（水位线逆向探测与状态机流转）
│   ├── sync_policies.py      # 政策法规库全文同步工具
│   ├── sync_historical.py    # 历史物理大盘项目建档脚本
│   └── schema.py             # DDL 建表与重置脚本
└── references/               # 领域参考文档
    ├── database_schema.md    # 核心表结构字典与状态机枚举权重
    ├── query_cheatsheet.md   # 常用业务检索 SQL 速查手册
    └── sources_guide.md      # 多城市数据源接入与抓取协议规范
```

---

## 工作流 1：业务检索与智能问答（直接执行 SQL）

数据库只有 5 张核心表，结构高度清晰规范。**Agent 无需调用封装死板的固定脚本，应根据用户问题直接探索表并编写 SQL 查询**。

- **数据库路径**：`skills/baozhangfang/data/housing.db`
- **执行方式**：通过终端命令 `sqlite3 -header -column skills/baozhangfang/data/housing.db "<SQL>"` 或 Python `sqlite3` 模块执行。
- **参考文档**：
  - 表结构与字段字典：[database_schema.md](file://references/database_schema.md)
  - 常用 SQL 查询模板：[query_cheatsheet.md](file://references/query_cheatsheet.md)

### 常用查询场景示例：

1. **查具体项目与最新批次**（如用户问“华越龙苑怎么样了，还有房子吗”）：
   ```sql
   SELECT p.project_name, p.district, b.batch_id, b.total_units, b.two_bedroom_units, b.three_bedroom_units, b.average_price, b.current_stage, b.sales_mode, b.consultation_phone
   FROM projects p LEFT JOIN batches b ON p.id = b.project_id
   WHERE p.project_name LIKE '%华越龙苑%' ORDER BY b.batch_id DESC;
   ```

2. **查常态化即时配售项目**（如用户问“现在有哪些楼盘可以直接去现场买”）：
   ```sql
   SELECT p.project_name, p.district, b.batch_id, b.total_units, b.average_price, b.current_stage, b.reception_location, b.consultation_phone
   FROM batches b JOIN projects p ON b.project_id = p.id
   WHERE b.has_regular_sales_exit = 1 OR b.current_stage = '常态化配售中' OR b.sales_mode LIKE '%常态化%'
   ORDER BY p.district, b.average_price ASC;
   ```

3. **户型与预算筛选**（如用户问“南山和宝安有没有4万以内的三房”）：
   ```sql
   SELECT p.project_name, p.district, b.three_bedroom_units, b.average_price, b.current_stage, p.address
   FROM batches b JOIN projects p ON b.project_id = p.id
   WHERE p.district IN ('南山区', '宝安区') AND b.three_bedroom_units > 0 AND b.average_price <= 40000
   ORDER BY b.average_price ASC;
   ```

4. **回答用户提问规范**：
   - **明确常态化属性**：清晰区分“公证集中摇号”与“常态化现场即时选房（交定金锁定）”；
   - **提供完整要素**：包括项目名称、批次文号、当前阶段、户型套数（两房/三房/四房）、配售均价、咨询电话与现场接待中心；
   - **公文溯源**：在必要时引用 `notices` 表中的官方公文标题与直链。

---

## 工作流 2：增量数据同步与状态机刷新（日常维护）

当用户要求“刷新保障房数据”、“看看最近有没有新通告/新入市批次”、“更新数据库”时，调用增量刷新引擎：

```bash
# 默认刷新深圳（或通过 --city 指定其他城市）
python3 skills/baozhangfang/scripts/sync_incremental.py [--city 深圳]
```

### 内部执行逻辑：
1. **水位线检测 (High Watermark)**：自动查询目标城市 `MAX(publish_date)`，作为抓取基准分界线；
2. **逆向扫描与自动熔断**：扫描市级住建局与各辖区平台 Page 1，遇到早于水位线的通告立即停止，单次耗时仅 3~5 秒；
3. **推售批次状态机推进 (单向递进不降级)**：
   - 规则：`认购中 (1)` $\to$ `初审名单公示 (2)` $\to$ `终审公示 (3)` $\to$ `公证摇号 (4)` $\to$ `选房签约中 (5)` $\to$ `常态化配售中 (6)` $\to$ `已完成选房 (7)`；
   - 自动在 `batches.notices_json` 中追加时间线流水；
4. **房源要素自动解析与新批次建档**：
   - 自动提取：两房套数 (`two_bedroom_units`)、三房套数 (`three_bedroom_units`)、四房套数 (`four_bedroom_units`)、配售均价、咨询电话、接待中心地址；
   - 发现全新批次文号（如 `住保售〔2026〕083号批次`）时自动新建台账并挂载物理项目；
5. **常态化出口判定**：
   - 若选房通告明确“选房结束后如有剩余房源，实行常态化配售”，标记 `has_regular_sales_exit = 1`；
   - 若通告启动现场即时选房，阶段转为 `常态化配售中`；
6. **新政策规约捕获**：新印发的管理办法与规范性公文自动全文沉淀入 `policies` 表。

---

## 工作流 3：政策法规规约同步与查询

当用户询问“某类保障房最新的政策文件”、“申请条件的法律依据”时：

1. **执行 SQL 检索现行有效政策**：
   ```sql
   SELECT title, publisher, publish_date, document_number, url
   FROM policies
   WHERE content_text LIKE '%全日制本科%' OR content_text LIKE '%单身%'
   ORDER BY publish_date DESC;
   ```
2. **需要拉取最新政策时**：
   ```bash
   python3 skills/baozhangfang/scripts/sync_policies.py [--city 深圳]
   ```
- 数据库 `policies` 表存储了从《深圳市保障性住房条例》到最新《配售型保障性住房管理办法》全部 35 部现行法规全文；
- 直接从 `content_text` 中检索确切条款解答用户的户籍、社保、单身年龄限制（30周岁/35周岁）、房产转让年限等政策要求。

---

## 工作流 4：多城市水平扩展

当需要将系统接入新城市（如广州、北京等）时：
1. **参考接入协议**：阅读 [sources_guide.md](file://references/sources_guide.md)；
2. **配置数据源**：在 `config/sources.json` 中配置该城市住建局或政务公开平台（支持标准 `gkmlpt` API 或 `topic_html` 页面）；
3. **执行针对该城市的初始化与增量刷新**：
   ```bash
   python3 skills/baozhangfang/scripts/sync_incremental.py --city 广州
   ```

---

## 详细参考索引

- [数据表结构与状态机枚举字典](file://references/database_schema.md) (`database_schema.md`)
- [常用业务检索与 SQL 速查手册](file://references/query_cheatsheet.md) (`query_cheatsheet.md`)
- [多城市政务数据源配置指南](file://references/sources_guide.md) (`sources_guide.md`)
