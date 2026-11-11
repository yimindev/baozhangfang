# 多城市数据源接入与扩展规范 (Sources Guide)

`baozhangfang` 支持多城市水平扩展，数据源由 `config/sources.json` 驱动。

---

## 1. 配置文件结构 (`config/sources.json`)

每个城市作为一个独立对象，包含城市基本信息与该城市下辖的各级政务数据源列表：

```json
{
  "cities": [
    {
      "city_id": "shenzhen",
      "city_name": "深圳市",
      "province": "广东省",
      "admin_code": "440300",
      "enabled": true,
      "metadata": {
        "platform_primary": "gkmlpt",
        "housing_types": ["人才配售房", "安居型商品房", "共有产权住房", "公共租赁住房"]
      },
      "sources": [
        {
          "source_id": "sz_municipal",
          "level": "municipal",
          "district": "市直属",
          "name": "深圳市住房保障署（市住建局）",
          "type": "topic_html",
          "enabled": true,
          "url": "https://zjj.sz.gov.cn/ztfw/zfbz/tzgg2017/index.html",
          "page_pattern": "https://zjj.sz.gov.cn/ztfw/zfbz/tzgg2017/index_{page}.html"
        },
        {
          "source_id": "sz_luohu",
          "level": "district",
          "district": "罗湖区",
          "name": "罗湖区住房和建设局",
          "type": "gkmlpt",
          "cat_id": 12588,
          "enabled": true,
          "api": "https://www.szlh.gov.cn/lhqzfhjsj/gkmlpt/api/all/12588?page={page}&m=5"
        }
      ],
      "policy_sources": [
        {
          "source_id": "sz_policy_zjj",
          "level": "municipal",
          "district": "市直属",
          "name": "深圳市住建局住房保障政策法规专栏",
          "type": "topic_html",
          "enabled": true,
          "url": "https://zjj.sz.gov.cn/ztfw/zfbz/zcfg2017/index.html",
          "page_pattern": "https://zjj.sz.gov.cn/ztfw/zfbz/zcfg2017/index_{page}.html"
        }
      ]
    }
  ]
}
```

> 两个列表相互独立：`sources` 供 `fetch_list.py --channel notices`（默认）使用，
> `policy_sources` 供 `--channel policies` 使用。`enabled: false` 的源会被跳过。
> 某个源抓不出条目时，`fetch_list.py` 会在 `empty_sources` 里报出来——**这类源要单独排查**（改版 / 反爬 / 选择器失效），
> 不要默认它"今天没公告"。

---

## 2. 支持的数据源采集协议

| 类型 (`type`) | 适用场景 | 采集方式 | 特点 |
| :--- | :--- | :--- | :--- |
| **`gkmlpt`** | 广东省各级政府“政府信息公开目录系统”标准接口 | 直接请求 JSON API（带 `{page}` 占位符） | 速度极快，自带标题、发布时间、摘要及附件直链。 |
| **`topic_html`** | 住建局保障房专栏、专题分页 HTML 列表 | 解析 HTML 列表（`<li><a title="..."><span>date</span></li>`） | 通用性强，适应各类专题网页。 |
| **`rss / api`** | 其他政务信息平台开放 API | 解析 RESTful JSON 或 RSS XML 流 | 易于扩展第三方接口。 |

---

## 3. 接入新城市三步走 (以接入广州市为例)

1. **查验官方通告发布地址**：
   - 广州市住房和城乡建设局保障房专栏：`http://zjj.gz.gov.cn/`；
   - 确认各区（天河、黄埔、南沙等）是否有信息公开目录或专题页。
2. **在 `config/sources.json` 追加城市配置**：
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
         "district": "市直属",
         "name": "广州市住建局保障房专栏",
         "type": "topic_html",
         "url": "http://zjj.gz.gov.cn/.../index.html"
       }
     ]
   }
   ```
3. **抓取该城市的列表并入库**：
   ```bash
   python3 <SKILL_DIR>/scripts/fetch_list.py --city 广州 --pages 1 --format table
   python3 <SKILL_DIR>/scripts/fetch_list.py --city 广州 --channel policies --format table
   # 之后的判断与写库按 references/sync_playbook.md 执行，写入时统一带 --city 广州
   ```
   数据将天然写入带 `city='广州'` 标记的记录，与已有数据隔离互不干扰。

---

## 4. 源不可用时的处置

| 现象 | 排查方向 | 处理 |
| :--- | :--- | :--- |
| 长期出现在 `empty_sources` | 栏目改版 / 接口参数变化 / 反爬 | 更新 `url` / `api` / `page_pattern`，或改 `enabled: false` |
| 抓到的页面是导航页（条目日期陈旧） | 配置的 `url` 不是真正的列表页 | 换成实际列表页，或摘除该源 |
| 返回条目缺日期或标题 | 页面结构不符合 `<li><a><span>` | 属 `topic_html` 适配问题，需按站点调整解析或改用 gkmlpt 接口 |

> 脚本不做关键词过滤，抓到的条目一律原样输出，由 Agent 决定取舍；
> 因此"抓到但没用上"是正常的，"抓不到"才是配置问题。
