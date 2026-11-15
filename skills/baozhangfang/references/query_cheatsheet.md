# 保障房业务检索与 SQL 速查手册 (Query Cheatsheet)

本手册为 Agent 与开发者提供查询保障房数据库（`skills/baozhangfang/data/housing.db`）的常用 SQL 模板与检索指南。
Agent 可通过终端命令 `sqlite3 -header -column skills/baozhangfang/data/housing.db "<SQL>"` 或 Python 的 `sqlite3` 模块直接执行查询。

> [!TIP]
> 推荐在命令行中使用 `-header -column` 参数以表格形式对齐输出，或使用 `-json` 参数获取 JSON 格式数据以便大模型结构化解析。

---

## 1. 全库资产总览与统计看板

### 1.1 全库核心台账数据量汇总
```sql
SELECT '物理项目 (projects)' AS 台账类别, COUNT(*) AS 总记录数 FROM projects
UNION ALL
SELECT '推售批次 (batches)', COUNT(*) FROM batches
UNION ALL
SELECT '政务通告 (notices)', COUNT(*) FROM notices
UNION ALL
SELECT '政策法规 (policies)', COUNT(*) FROM policies
UNION ALL
SELECT '认购家庭 (households)', COUNT(*) FROM households;
```

### 1.2 各区推售房源套数与均价分布
```sql
SELECT 
    b.district AS 行政区,
    COUNT(DISTINCT bp.project_id) AS 项目数,
    COUNT(DISTINCT b.batch_id) AS 推售批次数,
    COALESCE(SUM(bp.units), 0) AS 累计推售套数,
    ROUND(AVG(bp.average_price), 0) AS 项目均价_元每平
FROM batches b
LEFT JOIN batch_projects bp ON bp.batch_id = b.batch_id
GROUP BY b.district
ORDER BY 累计推售套数 DESC;
```

---

## 2. 楼盘项目与推售批次查询

### 2.1 按项目名称模糊查询（含最新批次、均价与当前阶段）
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 所属区,
    p.housing_type AS 房源类别,
    b.batch_id AS 批次文号,
    bp.units AS 本项目本批次套数,
    b.two_bedroom_units AS 两房套数,
    b.three_bedroom_units AS 三房套数,
    bp.average_price AS 配售均价_元每平,
    b.current_stage AS 当前阶段,
    b.sales_mode AS 销售模式,
    b.consultation_phone AS 咨询电话
FROM projects p
JOIN batch_projects bp ON bp.project_id = p.id
JOIN batches b ON b.batch_id = bp.batch_id
WHERE p.project_name LIKE '%华越龙苑%' OR p.aliases LIKE '%华越龙苑%'
ORDER BY b.batch_id DESC;
```

> 必须走 `batch_projects`：一个批次可同时推售多个楼盘（如龙岗 `住保售〔2026〕076` 含宝翠/宝澜/宝锦），
> 只 `JOIN batches ON batches.project_id = projects.id` 会漏掉非主项目。

### 2.2 查询正在进行中的活跃批次（认购中、选房中、常态化）
```sql
SELECT 
    GROUP_CONCAT(p.project_name, '/') AS 项目名称,
    b.district AS 所属区,
    b.batch_id AS 批次文号,
    b.current_stage AS 当前生命周期阶段,
    SUM(bp.units) AS 推售套数,
    GROUP_CONCAT(DISTINCT bp.average_price) AS 各项目均价,
    b.sub_start_date AS 认购开始,
    b.sub_end_date AS 认购截止
FROM batches b
JOIN batch_projects bp ON bp.batch_id = b.batch_id
JOIN projects p ON p.id = bp.project_id
WHERE b.current_stage IN ('认购中', '选房签约中', '常态化配售中', '公证摇号')
GROUP BY b.batch_id
ORDER BY b.sub_start_date DESC;
```

### 2.3 按别名/异名找项目（如公告写“家园”、项目库写“花园”）
```sql
SELECT id, project_name, district, aliases, developer
FROM projects
WHERE project_name LIKE '%小梅沙%' OR aliases LIKE '%小梅沙%';
```

> `aliases` 是 JSON 数组文本，查询用 `LIKE '%关键词%'` 即可；写入用
> `db_io.py upsert-project --name 标准名 --aliases "异名1,异名2"`。

### 2.4 查一个批次到底包含哪几个楼盘
```sql
SELECT b.batch_id, p.project_name, p.district, bp.batch_seq, bp.units,
       bp.two_bedroom_units, bp.three_bedroom_units, bp.average_price
FROM batches b
JOIN batch_projects bp ON bp.batch_id = b.batch_id
JOIN projects p ON p.id = bp.project_id
WHERE b.batch_id = '住保售〔2026〕076号批次'
ORDER BY bp.units DESC;
```

> 批次级查询（2.2 / 3.1 / 4.1）仍可只用 `batches`：那里的 `average_price` 是单项目批次价格，
> 多项目混价的批次置空（不编造加权均价），此时改看 `batch_projects.average_price`。

---

## 3. 常态化即时配售房源盘点（随时可现场认购）

### 3.1 筛选所有支持“现场常态化即时配售”的项目清单
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 所属区,
    b.batch_id AS 批次文号,
    bp.units AS 本项目套数,
    bp.two_bedroom_units AS 两房,
    bp.three_bedroom_units AS 三房,
    bp.average_price AS 均价_元每平,
    b.current_stage AS 当前状态,
    b.reception_location AS 现场接待中心,
    b.consultation_phone AS 咨询热线
FROM batches b
JOIN batch_projects bp ON bp.batch_id = b.batch_id
JOIN projects p ON p.id = bp.project_id
WHERE b.has_regular_sales_exit = 1 
   OR b.current_stage = '常态化配售中'
   OR b.sales_mode LIKE '%常态化%'
ORDER BY p.district, bp.average_price ASC;
```

---

## 4. 户型与预算条件筛选

### 4.1 筛选带三房或四房且均价低于 4 万元/㎡ 的在售/配售项目
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 行政区,
    bp.three_bedroom_units AS 三房套数,
    bp.four_bedroom_units AS 四房套数,
    bp.average_price AS 均价_元每平,
    b.current_stage AS 当前状态,
    p.address AS 地址
FROM batch_projects bp
JOIN batches b ON b.batch_id = bp.batch_id
JOIN projects p ON p.id = bp.project_id
WHERE (bp.three_bedroom_units > 0 OR bp.four_bedroom_units > 0)
  AND bp.average_price <= 40000
ORDER BY bp.average_price ASC;
```

### 4.2 筛选特定行政区（如南山区、福田区、宝安区）的所有保障房项目
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 行政区,
    p.housing_type AS 房源类别,
    p.total_planned_units AS 规划总套数,
    p.status AS 工程状态,
    p.address AS 具体地址
FROM projects p
WHERE p.district IN ('南山区', '福田区', '宝安区')
ORDER BY p.district, p.project_name;
```

---

## 5. 公文流水与批次生命周期演进

### 5.1 查看某一特定批次（如 081 批次）全流程官方通告链条
```sql
SELECT 
    publish_date AS 发布日期,
    category AS 通告类型,
    title AS 通告标题,
    url AS 官方原文链接
FROM notices
WHERE batch_id LIKE '%081%' OR title LIKE '%081号%'
ORDER BY publish_date ASC, id ASC;
```

### 5.2 检索最近发布的保障房公开通告（前 10 条）
```sql
SELECT 
    publish_date AS 发布日期,
    district AS 发布辖区,
    category AS 类别,
    title AS 标题,
    url AS 链接
FROM notices
ORDER BY publish_date DESC
LIMIT 10;
```

---

## 6. 政策法规与申购资格检索

### 6.1 全文搜索特定政策条款（如：学历、社保、单身年龄要求）
```sql
SELECT 
    title AS 政策标题,
    publisher AS 发文机关,
    publish_date AS 印发日期,
    document_number AS 文号,
    url AS 原文链接
FROM policies
WHERE content_text LIKE '%全日制本科%'
   OR content_text LIKE '%单身%'
   OR content_text LIKE '%社保%'
ORDER BY publish_date DESC;
```

### 6.2 查询现行有效的核心保障房管理办法
```sql
SELECT 
    category AS 政策分类,
    title AS 文件标题,
    publish_date AS 发布日期,
    status AS 状态,
    url AS 原文链接
FROM policies
WHERE status = '现行有效' OR status IS NULL
ORDER BY publish_date DESC
LIMIT 10;
```

---

## 7. 申购名单与家庭审核情况（`households` 表）

### 7.1 查询特定批次的申请队列人数分布与户型需求
```sql
SELECT 
    queue AS 申请队列,
    housing_type AS 申请户型,
    COUNT(*) AS 审核合格家庭数
FROM households
GROUP BY queue, housing_type
ORDER BY housing_type, queue;
```

### 7.2 查询具体申请人审核记录（脱敏）
```sql
SELECT 
    batch_id AS 批次文号,
    applicant_code AS 申请编号,
    main_applicant AS 申请人,
    queue AS 所属队列,
    housing_type AS 意向户型,
    family_size AS 家庭人口
FROM households
WHERE main_applicant LIKE '张%'
LIMIT 10;
```

---

## 8. 数据源健康巡检

### 8.1 各区最新公文日期与条数（看空档）
```sql
SELECT district, COUNT(*) AS 条数, MAX(publish_date) AS 最新日期, MIN(publish_date) AS 最早日期
FROM notices
GROUP BY district
ORDER BY 最新日期 DESC;
```

### 8.2 入库覆盖按月统计（看历史空档）
```sql
SELECT substr(publish_date, 1, 7) AS 月份, COUNT(*) AS 条数
FROM notices
WHERE publish_date >= '2025-01-01'
GROUP BY 月份
ORDER BY 月份;
```

> 同步不维护独立水位线表；增量以 `fetch_list` + `db_io diff` 的 new/known 判定为准。

### 8.3 重复公告检查（应为空）
```sql
SELECT district, title, publish_date, COUNT(*) AS c
FROM notices
GROUP BY district, title, publish_date
HAVING c > 1
ORDER BY c DESC;
```

同名但日期不同：可能是多源重复（日期漂移），也可能是轮候公示、补贴名单、季度退出表这类周期性新一期，需看正文判断。
经验：间隔 1–2 天的几乎都是重复，间隔 ≥10 天的多为新一期。

```sql
SELECT district, title, COUNT(*) AS c, GROUP_CONCAT(publish_date) AS dates
FROM notices
GROUP BY district, title
HAVING COUNT(DISTINCT publish_date) > 1
ORDER BY c DESC;
```

> 入库时不设天数容差：`publish_date` 一律取列表日期，`diff` 与 `upsert-notice` 均按「同区 + 同一化标题 + 同日」精确比对。

### 8.4 项目与批次脏数据巡检（结果应为空或已解释）
```sql
-- ① 项目名像正文片段（被正则吞了前缀）
SELECT id, project_name FROM projects
WHERE project_name GLOB '现*' OR project_name GLOB '关于*' OR project_name GLOB '决定*'
   OR project_name LIKE '%通知%' OR project_name LIKE '%通告%'
   OR LENGTH(project_name) > 25;

-- ② 去掉“项目/（...）”后重名，疑似同一实体两行
SELECT REPLACE(project_name, '项目', '') AS 归一化名, COUNT(*) AS c,
       GROUP_CONCAT(id || ':' || project_name, ' | ') AS 行
FROM projects
GROUP BY 归一化名
HAVING c > 1;

-- ③ 批次挂到了别的区的项目（市级/保障署除外）
SELECT DISTINCT b.batch_id, b.district AS 批次主管, p.id, p.project_name, p.district AS 项目所在区
FROM batches b
JOIN batch_projects bp ON bp.batch_id = b.batch_id
JOIN projects p ON p.id = bp.project_id
WHERE b.district NOT IN ('市住建局', '市住房保障署') AND b.district <> p.district;

-- ④ 公文引用了不存在的批次（应为空）
SELECT n.batch_id, COUNT(*) AS c
FROM notices n LEFT JOIN batches b ON n.batch_id = b.batch_id
WHERE n.batch_id IS NOT NULL AND n.batch_id <> '' AND b.batch_id IS NULL
GROUP BY n.batch_id ORDER BY c DESC;
```

> 处理原则：能确定的（文号格式、区划）按规则修；归属有歧义的先查正文与近似项目，
> 仍不确定就停下来报给用户，不要凭猜测 UPDATE。

### 8.5 同一公告的多个 URL（UI / gkmlpt 并存）
```sql
SELECT title, publish_date, COUNT(*) AS c, GROUP_CONCAT(url, ' | ') AS urls
FROM notices
GROUP BY title, publish_date
HAVING c > 1;
```

### 8.6 无归属批次的公文占比（孤儿检查）
```sql
SELECT
  SUM(CASE WHEN batch_id IS NULL OR batch_id = '' THEN 1 ELSE 0 END) AS 无批次,
  COUNT(*) AS 总数,
  ROUND(100.0 * SUM(CASE WHEN batch_id IS NULL OR batch_id = '' THEN 1 ELSE 0 END) / COUNT(*), 1) AS 占比
FROM notices;
```

> 结构性巡检优先用脚本：`python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳`，
> 会同时核对 API、库内最新日期、重复记录与 UI 独有公告。
