# 保障房业务检索与数据巡检速查手册 (Query Cheatsheet)

本手册汇总了日常查询保障房大盘资产、在售批次、常态化房源、以及巡检数据库的常用 SQL 与 CLI 命令。

---

## 1. 常用 CLI 快捷查询命令

```bash
# 1. 查验全库资产健康指标与批次阶段分布
python3 scripts/query_housing.py --stats

# 2. 模糊查询具体楼盘 (如: 华越龙苑、深铁熙府、缙熙园)
python3 scripts/query_housing.py 华越龙苑

# 3. 筛选所有“常态化现场即时配售”房源清单
python3 scripts/query_housing.py --regular

# 4. 按户型筛选 (筛选有三房或四房的在售项目)
python3 scripts/query_housing.py --beds 3
python3 scripts/query_housing.py --beds 4

# 5. 按阶段筛选 (查看正在选房签约的项目)
python3 scripts/query_housing.py --stage 选房签约中
```

---

## 2. 常用业务 SQL 查询模板

### 2.1 查询当前所有“常态化现场即时配售”或具备退出通道的批次
```sql
SELECT 
    b.batch_id AS 批次文号,
    p.project_name AS 项目名称,
    p.district AS 所属辖区,
    b.total_units AS 总套数,
    b.two_bedroom_units AS 两房套数,
    b.three_bedroom_units AS 三房套数,
    b.four_bedroom_units AS 四房套数,
    b.average_price AS 均价_元每平,
    b.current_stage AS 当前阶段,
    b.consultation_phone AS 咨询电话,
    b.reception_location AS 营销中心地址
FROM batches b
JOIN projects p ON b.project_id = p.id
WHERE (b.has_regular_sales_exit = 1 OR b.current_stage = '常态化配售中')
ORDER BY b.batch_id DESC;
```

### 2.2 展开某一特定批次（如 073 批次）的全流程官方公文演进链
```sql
SELECT 
    n.publish_date AS 发布日期,
    n.category AS 通告类型,
    n.title AS 公文标题,
    n.url AS 官方原文链接
FROM notices n
WHERE n.batch_id = '住保售〔2026〕073号批次'
ORDER BY n.publish_date ASC, n.id ASC;
```

### 2.3 查看各区在售房源与平均价格分布
```sql
SELECT 
    p.district AS 行政区,
    COUNT(DISTINCT p.id) AS 项目个数,
    COUNT(b.batch_id) AS 推售批次数,
    SUM(b.total_units) AS 累计推售套数,
    ROUND(AVG(b.average_price), 0) AS 区域均价_元每平
FROM projects p
JOIN batches b ON p.id = b.project_id
GROUP BY p.district
ORDER BY SUM(b.total_units) DESC;
```

### 2.4 查询最新出台的规范性政策法规（按发布时间降序）
```sql
SELECT 
    publish_date AS 发布日期,
    category AS 政策类别,
    title AS 政策标题,
    publisher AS 发文部门,
    status AS 现行状态,
    url AS 原文直链
FROM policies
ORDER BY publish_date DESC
LIMIT 10;
```
