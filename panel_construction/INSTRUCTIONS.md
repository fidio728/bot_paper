# Panel Construction: Historical robots.txt Policy Panel via Wayback Machine

## What this project does

Build a monthly panel of robots.txt **policies** for 4,350 corporate website hosts, covering January 2021 to March 2026 (63 months). This is a **policy panel**, not a historical version of the main treatment variable (`search_public_block`). The effect-based Tier 2 treatment requires sitemap intensity data which is only available for the March 2026 snapshot.

The panel is used for:
- Identifying **when** each firm first blocked each AI bot (treatment timing for staggered DID)
- Event study around GPTBot launch (Aug 2023), Google-Extended launch (Sep 2023), and search bot launches (2024)
- Documenting the diffusion of AI-related robots.txt rules over time

Effect on public content will be validated separately via the pilot test (ChatGPT Search citations) and Common Crawl coverage analysis.

## Existing code — DO NOT REWRITE

Import from the parent directory (`bot_paper/`):

```python
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from robots_parser import parse_robots, classify_bot, get_applicable_rules
```

**Available functions:**
- `parse_robots(content) -> list` — parses robots.txt into groups
- `classify_bot(groups, bot_name, aliases) -> dict` — returns `root_block`, `has_nonroot_disallow`, `specific_rule`, `effective_source`
- `get_applicable_rules(groups, aliases) -> (rules, has_specific, source)` — use this to count `n_disallow_rules` (count Disallow entries in the returned `rules` list)

**Bot taxonomy** (copy this dict into your scripts):
```python
BOT_TAXONOMY = {
    "GPTBot":              {"group": "training",  "aliases": ["gptbot"]},
    "ClaudeBot":           {"group": "training",  "aliases": ["claudebot"]},
    "Google-Extended":     {"group": "training",  "aliases": ["google-extended"]},
    "CCBot":               {"group": "training",  "aliases": ["ccbot"]},
    "Meta-ExternalAgent":  {"group": "training",  "aliases": ["meta-externalagent"]},
    "OAI-SearchBot":       {"group": "search",    "aliases": ["oai-searchbot"]},
    "Claude-SearchBot":    {"group": "search",    "aliases": ["claude-searchbot"]},
    "PerplexityBot":       {"group": "search",    "aliases": ["perplexitybot"]},
    "ChatGPT-User":        {"group": "user",      "aliases": ["chatgpt-user"]},
    "Perplexity-User":     {"group": "user",      "aliases": ["perplexity-user"]},
    "Meta-ExternalFetcher":{"group": "user",      "aliases": ["meta-externalfetcher"]},
    "Googlebot":           {"group": "control",   "aliases": ["googlebot"]},
}
```

**Host list:** `bot_paper/compustat_2025_clean.csv`, column `host_clean`, 4,350 unique hosts after dedup.

**Path handling:** Always use `Path(__file__).resolve().parent.parent` to find `bot_paper/`. Never hardcode absolute paths (directory contains special character: Ramón).

---

## Critical design decisions

### 1. 404 = observed allow-all, NOT missing

Match the cross-sectional scan logic exactly:
- **`no_snapshot`**: Wayback has no archive for this month → all bot fields = **NA**
- **`no_robots_file`**: Wayback snapshot exists, original HTTP status was 404 or 410 → this is an observation of **allow-all** per RFC 9309. Record `root_block=0, has_nonroot_disallow=0, blocked_any=0, specific_rule=0, effective_source="no_robots_file"`
- **`ok_200`**: Wayback snapshot exists, status 200 → download content and parse
- **Other status codes** (3xx, 5xx, etc.): → `archived_http_error`, all bot fields = **NA**
- **`content_missing`**: digest exists but download failed → all bot fields = **NA**

### 2. Step 1: NO `collapse=digest`

Do NOT collapse in the CDX query. Collapsing removes consecutive identical snapshots, which makes Step 2 think months with unchanged content have no snapshot. Get the full list in Step 1; deduplicate downloads in Step 3.

### 3. Step 3: only download status-200 digests

Do not download 404/410 bodies (they are error pages, not robots.txt). Directly classify as `no_robots_file` in Step 4.

### 4. Timing columns must be explicit about what is blocked

Use `first_month_root_blocked` not `first_month_blocked`. Otherwise it is ambiguous whether "blocked" means `root_block=1` or `blocked_any=1`.

### 5. Policy changes must record time gaps

If the gap between consecutive observed months is >1 month, the exact timing of the change is unknown (interval-censored). Record `gap_months` and `timing_interval_censored = 1`.

---

## Output files

### Layer 1: `robots_panel_monthly.csv` (raw bot-level)

Unit: `host × year_month × bot`. One row per combination.

| Column | Type | Description |
|---|---|---|
| `host` | str | Website host |
| `year_month` | str | YYYY-MM |
| `snapshot_timestamp` | str | Full Wayback timestamp, NA if no snapshot |
| `snapshot_date` | str | YYYY-MM-DD |
| `bot` | str | Bot name |
| `bot_group` | str | training / search / user / control |
| `fetch_status` | str | ok_200 / no_robots_file / archived_http_error / no_snapshot / content_missing |
| `http_status` | int/NA | Original HTTP status from CDX |
| `robots_hash` | str | CDX digest |
| `root_block` | float | 0/1/NA |
| `has_nonroot_disallow` | float | 0/1/NA |
| `blocked_any` | float | 0/1/NA (root_block OR has_nonroot_disallow) |
| `specific_rule` | float | 0/1/NA |
| `effective_source` | str | specific / wildcard / none / no_robots_file / fetch_error |
| `n_disallow_rules` | int/NA | Count of Disallow rules for this bot (use `get_applicable_rules()`) |

### Layer 2: `firm_panel_monthly.csv` (firm-level aggregated)

Unit: `gvkey × year_month`.

| Column | Type | Description |
|---|---|---|
| `gvkey` | int | Compustat firm ID |
| `host` | str | Website host (**keep this** for clustering) |
| `year_month` | str | YYYY-MM |
| `any_block` | float | Tier 0: any of 8 treatment bots has blocked_any=1 |
| `search_block` | float | Tier 1: any of 3 search bots has blocked_any=1 |
| `search_full_block` | float | All 3 search bots root-blocked |
| `search_block_specific` | float | Any search bot blocked via specific rule |
| `training_block` | float | Any training bot root-blocked |
| `n_search_root_blocked` | int | 0-3 |
| `n_training_root_blocked` | int | 0-5 |
| `fetch_status` | str | ok / no_snapshot / error |

### `treatment_timing.csv` (host × bot)

| Column | Description |
|---|---|
| `host`, `bot`, `bot_group` | Identifiers |
| `first_month_mentioned` | First YYYY-MM where `specific_rule = 1` |
| `first_month_root_blocked` | First YYYY-MM where `root_block = 1` |
| `first_month_any_restriction` | First YYYY-MM where `blocked_any = 1` |
| `last_month_root_blocked` | Last YYYY-MM where `root_block = 1` |
| `never_root_blocked` | 1 if root_block was never 1 |
| `always_root_blocked` | 1 if root_block was 1 in every observed month |
| `switcher_root` | 1 if root_block changed at least once |
| `switcher_any` | 1 if blocked_any changed at least once |
| `n_months_observed` | Months with non-missing data |

### `policy_changes.csv` (host × bot × event)

| Column | Description |
|---|---|
| `host`, `bot` | Identifiers |
| `year_month` | Month change was first observed |
| `prev_year_month` | Previous observed month |
| `change_type` | first_mention / allow_to_root_block / root_block_to_allow / allow_to_nonroot / nonroot_to_allow |
| `gap_months` | Months between prev and current observation |
| `timing_interval_censored` | 1 if gap_months > 1 (exact timing unknown) |

### `firm_treatment_timing_bot.csv` (gvkey × bot)

Per gvkey × bot: same columns as `treatment_timing.csv` plus `gvkey`. One row per gvkey × bot combination. Used for bot-specific staggered DID and launch event studies.

### `firm_treatment_timing.csv` (gvkey search-level onset)

One row per gvkey. Search-level aggregated onset timing:
- `first_month_search_block`: first YYYY-MM where `search_block = 1`
- `first_month_search_full_block`: first YYYY-MM where `search_full_block = 1`
- `first_month_search_block_specific`: first YYYY-MM where `search_block_specific = 1`
- `first_month_any_block`: first YYYY-MM where `any_block = 1`

---

## Pipeline: 5 scripts

### Script 1: `01_query_cdx.py` (~2-3 hours)

Query Wayback Machine CDX API for ALL snapshot timestamps (no collapse).

**API per host:**
```
GET https://web.archive.org/cdx/search/cdx
    ?url={host}/robots.txt
    &output=json
    &from=20210101
    &to=20260401
    &fl=timestamp,statuscode,digest,length,original
```

**Do NOT use `collapse=digest`.** Get full list. Dedup at download in Step 3.

- `original` field: contains the original URL with scheme (https:// or http://), needed in Step 3
- Rate limit: 1 request/second
- User-Agent: `Mozilla/5.0 (compatible; AcademicResearchBot/1.0; robots-panel-study)`

**Input:** `bot_paper/compustat_2025_clean.csv` → unique `host_clean`

**Output:**
- `cdx_snapshots.json`: `{host: [[timestamp, statuscode, digest, length, original], ...], ...}`
- `cdx_coverage_summary.csv`: `host, n_snapshots, n_distinct_months, first_snapshot_date, last_snapshot_date, has_pre_202308, has_post_202308`

**Checkpoint:** Save JSON every 100 hosts. On restart, skip hosts already in JSON.

**Feasibility check (print at end):**
```
Hosts with ≥1 snapshot: ???
Hosts with ≥12 distinct months: ???
Hosts with ≥24 distinct months: ???
Hosts with pre AND post 2023-08: ???
>>> If <1,000 hosts have 12+ months, STOP.
```

---

### Script 2: `02_select_monthly.py` (~1 minute)

For each host × month (63 months), pick the best snapshot.

- Find all CDX snapshots in that calendar month
- Pick the one closest to the 15th
- If none exists: `has_snapshot = 0`, all other fields NA
- Compare `digest` to previous month: `content_changed = True` if different

**Output:** `monthly_snapshots.csv`

| Column | Description |
|---|---|
| `host` | |
| `year_month` | YYYY-MM |
| `snapshot_timestamp` | Full timestamp or NA |
| `statuscode` | HTTP status or NA |
| `digest` | Content hash or NA |
| `original_url` | Original URL with scheme or NA |
| `has_snapshot` | 0/1 |
| `content_changed` | True if digest differs from previous month |

**Print:** total cells, filled %, unique digests, coverage % by year

---

### Script 3: `03_download_content.py` (~hours to 1 day)

Download robots.txt content for unique digests **where statuscode == 200 only**.

- Skip 404/410 digests (Step 4 classifies these as `no_robots_file` directly)
- Skip other non-200 statuses (Step 4 classifies as `archived_http_error`)
- Same digest = same content → download once

**URL format:**
```
https://web.archive.org/web/{timestamp}id_/{original_url}
```
Use `original_url` from Step 2 to get the correct scheme. If not available, try HTTPS then HTTP.

- Rate limit: 1 request/second. Timeout: 15 seconds.

**Input:** `monthly_snapshots.csv`

**Output:** `robots_content.json`: `{digest: "content string", ...}`

**Checkpoint:** Save every 200 downloads.

**Print:** 200-status digests downloaded, non-200 skipped, failures

---

### Script 4: `04_parse_panel.py` (~minutes, CPU only)

Parse content and build the raw panel.

For each row in `monthly_snapshots.csv`:
- `has_snapshot = 0` → `fetch_status = "no_snapshot"`, all bot fields = NA
- `statuscode` is 404 or 410 → `fetch_status = "no_robots_file"`, `root_block=0, has_nonroot_disallow=0, blocked_any=0, specific_rule=0, effective_source="no_robots_file"` for ALL 12 bots
- `statuscode == 200`:
  - Look up content by `digest` in `robots_content.json`
  - If found: `groups = parse_robots(content)`, then for each bot: `classify_bot(groups, name, aliases)`
  - Also: `rules, _, _ = get_applicable_rules(groups, aliases)` → `n_disallow_rules = sum(1 for d, _ in rules if d == "disallow")`
  - `blocked_any = root_block OR has_nonroot_disallow`
  - If content not found: `fetch_status = "content_missing"`, all bot fields = NA
- Other status codes → `fetch_status = "archived_http_error"`, all bot fields = NA

**After building full panel:**

A. Compute `treatment_timing.csv`
B. Compute `policy_changes.csv` (with `gap_months` and `timing_interval_censored`)

**CRITICAL additional check (print at end):**
```
=== Switcher Analysis ===
Hosts where any_block changed: ???
Hosts where search_block changed: ???
Hosts where GPTBot specific_rule first appeared: ???
Hosts where OAI-SearchBot specific_rule first appeared: ???
Hosts with pre+post around a switch: ???
>>> If <200 switchers for search_block, DID may be underpowered.
```

**Output:** `robots_panel_monthly.csv`, `treatment_timing.csv`, `policy_changes.csv`

---

### Script 5: `05_merge_firm_panel.py` (~minutes)

Map hosts to firms, aggregate, create firm-level panel.

- Read `compustat_2025_clean.csv` for `host_clean` → `gvkey` mapping
- Multiple firms share one host → identical treatment values
- **Keep `host` in output** (needed for clustering)
- Aggregate per firm × month (same logic as cross-sectional `build_analysis_sample.py`)
- Also compute search-level aggregated onset timing per gvkey

**Output:** `firm_panel_monthly.csv`, `firm_treatment_timing.csv`, `panel_summary.csv`

**Print:**
```
Total firm × month observations: ???
With data: ???
Firms that switched (search_block): ???
Firms that switched (any_block): ???
Always-allow: ???
Always-block: ???
Firms with pre+post 2023.08: ???
```

---

## How to run

```bash
cd "bot_paper/panel_construction/"
python 01_query_cdx.py        # ~2-3 hours, checkpoint every 100 hosts
# >>> CHECK feasibility. If <1,000 hosts have 12+ months, STOP.
python 02_select_monthly.py   # ~1 minute
python 03_download_content.py # ~hours to 1 day, checkpoint every 200 digests
python 04_parse_panel.py      # ~minutes
# >>> CHECK switcher count. If <200 switchers, DID may be underpowered.
python 05_merge_firm_panel.py # ~minutes
```

---

## Verification

1. March 2026 panel values should match cross-sectional `robots_bot_panel.csv`
2. Spot-check: Apple, Amazon, NYT, Pinterest, Adobe — do timelines make sense?
3. GPTBot `first_month_mentioned` should cluster around Aug-Oct 2023
4. Google-Extended `first_month_mentioned` around Sep-Nov 2023
5. OAI-SearchBot is newer, `first_month_mentioned` should be 2024+

---

## Rules

1. **Import parser, do not rewrite.** `from robots_parser import parse_robots, classify_bot, get_applicable_rules`
2. **404 = allow-all, not missing.** Follow RFC 9309 and match cross-sectional scan logic.
3. **Missing (no_snapshot) = NA.** Never impute 0.
4. **Use Path() for all paths.** No hardcoded strings.
5. **Checkpoint everything.** Steps 1 and 3 are long-running.
6. **Be polite.** 1 req/sec to Wayback Machine.
7. **Store raw fields.** Keep `root_block`, `has_nonroot_disallow`, `specific_rule`, `effective_source`, `blocked_any`.
8. **Keep `host` in firm panel.** Needed for clustering.
9. **No `collapse=digest` in Step 1.** Full snapshot list.
10. **Only download 200-status digests in Step 3.** 404 → classify directly, don't download body.
11. **Record gap_months in policy_changes.** Flag interval-censored transitions.

---

## File structure

```
bot_paper/panel_construction/
├── INSTRUCTIONS.md
├── 01_query_cdx.py
├── 02_select_monthly.py
├── 03_download_content.py
├── 04_parse_panel.py
├── 05_merge_firm_panel.py
├── cdx_snapshots.json              (Step 1, checkpoint)
├── cdx_coverage_summary.csv        (Step 1)
├── monthly_snapshots.csv           (Step 2)
├── robots_content.json             (Step 3, checkpoint)
├── robots_panel_monthly.csv        (Step 4, Layer 1)
├── treatment_timing.csv            (Step 4)
├── policy_changes.csv              (Step 4)
├── firm_panel_monthly.csv          (Step 5, Layer 2)
├── firm_treatment_timing_bot.csv   (Step 5, gvkey × bot)
├── firm_treatment_timing.csv       (Step 5, gvkey search-level onset)
└── panel_summary.csv               (Step 5)
```
