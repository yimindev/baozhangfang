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
# ① 库内最新日期（仅作参考，不是同步游标）
python3 <SKILL_DIR>/scripts/db_io.py latest --city 深圳
python3 <SKILL_DIR>/scripts/db_io.py latest --city 深圳 --district 盐田区

# ② 列表（宽松抓取，默认只用 enabled 源，不做任何关键词过滤）
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --pages 1 --summary
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --pages 1-3 --since 2026-11-01 --out /tmp/todo.json
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --channel policies --summary
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --source sz_longgang --summary   # 显式指定可抓旧源

# ③ 差集（按 URL 或 district+title+publish_date 判定已入库）
python3 <SKILL_DIR>/scripts/db_io.py diff --city 深圳 --input /tmp/todo.json
python3 <SKILL_DIR>/scripts/db_io.py diff --city 深圳 --input /tmp/todo.json --format lines   # 只列 new
python3 <SKILL_DIR>/scripts/db_io.py diff --city 深圳 --channel policies --input /tmp/policies.json
python3 <SKILL_DIR>/scripts/db_io.py known-urls --city 深圳 --since 2026-10-01 --format json

# ④ 正文（可一次传多个 URL；--tables 抽表格；--save-dir 落盘原始文件）
python3 <SKILL_DIR>/scripts/fetch_detail.py --url-file /tmp/todo_urls.txt --save-dir /tmp/bf_html
python3 <SKILL_DIR>/scripts/fetch_detail.py <url> --tables

# ⑤ 写库（全部参数化；通知按 district+title+publish_date → url 两级去重）
python3 <SKILL_DIR>/scripts/db_io.py upsert-project --name 星河开市客环球商业中心 --district 龙华区
python3 <SKILL_DIR>/scripts/db_io.py upsert-batch --batch-id "住保售〔2026〕054号批次" --project-id 84 \
        --total-units 300 --three-bedroom-units 300 --average-price 28000 --current-stage 选房签约中
python3 <SKILL_DIR>/scripts/db_io.py upsert-notice --url <url> --title "<标题>" --date 2026-11-10 \
        --district 光明区 --category 综合公告 --content-file /tmp/body.txt
python3 <SKILL_DIR>/scripts/db_io.py upsert-policy --url <url> --title "<法规标题>" --category 地方性法规 \
        --publisher 深圳市住房和建设局 --date 2026-08-01 --content-file /tmp/policy.txt
python3 <SKILL_DIR>/scripts/db_io.py append-timeline --batch-id "<批次>" --stage 初审名单 \
        --title "<标题>" --date 2026-11-09 --url <url>

# ⑥ 定期巡检（非每日必跑；源切换/回填验收/每周体检时用）
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳
```

---

## 2. 标准流程

### Step 1 看库内最新（仅参考）
`db_io.py latest --city 深圳` 返回库内已入库的最新日期，用于判断大概缺口，**不是抓取起点**。
增量判断不依赖“上次同步到哪”，而是每次抓最近 1–2 页后做 `diff`：

> 本技能不维护独立水位线表。库内 `notices` 就是唯一真相；`diff` 负责回答
> “这条公告是否已入库”。因此停更几天、补发旧日期公告、历史回填，都不会被游标跳过。
> 需要补深历史时，显式加 `fetch_list --pages` 或 `--since`，不需要更新任何状态。

### Step 2 抓列表（宽松）
一次抓完所有启用源的第 1 页；若某源第 1 页条数明显偏少、最新日期异常，或需要补历史，再加 `--pages 1-2`（或更多页）。
`--summary` 会输出每源条数、最新/最旧日期、栏目名与前 3 条，先看这一屏再决定抓哪些正文。
脚本会在 JSON 的 `empty_sources` 里告诉你哪些源颗粒无收——**空源要单独排查**（改版？反爬？页面结构变了？），
不要默默当成“今天没公告”。

### Step 3 差集
用 `db_io.py diff --input /tmp/todo.json` 直接分为 `new` / `known`：

1. 通知：按 `district + title + publish_date` 判定；政策：按 `city + title + publish_date` 判定（政策表无 district）；
2. 再按 `url` 兜底；
3. 只有 `new` 才需要抓正文与写库。

同一条公告/政策在 UI 与 gkmlpt 的 URL 不同时，只保留一条；`upsert-notice` / `upsert-policy`
会自动把旧的非 gkmlpt URL 升级为 gkmlpt URL，并返回 `matched_by` 与 `url_replaced`，便于核对。

政策源同样走 `--channel policies`：

```bash
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --channel policies --pages 1 --out /tmp/policies.json --summary
python3 <SKILL_DIR>/scripts/db_io.py diff --city 深圳 --channel policies --input /tmp/policies.json --format lines
```

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

`upsert-notice` 按 `district + title + publish_date` 优先去重，再按 URL 兜底，重复执行不会新增记录；
命中标题+日期时，会更新正文/附件，并在旧 URL 不是 gkmlpt 时升级为 gkmlpt 直链。

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
python3 <SKILL_DIR>/scripts/db_io.py query "SELECT district, title, publish_date, COUNT(*) c FROM notices GROUP BY district, title, publish_date HAVING c > 1"
```
逐项确认：① 新公文都进了库；② 没有重复 `title + publish_date`；③ 批次套数/价格没有明显离谱值；
④ 阶段只前进没后退；⑤ `fetch_list --summary` 里的 `empty_sources` 已排查。
最后向用户汇报“新增几条、涉及哪些批次、哪些跳过及原因”。

### 定期巡检（非每日必跑）

`audit_sources.py` 是只读体检工具，**不参与每日同步主流程**。它在同步链路之外，适合在以下时机运行：

- 新增或切换数据源后；
- 历史回填完成后的验收；
- 每周/每月定期体检；
- `fetch_list --summary` 出现空源、最新日期异常，或怀疑某区长期没更新时。

```bash
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳 --channel policies
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳 --include-disabled   # 确认旧源已无新增
```

出现 `FAIL`（API 无返回）或连续 `WARN`（库内落后、UI 有独有公告）时，
按 `references/sources_guide.md` 第 5、6 节排查；必要时回滚：新源 `enabled: false`、
旧源（`replaced_by` 指向的源）`enabled: true`，再重跑一次并检查重复。

---

## 3. 反模式（明确禁止）

- ❌ 在脚本里加 `HOUSING_KEYWORDS` 之类的关键词白名单来决定抓什么——关键词会漏掉新表述，判断权属于 Agent。
- ❌ 用正则硬猜批次号/项目名后直接入库——猜错会污染台账（历史事故：`住保租` 被当成配售批次、
  `星河开市客` 被挂到"文化创意园"、`光盘2套` 被当成三房套数）。
- ❌ 一条公文挂多个批次，或把派生通知单独建批次。
- ❌ 因为“今天没抓到”就断言“官方没发”——先排查空源与页面改版。
- ❌ 只靠城市级 `MAX(publish_date)` 判断所有区都同步完成——按源看 `fetch_list --summary` 与 `diff`，定期用 `audit_sources` 复核。
- ❌ 只按 URL 去重——同一公告在 UI 与 gkmlpt 的 URL 不同，必须先比 `district + title + publish_date`。

---

## 4. 待人工确认的情况

遇到以下情形，写入时在汇报里单列，不要自行拍板：
- 正文套数与标题/附件表格数字对不上；
- 同一文号在两个区同时出现（跨区联合配售）；
- 项目名与库内已有项目疑似同一实体但名称不同（如"XX 花园"vs"XX 花园（二期）"）；
- 公文只给"剩余房源"未给套数。
