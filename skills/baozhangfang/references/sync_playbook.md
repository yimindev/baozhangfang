# 同步作业手册 (Sync Playbook) —— Agent 主导的抓取与入库流程

> 本文件是流程的**唯一权威来源**。脚本只做原子动作（抓列表 / 抓正文 / 读写一条记录），
> 判断哪些公文相关、要不要抓全文、字段怎么读、批次怎么挂、阶段怎么推，**全部由 Agent 依据本手册决策**，
> 不要在脚本里加关键词白名单、正则推断、状态机硬编码。

---

## 0. 角色分工

| 角色 | 职责 | 不该做的事 |
| :--- | :--- | :--- |
| `fetch_list.py` | 把配置里所有源的第 1~N 页条目**原样**抓成 JSON | 不判断相关性、不分类、不查库 |
| `fetch_detail.py` | 给 URL，返回正文纯文本 + 附件直链 +（可选）表格 | 不抽业务字段、不判归属 |
| `db_io.py` | 参数化的单记录读写：项目/批次/公文/政策 upsert、时间线追加、只读查询 | 不替你做匹配和阶段推断 |
| **Agent（你）** | 读列表 → 判相关性 → 决定抓哪些全文 → 读正文抽要素 → 决定归属 → 逐条写入 → 自检 | 不要指望脚本替你判断 |

---

## 1. 工具契约

```bash
# ① 水位线：本次从哪天开始看
python3 <SKILL_DIR>/scripts/db_io.py watermark --city 深圳          # -> 2026-11-10

# ② 列表（宽松抓取，12 个源并集，默认不过滤任何关键词）
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --pages 1 --format table
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --pages 1-3 --since 2026-11-01 --format json
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --channel policies      # 政策法规专栏

# ③ 已入库 URL（用来做差集，避免重复抓正文）
python3 <SKILL_DIR>/scripts/db_io.py known-urls --city 深圳 --since 2026-10-01

# ④ 正文（可一次传多个 URL；--tables 抽表格；--save-dir 落盘原始文件）
python3 <SKILL_DIR>/scripts/fetch_detail.py --url-file /tmp/todo_urls.txt --save-dir /tmp/bf_html
python3 <SKILL_DIR>/scripts/fetch_detail.py <url> --tables

# ⑤ 写库（全部按 URL / batch_id / (city, project_name) 幂等）
python3 <SKILL_DIR>/scripts/db_io.py upsert-project --name 星河开市客环球商业中心 --district 龙华区
python3 <SKILL_DIR>/scripts/db_io.py upsert-batch --batch-id "住保售〔2026〕054号批次" --project-id 84 \
        --total-units 300 --three-bedroom-units 300 --average-price 28000 --current-stage 选房签约中
python3 <SKILL_DIR>/scripts/db_io.py upsert-notice --url <url> --title "<标题>" --date 2026-11-10 \
        --district 光明区 --category 综合公告 --content-file /tmp/body.txt
python3 <SKILL_DIR>/scripts/db_io.py upsert-policy --url <url> --title "<法规标题>" --category 地方性法规 \
        --publisher 深圳市住房和建设局 --date 2026-08-01 --content-file /tmp/policy.txt
python3 <SKILL_DIR>/scripts/db_io.py append-timeline --batch-id "<批次>" --stage 初审名单 \
        --title "<标题>" --date 2026-11-09 --url <url>
```

---

## 2. 标准流程

### Step 1 取水位线
`<SKILL_DIR>/scripts/db_io.py watermark` 拿到最新已入库日期。它只是**参考起点**，不是硬边界——
若怀疑历史漏采，直接把 `--since` 往前推（例如推到上季度），宁可多抓不要漏抓。

### Step 2 抓列表（宽松）
一次抓完所有源的第 1 页；若某源第 1 页有大量条目晚于水位线，再加 `--pages 1-2` 补看第 2 页。
脚本会在 JSON 的 `empty_sources` 里告诉你哪些源颗粒无收——**空源要单独排查**（改版？反爬？页面结构变了？），
不要默默当成"今天没公告"。

### Step 3 差集
用 `known-urls` 的输出对 URL 去重。注意同一条公文在不同栏目可能有两个 URL（正文页 vs 附件页），
去重时同时比对 `标题+日期`，别只看 URL。

### Step 4 相关性判断（保留 or 跳过）
**保留**：凡涉及——配售/配租/轮候/认租/认购/名单公示/摇号/选房/签约/退房/房源信息/价格/补贴/需求库/政策法规/计划与规划。
**跳过**：行政处罚、执法文书送达、内部采购/中标、人事任免、消防验收、招标计划、加装电梯补贴、
纯物业/租赁市场监管通知——除非正文里明确涉及保障房房源或家庭。

判断时看**标题 + 摘要**即可；标题模糊（如"关于……有关事项的通知"）时，先抓正文再定，不要靠猜。

### Step 5 决定要不要抓全文
**必须抓全文**：
- 认购/配租通告（含套数、户型、价格、认购条件、时间、电话、接待点）
- 初审/终审/核查名单公示（含户数、队列、合格/不合格数、公示期）
- 摇号通告/结果（含顺序号规则、时间地点）
- 选房通告/选房结果（含场次、剩余房源、常态化出口条款）
- 政策法规、实施细则、管理办法
- 房源信息表、价格表类公告

**可以只存列表信息（不抓正文）**：轮候合格家庭公示、需求库名单、纯流程性通知——除非用户明确要看细节。

### Step 6 从正文抽要素
按 `batches` 表字段清单逐项找，**找不到就留空，不要凑数**：

| 要素 | 常见表述 | 坑 |
| :--- | :--- | :--- |
| 总套数 | 房源合计/共提供房源 N 套 | 注意区分"本批次"与"项目累计" |
| 各户型套数 | 两房 N 套、三房 N 套；"均为三房" | **"摇号系统光盘2套""公证处电脑2台"不是房源**，凡套数紧邻"光盘/电脑/车辆/标书"一律不算 |
| 配售均价 | 均价/配售均价/基准售价 N 元/㎡ | 区分"均价"与"最高价""总价" |
| 认购订金 | 订金/保证金 N 万元 | 万元要换算成元 |
| 咨询电话 | 咨询电话/业务咨询电话 0755-xxxx | 取业务电话，不取投诉举报电话 |
| 接待中心 | 接待中心/看房地址/项目地址 | 与项目物理地址区分 |
| 认购窗口 | 认购时间 X 至 Y | 转成 YYYY-MM-DD |
| 常态化出口 | "剩余房源实行常态化配售"/"现场认购、即时选房" | 命中则 `has_regular_sales_exit=1` |

### Step 7 判断归属：项目 → 批次
- **项目**：取正文里的标准项目名（"XX 项目""XX 花园/苑/府/城/大厦"）。库里已有则复用，
  没有就先 `upsert-project` 建档（district 必填）。**不要**把区住建局、保障署当项目名。
- **批次**：以官方文号为准，规范化为 `住保售〔YYYY〕NNN号批次`（序号**补零三位**）。
  - `住保租〔YYYY〕NNN号` 属于**配租**，不进 `batches`（配售台账），只记 `notices`。
  - 同一项目多次推售（如 043 → 073 → 083）是**不同批次**，不要合并。
  - 同一批次的"选房有关事项通知（2026077-1）"这类派生文号，归到主批次上。
  - 若需解除已挂批次（如误挂或不适用），传 `--batch-id ""` 即可清空为 NULL。

### Step 8 写入顺序（有外键依赖）
1. `upsert-project` → 拿到 `project_id`
2. `upsert-batch`（新批次才需要；用 `--project-id`）
3. `upsert-notice`（`--batch-id` 可为空串表示不挂批次）
4. `append-timeline`（把该公文事件的 stage/title/date/url 追加到批次时间线）
5. 若为政策法规，则直接执行 `upsert-policy`

全部按 URL / batch_id / (city, project_name) 幂等，重复执行不会产生脏数据，可放心重跑。

### Step 9 状态机推进（单向不降级）
```
认购中(1) → 初审名单公示(2) → 终审公示(3) → 公证摇号(4) → 选房签约中(5) → 常态化配售中(6) → 已完成选房(7)
```
- 只用**明确信号**推进：初审名单→2、终审结果→3、摇号通告/结果→4、选房通告/结果→5、
  明确"现场即时选房/常态化配售"→6、选房售罄公告→7。
- **绝不降级**：新通告阶段权重 ≤ 当前权重时，不动 `current_stage`，只在时间线追加事件。
- 一类容易误判的情形：项目上一批次已进入"常态化配售中"，新批次又从"认购中"开始——
  这是**新批次**，不是降级，按新 batch_id 建行即可。

### Step 10 自检（必做）
```bash
python3 <SKILL_DIR>/scripts/db_io.py stats --city 深圳
python3 <SKILL_DIR>/scripts/db_io.py query "SELECT publish_date, district, substr(title,1,40) FROM notices ORDER BY publish_date DESC LIMIT 10"
python3 <SKILL_DIR>/scripts/db_io.py query "SELECT batch_id, current_stage, total_units, average_price FROM batches ORDER BY batch_id DESC LIMIT 10"
python3 <SKILL_DIR>/scripts/db_io.py query "SELECT url, COUNT(*) c FROM notices GROUP BY url HAVING c>1"
```
逐项确认：① 新公文都进了库；② 没有重复 URL；③ 批次套数/价格没有明显离谱值；
④ 阶段只前进没后退；⑤ 空源已排查。最后向用户汇报"新增几条、涉及哪些批次、哪些跳过及原因"。

---

## 3. 反模式（明确禁止）

- ❌ 在脚本里加 `HOUSING_KEYWORDS` 之类的关键词白名单来决定抓什么——关键词会漏掉新表述，判断权属于 Agent。
- ❌ 用正则硬猜批次号/项目名后直接入库——猜错会污染台账（历史事故：`住保租` 被当成配售批次、
  `星河开市客` 被挂到"文化创意园"、`光盘2套` 被当成三房套数）。
- ❌ 一条公文挂多个批次，或把派生通知单独建批次。
- ❌ 因为"今天没抓到"就断言"官方没发"——先排查空源与页面改版。

---

## 4. 待人工确认的情况

遇到以下情形，写入时在汇报里单列，不要自行拍板：
- 正文套数与标题/附件表格数字对不上；
- 同一文号在两个区同时出现（跨区联合配售）；
- 项目名与库内已有项目疑似同一实体但名称不同（如"XX 花园"vs"XX 花园（二期）"）；
- 公文只给"剩余房源"未给套数。
