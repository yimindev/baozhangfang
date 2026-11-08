# 保障房自包含数据库结构字典 (Database Schema)

本数据库（SQLite `data/housing.db`）采用**解耦物理资产与业务推售批次**的生产级范式设计，原生支持多城市水平扩展（`city` 为一等公民）。

---

## 核心数据表结构

### 1. `projects`：物理资产大盘台账
记录物理地理意义上的建筑小区实体（一个地块或大盘），与分次入市的业务批次完全解耦。

| 字段名 | 类型 | 说明 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 物理项目自增主键 | `1` |
| `city` | TEXT NOT NULL | 所在城市（支持多城市） | `'深圳'`, `'广州'` |
| `district` | TEXT | 行政区划 | `'龙华区'`, `'南山区'` |
| `subdistrict` | TEXT | 街道办/片区 | `'民治街道'` |
| `project_name` | TEXT NOT NULL | 项目标准物理名称 | `'安居华越龙苑'` |
| `developer` | TEXT | 建设/开发主体 | `'深圳市安居集团有限公司'` |
| `housing_type` | TEXT | 房源宏观类别 | `'人才配售房'`, `'共有产权住房'` |
| `total_planned_units` | INTEGER | 规划总套数（物理大盘总量） | `1350` |
| `planned_area` | REAL | 规划总建筑面积（万㎡） | `15.0` |
| `address` | TEXT | 物理具体地址 | `'龙华区民治街道新牛社区'` |
| `status` | TEXT | 工程/大盘状态 | `'配售中'`, `'计划竣工/在建'` |
| `notices_json` | TEXT | 物理项目关联宏观公文（如规划审批） | `JSON 数组` |

*约束*: `UNIQUE(city, project_name)`

---

### 2. `batches`：推售批次业务台账
记录每一次面向社会的具体配售活动（一期、二期、常态化批次等），通过 `project_id` 关联物理项目。

| 字段名 | 类型 | 说明 | 示例 |
| :--- | :--- | :--- | :--- |
| `batch_id` | TEXT PRIMARY KEY | 官方推售文号主键 | `'住保售〔2026〕083号批次'` |
| `project_id` | INTEGER NOT NULL | 外键关联 `projects.id` | `1` |
| `city` | TEXT NOT NULL | 所在城市 | `'深圳'` |
| `district` | TEXT | 主管辖区 | `'市住建局'`, `'龙华区'` |
| `batch_seq` | INTEGER | 该项目的第几次推售 | `1, 2, 3` |
| `housing_type` | TEXT | 房源类型 | `'人才配售房'`, `'安居型商品房'` |
| `total_units` | INTEGER | 本次推售总套数 | `433` |
| `one_bedroom_units` | INTEGER | 一房套数（独立整数列） | `NULL` |
| `two_bedroom_units` | INTEGER | 两房套数（独立整数列） | `NULL` |
| `three_bedroom_units` | INTEGER | 三房套数（独立整数列） | `433` |
| `four_bedroom_units` | INTEGER | 四房套数（独立整数列） | `NULL` |
| `other_units` | INTEGER | 其他户型套数 | `NULL` |
| `average_price` | REAL | 配售均价（元/㎡） | `39600.0` |
| `deposit_amount` | REAL | 认购订金（元） | `20000.0` |
| `sales_mode` | TEXT | 销售模式 | `'公证摇号'`, `'常态化即时配售'` |
| `has_regular_sales_exit`| INTEGER | 是否具备常态化出口（1有，0无） | `1` |
| `reception_location` | TEXT | 营销/选房接待中心地址 | `'龙华区民治街道新牛社区接待中心'` |
| `consultation_phone` | TEXT | 咨询服务热线 | `'0755-86266999'` |
| `booking_channel` | TEXT | 预约/看房渠道 | `'安居选房通微信小程序'` |
| `sub_start_date` | TEXT | 认购开始时间 | `'2026-09-28'` |
| `sub_end_date` | TEXT | 认购截止时间 | `'2026-10-08'` |
| `current_stage` | TEXT | 当前生命周期阶段（状态机推进） | `'常态化配售中'` |
| `notices_json` | TEXT | 该批次关联的全生命周期公文链 | `[{"stage":"认购通告","title":"...","date":"2026-09-28"}]` |

---

### 3. `notices`：官方公文与阶段事件流水台账
存储各级住建局与公开目录发布的每一篇公告原文、正文全文与附件直链。

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 自增主键 |
| `city` | TEXT NOT NULL | 发布城市 |
| `district` | TEXT | 发布机构辖区（市局或区局） |
| `project_id` | INTEGER | 外键关联 `projects.id` |
| `batch_id` | TEXT | 外键关联 `batches.batch_id` |
| `category` | TEXT | 通告类型（认购通告/初审名单/终审结果/摇号结果/选房通知/综合公告） |
| `title` | TEXT NOT NULL | 公告完整标题 |
| `publish_date` | TEXT | 发布日期（YYYY-MM-DD） |
| `url` | TEXT NOT NULL UNIQUE | 官方原文直链 |
| `summary` | TEXT | 简报摘要 |
| `content_text` | TEXT | 正文纯文本（支撑全文检索与要素抽取） |
| `attachments_json` | TEXT | 附件列表 JSON（含 PDF/表格直链与文件名） |

---

### 4. `policies`：政策法规规约台账
存储中央、省、市保障性住房法规与管理细则全文。

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 自增主键 |
| `city` | TEXT NOT NULL | 适用城市 |
| `category` | TEXT | 政策分类（配售型保障房/共有产权住房/人才住房/综合保障） |
| `title` | TEXT NOT NULL | 政策文件标题 |
| `document_number` | TEXT | 公文字号（如深府规〔2023〕4号） |
| `publisher` | TEXT | 发文机关 |
| `publish_date` | TEXT | 印发日期 |
| `effective_date` | TEXT | 施行日期 |
| `status` | TEXT | 现行状态（现行有效 / 已废止） |
| `url` | TEXT NOT NULL UNIQUE | 官方正文直链 |
| `content_text` | TEXT | 政策正文全文 |

---

### 5. `applications`：申购家庭与状态机台账
用于记录认购家庭在单次批次中的全生命周期流转。

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `batch_id` | TEXT NOT NULL | 申购批次文号 |
| `applicant_code` | TEXT NOT NULL | 申请编号（如 SQ2026...） |
| `main_applicant` | TEXT NOT NULL | 主申请人姓名 |
| `id_card` | TEXT | 脱敏身份证号 |
| `queue` | TEXT | 申请队列（第一至第五队列） |
| `verify_status` | TEXT | 审核状态（初审合格 / 复核合格 / 放弃） |
| `ballot_seq` | INTEGER | 公证摇号选房顺序号 |
| `selection_result` | TEXT | 选房结果（已签约 / 弃选） |
| `selected_unit` | TEXT | 选定房号 |

*约束*: `UNIQUE(batch_id, applicant_code)`

---

## 批次推售状态机权重定义 (Stage Weights)

状态机采用**单向递进、高阶不降级**原则：

```
认购中 (权重 1)
  ↓
初审名单公示 (权重 2)
  ↓
终审公示 (权重 3)
  ↓
公证摇号 (权重 4)
  ↓
选房签约中 (权重 5)
  ↓
常态化配售中 (权重 6)
  ↓
已完成选房 (权重 7)
```
- 若公文明确“现场认购、即时选房”或直接发布常态化通告，直接进入权重 6（常态化配售中）；
- 若通告为“选房通告”且条款包含常态化退出机制，批次标记 `has_regular_sales_exit = 1`，阶段为“选房签约中”。
