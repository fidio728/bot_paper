"""Quick analysis of pilot test results."""
import csv
from collections import defaultdict
from pathlib import Path

SHEET = Path(__file__).parent / "pilot_recording_sheet_filled.csv"

with open(SHEET, encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

# ── Overall ────────────────────────────────────────────────────────────
control = [r for r in rows if r["pilot_group"] == "control"]
treated = [r for r in rows if r["pilot_group"] == "treated"]

def stats(group, label):
    n = len(group)
    cited = sum(int(r["OfficialCited"]) for r in group)
    ranks = [int(r["OfficialRank"]) for r in group if int(r["OfficialRank"]) < 999]
    avg_rank = sum(ranks) / len(ranks) if ranks else float("nan")
    n_src = [int(r["n_cited_sources"]) for r in group]
    avg_src = sum(n_src) / len(n_src)
    print(f"  {label}: OfficialCited={cited}/{n} ({cited/n:.1%}), "
          f"AvgRank={avg_rank:.2f} (when cited), AvgSources={avg_src:.1f}")

print("=== Overall ===")
stats(control, "Control")
stats(treated, "Treated")

# ── By query type ──────────────────────────────────────────────────────
print("\n=== By query type ===")
query_types = ["Q1_what_does", "Q2_financial_performance", "Q3_investor_relations",
               "Q4_management_team", "Q5_recent_news"]

print(f"{'Query':<28} {'Control':>10} {'Treated':>10} {'Diff':>10}")
print("-" * 60)
for qt in query_types:
    c = [r for r in control if r["query_id"] == qt]
    t = [r for r in treated if r["query_id"] == qt]
    c_rate = sum(int(r["OfficialCited"]) for r in c) / len(c)
    t_rate = sum(int(r["OfficialCited"]) for r in t) / len(t)
    diff = t_rate - c_rate
    print(f"  {qt:<26} {c_rate:>9.1%} {t_rate:>9.1%} {diff:>+9.1%}")

# ── By pair ────────────────────────────────────────────────────────────
print("\n=== By pair (OfficialCited rate) ===")
pairs = sorted(set(r["pair_id"] for r in rows), key=int)
print(f"{'Pair':>4} {'Control':>12} {'Treated':>12} {'C_ticker':>10} {'T_ticker':>10}")
print("-" * 60)
wins_c = wins_t = ties = 0
for p in pairs:
    c = [r for r in control if r["pair_id"] == p]
    t = [r for r in treated if r["pair_id"] == p]
    c_rate = sum(int(r["OfficialCited"]) for r in c) / len(c)
    t_rate = sum(int(r["OfficialCited"]) for r in t) / len(t)
    c_tick = c[0]["ticker"]
    t_tick = t[0]["ticker"]
    print(f"  {p:>2}  {c_rate:>10.0%}   {t_rate:>10.0%}    {c_tick:>8}  {t_tick:>8}")
    if c_rate > t_rate:
        wins_c += 1
    elif t_rate > c_rate:
        wins_t += 1
    else:
        ties += 1

print(f"\nPair-level: Control wins {wins_c}, Treated wins {wins_t}, Ties {ties}")
print(f"Sign test: {wins_c}/{wins_c+wins_t} pairs show control > treated")
