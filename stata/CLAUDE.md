# Bot Paper — Stata Analysis

## Data Paths
- Raw data: `C:/Users/xl/OneDrive - Universitat Ramón Llull/bot_paper/` (CSV files from Python pipeline)
- Analysis sample: `analysis_sample.csv` (9,484 firms, 106 columns)
- Stata output: `stata-mcp-folder/stata-mcp-result/`

## Coding Standards
- All do-files must start with: `version 17`
- Use `reghdfe` instead of `areg` for high-dimensional fixed effects
- Export regression tables with `estout`/`esttab`
- Graphs use `scheme(s2color)` unless specified otherwise
- Variables with `-inf`/`inf` from CSV import need `destring, force` before use

## Current Research Design
- Research question: Do website access rules incidentally reduce firms' visibility in AI search systems?
- Mechanism: The effect is strongest when rules cover economically relevant public pages.
- Supplementary: Explicit AI-specific rules are rare (44 firms); most blocking is incidental via generic wildcard rules.
- Primary treatment: `search_public_block` (effect-based: rules actually block public pages)
- Platform-specific mechanism tests: `block_oai_broad` / `block_perplexity_broad` / `block_claude_search_broad` (for credibility, run 3x)
- Controls (lagged, fyear=2024): `log_at_2024`, `roa_2024`, `leverage_2024`, `cash_ratio_2024`, `rd_intensity_2024`, `intan_ratio_2024`, `log_mkcap_2024`
- Robustness controls: same variables with `_2025` suffix
- Industry classification: `sic`, `naics`

## Sample Definition
This research is about AI-mediated information acquisition and website access visibility, not traditional capital structure. Financial firms' websites (banks, insurance, REITs) contain investor-relevant content and are meaningful for the AI search citation mechanism. Do NOT mechanically exclude all SIC 6000-6999.

- Full sample: 9,484 unique firms (after dedup)
- Fund/ETF (SIC 6722/6726): 5,719 firms (`fund_flag == 1`) — no accounting data
- Non-fund firms: 3,765 firms (`fund_flag == 0`) — includes operating financials, 99.5% accounting coverage
- `fin_flag`: 1 if SIC 6000-6999 (for robustness exclusion, NOT baseline exclusion)

Sample usage:
- Descriptive analysis: full sample
- Baseline regressions: `fund_flag == 0` (retains operating financials)
- Main treatment regression sample: `search_public_block` non-NA → ~7,141 firms
- Robustness 1: `fin_flag == 0` (exclude all financials)
- Robustness 2: `fin_flag × treatment` interaction

Labeling: call it "non-fund firms", NOT "non-financial operating firms".

## Workflow
- Do-files stored in: `stata-mcp-folder/stata-mcp-dofile/`
- Log files: `stata-mcp-folder/stata-mcp-log/`
- Result files (tables, etc.): `stata-mcp-folder/stata-mcp-result/`
- Naming: `01_table1.do`, `02_analysis_*.do`, etc.

## Complete Variable Dictionary (106 columns)

### 1. Identifiers (cols 1-5)
| # | Variable | Description | Source |
|---|---|---|---|
| 1 | `scan_date` | Date robots.txt was scanned (YYYY-MM-DD, March 2026) | `scan_robots.py` |
| 2 | `firm` | Company name | Compustat `conm` |
| 3 | `ticker` | Stock ticker symbol | Compustat `tic` |
| 4 | `gvkey` | Compustat Global Company Key (primary merge key) | Compustat |
| 5 | `host` | Canonical website host scanned (e.g., `www.apple.com`) | `clean_weburl.py` |

### 2. Three-tier treatment variables

#### Tier 1 — Main treatment: `search_public_block` (effect-based)
| Variable | Description | Values |
|---|---|---|
| `search_public_block` | **PRIMARY TREATMENT.** 1 if rules actually block sitemap-listed public pages for search bots. | =1: 647, =0: 6,494, =NA: 2,343 |

Definition:
- `1` if `search_full_block=1` OR `search_intensity > 0`
- `0` if `search_allow` OR (`search_partial_block` AND `search_intensity == 0`)
- `NA` if `search_fetch_error` OR no sitemap data to evaluate

Main regression sample: 647 + 6,494 = **7,141 firms**.

#### Tier 2 — Broad: `search_block` (descriptive / upper bound)
| Variable | Description | Values |
|---|---|---|
| `search_block` | 1 if any search bot has root_block=1 or nonroot_disallow=1. Includes generic wildcard rules. | =1: 3,835 (40.4%) |
| `search_treatment` | Categorical: search_allow / search_partial_block / search_full_block / search_fetch_error | |
| `search_full_block` | 1 if all 3 search bots root-blocked | =1: 29 |
| `n_search_root_blocked` | Count of search bots root-blocked (0-3) | |

**NOT the main treatment** — ~99% of the 3,835 are generic wildcard rules (/admin/, /search/), not AI-specific decisions.

#### Tier 3 — Specific: `search_block_specific` (AI-specific intent, appendix)
| Variable | Description | Values |
|---|---|---|
| `search_block_specific` | 1 if any search bot has effective_source="specific" AND is blocked | =1: 44, =NA: 732 |

Too few for main regression. Appendix / rare-event descriptive only.

#### Per-platform variables (for mechanism alignment in Layer 1)
| Variable | Bot | =1 (broad) | =1 (specific) |
|---|---|---|---|
| `block_oai_broad` / `block_oai_specific` | OAI-SearchBot | 3,815 | 23 |
| `block_perplexity_broad` / `block_perplexity_specific` | PerplexityBot | 3,811 | 42 |
| `block_claude_search_broad` / `block_claude_search_specific` | Claude-SearchBot | 3,833 | 8 |

Cross-platform blocking is ~99% identical. Platform variables are for **mechanism alignment** (matching treatment to platform-specific outcome), not heterogeneity identification.

#### Background (NOT main treatment)
| Variable | Description | Role |
|---|---|---|
| `treatment_category` | Old 8-bot definition (allow / partial_disallow / full_disallow / fetch_error) | Comparison with prior work |
| `training_block` | 1 if any training bot root-blocked (194 firms) | Descriptive |
| `n_training_root_blocked` | Count of training bots root-blocked (0-5) | Descriptive |
| `training_intensity` | Mean of 5 training bot intensities | Descriptive |
| `search_intensity` | Mean of 3 search bot intensities | Continuous robustness |
| `intensity_final` | Mean of all 8 bots | Too blended for causal claims |

### 3. Old 8-bot treatment (cols 6-8)
| # | Variable | Description |
|---|---|---|
| 6 | `treatment_category` | allow / partial_disallow / full_disallow / fetch_error |
| 7 | `intensity_final` | Continuous blocking intensity (mean of 8 bots) |
| 8 | `intensity_source` | Data quality label (8 categories) |

### 4. Sitemap intensity detail (cols 9-19)
Only populated for `partial_disallow` firms with available sitemaps.

| # | Variable | Description |
|---|---|---|
| 9 | `step4_scan_utc` | ISO timestamp of sitemap intensity computation |
| 10 | `robots_refetch_status` | Status of robots.txt re-fetch (ok_200 / error) |
| 11 | `sitemap_url` | First Sitemap: URL declared in robots.txt |
| 12 | `sitemap_fetch_status` | ok / partial_ok / error type |
| 13-15 | `n_urls_*` | URL counts before/after host filter, dropped count |
| 16 | `n_sitemap_urls` | Final comparison URL count |
| 17-19 | `url_cap_hit`, `n_urls_dropped_by_cap`, `sitemaps_truncated` | Safety cap flags |

### 5. Per-bot blocking counts and intensities (cols 20-37)
8 treatment bots × 2 columns each. Only populated for `partial_sitemap` firms.

| # | Variable | Description |
|---|---|---|
| 20-27 | `{Bot}_n_blocked` | Sitemap URLs blocked for this bot |
| 28-35 | `{Bot}_intensity` | n_blocked / n_sitemap_urls (0-1) |
| 36 | `mean_treatment_intensity` | Mean of 8 bot intensities |
| 37 | `max_treatment_intensity` | Max across 8 bot intensities |

Bots: GPTBot, ClaudeBot, Google-Extended, CCBot, Meta-ExternalAgent, OAI-SearchBot, Claude-SearchBot, PerplexityBot.

### 6. Channel-specific intensity (cols 91-92)
| # | Variable | Description |
|---|---|---|
| 91 | `training_intensity` | Mean of 5 training bot intensities |
| 92 | `search_intensity` | Mean of 3 search bot intensities |

Training intensity (~0.028) is ~3x higher than search intensity (~0.009) among partial firms.

### 7. Firm identifiers and industry (cols 38-42)
| # | Variable | Description |
|---|---|---|
| 38 | `exchg` | Stock exchange code |
| 39 | `fic` | Foreign incorporation code |
| 40 | `loc` | Country of headquarters |
| 41 | `naics` | NAICS (6-digit) |
| 42 | `sic` | SIC (4-digit) |

### 8. Sample flags (cols 43-44)
| # | Variable | Description | N=1 |
|---|---|---|---|
| 43 | `fund_flag` | 1 if SIC 6722/6726 (fund/ETF) | 5,719 |
| 44 | `fin_flag` | 1 if SIC 6000-6999 (all financials) | 6,548 |

### 9. Raw Compustat financials (cols 45-74)
Filtered to costat=="A" & datafmt=="STD" & indfmt=="INDL". Suffix `_2024` (baseline) / `_2025` (robustness).

| # | Variable | Description |
|---|---|---|
| 45/60 | `at` | Total Assets |
| 46/61 | `ceq` | Common Equity |
| 47/62 | `che` | Cash & Short-term Investments |
| 48/63 | `dlc` | Current Debt |
| 49/64 | `dltt` | Long-term Debt |
| 50/65 | `intan` | Intangible Assets |
| 51/66 | `ppegt` | Gross PP&E |
| 52/67 | `ni` | Net Income |
| 53/68 | `oibdp` | Operating Income Before Depreciation |
| 54/69 | `revt` | Revenue |
| 55/70 | `xrd` | R&D Expense (50% missing) |
| 56/71 | `capx` | Capital Expenditure |
| 57/72 | `csho` | Shares Outstanding |
| 58/73 | `emp` | Number of Employees |
| 59/74 | `prcc_f` | Fiscal Year-End Stock Price |

### 10. Derived controls (cols 75-90)
| # | Variable | Formula | Coverage (non-fund, 2024) | Stata note |
|---|---|---|---|---|
| 75/83 | `log_at` | log(at) | 99.5% | |
| 76/84 | `roa` | ni / at | 99.4% | `destring, force` needed |
| 77/85 | `leverage` | (dltt + dlc) / at | 99.5% | `destring, force` needed |
| 78/86 | `cash_ratio` | che / at | 99.5% | |
| 79/87 | `rd_intensity` | xrd / at | 50.2% | Regressions: set missing=0 + `rd_missing` dummy |
| 80/88 | `intan_ratio` | intan / at | 98.0% | |
| 81/89 | `mkcap` | csho × prcc_f | 93.5% | |
| 82/90 | `log_mkcap` | log(mkcap) | 93.5% | |
