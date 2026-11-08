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
    p.district AS 行政区,
    COUNT(DISTINCT p.id) AS 项目数,
    COUNT(b.batch_id) AS 推售批次数,
    COALESCE(SUM(b.total_units), 0) AS 累计推售套数,
    ROUND(AVG(b.average_price), 0) AS 区域均价_元每平
FROM projects p
LEFT JOIN batches b ON p.id = b.project_id
GROUP BY p.district
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
    b.total_units AS 推售套数,
    b.two_bedroom_units AS 两房套数,
    b.three_bedroom_units AS 三房套数,
    b.average_price AS 配售均价_元每平,
    b.current_stage AS 当前阶段,
    b.sales_mode AS 销售模式,
    b.consultation_phone AS 咨询电话
FROM projects p
LEFT JOIN batches b ON p.id = b.project_id
WHERE p.project_name LIKE '%华越龙苑%'
ORDER BY b.batch_id DESC;
```

### 2.2 查询正在进行中的活跃批次（认购中、选房中、常态化）
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 所属区,
    b.batch_id AS 批次文号,
    b.current_stage AS 当前生命周期阶段,
    b.total_units AS 推售套数,
    b.average_price AS 均价,
    b.sub_start_date AS 认购开始,
    b.sub_end_date AS 认购截止
FROM batches b
JOIN projects p ON b.project_id = p.id
WHERE b.current_stage IN ('认购中', '选房签约中', '常态化配售中', '公证摇号')
ORDER BY b.sub_start_date DESC;
```

---

## 3. 常态化即时配售房源盘点（随时可现场认购）

### 3.1 筛选所有支持“现场常态化即时配售”的项目清单
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 所属区,
    b.batch_id AS 批次文号,
    b.total_units AS 批次总套数,
    b.two_bedroom_units AS 两房,
    b.three_bedroom_units AS 三房,
    b.average_price AS 均价_元每平,
    b.current_stage AS 当前状态,
    b.reception_location AS 现场接待中心,
    b.consultation_phone AS 咨询热线
FROM batches b
JOIN projects p ON b.project_id = p.id
WHERE b.has_regular_sales_exit = 1 
   OR b.current_stage = '常态化配售中'
   OR b.sales_mode LIKE '%常态化%'
ORDER BY p.district, b.average_price ASC;
```

---

## 4. 户型与预算条件筛选

### 4.1 筛选带三房或四房且均价低于 4 万元/㎡ 的在售/配售项目
```sql
SELECT 
    p.project_name AS 项目名称,
    p.district AS 行政区,
    b.three_bedroom_units AS 三房套数,
    b.four_bedroom_units AS 四房套数,
    b.average_price AS 均价_元每平,
    b.current_stage AS 当前状态,
    p.address AS 地址
FROM batches b
JOIN projects p ON b.project_id = p.id
WHERE (b.three_bedroom_units > 0 OR b.four_bedroom_units > 0)
  AND b.average_price <= 40000
ORDER BY b.average_price ASC;
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
