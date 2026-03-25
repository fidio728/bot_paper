# Bot Paper - Corporate AI Crawler Policy and Capital Market Consequences

## Target
High-quality corporate finance journal (e.g., RFS, JFE, JAR). All analysis must be rigorous, verified, and honest. Do not fabricate results or make claims without evidence.

## Supervisor
Emanuele Rizzo, Universitat Ramón Llull (IQS School of Management)

## Research Question
How do corporate robots.txt policies toward AI crawlers affect investor information acquisition and capital market outcomes?

## Core Logic Chain (from supervisor meeting 2025-03-25)
1. Build firm-level robots.txt database; classify: no AI rules / full disallow / partial disallow
2. Mechanism: allow/disallow AI bot on website -> change how investors get information (not information disappears, but AI-assisted information acquisition becomes noisier, narrower, or more costly)
3. Capital market consequences: pricing efficiency, analyst forecast accuracy/dispersion, bid-ask spread, retail trading informativeness

## Key Framing
- NOT: "disallow AI bot -> investors cannot get firm information"
- YES: "disallow AI bot -> investors lose one lower-cost, AI-mediated way of acquiring and organizing firm information, so effective information acquisition becomes costlier or less complete"
- This parallels Gao & Huang (RFS 2020) EDGAR digitalization: not that information didn't exist before EDGAR, but that new technology made it cheaper to disseminate and process -> improved outsider information production
- Blocking AI bots is the mirror image: raises the cost of AI-mediated information acquisition

## Treatment Variable Design
Three levels (not binary):
- Allow: no AI-specific restrictions
- Full disallow: `Disallow: /` for specific AI bots (e.g., amazon.com blocks all AI bots site-wide)
- Partial disallow: sub-directory blocks only (e.g., Goldman Sachs blocks GPTBot on /research/ but not rest of site)

Continuous measure: (URLs under disallowed paths) / (total sitemap URLs) = blocking intensity

## Two Empirical Layers
- Layer 1 (mechanism validation): Prove that disallow actually changes AI tools' ability to access/cite/summarize firm information. Compare allow vs disallow firms on AI search citation rates, answer completeness, etc.
- Layer 2 (capital market outcomes): analyst forecast precision/dispersion, bid-ask spread, price efficiency, return informativeness, retail trading informativeness

## Identification Strategy (preliminary, to be developed later)
- GPTBot launch (Aug 2023) as exogenous shock
- Google-Extended launch (Sep 2023) as decoupling event (reduced cost of training opt-out to zero without losing Google Search visibility)
- Current stage: descriptive cross-section first, identification comes later

## Bot Taxonomy (from official documentation)
Training crawlers:
- GPTBot (OpenAI): training data collection. Blocking = content excluded from future model training
- ClaudeBot (Anthropic): training data collection
- Google-Extended (Google): controls Gemini/Vertex training and grounding. Does NOT affect Google Search indexing. Not a ranking signal
- CCBot (Common Crawl): feeds into many LLM training sets indirectly
- Meta-ExternalAgent (Meta): training/indexing for Meta AI products

Search/index crawlers:
- OAI-SearchBot (OpenAI): determines if site appears in ChatGPT search answers. Opt-out = not in search answers, but may still appear as navigational links
- PerplexityBot: search results only, explicitly "not used for foundation model training"
- Claude-SearchBot (Anthropic): improves search result quality

User-triggered fetchers (may ignore robots.txt per official docs):
- ChatGPT-User (OpenAI): user-initiated browsing, "does not crawl the web autonomously"
- Perplexity-User: user actions, "generally ignores robots.txt"
- Meta-ExternalFetcher: user-initiated, "may bypass robots.txt"

## Data
- compustat_2025.csv: Compustat Fundamentals Annual 2025 cross-section (~10,489 firms)
- Key variables: gvkey (primary firm ID), conm, weburl, tic, cik, cusip, exchg, fic, loc, sic, naics
- weburl needs cleaning: extract canonical host (keeping subdomains as-is, since robots.txt is host-level), check for missing/broken URLs, handle multiple domains per firm

## Current Stage (as of 2025-03-25)
Step 1: Clean weburl, standardize domains, build scanning pipeline
Step 2: Batch-scan robots.txt for all firms with valid weburl
Step 3: Classify each firm (no AI rules / full block / partial block / explicit allow)
Step 4: For partial-block firms, fetch sitemap and calculate blocking intensity
Step 5: Compare blocking vs non-blocking firms on observables (descriptive statistics)

## Known Issues / Bugs to Fix
- Previous scanning script confused Allow with Disallow (Walmart bug: script recorded Allow rules as blocks)
- Must parse robots.txt direction correctly per RFC 9309
- Compustat weburl may have high missing rate or outdated URLs - verify before bulk scanning
- Some firms have multiple domains with different policies (e.g., amazon.com vs aboutamazon.com) - Compustat only has one weburl

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

## Implementation Decisions (2025-03-25)
- Host-level scanning (not root domain): robots.txt is host-specific, so ir.tesla.com and www.tesla.com can have different policies. Cleaning extracts host_clean but does NOT collapse to root domain. This is intentional.
- Treatment denominator: training + search bots only (8 bots). User-triggered fetchers (ChatGPT-User, Perplexity-User, Meta-ExternalFetcher) are tracked separately because they may ignore robots.txt per official documentation. They should not gate "full_disallow" classification.
- Parser scope: current robots_parser.py implements core RFC 9309 semantics (specificity, longest-prefix-match, allow-wins-on-tie) but does not support * and $ pattern characters or percent-encoding normalization. Sufficient for root-block/has-nonroot-disallow classification; would need upgrade for Step 4 sitemap intensity.
- Alias/redirect domains (e.g., aaauetf.com → am.gs.com): some Compustat weburl entries are vanity/alias domains whose homepage redirects to a different host. The primary scan uses the exact Compustat host (strict host definition) because: (1) robots.txt is a host-level protocol object — homepage redirect does not imply shared robots.txt; (2) mechanically reproducible without subjective "is this an alias?" judgments; (3) avoids rewriting the sample. Future robustness check: fetch each host's homepage, record homepage_final_host, flag alias redirects, and re-run treatment assignment using the canonical destination host.
- 403/WAF-gated robots.txt: some hosts (e.g., behind Cloudflare challenge pages) return 403 even for robots.txt, including to browsers in incognito mode. This is NOT a robots policy — it is an access gate above the robots layer. These are correctly classified as fetch_error/unknown (all bot fields NA), never inferred as allow or disallow. The scanner observes "publicly accessible robots.txt content as seen by an unauthenticated automated client" — this is the reproducible research-grade definition. Attempting to bypass challenges (JS execution, cookie handling) would conflate "declared robots policy" with "content reachable after human-style authentication" and contaminate the treatment variable.

## GPT Feedback Summary (2025-03-25)
Key insight endorsed: reframe mechanism from "information disappears" to "AI-mediated information acquisition cost rises." Suggested decomposing into coverage effect (fewer pages in AI answers) and processing-cost effect (more manual search needed). Recommended two-layer empirical design: first prove mechanism (Layer 1), then test capital market outcomes (Layer 2). Endorsed sitemap-based blocking intensity as continuous treatment variable. Identified two gaps: (1) selection bias in who blocks, (2) quantifying the first-stage mechanism is the hardest and most important task.
