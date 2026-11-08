# AGENTS.md

This file guides agentic coding assistants working on the **baozhangfang** repository.

---

## Project Overview

**baozhangfang (保障房助手)** is an end-to-end data synchronization, batch lifecycle tracking, policy management, and intelligent assistant platform for government-subsidized / affordable housing (人才房, 安居房, 共有产权房, 保租房).

- **Primary Asset**: A self-contained, portable Agent Skill located under `skills/baozhangfang/`.
- **Core Capabilities**:
  1. Multi-source incremental scraping from municipal and district housing bureaus.
  2. Batch lifecycle state machine tracking (`认购中` -> `认购名单已出` -> `选房中` -> `已选房/已完结`).
  3. Structured policy & regulation repository indexing.
  4. Instant CLI & natural language queries against an embedded SQLite database.
  5. Multi-city readiness via declarative JSON source configuration.

---

## General Principles

1. **Self-Contained Skill Principle (CRITICAL)**:
   - The skill at `skills/baozhangfang/` **MUST** remain 100% self-contained and portable.
   - All skill scripts must use the embedded pure SQLite database (`skills/baozhangfang/data/housing.db`).
   - The skill must **NEVER** depend on external MySQL databases, cloud RDS, or credentials outside its own directory.
   - External MySQL syncing scripts (for BI / Aliyun RDS) live exclusively in the root `scripts/sync_to_mysql.py` and are optional utility tools, not part of the skill runtime.

2. **Security & Credential Protection (ABSOLUTE)**:
   - **NEVER** commit `config/database.json` or any file containing real database passwords, API keys, or access tokens.
   - Only committed configuration templates (such as `config/database.json.example`) with sanitized dummy values are permitted.
   - Verify with `git status` and `git check-ignore` before staging any configuration files.

3. **No Over-Engineering & Minimal Dependencies**:
   - Prefer Python standard library (`sqlite3`, `json`, `pathlib`, `re`, `argparse`, `datetime`).
   - Keep external dependencies minimal: only `requests` and `beautifulsoup4` for web scraping, and `pdfplumber` / `pypdf` for PDF parsing.

4. **Multi-City Extensibility**:
   - Do not hardcode Shenzhen in architecture or data models.
   - Data sources are declaratively defined in `config/sources.json` (city, district, source URLs, CSS selectors, category rules).
   - Ensure table schemas include `city` and `district` partition fields.

5. **Clean Working Tree**:
   - Temporary PDF downloads, sample spreadsheets (`*.xlsx`), and intermediate JSON caches must remain gitignored.
   - Do not leave ad-hoc test scripts or scratch output files in the repository root.

---

## Repository Structure

```text
baozhangfang/
├── AGENTS.md                     # Agent guidelines and operating instructions (this file)
├── README.md                     # Project documentation & quick start
├── .gitignore                    # Git exclusion rules (sensitive configs, temporary files)
├── skills/
│   └── baozhangfang/             # Portable Agent Skill (self-contained)
│       ├── SKILL.md              # Skill specification & prompt instructions for LLMs
│       ├── config/
│       │   └── sources.json      # Multi-city data source configurations
│       ├── data/
│       │   └── housing.db        # Embedded SQLite database (projects, batches, notices, policies)
│       ├── scripts/
│       │   ├── schema.py         # SQLite DDL & table initialization
│       │   ├── sync_incremental.py # Incremental notice scraper & batch state machine
│       │   ├── sync_policies.py  # Housing policy scraper & categorizer
│       │   ├── sync_historical.py# Historical notice & batch baseline builder
│       │   └── query_housing.py  # CLI search & statistical query tool
│       └── references/
│           ├── database_schema.md# Detailed table structures & ER diagrams
│           ├── query_cheatsheet.md# Common SQL snippets & query examples
│           └── sources_guide.md  # Guide for adding new city data sources
├── config/
│   ├── database.json.example     # Sanitized Aliyun RDS MySQL configuration template
│   └── sources.json              # Source configuration for root utilities
├── scripts/                      # Root developer utilities & data pipelines
│   ├── build_dashboard.py        # Dashboard HTML generator
│   ├── parse_pdf.py              # PDF applicant qualification list parser
│   ├── sync_to_mysql.py          # Aliyun RDS MySQL bridge (optional)
│   └── ...
├── data/
│   └── housing.db                # Local working SQLite copy
└── dashboard.html                # Interactive data visualizer & statistics dashboard
```

---

## Database Architecture & Tables

Both `skills/baozhangfang/data/housing.db` and the root `data/housing.db` share the same schema:

| Table | Purpose | Key Columns |
|---|---|---|
| `housing_projects` | Housing project master table | `project_id`, `project_name`, `city`, `district`, `project_type`, `total_units`, `record_price`, `status` |
| `subscription_batches` | Subscription batch lifecycle | `batch_id`, `batch_title`, `batch_code`, `project_id`, `batch_status`, `apply_start`, `apply_end` |
| `official_notices` | Scraped official government notices | `notice_id`, `title`, `url`, `publish_date`, `notice_type`, `city`, `district`, `batch_code` |
| `policies` | Housing policies & regulations | `policy_id`, `title`, `url`, `publish_date`, `department`, `category`, `summary`, `content` |
| `sync_watermark` | Incremental sync tracking | `city`, `source_id`, `last_sync_time`, `last_notice_date`, `total_synced` |

### Batch State Machine Transitions
```text
[认购通告发布] -> 认购中 (subscribing)
     ↓
[认购名单公布] -> 认购名单已出 (list_published)
     ↓
[选房通告发布] -> 选房中 (selecting)
     ↓
[选房结果公告] -> 已选房 / 已完结 (completed)
```

---

## Commands & Workflows

### 1. Skill CLI Queries (SQLite)
```bash
# Display overall statistics dashboard
python3 skills/baozhangfang/scripts/query_housing.py --stats

# Fuzzy search housing projects by name
python3 skills/baozhangfang/scripts/query_housing.py --project "华越龙苑"

# Query active batches (subscribing / selecting)
python3 skills/baozhangfang/scripts/query_housing.py --active

# Query latest housing policies
python3 skills/baozhangfang/scripts/query_housing.py --policies --limit 5

# Query open regular subscription projects (常态化申购)
python3 skills/baozhangfang/scripts/query_housing.py --regular
```

### 2. Incremental Synchronization
```bash
# Run incremental sync across official sources (updates notices & batches)
python3 skills/baozhangfang/scripts/sync_incremental.py

# Scrape and update policy database
python3 skills/baozhangfang/scripts/sync_policies.py
```

### 3. Adding a New City or District
1. Open `skills/baozhangfang/config/sources.json`.
2. Add a new source entry under the target city with:
   - `id`: unique source identifier.
   - `name`: government department name.
   - `city` / `district`: administrative division.
   - `list_url`: official notice list page URL.
   - `selectors`: CSS selectors for title, link, date, and pagination.
3. Test scraper compatibility with `python3 skills/baozhangfang/scripts/sync_incremental.py`.

---

## Agent Operational Rules

1. **Verify Before Modifying**:
   - When modifying scrapers or database schemas, test against a copy or run `query_housing.py --stats` to confirm data integrity.
2. **Synchronize Skill and Root Assets**:
   - If updates are made to `skills/baozhangfang/config/sources.json`, keep root `config/sources.json` aligned if applicable.
3. **Commit Cleanly**:
   - Write clear, conventional commit messages (`feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`).
   - Run `git status` to ensure no unwanted files or secrets are staged.
