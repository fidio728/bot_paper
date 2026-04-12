"""Merge three platform CSVs into one panel and construct regression variables."""
import csv
from pathlib import Path

BASE = Path(__file__).parent
SAMPLE = BASE.parent / "stata" / "stata-mcp-folder" / "stata-mcp-result" / "pilot_sample.csv"

sources = {
    "chatgpt": ("ChatGPT", "Bing", BASE / "pilot_recording_sheet_filled.csv"),
    "gemini":  ("Gemini",  "Google", BASE / "pilot_recording_sheet_gemini.csv"),
    "claude":  ("Claude",  "Brave",  BASE / "Claude" / "claude.csv"),
}

# Load firm-level controls from pilot_sample.csv
firm_controls = {}
with open(SAMPLE, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        key = r["ticker"]
        firm_controls[key] = {
            "log_at": r["log_at_2024"],
            "roa": r["roa_2024"],
            "leverage": r["leverage_2024"],
            "intan_ratio": r["intan_ratio_2024"],
            "log_mkcap": r["log_mkcap_2024"],
            "search_intensity": r["search_intensity"],
            "sic2": r["sic2"],
            "size_tercile": r["size_tercile"],
            "gvkey": r["gvkey"],
        }

all_rows = []
for platform_id, (platform_name, search_engine, path) in sources.items():
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["platform"] = platform_name
            r["search_engine"] = search_engine

            # ── Construct regression variables ──

            # 1. treated (binary): same as search_public_block
            r["treated"] = int(r["search_public_block"])

            # 2. official_cited (binary): primary DV
            r["official_cited"] = int(r["OfficialCited"])

            # 3. official_rank_inv: inverse rank (higher = better visibility)
            #    rank=1 -> 1.0, rank=2 -> 0.5, rank=999 -> 0
            rank = int(r["OfficialRank"])
            r["official_rank_inv"] = round(1.0 / rank, 4) if rank < 999 else 0

            # 4. official_rank_top3: cited in top 3 domains (binary)
            r["official_rank_top3"] = 1 if rank <= 3 else 0

            # 5. n_sources: total unique domains cited
            r["n_sources"] = int(r["n_cited_sources"])

            # 6. query_type dummies
            qid = r["query_id"]
            for qt in ["Q1_what_does", "Q2_financial_performance",
                        "Q3_investor_relations", "Q4_management_team",
                        "Q5_recent_news"]:
                r[f"is_{qt}"] = 1 if qid == qt else 0

            # 7. query number (1-5)
            r["query_num"] = int(qid[1])

            # 8. platform dummies
            for pid in sources:
                pname = sources[pid][0]
                r[f"is_{pname}"] = 1 if platform_name == pname else 0

            # 9. firm-level controls from pilot_sample.csv
            fc = firm_controls.get(r["ticker"], {})
            r["log_at"] = fc.get("log_at", "")
            r["roa"] = fc.get("roa", "")
            r["leverage"] = fc.get("leverage", "")
            r["intan_ratio"] = fc.get("intan_ratio", "")
            r["log_mkcap"] = fc.get("log_mkcap", "")
            r["search_intensity"] = fc.get("search_intensity", "")
            r["sic2"] = fc.get("sic2", "")
            r["size_tercile"] = fc.get("size_tercile", "")
            r["gvkey"] = fc.get("gvkey", "")

            all_rows.append(r)

# ── Output ──
out_path = BASE / "pilot_panel.csv"
fieldnames = [
    # identifiers
    "pair_id", "pilot_group", "firm", "ticker", "host", "gvkey",
    "platform", "search_engine",
    # treatment
    "treated", "search_public_block", "search_intensity",
    # outcomes
    "official_cited", "OfficialRank", "official_rank_inv", "official_rank_top3",
    "OfficialListed", "n_sources",
    # firm-level controls
    "log_at", "roa", "leverage", "intan_ratio", "log_mkcap",
    "sic2", "size_tercile",
    # query info
    "query_id", "query_num", "prompt",
    # query dummies
    "is_Q1_what_does", "is_Q2_financial_performance",
    "is_Q3_investor_relations", "is_Q4_management_team", "is_Q5_recent_news",
    # platform dummies
    "is_ChatGPT", "is_Gemini", "is_Claude",
    # raw
    "source_domains", "timestamp", "notes",
]

with open(out_path, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(all_rows)

print(f"Saved: {out_path}")
print(f"Total rows: {len(all_rows)} (300 queries x 3 platforms)")
print(f"Columns: {len(fieldnames)}")

# Quick check
treated = [r for r in all_rows if r["treated"] == 1]
control = [r for r in all_rows if r["treated"] == 0]
print(f"\nTreated: {len(treated)} obs, Control: {len(control)} obs")
print(f"OfficialCited — Control: {sum(r['official_cited'] for r in control)/len(control):.1%}, "
      f"Treated: {sum(r['official_cited'] for r in treated)/len(treated):.1%}")
