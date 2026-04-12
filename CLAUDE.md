# Bot Paper - Corporate AI Crawler Policy and Capital Market Consequences

## Target
High-quality corporate finance journal (e.g., RFS, JFE, JAR). All analysis must be rigorous, verified, and honest. Do not fabricate results or make claims without evidence.

## Research Question
Do website access rules incidentally reduce firms' visibility in AI search systems, and does this affect the information environment?

## Core Story (2026-04-06)
Most firms do not deliberately target AI search crawlers. However, pre-existing website access rules — originally designed for general web management — incidentally constrain what AI search systems can surface. When these rules happen to cover economically relevant public pages, they measurably reduce official content visibility in AI search results.

This parallels Gao & Huang (RFS 2020) EDGAR digitalization as a mirror image: EDGAR made information cheaper to disseminate/process -> improved outsider information production. Website rules that reduce AI search visibility make AI-mediated information acquisition costlier/less complete -> potential deterioration.

## Causal Chain
```
Website rules block public pages from search bot access
-> Official website less likely to be surfaced/cited by AI search
-> AI-mediated information acquisition becomes costlier / less complete
-> Information environment deteriorates
```

## What This Paper is NOT About
- NOT: "information disappears from the web" — it's still on the company website
- NOT: "AI training data gets worse" — we cannot measure the training channel (uncertain lags, unobservable training sets)
- NOT: "firms deliberately target AI" — only 44 firms have any AI-specific search bot rules; the vast majority of blocking is incidental via generic wildcard rules

## Scope: Search Channel Only
We focus on the **search channel** because it generates immediate effects on AI-mediated information access. Blocking search bots (OAI-SearchBot, PerplexityBot, Claude-SearchBot) reduces the probability that official website content is surfaced or cited in AI search answers.

The training channel (whether blocking affects future model knowledge) operates with uncertain lags and is not directly testable in our cross-sectional setting. We leave this to future work.

Note: blocking does not guarantee complete exclusion. Per OpenAI docs, blocked sites "don't appear in search answers" but "may still appear as navigational links." The mechanism is best understood as reducing the probability of being used/surfaced, not as mechanical exclusion.

## Treatment Variable Design (four tiers)

### Critical empirical fact
Among non-fund firms with observable robots.txt: ~47% have some rule applicable to any AI bot (`any_ai_block`), and ~40% have a rule applicable to search bots specifically (`search_block`). But almost all of these come from generic `User-agent: *` wildcard rules (e.g., `Disallow: /admin/`). Of firms with search bot blocking, ~99% are via wildcard rules, not AI-specific decisions. Only 44 firms (1.2%) have specific `User-agent` rules naming a search bot (23 for OAI-SearchBot, 42 for PerplexityBot, 8 for Claude-SearchBot; some overlap). Treatment must reflect **actual effect on public page access**, not just rule existence.

### Tier 0 — Broadest: `any_block` (descriptive upper bound)
- `1` if any of 8 treatment bots has root_block=1 or has_nonroot_disallow=1 (includes generic wildcard rules)
- Distribution (non-fund observable): =1: 1,588 / 3,395 (46.8%)
- Mixes training and search channels. NOT the main treatment.

### Tier 1 — Search-focused broad: `search_block` (search upper bound)
- `1` if any of 3 search bots has root_block=1 or has_nonroot_disallow=1
- Distribution (non-fund observable): =1: 1,541 / 3,395 (45.4%)
- Narrows to search channel but still includes generic wildcard rules. Descriptive only.

### Tier 2 — Main treatment: `search_public_block` (effect-based)
- `1` if search_full_block=1 OR search_intensity > 0 (rules actually block sitemap-listed public pages)
- `0` if no search restriction, OR has rules but search_intensity = 0 (rules don't affect public pages)
- `NA` if fetch_error OR no sitemap data to evaluate
- Why conditions (a) and (b) merge: both mean search bots face reduced access to public content. (a) = complete exclusion, (b) = partial exclusion verified by URL matching.

Distribution (full sample): =1: 647 / =0: 6,494 / =NA: 2,343
Distribution (non-fund observable, N=2,823): =1: 164 (5.8%) / =0: 2,659 (94.2%)
Main regression sample (non-fund): 164 + 2,659 = 2,823 firms

### Tier 3 — Specific: `search_block_specific` (AI-specific intent, appendix)
- `1` if any search bot has effective_source="specific" AND is blocked
- Distribution: =1: 44 firms (0.5%)
- Too few for main regression. Appendix / rare-event descriptive only.

### Per-platform variables (for mechanism alignment in Layer 1)
| Variable | Bot | =1 (broad) | =1 (specific) |
|---|---|---|---|
| `block_oai_broad` / `block_oai_specific` | OAI-SearchBot | 3,815 | 23 |
| `block_perplexity_broad` / `block_perplexity_specific` | PerplexityBot | 3,811 | 42 |
| `block_claude_search_broad` / `block_claude_search_specific` | Claude-SearchBot | 3,833 | 8 |

Cross-platform blocking is ~99% identical. Platform variables are for **mechanism alignment** (matching treatment to platform-specific outcome), not heterogeneity identification.

### Background (NOT main treatment)
- `treatment_category`: old 8-bot definition — comparison only
- `training_block` (194 firms, 2.0%) / `training_intensity`: descriptive only
- `intensity_final`: mean of all 8 bots (too blended)

### Training vs search blocking
Among `search_partial_block` firms with sitemap data: `training_intensity` (mean=0.028) is ~3x higher than `search_intensity` (mean=0.009). This means firms' rules block more content from training bots than from search bots. But note: `training_block` (root-blocked for training, 194 firms) is much smaller than `search_block` broad (3,835 firms), because `search_block` broad includes all wildcard nonroot rules.

## Empirical Design (three steps)

### Step 1: Descriptive facts
- Three-tier treatment distribution
- search_public_block = 647 treated / 6,494 control / 2,343 NA
- Table 1: balance table showing selection on size and intangibility (search_public_block=1 firms are larger, more profitable, more intangible-asset-intensive)

### Step 2: Mechanism test (Layer 1) — MOST IMPORTANT
Start with a ChatGPT Search pilot using a 1:1 matched sample (30 pairs, matched within `sic2 x size_tercile`). Perplexity and Claude Search are robustness extensions if feasible after the ChatGPT pilot.

**Key technical facts for the ChatGPT pilot (from OpenAI docs):**
- OAI-SearchBot is the relevant crawler governing eligibility for inclusion in ChatGPT search answers
- Blocked sites don't appear in search answers, but may still appear as "navigational links"
- ChatGPT-User does NOT determine search inclusion — the search feature uses search bots
- ChatGPT Search has two layers: **inline citations** (content actually used in answer) and **Sources panel** (includes cited sources + other relevant links). These must be tracked separately.

**Mechanism DVs (priority order):**

1. `OfficialCited_{iq}` — **PRIMARY**. Whether official website appears in **inline citations**. Most directly measures "did AI search use this firm's official content?"

2. `OfficialRank_{iq}` — Position of official site's first appearance in citations. Even if not fully excluded, dropping in rank reduces visibility.

3. `OfficialShare_{iq}` — Official site citations / total citations. Captures information substitution.

4. `OfficialListed_{iq}` — **SUPPLEMENTARY**. Whether official website appears anywhere in Sources panel. Weaker because Sources panel mixes cited sources with "relevant links."

**Firm-level aggregates:**
- `OfficialCitedCoverage_i` = mean of OfficialCited across queries — **primary firm-level DV**

**Main regression:**
```
OfficialCitedCoverage_i = a + b * SearchPublicBlock_i + c * X_i + e_i
```
If b < 0, the mechanism is supported.

**Mechanism alignment (per platform, robustness if feasible after the ChatGPT pilot):**
```
OfficialCited_{iqp} = a + b * Block_{ip}_broad + c * X_i + d_q + e_{iqp}
```
Run separately for ChatGPT (`block_oai_broad`) first, then Perplexity (`block_perplexity_broad`) and Claude (`block_claude_search_broad`) if those pilots are feasible. Consistent `b` across platforms would be a credibility anchor, not a prerequisite for the main paper.

### Step 2b: Common Crawl validation (complements pilot, not replaces)
Use Common Crawl's public CDX index to verify that robots.txt rules actually reduce crawler coverage of firm URLs.

**What it tests:** block crawler → crawler's actual URL coverage drops. This is the crawler-facing counterpart to the pilot's user-facing test (block → AI search citations drop).

**Design:**
- Define "target URL universe" per firm: sitemap URLs under economically relevant paths (/investor/, /news/, /press/, /governance/, /sustainability/). Exclude utility paths (/admin/, /cart/, /search/).
- Query Common Crawl CDX index for each target URL: did it appear in a given CC-MAIN crawl?
- Compute: CCCoverage_it = (# target URLs appearing in crawl t) / (# target URLs in universe)

**Strongest version (event study, requires panel):**
- Identify firms that changed robots.txt policy over time (allow → block or block → allow)
- Source: Wayback Machine historical robots.txt snapshots, or Common Crawl's own archived robots.txt
- Test: CCCoverage drops after policy tightening, recovers after loosening
- Placebo: blocking /admin/ should not affect /investor/ coverage

**Weaker but feasible version (cross-sectional):**
- Compare CCCoverage between search_public_block=1 and =0 firms in a single recent crawl
- Less causal, but still shows that treatment variable correlates with actual crawler behavior

**Key caveats:**
- Common Crawl is a sample, not a census. URL absence != definitely blocked. Need before/after + matched controls to be convincing.
- CCBot is not OAI-SearchBot. Different bots may have different compliance rates. But if CCBot coverage drops when User-agent: * rules apply, it validates the mechanism for all bots that obey wildcard rules.

**Priority relative to pilot:**
1. Pilot test first (directly tests the paper's mechanism: AI search citations)
2. Common Crawl validation second (provides scale, automation, and a different angle)
3. Event study version later (requires historical robots.txt panel, higher effort)

### Step 3: Information environment outcomes (Layer 2) — cautious
Priority 1: Analyst forecast dispersion, analyst forecast accuracy
Priority 2: Bid-ask spread, Amihud illiquidity
Priority 3: PEAD, price efficiency measures

Language: "associated with" / "suggestive evidence" / "consistent with the mechanism"

## Identification Strategy (preliminary, to be developed later)
- GPTBot launch (Aug 2023) as exogenous shock
- Google-Extended launch (Sep 2023) as decoupling event
- Current stage: descriptive cross-section first, identification comes later

## Bot Taxonomy (from official documentation)

Training crawlers (5):
- GPTBot (OpenAI): training data collection
- ClaudeBot (Anthropic): training data collection
- Google-Extended (Google): Gemini/Vertex training. Does NOT affect Google Search
- CCBot (Common Crawl): feeds into many LLM training sets
- Meta-ExternalAgent (Meta): training/indexing for Meta AI

Search crawlers (3):
- OAI-SearchBot (OpenAI): controls ChatGPT search answer inclusion. Opt-out = not in search answers, may still appear as navigational links
- PerplexityBot: search results only, "not used for foundation model training"
- Claude-SearchBot (Anthropic): search result quality

User-triggered fetchers (may ignore robots.txt):
- ChatGPT-User, Perplexity-User, Meta-ExternalFetcher

## Current Stage (2026-04-06)
Steps 1-5 complete. analysis_sample.csv (9,484 firms, 106 columns) ready.
Step 6 (Table 1) done in Stata.
Layer 1 pilot sample drawn (30 pairs, 60 firms). Recording sheet ready.
Next: run 300 ChatGPT Search queries, then analyze Layer 1 results.

## Key References
- Gao & Huang (RFS 2020): EDGAR digitalization -> information production by outsiders increases
- Goldstein et al. (2023): EDGAR mandatory adoption -> investment and financing improve
- Da et al. (2011): Google search volume as investor attention proxy
- Drake et al. (2012): Information demand around earnings via Google search
- Boulland, Bourveau & Breuer (2025): Website disclosure as new measurement dimension
- Kim et al. (IMC 2025): Scrapers selectively respect robots.txt; compliance drops with stricter rules
- Longpre et al. (NeurIPS 2024): Consent in Crisis; AI data restrictions rising from ~0% to 28%
- Cui et al. (CCS 2025): robots.txt governance; 7.4% of top-1M domains reference LLM bots
- RFC 9309: robots.txt is "not a form of access authorization"

## RFC 9309 Rules (source: https://www.rfc-editor.org/rfc/rfc9309.html)

All robots.txt parsing in this project follows these rules.

### File format
- File at `scheme://authority/robots.txt`, UTF-8, `text/plain`
- `#` for line comments, CR/LF/CRLF accepted

### Group structure
- Group = User-agent lines + Allow/Disallow rules
- Consecutive User-agent lines before rules = one group
- Sitemap: lines do NOT terminate groups

### Which group applies
- Case-insensitive matching on product token
- Multiple matching groups: merge rules
- No specific match: use `*` group if present
- No match at all: everything allowed

### Path matching
- Case sensitive, prefix-based
- Longest match wins; allow wins on tie
- `*` = 0+ characters, `$` = end anchor (implemented in robots_parser.py)
- Percent-encoding: unreserved chars decoded before comparison (implemented)

### HTTP status handling
- 2xx: parse and follow rules
- 3xx: follow redirects (up to 5 per RFC)
- 4xx: file unavailable = allow all
- 5xx: file unreachable = assume disallow (we deviate: classify as fetch_error/unknown)

### Our deviations from RFC 9309
1. 5xx: we classify as `fetch_error` (unknown), not "assume complete disallow." Rationale: assuming disallow on server error would introduce false positives in our research cross-section.
2. Redirect limit: `requests` library follows up to 30 redirects. We record `robots_final_url` but don't enforce the 5-redirect limit.

## Implementation Decisions (2025-03-25)
- Host-level scanning (not root domain): robots.txt is host-specific
- Treatment denominator: training + search bots only (8 bots). User-triggered fetchers tracked separately.
- Parser: implements RFC 9309 including wildcard `*`/`$` and percent-encoding normalization
- Alias/redirect domains: primary scan uses exact Compustat host
- 403/WAF-gated: classified as fetch_error, never inferred as allow or disallow

## Table 1 Findings (2026-04-06)
Using `search_public_block` as the main treatment among non-fund firms with nonmissing 2024 controls and nonmissing `search_public_block` (N=2,823):
- Blocked firms (N=164) are significantly larger (log mkt cap 8.60 vs 7.20, p<0.001), more profitable (ROA 0.02 vs -0.31, p<0.001), lower leverage (0.27 vs 0.41, p=0.002), lower R&D intensity (0.07 vs 0.14, p<0.001), and more intangible-asset-intensive (0.22 vs 0.16, p<0.001).
- This confirms selection on observables: large, mature, intangible-asset-heavy firms are more likely to have rules that block public pages. Regressions must control for these.
