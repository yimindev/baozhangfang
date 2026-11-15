# 保障房助手（baozhangfang）

把深圳市、区两级住建局的保障性住房公告，整理成一份可直接查询的 SQLite 数据集：楼盘、推售批次、公告原文、政策法规都在里面，写 SQL 或用自然语言提问都能查。

## 里面有什么

| 数据 | 规模 | 内容 |
| :-- | :-- | :-- |
| `projects` 项目 | 84 | 楼盘基础信息：区域、地址、户型、规划套数 |
| `batches` 批次 | 21 | 每次推售的套数与户型、配售均价、当前阶段、接待点与咨询电话 |
| `notices` 公文 | 1200+ | 认购、初审/终审公示、摇号、选房等公告原文与官方链接 |
| `policies` 政策 | 35 | 保障性住房条例、配售型保障房管理办法等全文 |

覆盖房源类型：人才配售房、安居型商品房、共有产权住房、配售型保障房、公共租赁住房。

能做的事：

- **多源增量同步**：市级住建局 + 福田、南山、罗湖、宝安、龙岗、龙华、光明、坪山、盐田、大鹏等区级公告源。
- **批次生命周期追踪**：认购中 → 名单公示 → 选房 → 常态化配售 / 已完结。
- **开箱即用**：纯 SQLite、零外部服务；数据以脱敏 SQL 种子随仓库分发。
- **多城市扩展**：新增城市只改配置，不动代码。

## 快速上手

```bash
pip install requests beautifulsoup4
python3 skills/baozhangfang/scripts/db.py     # 由 seed.sql 生成 data/housing.db

# 查某个楼盘的批次、套数、均价、阶段
sqlite3 -header -column skills/baozhangfang/data/housing.db "
SELECT p.project_name, p.district, b.batch_id, b.total_units, b.average_price, b.current_stage
FROM projects p JOIN batches b ON p.id = b.project_id
WHERE p.project_name LIKE '%华越龙苑%';"
```

刷新数据走「原子脚本 + Agent 作业手册」流程：`fetch_list.py` 抓列表 → `db_io.py diff` 挑出新公文 → `fetch_detail.py` 抓正文 → Agent 判断后写库 `db_io.py upsert-*`，详见 `skills/baozhangfang/references/sync_playbook.md`。

## 目录

```text
skills/baozhangfang/   # 自包含技能：配置、脱敏种子、原子脚本、参考文档
scripts/               # 可选扩展：数据看板、PDF 名单解析、MySQL 同步
config/                # 外部 MySQL 配置模版（可选）
```

常用查询模板见 `skills/baozhangfang/references/query_cheatsheet.md`，表结构见 `database_schema.md`。

## 作为 AI 技能使用

`skills/baozhangfang` 是一个自包含 Agent Skill，拷到技能目录即可让 AI 直接查库答题、执行数据同步。

## 许可

基于 [Apache License 2.0](LICENSE) 开源。
