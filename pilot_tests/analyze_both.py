"""Detailed analysis of pilot test results across platforms."""
import csv
from pathlib import Path

BASE = Path(__file__).parent
sheets = {
    "ChatGPT (GPT-4o, Bing)": BASE / "pilot_recording_sheet_filled.csv",
    "Gemini (2.5 Flash, Google Search)": BASE / "pilot_recording_sheet_gemini.csv",
    "Claude (Sonnet, Brave Search)": BASE / "Claude" / "claude.csv",
}

query_labels = {
    "Q1_what_does": "Q1: What does [Company] do?",
    "Q2_financial_performance": "Q2: Latest financial performance",
    "Q3_investor_relations": "Q3: Investor relations",
    "Q4_management_team": "Q4: Management team",
    "Q5_recent_news": "Q5: Recent news",
}

all_platform_stats = {}

for platform, path in sheets.items():
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    control = [r for r in rows if r["pilot_group"] == "control"]
    treated = [r for r in rows if r["pilot_group"] == "treated"]

    # ── Header ──
    print()
    print("=" * 70)
    print(f"  PLATFORM: {platform}")
    print("=" * 70)

    # ── 1. Overall OfficialCited ──
    c_cite = sum(int(r["OfficialCited"]) for r in control)
    t_cite = sum(int(r["OfficialCited"]) for r in treated)
    c_rate = c_cite / len(control)
    t_rate = t_cite / len(treated)
    diff = t_rate - c_rate

    print(f"\n  1. OfficialCited (primary outcome: 0/1 whether official site appears")
    print(f"     in inline citations)")
    print()
    print(f"     {'':30} {'Control':>10} {'Treated':>10} {'Diff':>10}")
    print(f"     {'-'*62}")
    print(f"     {'OfficialCited count':30} {c_cite:>7}/150 {t_cite:>7}/150")
    print(f"     {'OfficialCited rate':30} {c_rate:>9.1%} {t_rate:>9.1%} {diff:>+9.1%}")

    # ── 2. OfficialRank ──
    c_ranks = [int(r["OfficialRank"]) for r in control if int(r["OfficialRank"]) < 999]
    t_ranks = [int(r["OfficialRank"]) for r in treated if int(r["OfficialRank"]) < 999]
    c_avg_rank = sum(c_ranks) / len(c_ranks) if c_ranks else float("nan")
    t_avg_rank = sum(t_ranks) / len(t_ranks) if t_ranks else float("nan")

    # Rank distribution
    c_rank1 = sum(1 for r in c_ranks if r == 1)
    t_rank1 = sum(1 for r in t_ranks if r == 1)

    print(f"\n  2. OfficialRank (position of official site among unique cited domains;")
    print(f"     999 = not cited)")
    print()
    print(f"     {'':30} {'Control':>10} {'Treated':>10}")
    print(f"     {'-'*52}")
    print(f"     {'Avg rank (when cited)':30} {c_avg_rank:>9.2f} {t_avg_rank:>9.2f}")
    print(f"     {'Rank=1 (first cited)':30} {c_rank1:>7}/{len(c_ranks)} {t_rank1:>7}/{len(t_ranks)}")
    print(f"     {'Not cited (rank=999)':30} {150-len(c_ranks):>9} {150-len(t_ranks):>9}")

    # ── 3. n_cited_sources ──
    c_src = [int(r["n_cited_sources"]) for r in control]
    t_src = [int(r["n_cited_sources"]) for r in treated]
    c_avg_src = sum(c_src) / len(c_src)
    t_avg_src = sum(t_src) / len(t_src)

    print(f"\n  3. n_cited_sources (total unique domains cited per query)")
    print()
    print(f"     {'':30} {'Control':>10} {'Treated':>10}")
    print(f"     {'-'*52}")
    print(f"     {'Avg sources per query':30} {c_avg_src:>9.1f} {t_avg_src:>9.1f}")
    print(f"     {'Min':30} {min(c_src):>9} {min(t_src):>9}")
    print(f"     {'Max':30} {max(c_src):>9} {max(t_src):>9}")

    # ── 4. By query type ──
    print(f"\n  4. OfficialCited rate by query type")
    print()
    print(f"     {'Query':<35} {'Control':>8} {'Treated':>8} {'Diff':>8}")
    print(f"     {'-'*61}")
    for qt, label in query_labels.items():
        c = [r for r in control if r["query_id"] == qt]
        t = [r for r in treated if r["query_id"] == qt]
        cr = sum(int(r["OfficialCited"]) for r in c) / len(c)
        tr = sum(int(r["OfficialCited"]) for r in t) / len(t)
        d = tr - cr
        marker = " ***" if abs(d) >= 0.20 else " **" if abs(d) >= 0.10 else ""
        print(f"     {label:<35} {cr:>7.1%} {tr:>7.1%} {d:>+7.1%}{marker}")
    print(f"     (*** >= 20pp, ** >= 10pp)")

    # ── 5. Pair-level ──
    pairs = sorted(set(r["pair_id"] for r in rows), key=int)
    print(f"\n  5. Pair-level results (30 matched pairs)")
    print()
    print(f"     {'Pair':>4} {'C_ticker':>8} {'C_rate':>8} {'T_ticker':>8} {'T_rate':>8} {'Winner':>10}")
    print(f"     {'-'*56}")
    wins_c = wins_t = ties = 0
    for p in pairs:
        c = [r for r in control if r["pair_id"] == p]
        t = [r for r in treated if r["pair_id"] == p]
        cr = sum(int(r["OfficialCited"]) for r in c) / len(c)
        tr = sum(int(r["OfficialCited"]) for r in t) / len(t)
        c_tick = c[0]["ticker"]
        t_tick = t[0]["ticker"]
        if cr > tr:
            winner = "Control"
            wins_c += 1
        elif tr > cr:
            winner = "Treated"
            wins_t += 1
        else:
            winner = "Tie"
            ties += 1
        print(f"     {p:>4} {c_tick:>8} {cr:>7.0%} {t_tick:>8} {tr:>7.0%} {winner:>10}")

    print(f"\n     Summary: Control wins {wins_c}, Treated wins {wins_t}, Ties {ties}")
    print(f"     Sign test: {wins_c}/{wins_c+wins_t} non-tied pairs favor control ({wins_c/(wins_c+wins_t):.0%})")

    all_platform_stats[platform] = {
        "c_rate": c_rate, "t_rate": t_rate, "diff": diff,
        "c_avg_rank": c_avg_rank, "t_avg_rank": t_avg_rank,
        "c_avg_src": c_avg_src, "t_avg_src": t_avg_src,
        "wins_c": wins_c, "wins_t": wins_t, "ties": ties,
    }


# ══════════════════════════════════════════════════════════════════════════
# CROSS-PLATFORM COMPARISON
# ══════════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("  CROSS-PLATFORM COMPARISON")
print("=" * 70)

print(f"\n  OfficialCited rate:")
print(f"  {'Platform':<35} {'Control':>8} {'Treated':>8} {'Gap':>8} {'Sign test':>12}")
print(f"  {'-'*73}")
for p, s in all_platform_stats.items():
    sign = f"{s['wins_c']}/{s['wins_c']+s['wins_t']} ({s['wins_c']/(s['wins_c']+s['wins_t']):.0%})"
    print(f"  {p:<35} {s['c_rate']:>7.1%} {s['t_rate']:>7.1%} {s['diff']:>+7.1%} {sign:>12}")

print(f"\n  Average sources per query:")
print(f"  {'Platform':<35} {'Control':>8} {'Treated':>8}")
print(f"  {'-'*53}")
for p, s in all_platform_stats.items():
    print(f"  {p:<35} {s['c_avg_src']:>7.1f} {s['t_avg_src']:>7.1f}")


# ══════════════════════════════════════════════════════════════════════════
# MECHANISM INTERPRETATION
# ══════════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("  MECHANISM INTERPRETATION")
print("=" * 70)

print("""
  Hypothesis (Layer 1 Mechanism):
  -----------------------------------------------------------------------
  Firms whose robots.txt blocks AI search crawlers from public pages
  (search_public_block = 1) will have LOWER official website visibility
  in AI search results, compared to matched control firms
  (search_public_block = 0).

  This is the first-stage mechanism: blocking -> reduced citation.
  Without this, the downstream effect on investor information
  environment has no channel.

  Variables and evidence:
  -----------------------------------------------------------------------

  1. OfficialCited (0/1) — PRIMARY OUTCOME
     -> SUPPORTS mechanism on ChatGPT and Gemini.
        ChatGPT: Control 65.3% vs Treated 52.7% (gap: -12.7 pp)
        Gemini:  Control 77.3% vs Treated 66.0% (gap: -11.3 pp)
     -> WEAK on Claude.
        Claude:  Control 81.3% vs Treated 77.3% (gap: -4.0 pp)
        Claude uses Brave Search, which may rely more on cached/indexed
        content and less on real-time crawling, reducing robots.txt impact.
        Also, Claude returns many more sources per query (~9), increasing
        the baseline probability of citing the official site.

  2. OfficialRank (position among cited domains) — SECONDARY
     -> INCONCLUSIVE across all platforms.
        When treated firms ARE cited, their rank is similar to control.
        This suggests blocking is mostly an extensive-margin effect
        (cited vs. not cited), not intensive-margin (cited later).

  3. n_cited_sources (total unique domains) — BALANCE CHECK
     -> NO MEANINGFUL DIFFERENCE within each platform.
        ChatGPT: ~2 sources (both groups)
        Gemini:  ~4 sources (both groups)
        Claude:  ~9 sources (both groups)
        AI search does not cite fewer sources overall for treated firms;
        it specifically substitutes away from the official site.

  4. Pair-level sign test — ROBUSTNESS
     -> SUPPORTS mechanism on ChatGPT and Gemini.
        ChatGPT: 62% of non-tied pairs favor control
        Gemini:  64% of non-tied pairs favor control
     -> Check Claude pair-level results in output above.

  5. By query type — HETEROGENEITY
     -> ChatGPT: strongest for Q1 (what does, -27pp) and Q5 (news, -23pp)
        Gemini:  strongest for Q2 (financials, -23pp) and Q5 (news, -13pp)
        Q5 (recent news) shows a gap on ChatGPT and Gemini — logical
        because news queries rely most on real-time web crawling.
        Q3 (investor relations) gap is moderate (-10pp on both).

  Overall assessment:
  -----------------------------------------------------------------------
  The pilot provides DIRECTIONAL SUPPORT for the Layer 1 mechanism.
  The effect is consistent across ChatGPT (Bing) and Gemini (Google),
  with an 11-13 pp gap in official site citation rates. Claude (Brave)
  shows a smaller gap (4 pp), possibly because Brave Search is less
  sensitive to robots.txt restrictions.

  The pilot (n=60 firms, 30 pairs) lacks power for statistical
  significance. The full-sample regression (n=2,823) should be
  sufficiently powered if the true effect is in this range.

  Cross-platform consistency (2 of 3 platforms show >10pp gap)
  strengthens the mechanism claim considerably.
""")
