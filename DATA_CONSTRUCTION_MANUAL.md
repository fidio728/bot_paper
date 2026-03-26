# Data Construction Manual: Corporate AI Crawler Policy Database

**Project**: Bot Paper — Corporate AI Crawler Policy and Capital Market Consequences
**Supervisor**: Emanuele Rizzo, Universitat Ramon Llull (IQS School of Management)
**Date**: 2026-03-26
**Research Question**: How do corporate robots.txt policies toward AI crawlers affect investor information acquisition and capital market outcomes?

---

## Overview

This manual documents the complete data construction pipeline from raw Compustat data to a firm-level robots.txt policy database. It maps to Steps 1-3 of the project roadmap defined in CLAUDE.md:

| Project Step | What was done | Output file |
|---|---|---|
| Step 1 | Clean weburl, extract canonical hosts | `compustat_2025_clean.csv` |
| Step 2 | Batch-scan robots.txt for all firms | `robots_bot_panel.csv` |
| Step 3 | Classify each firm's AI crawler policy | `robots_firm_summary.csv` |

Steps 4-5 (sitemap intensity, descriptive statistics) are not yet implemented.

---

## Pipeline Architecture

Four Python files were written from scratch. No code was inherited from earlier prototype scripts (which had known bugs, including a Walmart Allow/Disallow confusion).

| File | Role | Dependencies |
|---|---|---|
| `robots_parser.py` | RFC 9309 parser (standalone, no I/O) | None (pure stdlib) |
| `test_robots_parser.py` | 12 unit tests for the parser | `robots_parser.py` |
| `clean_weburl.py` | URL cleaning and host extraction | `pandas`, `urllib.parse` |
| `scan_robots.py` | HTTP fetching, orchestration, output | `pandas`, `requests`, `robots_parser.py` |

**Implementation order**: parser and tests first (most dangerous part), then cleaning, then scanning. The parser was written and tested independently before being plugged into the scanner, because a previous version of the project had already been bitten by parser bugs.

---

## Step 1: URL Cleaning (`clean_weburl.py`)

### Goal (from CLAUDE.md Step 1)

> Clean weburl, standardize domains, build scanning pipeline

### Input

`compustat_2025.csv` — Compustat Fundamentals Annual 2025 cross-section.
- 10,489 rows (firms)
- 21 columns: costat, curcd, datafmt, indfmt, consol, tic, fyear, gvkey, conm, cusip, cik, exchg, fic, loc, naics, prican, prirow, priusa, sic, stko, weburl
- The `weburl` column contains raw corporate website URLs as reported by Compustat

### What this step does

Extracts a canonical host from each firm's `weburl` for use as the scanning unit. This is a normalization step, not a content step — it does not visit any website.

### Cleaning pipeline (per URL)

1. Strip leading/trailing whitespace
2. Detect original scheme (`https`, `http`, or `missing_scheme` if none present)
3. If no scheme prefix, prepend `https://` so `urllib.parse.urlparse()` can parse correctly
4. Call `urlparse()` to extract the `hostname` component
5. Remove default ports (`:80`, `:443`) if present
6. Strip trailing dots (e.g., `example.com.` becomes `example.com`)
7. Lowercase the entire host
8. If parsing fails or host is empty, flag as `url_parse_error = True`

### Design decisions made at this step

**Decision 1: Keep subdomains as-is (do not collapse to root domain).**

- Rationale: robots.txt is a host-level protocol object. `ir.tesla.com/robots.txt` and `www.tesla.com/robots.txt` can have completely different content. Collapsing subdomains would mix unrelated policies.
- Example: Compustat gives `corporate.walmart.com` for Walmart. We scan `corporate.walmart.com/robots.txt`, not `walmart.com/robots.txt`.

**Decision 2: Exact host deduplication.**

- `ir.tesla.com` and `www.tesla.com` are treated as two different hosts. Only rows with the identical `host_clean` value count as duplicates.
- This matters because many ETF/fund firms share the same host (e.g., 358 firms all point to `www.ishares.com`). The scanner will scan that host once and map the result to all 358 firms.

**Decision 3: Do not follow homepage redirects.**

- Some Compustat URLs are vanity domains (e.g., `aaauetf.com` redirects to `am.gs.com`). We scan the exact Compustat host, not the redirect destination, because: (1) homepage redirects and robots.txt redirects are independent; (2) this keeps the sample mechanically reproducible.
- Future robustness check planned: fetch homepages separately to detect alias redirects.

### Output

`compustat_2025_clean.csv` — all 10,489 original rows preserved, with 6 new columns appended:

| New column | Type | Description |
|---|---|---|
| `host_clean` | string | Canonical host extracted from weburl (lowercase, no paths/fragments/ports) |
| `weburl_missing` | boolean | True if original weburl was empty or NaN |
| `url_parse_error` | boolean | True if host extraction failed (e.g., spaces in domain) |
| `host_source_scheme` | string | Original scheme detected: `https`, `http`, or `missing_scheme` |
| `shared_host_flag` | boolean | True if multiple firms share this exact `host_clean` |
| `host_duplicate_count` | integer | Number of firms with the identical `host_clean` (0 if missing) |

### Summary statistics

| Metric | Value |
|---|---|
| Total rows | 10,489 |
| Missing weburl | 427 (4.1%) |
| Parse errors | 0 |
| Valid hosts (non-missing, non-error) | 10,062 |
| Unique hosts | 4,350 |
| Shared hosts (used by >1 firm) | 911 |
| Firms on shared hosts | 6,623 |

Top 5 most-shared hosts (all ETF/fund companies):

| Host | Firms |
|---|---|
| `www.ishares.com` | 358 |
| `www.ftportfolios.com` | 292 |
| `www.invesco.com` | 264 |
| `www.blackrock.com` | 194 |
| `www.ssga.com` | 163 |

### Verification checks performed

- Row count preserved: 10,489 in = 10,489 out
- Missing count: exactly 427 rows with `weburl_missing == True`
- No `host_clean` value contains `/`, `#`, or `?` (paths/fragments fully stripped)
- All `host_clean` values are lowercase
- Spot checks: `www.deere.com/en` -> `www.deere.com`; `advisorshares.com/etfs/vega/#vega` -> `advisorshares.com`

### Command to reproduce

```bash
cd bot_paper/
python clean_weburl.py
```

---

## Step 2: robots.txt Parser (`robots_parser.py`)

### Goal

Build a correct parser for robots.txt files before scanning 4,350 hosts. This was done first because a previous prototype had a critical parser bug (the "Walmart bug": it confused Allow with Disallow directives, causing false block classifications).

### What this module does

`robots_parser.py` is a standalone module (no HTTP, no pandas, no file I/O). It takes raw robots.txt text content and returns structured rule evaluations for any bot.

### Core functions

**`parse_robots(content) -> list of groups`**

Parses robots.txt text into groups. Each group contains a list of user-agent names and their associated Allow/Disallow rules.

Example input:
```
User-agent: GPTBot
Disallow: /

User-agent: *
Disallow: /private
Allow: /
```

Example output:
```python
[
    {"agents": ["gptbot"], "rules": [("disallow", "/")]},
    {"agents": ["*"], "rules": [("disallow", "/private"), ("allow", "/")]}
]
```

Parsing rules:
- Agent names and directives are lowercased
- Consecutive `User-agent:` lines before any rules form one group
- A blank line closes the current group
- Inline comments (after `#`) are stripped
- Unparseable lines are silently skipped

**`get_applicable_rules(groups, bot_aliases) -> (rules, has_specific_rule, effective_source)`**

Determines which rules apply to a given bot, following RFC 9309 specificity:

1. If the bot has specific `User-agent` groups, **merge rules from ALL matching groups** and use only those (`effective_source = "specific"`)
2. If no specific match, fall back to all `User-agent: *` groups, **merged** (`effective_source = "wildcard"`)
3. If neither exists, return empty rules (`effective_source = "none"`)

Critical detail: if a bot has a specific group but that group contains no rules, it is still treated as "specific" — meaning the bot is allowed everywhere (empty rules = allow). It does NOT fall back to wildcard. This was a bug in the previous prototype that is now fixed and tested (test case #5).

Critical detail: rules from ALL matching groups are merged, not just the first group found. Real-world robots.txt files sometimes list the same bot in multiple groups. This is tested in cases #11 and #12.

**`is_path_blocked(rules, path="/") -> bool`**

RFC 9309 longest-prefix-match with allow-wins-on-tie:

1. For each rule, check if the rule's path is a prefix of the target path
2. Among all matching rules, the one with the longest path wins
3. If two rules match with the same length, `Allow` beats `Disallow`

This is the fix for the Walmart bug: `Disallow: /` + `Allow: /` -> the two paths are the same length (1 character), so Allow wins, and the bot is NOT blocked.

**`classify_bot(groups, bot_name, bot_aliases) -> dict`**

Combines the above functions to produce a per-bot classification:

| Output field | Type | Meaning |
|---|---|---|
| `specific_rule` | 0 or 1 | Whether this bot has its own User-agent group (vs. falling back to wildcard) |
| `effective_source` | string | `"specific"`, `"wildcard"`, or `"none"` |
| `root_block` | 0 or 1 | Whether the bot is blocked at root path `/` (i.e., blocked from the entire site) |
| `has_nonroot_disallow` | 0 or 1 | Whether any Disallow exists for a non-root path (heuristic indicator, not a full reachability proof) |

### Known limitations

The parser implements the core RFC 9309 semantics sufficient for this project's treatment variable (root-block and has-nonroot-disallow). It does NOT implement:

- Special pattern characters `*` and `$` (e.g., `Disallow: /*.gif$`)
- Percent-encoding normalization (e.g., `%7E` vs `~`)

These would matter for fine-grained path-level analysis (Step 4: sitemap-based blocking intensity) but do not affect root-block classification.

### Unit tests (`test_robots_parser.py`)

12 test cases covering all critical edge cases:

| # | Test case | What it verifies |
|---|---|---|
| 1 | Wildcard `Disallow: /` | Basic root block detection |
| 2 | Specific bot + wildcard both present | Specific rules override wildcard entirely |
| 3 | `Allow: /` vs `Disallow: /` same length | Allow wins on tie (Walmart bug fix) |
| 4 | `Allow: /public/` vs `Disallow: /` | Longer match wins: `/public/page` is allowed |
| 5 | Specific bot listed with no rules | Empty specific group = allow all (does NOT fallback to wildcard) |
| 6 | Empty `Disallow:` | Means "allow all" per RFC 9309 |
| 7 | Case insensitive `user-agent: GPTBOT` | Matches `GPTBot` regardless of case |
| 8 | Multiple groups with blank line separation | Groups parsed correctly |
| 9 | No matching agent, no wildcard | Bot is allowed (`effective_source = "none"`) |
| 10 | Real-world Walmart-style robots.txt | Integration test with mixed specific + wildcard rules |
| 11 | Same bot in multiple specific groups | Rules from all matching groups are merged |
| 12 | Multiple wildcard groups | Wildcard rules from all `*` groups are merged |

All 12 tests pass.

### Command to reproduce

```bash
cd bot_paper/
python test_robots_parser.py
```

---

## Step 2-3: Batch Scanning and Classification (`scan_robots.py`)

### Goal (from CLAUDE.md Steps 2-3)

> Step 2: Batch-scan robots.txt for all firms with valid weburl
> Step 3: Classify each firm (no AI rules / full block / partial block / explicit allow)

### Bot taxonomy

12 bots are tracked, organized into 4 groups:

| Group | Bots | Role in treatment |
|---|---|---|
| **Training** (5) | GPTBot, ClaudeBot, Google-Extended, CCBot, Meta-ExternalAgent | Part of treatment denominator |
| **Search** (3) | OAI-SearchBot, Claude-SearchBot, PerplexityBot | Part of treatment denominator |
| **User** (3) | ChatGPT-User, Perplexity-User, Meta-ExternalFetcher | Tracked separately (may ignore robots.txt) |
| **Control** (1) | Googlebot | Benchmark only (not AI) |

**Treatment denominator = training + search bots (8 bots).** User-triggered fetchers are excluded because their official documentation states they may bypass robots.txt. Including them would contaminate the treatment variable.

### Scanning process

For each of the 4,350 unique hosts:

1. **Fetch**: Request `https://{host}/robots.txt` with a fixed research User-Agent
   - If 403: retry once with a browser-like User-Agent
   - If SSL error: fall back to `http://{host}/robots.txt` (only SSL errors trigger HTTP fallback; connection errors and timeouts do not)
   - Record the final URL after any redirects
2. **Parse**: Feed the response content to `robots_parser.parse_robots()`
3. **Classify**: For each of the 12 bots, call `robots_parser.classify_bot()` to get `root_block`, `has_nonroot_disallow`, `specific_rule`, and `effective_source`
4. **Save**: Append bot-level rows to `robots_bot_panel.csv`, then update `scan_progress.json`

### HTTP response handling

| `robots_status_type` | HTTP status | Interpretation | Bot-level defaults |
|---|---|---|---|
| `ok_200` | 200 | Got robots.txt content | Parse and evaluate per bot |
| `missing_404` | 404 | No robots.txt file exists | All bots allowed (root_block=0, has_nonroot_disallow=0) |
| `http_error_4xx` | 401/403/429 | Access gated (WAF, auth required) | **Unknown** — all fields NA |
| `http_error_5xx` | 5xx | Server error | **Unknown** — all fields NA |
| `timeout` | — | Request timed out | **Unknown** — all fields NA |
| `ssl_error` | — | SSL/TLS failure | **Unknown** — all fields NA |
| `connection_error` | — | DNS failure, firewall, etc. | **Unknown** — all fields NA |
| `too_many_redirects` | — | Redirect loop | **Unknown** — all fields NA |

**Critical design rule**: 404 means "no restrictions" (per RFC 9309 — absence of robots.txt means all bots are allowed). But 403, 5xx, timeout, and connection errors mean "policy is unobservable" — we do NOT infer allow or disallow. These are classified as `fetch_error` in the treatment variable.

**Why 403 is not treated as "blocked"**: Some hosts (e.g., those behind Cloudflare challenge pages) return 403 even for robots.txt, even to browsers in incognito mode. This is a WAF/access gate above the robots layer, not a declared robots policy. Manually verified with the `1cminc.com` case during development.

### Deduplication

- 10,062 firms have valid hosts, but only 4,350 unique hosts exist
- Each unique host is scanned exactly once
- Results are mapped back to all firms sharing that host
- Columns `shared_host_flag` and `host_duplicate_count` track this

### Checkpoint and resume

- After each host is scanned, results are appended to `robots_bot_panel.csv` first, then `scan_progress.json` is updated (safe ordering: if crash occurs between the two, the host will be re-scanned on resume, producing at most a few duplicate rows but never silent data loss)
- On restart, the scanner loads the progress file, skips all completed hosts, and continues
- The progress file uses direct writes with retries to handle OneDrive file locking during sync

### Polite scanning

- 0.3-0.5 second random delay between requests
- 15-second timeout per request
- Fixed, transparent User-Agent string (not randomized, for reproducibility)

### Treatment classification (`assign_treatment_v1()`)

The treatment variable is assigned per firm based on training + search bots only (8 bots):

| Treatment | Definition |
|---|---|
| `allow` | No training or search bot is root-blocked, and none has any nonroot Disallow |
| `full_disallow` | All 8 training+search bots are root-blocked (`Disallow: /`) |
| `partial_disallow` | At least one bot is root-blocked or has nonroot restrictions, but not all 8 are root-blocked |
| `fetch_error` | robots.txt could not be retrieved (status not 200 or 404) |

This function is isolated so the treatment definition can be revised without re-scanning.

### Output: `robots_bot_panel.csv`

One row per firm x bot. 120,900 rows = 10,062 firms x 12 bots.

| Column | Description |
|---|---|
| `scan_utc` | ISO 8601 timestamp of when this host was scanned |
| `scan_date` | YYYY-MM-DD date |
| `firm` | Company name (from Compustat `conm`) |
| `ticker` | Stock ticker (from Compustat `tic`) |
| `host` | Canonical host that was scanned |
| `gvkey` | Compustat firm identifier |
| `bot` | Bot name (e.g., "GPTBot") |
| `bot_group` | "training", "search", "user", or "control" |
| `root_block` | 1 if bot is blocked at root `/`, 0 if not, NA if fetch failed |
| `has_nonroot_disallow` | 1 if any nonroot Disallow exists for this bot, 0 if not, NA if fetch failed |
| `specific_rule` | 1 if this bot has its own User-agent group, 0 if using wildcard |
| `effective_source` | "specific", "wildcard", "none", "no_robots_file", or "fetch_error" |
| `googlebot_block` | 1 if Googlebot is root-blocked on this host (for cross-reference) |
| `status_code` | HTTP status code of the robots.txt fetch |
| `robots_status_type` | Classified status: ok_200, missing_404, http_error_4xx, etc. |
| `fetch_error` | Error description if fetch failed, empty string otherwise |
| `robots_final_url` | Final URL after any redirects |

### Output: `robots_firm_summary.csv`

One row per firm. 10,062 rows.

| Column | Description |
|---|---|
| `scan_date` | YYYY-MM-DD |
| `firm` | Company name |
| `ticker` | Stock ticker |
| `gvkey` | Compustat firm identifier |
| `weburl_original` | Original Compustat weburl (before cleaning) |
| `host` | Canonical host scanned |
| `shared_host_flag` | Whether multiple firms share this host |
| `host_duplicate_count` | Number of firms with the same host |
| `status_code` | HTTP status code |
| `robots_status_type` | ok_200, missing_404, http_error_4xx, etc. |
| `googlebot_block` | 1 if Googlebot is root-blocked |
| `any_ai_specific_rule` | 1 if any AI bot has a specific User-agent rule (not wildcard) |
| `n_training_bots_root_blocked` | Count of training bots (0-5) root-blocked |
| `n_training_bots_has_nonroot_disallow` | Count of training bots with nonroot restrictions |
| `n_search_bots_root_blocked` | Count of search bots (0-3) root-blocked |
| `n_search_bots_has_nonroot_disallow` | Count of search bots with nonroot restrictions |
| `n_treatment_bots_root_blocked` | Count of treatment bots (0-8) root-blocked |
| `n_treatment_bots_has_nonroot_disallow` | Count of treatment bots with nonroot restrictions |
| `n_user_bots_root_blocked` | Count of user-triggered bots (0-3) root-blocked |
| `n_user_bots_has_nonroot_disallow` | Count of user bots with nonroot restrictions |
| `treatment_category` | "allow", "full_disallow", "partial_disallow", or "fetch_error" |

### Final results

**Scan status distribution (host-level, N=4,350):**

| Status | Hosts | % |
|---|---|---|
| ok_200 | 3,579 | 82.3% |
| missing_404 | 352 | 8.1% |
| http_error_4xx | 229 | 5.3% |
| timeout | 125 | 2.9% |
| connection_error | 40 | 0.9% |
| ssl_error | 13 | 0.3% |
| http_error_5xx | 9 | 0.2% |
| too_many_redirects | 3 | 0.1% |

**Treatment distribution (firm-level, N=10,062):**

| Treatment | Firms | % |
|---|---|---|
| allow | 5,083 | 50.5% |
| partial_disallow | 4,161 | 41.4% |
| fetch_error | 786 | 7.8% |
| full_disallow | 32 | 0.3% |

**Key observations:**
- About half of firms have no AI-specific restrictions at all
- 41% have some form of partial restriction (ranging from blocking one bot to blocking most but not all)
- Only 32 firms (0.3%) fully block all training and search AI bots at the root level
- 373 firms (4.0% of those with observable robots.txt) have at least one AI-specific User-agent rule (as opposed to relying on wildcard rules)
- Only 17 firms block Googlebot (very rare, as expected — blocking Googlebot means losing Google Search visibility)

### Sanity checks performed

- Bot panel rows: 120,900 = 10,062 firms x 12 bots
- Firm summary rows: 10,062 = all firms with valid hosts
- All 32 `full_disallow` firms have `n_treatment_bots_root_blocked == 8`
- Very few firms block Googlebot (17) — confirms the treatment is AI-specific
- 404 responses classified as `allow` (correct per RFC 9309)
- 403/5xx/timeout classified as `fetch_error` with all bot fields NA (never inferred)

### Command to reproduce

```bash
cd bot_paper/
python scan_robots.py
# Takes ~60-90 minutes for all 4,350 hosts
# Safe to interrupt and resume (checkpointed after each host)
```

---

## File inventory

After running the full pipeline, the `bot_paper/` directory contains:

| File | Type | Size | Description |
|---|---|---|---|
| `compustat_2025.csv` | Input data | 1.3 MB | Raw Compustat cross-section |
| `compustat_2025_clean.csv` | Intermediate | ~2 MB | Cleaned URLs with host extraction |
| `robots_bot_panel.csv` | Output | ~15 MB | Bot-level panel (120,900 rows) |
| `robots_firm_summary.csv` | Output | ~1 MB | Firm-level summary (10,062 rows) |
| `scan_progress.json` | Checkpoint | ~40 MB | Full scan results by host (for resume) |
| `robots_parser.py` | Code | 5 KB | RFC 9309 parser module |
| `test_robots_parser.py` | Code | 6 KB | 12 unit tests |
| `clean_weburl.py` | Code | 4 KB | URL cleaning script |
| `scan_robots.py` | Code | 18 KB | Batch scanner + classifier |
| `CLAUDE.md` | Documentation | 7 KB | Project spec and decisions |

---

## What comes next

| Step | Status | Description |
|---|---|---|
| Step 1 | Done | Clean weburl |
| Step 2 | Done | Batch scan robots.txt |
| Step 3 | Done | Classify firms (treatment variable) |
| Step 4 | Not started | For partial-block firms: fetch sitemaps, calculate blocking intensity (continuous treatment measure) |
| Step 5 | Not started | Descriptive statistics: compare blocking vs non-blocking firms on observables |
