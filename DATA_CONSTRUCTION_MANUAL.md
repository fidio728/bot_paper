# Data Construction Manual: Corporate AI Crawler Policy Database

**Project**: Bot Paper — Corporate AI Crawler Policy and Capital Market Consequences
**Supervisor**: Emanuele Rizzo, Universitat Ramon Llull (IQS School of Management)
**Date**: 2026-03-26
**Research Question**: How do corporate robots.txt policies toward AI crawlers affect investor information acquisition and capital market outcomes?

---

## Overview

This manual documents the complete data construction pipeline from raw Compustat data to a firm-level robots.txt policy database with continuous blocking intensity measures. It maps to Steps 1-4 of the project roadmap defined in CLAUDE.md:

| Project Step | What was done | Output file |
|---|---|---|
| Step 1 | Clean weburl, extract canonical hosts | `compustat_2025_clean.csv` |
| Step 2 | Batch-scan robots.txt for all firms | `robots_bot_panel.csv` |
| Step 3 | Classify each firm's AI crawler policy | `robots_firm_summary.csv` |
| Step 4 | Sitemap-based blocking intensity for partial_disallow firms | `robots_sitemap_intensity_firm.csv` |
| Step 5 | Merge Compustat financials, build analysis-ready sample | `analysis_sample.csv` |

Step 6 (descriptive statistics / Table 1) is not yet implemented.

---

## Pipeline Architecture

Six Python files were written from scratch. No code was inherited from earlier prototype scripts (which had known bugs, including a Walmart Allow/Disallow confusion).

| File | Role | Dependencies |
|---|---|---|
| `robots_parser.py` | RFC 9309 parser (standalone, no I/O) | None (pure stdlib: `re`) |
| `test_robots_parser.py` | 19 unit tests for the parser | `robots_parser.py` |
| `clean_weburl.py` | URL cleaning and host extraction | `pandas`, `urllib.parse` |
| `fetch_utils.py` | Shared HTTP fetch utilities | `requests` |
| `scan_robots.py` | Batch robots.txt scanning + classification | `pandas`, `robots_parser.py`, `fetch_utils.py` |
| `sitemap_intensity.py` | Sitemap-based blocking intensity (Step 4) | `pandas`, `robots_parser.py`, `fetch_utils.py`, `xml.etree`, `gzip` |

**Implementation order**: parser and tests first (most dangerous part), then cleaning, then scanning. The parser was written and tested independently before being plugged into the scanner, because a previous version of the project had already been bitten by parser bugs. Fetch utilities were later extracted to `fetch_utils.py` to share HTTP logic between `scan_robots.py` and `sitemap_intensity.py`.

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

RFC 9309 longest-match-wins with allow-wins-on-tie. Supports:

1. Plain prefix matching (e.g., `Disallow: /private/`)
2. RFC 9309 wildcard `*` (matches 0+ characters, e.g., `Disallow: /*.gif`)
3. RFC 9309 end anchor `$` (e.g., `Disallow: /private/$`)
4. Percent-encoding normalization: unreserved ASCII chars (`A-Za-z0-9-._~`) are decoded before comparison per RFC 3986 §2.3; reserved characters stay encoded

Among all matching rules, the one with the longest path wins. If two rules match with the same length, `Allow` beats `Disallow`.

This is the fix for the Walmart bug: `Disallow: /` + `Allow: /` -> the two paths are the same length (1 character), so Allow wins, and the bot is NOT blocked.

**`extract_sitemap_urls(content) -> list`**

Extracts `Sitemap:` URL declarations from robots.txt content. Sitemap records are file-level (not group-level) per RFC 9309. Strips inline comments, case-insensitive field matching. Returns a list of URL strings in the order they appear.

**`classify_bot(groups, bot_name, bot_aliases) -> dict`**

Combines the above functions to produce a per-bot classification:

| Output field | Type | Meaning |
|---|---|---|
| `specific_rule` | 0 or 1 | Whether this bot has its own User-agent group (vs. falling back to wildcard) |
| `effective_source` | string | `"specific"`, `"wildcard"`, or `"none"` |
| `root_block` | 0 or 1 | Whether the bot is blocked at root path `/` (i.e., blocked from the entire site) |
| `has_nonroot_disallow` | 0 or 1 | Whether any Disallow exists for a non-root path (heuristic indicator, not a full reachability proof) |

### Unit tests (`test_robots_parser.py`)

19 test cases covering all critical edge cases:

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
| 13 | `has_nonroot_disallow` flag | Detects nonroot Disallow paths correctly; root-only Disallow does not trigger |
| 14 | Wildcard `*` matching | `/*.gif` blocks `/image.gif` not `/image.png`; `/private*` blocks `/private/sub` |
| 15 | Dollar `$` end anchor | `/private/$` blocks `/private/` not `/private/subfolder` |
| 16 | Combined `*` and `$` | `/*.pdf$` blocks `/report.pdf` not `/report.pdf.bak` |
| 17 | `extract_sitemap_urls()` | Correct URL extraction; strips inline comments; case-insensitive; skips non-sitemap lines |
| 18 | `Disallow: /*` blocks root | `/*` matches `/` and `/abc` (validates Step 3 re-scan rationale) |
| 19 | Percent-encoding normalization | `/%7Eprivate/` matches `/~private/page` (unreserved decoded); `/public%2Fpage` does NOT match `/public/page` (reserved stays encoded) |

All 19 tests pass.

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

### Step 3 re-scan (after parser upgrade)

After adding wildcard `*`/`$` support and percent-encoding normalization to `robots_parser.py`, Step 3 was re-run from scratch. The upgrade changes `root_block` for firms using `Disallow: /*` — the old parser evaluated `"/".startswith("/*")` = False (not blocked), while the new parser correctly matches `/*` as a regex pattern against `/` = True (blocked). `has_nonroot_disallow` is a string-presence check and is unaffected.

HTTP fetch logic was also extracted to `fetch_utils.py` (see below). `scan_robots.py` now imports `fetch_robots`, `UA_RESEARCH`, `UA_BROWSER`, `MAX_CONTENT_BYTES` from `fetch_utils` instead of defining them inline. No logic or CSV schema changes.

### Command to reproduce

```bash
cd bot_paper/
python scan_robots.py
# Takes ~60-90 minutes for all 4,350 hosts
# Safe to interrupt and resume (checkpointed after each host)
```

---

## Shared HTTP Utilities (`fetch_utils.py`)

### Goal

Provide shared HTTP fetch logic used by both `scan_robots.py` (robots.txt fetching) and `sitemap_intensity.py` (robots.txt re-fetch + sitemap fetching). Avoids code duplication.

### Two-layer design

**`fetch_url(url, timeout=30, as_bytes=False, ua=UA_RESEARCH)`** — generic URL fetcher:
- Retries once with browser UA if first attempt returns 403
- Returns `{"status_code", "content", "final_url", "fetch_error"}`
- `as_bytes=True` returns raw response bytes (used for sitemap XML/gzip)
- No robots.txt-specific logic (no SSL fallback, no HTTP fallback)

**`fetch_robots(host, timeout=15)`** — robots.txt-specific wrapper:
- Tries HTTPS first with research UA; retries with browser UA on 403
- SSL error only: falls back to HTTP (connection errors and timeouts do NOT trigger HTTP fallback — they are not HTTPS-specific issues)
- Returns `{"status_code", "content", "final_url", "fetch_error", "ua_used", "http_fallback"}`

**Rule**: robots.txt uses `fetch_robots()`. Sitemaps use `fetch_url(..., as_bytes=True)`. Never mix.

### Constants

| Constant | Value | Purpose |
|---|---|---|
| `UA_RESEARCH` | `Mozilla/5.0 (compatible; AcademicResearchBot/1.0)` | Primary User-Agent |
| `UA_BROWSER` | Chrome 124 browser string | Fallback for 403 responses |
| `MAX_CONTENT_BYTES` | 1,000,000 (1 MB) | robots.txt content cap |

---

## Step 4: Sitemap Blocking Intensity (`sitemap_intensity.py`)

### Goal (from CLAUDE.md Step 4)

> For partial-block firms: fetch declared sitemaps, evaluate each URL against each bot's rules, compute a continuous blocking intensity measure.

### Why this step matters

The Step 3 treatment variable (`partial_disallow`) is binary and coarse — it groups together firms that block one bot from one path with firms that block seven bots from nearly everything. Sitemap intensity provides a continuous measure: what fraction of a firm's sitemap-listed URLs are blocked for each AI bot.

### Important caveat: lower-bound proxy

`intensity_final` is a **lower-bound proxy** based on sitemap-listed URLs. Sitemaps typically contain only search-indexable public pages — a subset of all site content. A firm could restrict AI access to non-indexed pages (APIs, internal tools, dynamic content) that never appear in sitemaps. Therefore:
- `intensity = 0.3` means "at least 30% of sitemap-listed pages are blocked"
- `intensity = 0` is valid for `partial_sitemap` hosts — rules exist but none match sitemap-listed paths
- The true blocking rate may be higher than measured

### Scope

Only `partial_disallow` hosts are scanned for sitemaps. Other treatment categories get deterministic values:
- `allow` → `intensity_final = 0` (no restrictions)
- `full_disallow` → `intensity_final = 1` (everything blocked)
- `fetch_error` → `intensity_final = NA`

### Per-host processing pipeline

For each unique `partial_disallow` host:

1. **Re-fetch robots.txt** via `fetch_robots(host)` — re-fetched rather than cached because the 50KB content cap in `scan_progress.json` could silently truncate late `Sitemap:` lines
   - Failure → `intensity_source = partial_refetch_error_na`

2. **Parse robots.txt** via `parse_robots(content)` + `extract_sitemap_urls(content)`
   - No sitemaps declared → `intensity_source = partial_no_sitemap_na`

3. **Fetch sitemaps** via `fetch_url(url, as_bytes=True, timeout=30)`:
   - Gzip detection: `.gz` extension or content inspection; `gzip.decompress()`
   - XML parsing: `xml.etree.ElementTree`; namespace-aware (`{http://www.sitemaps.org/schemas/sitemap/0.9}loc` then bare `loc`)
   - `<sitemapindex>`: recursively fetch child sitemaps (max depth 2, max 20 child sitemaps); `visited_sitemaps` set prevents circular references
   - `<urlset>`: collect `<loc>` URL strings
   - Partial failure: if some sitemaps fail but others succeed, continue with successful ones (`sitemap_fetch_status = partial_ok`)
   - All failed → `intensity_source = partial_sitemap_error_na`

4. **Host-scope filter**: keep only URLs where `urlparse(loc).hostname.lower().rstrip('.') == host.lower().rstrip('.')`
   - Conservative: may discard valid canonical aliases, but prevents applying one host's robots rules to another host's URLs
   - Tracked via `n_urls_before_host_filter`, `n_urls_after_host_filter`, `n_urls_dropped_by_host_filter`

5. **Two-stage deduplication**:
   - (a) Deduplicate on full URL string
   - (b) Extract comparison string: `path + ('?' + query if query else '')`
   - (c) Deduplicate on comparison string (keeps first occurrence)

6. **URL cap**: `MAX_COMPARISON_URLS = 200,000` — streaming stop (not post-hoc truncation). Stops fetching additional child sitemaps once cap reached. Flags `url_cap_hit = 1` and records `n_urls_dropped_by_cap`. These hosts can be re-run individually later.

7. **Evaluate blocking**: for each of 8 treatment bots, compute `n_blocked / n_total` using `get_applicable_rules()` + `is_path_blocked()` with full wildcard and percent-encoding support

8. **Aggregate**: `mean_treatment_intensity` = average of 8 bot intensities (host-level)

### `intensity_source` taxonomy (8 categories)

| Value | Condition |
|---|---|
| `allow_zero` | `treatment_category == allow` |
| `full_one` | `treatment_category == full_disallow` |
| `partial_sitemap` | partial + ≥1 sitemap ok + `n_total > 0` |
| `partial_no_sitemap_na` | partial + no `Sitemap:` in robots.txt |
| `partial_sitemap_error_na` | partial + all sitemaps failed + `n_total = 0` |
| `partial_no_urls_na` | partial + sitemaps fetched but `n_total = 0` after filter+dedup |
| `partial_refetch_error_na` | partial + robots.txt re-fetch failed in Step 4 |
| `fetch_error_na` | `treatment_category == fetch_error` |

### Output: `robots_sitemap_intensity_host.csv`

One row per `partial_disallow` host. Contains:
- `host`, `step4_scan_utc`, `robots_refetch_status`, `sitemap_url`, `sitemap_fetch_status`
- `n_urls_before_host_filter`, `n_urls_after_host_filter`, `n_urls_dropped_by_host_filter`, `n_sitemap_urls` (after all dedup), `url_cap_hit`, `n_urls_dropped_by_cap`, `sitemaps_truncated`
- `{Bot}_n_blocked`, `{Bot}_intensity` for each of 8 treatment bots
- `mean_treatment_intensity`, `max_treatment_intensity`

### Output: `robots_sitemap_intensity_firm.csv`

One row per firm. 10,062 rows (same anchor as `robots_firm_summary.csv`). Contains all columns from `robots_firm_summary.csv` plus:
- Host-level intensity columns merged on `host`
- `intensity_final`: 0 (allow) / computed mean (partial_sitemap) / 1 (full_disallow) / NA (all other)
- `intensity_source`: 8-value label

Intensity is computed at unique-host level, then mapped to all firms sharing that host (firms sharing a host get identical values).

### Checkpoint and resume

- `sitemap_progress.json` — tracks completed hosts; direct write with 5 retries (OneDrive-safe)
- 0.3–0.5s delay between hosts

### Command to reproduce

```bash
cd bot_paper/
python sitemap_intensity.py --limit 20   # smoke test (first 20 hosts)
python sitemap_intensity.py              # full run
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
| `robots_sitemap_intensity_host.csv` | Output | varies | Host-level sitemap intensity (partial_disallow hosts) |
| `robots_sitemap_intensity_firm.csv` | Output | ~2 MB | Firm-level intensity (10,062 rows, regression-ready) |
| `scan_progress.json` | Checkpoint | ~40 MB | Full scan results by host (for resume) |
| `sitemap_progress.json` | Checkpoint | varies | Sitemap scan progress (for resume) |
| `robots_parser.py` | Code | 9 KB | RFC 9309 parser with wildcard/percent-encoding support |
| `test_robots_parser.py` | Code | 12 KB | 19 unit tests |
| `clean_weburl.py` | Code | 4 KB | URL cleaning script |
| `fetch_utils.py` | Code | 7 KB | Shared HTTP fetch utilities |
| `scan_robots.py` | Code | 16 KB | Batch scanner + classifier |
| `sitemap_intensity.py` | Code | ~12 KB | Sitemap blocking intensity (Step 4) |
| `CLAUDE.md` | Documentation | 7 KB | Project spec and decisions |
| `DATA_CONSTRUCTION_MANUAL.md` | Documentation | ~18 KB | This file |

---

## Cross-validation

An independent reimplementation of the entire pipeline (Steps 1-4) was built from scratch by a separate AI (GPT) using only the CLAUDE.md spec and this manual. Full comparison results are in `gpt answer/`.

### Firm-level comparison (N=10,062)

| Metric | Value |
|---|---|
| Rows matched | 10,062 / 10,062 (100%) |
| `intensity_final` identical or both NA | 9,198 (91.4%) |
| `treatment_category` mismatch | 151 rows |
| `intensity_source` mismatch | 287 rows |
| Mean absolute diff (both non-NA, N=7,286) | 0.000108 |
| Median absolute diff | 0.0 |
| p95 absolute diff | 3.28e-07 |
| Max absolute diff | 0.1215 (www.omadahealth.com) |

### Source of differences

All discrepancies trace to **live fetch timing** — robots.txt content and sitemap availability change between scans. There are zero differences attributable to algorithmic divergence:
- `treatment_category` mismatches (151): server status changed between two scan runs (e.g., 403→200 or vice versa)
- `intensity_source` mismatches (287): sitemap availability changed (e.g., sitemap returned 200 in one run, 403 in the other)
- Top host-level differences (omadahealth, timken, tronox, bing, allot) all show different `n_sitemap_urls`, confirming sitemap content drift

### GPT code review findings

The GPT codebase was reviewed for correctness. Valid engineering issues found:
- `fetch_utils.py`: 403 retry condition is always true (dead code on the `return first` fallback)
- `sitemap_intensity.py`: `gzip.decompress()` has no decompressed-size limit (gzip bomb risk)
- `sitemap_intensity.py`: `collect_locs()` function defined but never called (dead code)
- `robots_parser.py`: specificity calculation includes `*` and `$` characters in rule length (edge case)

Three RFC-related claims in the review were evaluated and rejected:
- "Only use first matching group" — RFC 9309 is ambiguous; merging all matching groups is an intentional design choice, consistent across both implementations
- "Cross-host redirect = no robots.txt" — RFC 9309 Section 2.3.1.2 says to follow redirects, not to discard cross-host results
- "401/407 = disallow all" — RFC 9309 Section 2.3.1.3 treats all 4xx as "may assume allow all," not disallow

---

## Step 5: Build Analysis Sample (`build_analysis_sample.py`)

### Goal

Merge robots outcome data with Compustat financial characteristics to produce an analysis-ready dataset for descriptive statistics and regressions.

### Input files

| File | Role |
|---|---|
| `robots_sitemap_intensity_firm.csv` | Main sample: robots.txt outcome + intensity (10,062 rows) |
| `compustat_2025_clean.csv` | Identifiers + SIC codes |
| `2024_firm_char.csv` | Compustat Fundamentals Annual, fyear=2024 (baseline controls) |
| `2025_firm_char.csv` | Compustat Fundamentals Annual, fyear=2025 (robustness) |

### Why two years of financial data

The robots.txt outcome was observed in March 2026. Using fyear=2024 financials as controls gives lagged (pre-determined) characteristics — standard practice in corporate finance to avoid look-ahead bias. fyear=2025 is included for robustness checks.

### Processing steps

1. **Drop exact duplicate rows** in main sample: 10,062 → 9,484 rows (578 duplicates removed; 9,484 unique gvkeys)

2. **Add SIC + flags** from `compustat_2025_clean.csv`:
   - `fund_flag = 1` if SIC ∈ {6722, 6726} (investment trusts / ETFs)
   - `fin_flag = 1` if SIC 6000-6999 (all financial firms, for robustness exclusion)
   - Fund/ETF: 5,719 firms (60.3%); Non-fund: 3,765 firms (39.7%)
   - Financial (SIC 6000-6999): 6,548; Non-financial: 2,936

3. **Filter firm_char** to clean lookup table:
   - `costat == "A"` (active companies)
   - `datafmt == "STD"` (standard format)
   - `indfmt == "INDL"` (industrial format — avoids duplicate rows from financial-services format)
   - After filter: 12,157 rows (2024) / 10,385 rows (2025), zero duplicate gvkeys

4. **Left-join** 2024 and 2025 financials on `gvkey`, with suffixes `_2024` / `_2025`

5. **Construct derived variables** (for each year):

| Variable | Formula | Coverage (non-fund, 2024) |
|---|---|---|
| `log_at` | log(total assets) | 99.5% |
| `roa` | ni / at | 99.4% |
| `leverage` | (dltt + dlc) / at | 99.5% |
| `cash_ratio` | che / at | 99.5% |
| `rd_intensity` | xrd / at | 50.2% (normal — many firms don't report R&D) |
| `intan_ratio` | intan / at | 98.0% |
| `mkcap` | csho × prcc_f | 93.5% |
| `log_mkcap` | log(market cap) | 93.5% |

5b. **Training vs Search intensity aggregates**:
   - `training_intensity` = mean of 5 training bot intensities (GPTBot, ClaudeBot, Google-Extended, CCBot, Meta-ExternalAgent)
   - `search_intensity` = mean of 3 search bot intensities (OAI-SearchBot, Claude-SearchBot, PerplexityBot)

5c. **Search-specific treatment variables** (built from `robots_bot_panel.csv`):

   Treatment is defined over the **search-bot universe** (3 bots: OAI-SearchBot, Claude-SearchBot, PerplexityBot), not all 8 bots. This matches the paper's mechanism: search blocking → AI search results visibility.

   | Variable | Definition |
   |---|---|
   | `search_treatment` | search_allow / search_partial_block / search_full_block / search_fetch_error |
   | `search_block` | 1 if any search bot is blocked (root or nonroot) — **primary binary treatment** |
   | `search_full_block` | 1 if all 3 search bots root-blocked |
   | `n_search_root_blocked` | Count of search bots root-blocked (0-3) |
   | `training_block` | 1 if any training bot root-blocked |
   | `n_training_root_blocked` | Count of training bots root-blocked (0-5) |

   Classification logic:
   - `search_allow`: no search bot has root_block=1 or has_nonroot_disallow=1
   - `search_partial_block`: at least one search bot blocked, but not all 3 root-blocked
   - `search_full_block`: all 3 search bots root-blocked
   - `search_fetch_error`: robots.txt unobservable (any search bot has root_block=NA)

   Distribution (N=9,484):

   | Search Treatment | N | % |
   |---|---|---|
   | search_allow | 4,917 | 51.8% |
   | search_partial_block | 3,806 | 40.1% |
   | search_full_block | 29 | 0.3% |
   | search_fetch_error | 732 | 7.7% |

   **Why search-specific treatment matters:** 128 firms that only block training bots (no search restriction) were `partial_disallow` under the old 8-bot definition but are correctly `search_allow` here. Including them in the treatment group would add noise without signal for the search channel mechanism.

### Why fund/ETF coverage is low

Fund/ETF firms (SIC 6722/6726) do not report standard industrial financial statements in Compustat Fundamentals Annual. Variables like `at`, `ni`, `revt` are structurally missing for these entities — not due to data quality issues but because these accounting items do not apply to investment vehicles.

### Sample strategy

| Analysis type | Sample | N |
|---|---|---|
| Full descriptive (blocking rates, treatment distribution) | All firms | 9,484 |
| Baseline regressions with accounting controls | Non-fund (`fund_flag == 0`), retains operating financials | 3,765 |
| Robustness: exclude all financials | `fin_flag == 0` | 2,936 |
| Robustness: financial heterogeneity | `fin_flag × search_block` interaction | 3,765 |
| Baseline controls | `*_2024` variables (lagged) | — |
| Robustness controls | `*_2025` variables | — |

Fund/ETF firms remain in the full sample for descriptive analysis — their robots.txt policies are meaningful (e.g., Vanguard, BlackRock websites contain investor-relevant information). They are only excluded from regressions that require industrial accounting controls. Operating financial firms (banks, insurance, REITs) are retained in the baseline because their corporate websites are economically meaningful information sources for the AI search mechanism. Excluding all SIC 6000-6999 is a robustness check, not the baseline.

### R&D missing values

`xrd` (R&D expense) is missing for ~50% of non-fund firms. This is standard in Compustat — firms with no material R&D do not report the item. Recommended treatment in regressions: set missing `xrd` to 0 and include an `rd_missing` dummy variable.

### Output: `analysis_sample.csv`

9,484 rows × 98 columns. One row per unique gvkey. Contains:
- All columns from `robots_sitemap_intensity_firm.csv`
- `sic`, `naics`, `exchg`, `fic`, `loc` from `compustat_2025_clean.csv`
- `fund_flag`, `fin_flag` (sample flags)
- `search_treatment`, `search_block`, `search_full_block`, `n_search_root_blocked` (search-specific treatment)
- `training_block`, `n_training_root_blocked` (training-specific, for descriptives)
- `training_intensity`, `search_intensity` (channel-specific continuous measures)
- Raw Compustat variables with `_2024` / `_2025` suffixes
- Derived variables (`roa_2024`, `leverage_2024`, `log_at_2024`, etc.)

### Command to reproduce

```bash
cd bot_paper/
python build_analysis_sample.py
```

---

## File inventory

After running the full pipeline, the `bot_paper/` directory contains:

| File | Type | Size | Description |
|---|---|---|---|
| `compustat_2025.csv` | Input data | 1.3 MB | Raw Compustat cross-section |
| `compustat_2025_clean.csv` | Intermediate | ~2 MB | Cleaned URLs with host extraction |
| `2024_firm_char.csv` | Input data | ~1 MB | Compustat Fundamentals Annual (fyear=2024) |
| `2025_firm_char.csv` | Input data | ~1 MB | Compustat Fundamentals Annual (fyear=2025) |
| `robots_bot_panel.csv` | Output | ~15 MB | Bot-level panel (120,900 rows) |
| `robots_firm_summary.csv` | Output | ~1 MB | Firm-level summary (10,062 rows) |
| `robots_sitemap_intensity_host.csv` | Output | varies | Host-level sitemap intensity (partial_disallow hosts) |
| `robots_sitemap_intensity_firm.csv` | Output | ~2 MB | Firm-level intensity (10,062 rows) |
| `analysis_sample.csv` | Output | ~4 MB | Analysis-ready sample (9,484 rows × 98 cols, with financials + search treatment) |
| `scan_progress.json` | Checkpoint | ~40 MB | Full scan results by host (for resume) |
| `sitemap_progress.json` | Checkpoint | varies | Sitemap scan progress (for resume) |
| `robots_parser.py` | Code | 9 KB | RFC 9309 parser with wildcard/percent-encoding support |
| `test_robots_parser.py` | Code | 12 KB | 19 unit tests |
| `clean_weburl.py` | Code | 4 KB | URL cleaning script |
| `fetch_utils.py` | Code | 7 KB | Shared HTTP fetch utilities |
| `scan_robots.py` | Code | 16 KB | Batch scanner + classifier |
| `sitemap_intensity.py` | Code | ~12 KB | Sitemap blocking intensity (Step 4) |
| `build_analysis_sample.py` | Code | 4 KB | Merge financials + build analysis sample (Step 5) |
| `CLAUDE.md` | Documentation | 7 KB | Project spec and decisions |
| `DATA_CONSTRUCTION_MANUAL.md` | Documentation | ~25 KB | This file |

---

## What comes next

| Step | Status | Description |
|---|---|---|
| Step 1 | Done | Clean weburl |
| Step 2 | Done | Batch scan robots.txt |
| Step 3 | Done | Classify firms (treatment variable) — re-run after parser upgrade |
| Step 4 | Done | Sitemap blocking intensity (continuous treatment measure) |
| Step 5 | Done | Merge Compustat financials, build analysis sample |
| Step 6 | In progress | Descriptive statistics: Table 1 balance table by search_treatment (Stata) |
