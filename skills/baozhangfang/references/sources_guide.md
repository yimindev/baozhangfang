# 多城市数据源接入与扩展规范 (Sources Guide)

`baozhangfang` 支持多城市水平扩展，数据源统一由 `config/sources.json` 声明式驱动。

---

## 0. 四条硬规则

1. **只入库 gkmlpt**：专题页/主题页只作为 `entry_url` 用于 UI 校验，不再并行入库。
2. **一个区一个主源**：优先住房保障专栏目；没有专栏目才退到综合通知公告。
3. **旧源先禁用、验证后再定**：默认 `role: legacy` + `enabled: false`；若新旧源对比发现旧源仍有独有住房公告，
   改为 `role: auxiliary` + `enabled: true` 长期补充（如深圳旧龙岗 `6622`、旧盐田 `17753`、旧南山 `15162`）。
4. **脚本不做相关性判断**：抓到的条目原样输出，保留哪些由 Agent 按 `sync_playbook.md` 决定。

---

## 1. 配置文件结构 (`config/sources.json`)

每个城市一个对象，`sources` 供通知公告使用，`policy_sources` 供政策法规使用：

```json
{
  "city_id": "shenzhen",
  "city_name": "深圳市",
  "province": "广东省",
  "admin_code": "440300",
  "enabled": true,
  "sources": [
    {
      "source_id": "sz_nanshan_zf",
      "level": "district",
      "district": "南山区",
      "name": "南山区住房和建设局（住房服务）",
      "type": "gkmlpt",
      "role": "primary",
      "enabled": true,
      "cat_id": 22231,
      "entry_url": "https://www.szns.gov.cn/nsqzjj/gkmlpt/index#22231",
      "api": "https://www.szns.gov.cn/nsqzjj/gkmlpt/api/all/22231?page={page}&m=5",
      "description": "南山区住房服务栏目，覆盖人才房、保租房配租配售"
    },
    {
      "source_id": "sz_nanshan",
      "level": "district",
      "district": "南山区",
      "name": "南山区住房和建设局（通知公告·旧）",
      "type": "gkmlpt",
      "role": "legacy",
      "enabled": false,
      "replaced_by": "sz_nanshan_zf",
      "cat_id": 15162,
      "entry_url": "https://www.szns.gov.cn/nsqzjj/gkmlpt/index#15162",
      "api": "https://www.szns.gov.cn/nsqzjj/gkmlpt/api/all/15162?page={page}&m=5",
      "description": "旧综合通知源，保留用于回滚与差异对比"
    }
  ],
  "policy_sources": [
    {
      "source_id": "sz_policy_zjj_gfxwj",
      "level": "municipal",
      "district": "市住建局",
      "name": "深圳市住建局政策法规-规范性文件",
      "type": "gkmlpt",
      "role": "policy",
      "enabled": true,
      "cat_id": 2020,
      "entry_url": "https://zjj.sz.gov.cn/xxgk/zcfgs/zcfg/index.html",
      "api": "https://zjj.sz.gov.cn/gkmlpt/api/all/2020?page={page}&m=5",
      "description": "保障性住房相关条例、办法、实施细则主源"
    }
  ]
}
```

### 字段说明

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| `source_id` | 是 | 全局唯一源标识，写入日志与巡检报告 |
| `level` | 是 | `municipal` / `district` |
| `district` | 是 | 入库时写入 `notices.district`；市级源统一用 `市住建局` |
| `name` | 是 | 发布机构全称 |
| `type` | 是 | 当前只推荐 `gkmlpt`；`topic_html` 仅保留给旧源 |
| `role` | 是 | `primary` 主源 / `auxiliary` 补充源 / `policy` 政策源 / `legacy` 旧源 |
| `enabled` | 是 | `false` 时 `fetch_list` 默认跳过；显式 `--source` 仍可抓 |
| `cat_id` | gkmlpt 必填 | 政府信息公开目录栏目 ID |
| `entry_url` | 是 | 官方 UI 入口，用于人工核对与 `audit_sources` 的 UI/API 对比 |
| `api` | gkmlpt 必填 | `.../gkmlpt/api/all/{cat_id}?page={page}&m=5`，`{page}` 为页码占位符 |
| `description` | 是 | 一句话说明该源覆盖范围与噪声水平 |
| `replaced_by` | legacy 建议 | 指向替代它的新 `source_id`，回滚时反向启用 |

> `sources` 与 `policy_sources` 相互独立：前者对应 `--channel notices`（默认），
> 后者对应 `--channel policies`。`enabled: false` 的源默认不抓，但保留用于对比与回滚。

---

## 2. 采集协议

| 类型 (`type`) | 适用场景 | 采集方式 | 说明 |
| :--- | :--- | :--- | :--- |
| **`gkmlpt`** | 广东省各级政府信息公开目录 | 直接请求 JSON API | 标准字段：`title`、`url`、`date`、`abstract`、`attachment`、`classify_main_name` |
| **`topic_html`** | 历史专题页（现仅旧源） | 解析 HTML 列表 | 仅作兼容保留，不再新增 |

### gkmlpt 日期字段优先级

```text
date (epoch) → display_publish_time → first_publish_time → created_at
```

`created_at` 是入库时间，**不能**直接当官方发布日期。典型案例：大鹏 `住保售〔2026〕078`，
`created_at=2026-10-28`，官方 `date=2026-10-30`。

### API 统一格式

```text
https://{站点}/gkmlpt/api/all/{cat_id}?page={page}&m=5
```

各站点前缀见 [SOURCE_REVIEW.md](../../../SOURCE_REVIEW.md) 附录。实际返回可能一次 100 条，
`m=5` 只是请求参数，不影响分页抓取。

---

## 3. 源发现与切换 SOP

1. **从 UI 主路径找栏目**：先按用户实际浏览路径进入住房保障栏目，记下页面上的 `cat_id`（`index#xxxxx`）。
2. **读 `classify.name` / `classify_main`**：API 返回的 `classify.name` 是栏目名，文章里的
   `classify_main_name` 是实际归类；两者不一致时以文章归类为准判断覆盖范围。
3. **别只看 TREE**：gkmlpt 的栏目树不是完整列表。宝安 `22387` 这类父聚合不在 TREE 中，
   需要通过文章 `classify_main`、父级 API 或直接试 `api/all/{cat_id}` 发现。
   部分站点/聚合栏目在 API 中不暴露 `sync_cats`，此时只能对比父级与子栏目条数，不能假定已同步全部子栏目。
4. **UI/API 对照**：UI 最新 N 条应能在 API 最新 M 条中找到（同栏目应精确重叠）；
   UI 有、API 无的条目只报告，不自动入库。
5. **新旧源差异对比**：新增源保持旧源启用，分别抓最新 100 条，按 `title + publish_date`
   比对，确认旧源没有独有的保障房公告。
6. **切换顺序**：新源 `enabled: true` → 入库验证 → 旧源先 `enabled: false` → 再跑一次
   `fetch_list` 与 `audit_sources`。若旧源仍有独有住房公告，改回 `enabled: true` 并标为 `auxiliary`，
   不要为了“配置干净”牺牲数据覆盖。
7. **记录结论**：把源映射、cat_id、切换日期、验证批次写进 `SOURCE_REVIEW.md` 或任务记录。

### 全站对照法（找“堂兄弟”栏目的漏配）

只检查父/兄弟栏目会漏掉相邻分支（如宝安 `5445` 与 `22387` 同属住建局但父节点不同）。
用 `api/all/0` 做站点级对照：它等于前端 `index` 无 hash 时的“全部”视图，
返回体没有 `classify` 字段，`total` 是该站点公开目录总数，100 条/页（`m` 参数被忽略）。

```bash
# 取站点最近 300 条 → 按住房关键词筛 → 尚未入库的条目按 classify_main_name 归类
curl -s '<站点前缀>/gkmlpt/api/all/0?page=1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["total"]); print(d["articles"][0]["title"])'
```

判据：缺失条目集中在某个 `classify_main`，且该 cat_id 既不是当前源的祖先也不是后代 → 该栏目需要新增或启用源。
注意 `api/all/0` 混有工作动态、机构领导、财政预决算等噪声，只看住房相关条目。

**父聚合只覆盖自己的子树**：宝安 `22353` 严格包含 `22387`（457 ⊆ 470，多出的 13 条是燃气/造价公告），
但住建局的综合公告在另一棵树 `22362 → 5445`，与两者交集为 0。
判断某部门是否配全，按「站点 + 发布部门」算，而不是只看一个父节点。

```bash
# 新源与旧源并排抓取对比（显式指定 --source 时包含已禁用源）
python3 <SKILL_DIR>/scripts/fetch_list.py --city 深圳 --source sz_nanshan_zf --source sz_nanshan \
        --pages 1 --out /tmp/compare.json --summary

# 只跑单源巡检
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳 --source sz_nanshan_zf
```

---

## 4. 接入新城市三步走（以广州为例）

1. **查验官方发布地址**：确认市局与各区的 gkmlpt 站点、栏目 `cat_id`、UI 入口页。
2. **追加城市配置**：
   ```json
   {
     "city_id": "guangzhou",
     "city_name": "广州市",
     "province": "广东省",
     "admin_code": "440100",
     "enabled": true,
     "sources": [
       {
         "source_id": "gz_municipal",
         "level": "municipal",
         "district": "市住建局",
         "name": "广州市住房和城乡建设局",
         "type": "gkmlpt",
         "role": "primary",
         "enabled": true,
         "cat_id": 12345,
         "entry_url": "https://zjj.gz.gov.cn/.../index.html",
         "api": "https://zjj.gz.gov.cn/gkmlpt/api/all/12345?page={page}&m=5",
         "description": "市级住房保障通知公告"
       }
     ],
     "policy_sources": []
   }
   ```
3. **验证并入库**：
   ```bash
   python3 <SKILL_DIR>/scripts/fetch_list.py --city 广州 --pages 1 --summary
   python3 <SKILL_DIR>/scripts/fetch_list.py --city 广州 --channel policies --summary
   # 之后的判断与写库按 references/sync_playbook.md 执行，写入时统一带 --city 广州
   ```
   记录天然带 `city='广州'`，与深圳数据隔离。

---

## 5. 巡检、告警与回滚

```bash
# 定期巡检（非每日）：API 条数/栏目名/最新日期 + 库内最新 + 重复 + UI 独有
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳 --channel policies
python3 <SKILL_DIR>/scripts/audit_sources.py --city 深圳 --include-disabled   # 确认旧源已无新增
```

状态含义：

| 状态 | 含义 | 处理 |
| :--- | :--- | :--- |
| `PASS` | API 可用、库内已跟上、无重复、UI 已被覆盖 | 无需处理 |
| `WARN` | 库内落后超过 `--max-lag` 天 / UI 有独有 / 有重复 | 查同步记录或栏目改版 |
| `FAIL` | API 无返回 | 按第 6 节排查，必要时切回旧源 |

**回滚步骤**（源异常或新源漏公告）：

1. 新源 `enabled: false`；
2. 旧源（`replaced_by` 指向的源）`enabled: true`；
3. 重跑 `fetch_list` + `audit_sources`；
4. 检查重复与孤儿 `batch_id`；
5. 在任务记录里写明回滚原因与日期。

---

## 6. 源不可用时的处置

| 现象 | 排查方向 | 处理 |
| :--- | :--- | :--- |
| `audit_sources` 报 FAIL | 栏目改版 / `cat_id` 失效 / 反爬 | 更新 `cat_id`、`api`、`entry_url`，或切回 `legacy` 源 |
| 抓到大量非住房公告 | 该区没有住房保障专栏目 | 换主源（如 16322 → 16835），噪声由 Agent 过滤 |
| 抓到的页面是导航页或日期陈旧 | `entry_url` 不是真正的列表页 | 修正 `entry_url`，入库仍以 `api` 为准 |
| API 最新日期长期不变 | 栏目变更 / 新公告发到别的栏目 | 查 `classify_main` 与父级栏目，必要时新增补充源 |
| 同一公告出现两条 | 两个源 URL 不同 | 按 `district + title + publish_date` 去重，见 `sync_playbook.md` |

> 脚本不做关键词过滤，抓到的条目一律原样输出，由 Agent 决定取舍；
> 因此“抓到但没用上”是正常的，“抓不到”才是配置问题。
