"""
05_merge_firm_panel.py — Map hosts to firms, aggregate to firm-level panel.

Input:  robots_panel_monthly.csv, compustat_2025_clean.csv
Output: firm_panel_monthly.csv, firm_treatment_timing.csv, panel_summary.csv
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PANEL_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("D:/anoconda/bot_paper_data")
PANEL_CSV = DATA_DIR / "robots_panel_monthly.csv"
INPUT_CSV = PROJECT_ROOT / "compustat_2025_clean.csv"
HOST_TIMING_CSV = PANEL_DIR / "treatment_timing.csv"
FIRM_PANEL_CSV = PANEL_DIR / "firm_panel_monthly.csv"
FIRM_TIMING_CSV = PANEL_DIR / "firm_treatment_timing.csv"
SUMMARY_CSV = PANEL_DIR / "panel_summary.csv"

SEARCH_BOTS = {"OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"}
TRAINING_BOTS = {"GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "Meta-ExternalAgent"}
# 8 treatment bots (training + search)
TREATMENT_BOTS = SEARCH_BOTS | TRAINING_BOTS


def load_host_to_gvkeys():
    """Load host_clean -> list of gvkeys mapping."""
    h2g = defaultdict(set)
    with open(INPUT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            host = row.get("host_clean", "").strip()
            gvkey = row.get("gvkey", "").strip()
            # Match 01_query_cdx.py filter: skip empty, nan, no-dot
            if not host or host.lower() == "nan" or "." not in host:
                continue
            if not gvkey:
                continue
            h2g[host].add(gvkey)
    return h2g


def main():
    host_to_gvkeys = load_host_to_gvkeys()
    print(f"Host-to-gvkey mappings: {len(host_to_gvkeys)} hosts -> "
          f"{sum(len(v) for v in host_to_gvkeys.values())} firm-host pairs")

    # Read bot-level panel, aggregate per host × month
    # We need: for each host × month, the bot-level data
    host_month_bots = defaultdict(dict)  # (host, ym) -> {bot: {root_block, blocked_any, specific_rule}}
    host_month_status = {}  # (host, ym) -> fetch_status

    with open(PANEL_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            host = row["host"]
            ym = row["year_month"]
            bot = row["bot"]
            key = (host, ym)

            if row["fetch_status"] == "no_snapshot":
                host_month_status[key] = "no_snapshot"
            elif row["fetch_status"] in ("archived_http_error", "archived_redirect", "content_missing"):
                # All non-200 statuses with no usable content → missing
                if key not in host_month_status:
                    host_month_status[key] = "error"
            else:
                host_month_status[key] = "ok"

            if row["root_block"] == "NA":
                continue

            host_month_bots[key][bot] = {
                "root_block": int(row["root_block"]),
                "blocked_any": int(row["blocked_any"]),
                "specific_rule": int(row["specific_rule"]),
            }

    print(f"Host × month cells with bot data: {len(host_month_bots)}")

    # Build firm panel
    firm_rows = []
    # Track per gvkey for timing
    gvkey_month_data = defaultdict(dict)  # gvkey -> {ym -> row_dict}

    # Get all year_months
    all_yms = sorted(set(ym for _, ym in host_month_status.keys()))

    for host, gvkeys in sorted(host_to_gvkeys.items()):
        for ym in all_yms:
            key = (host, ym)
            status = host_month_status.get(key, "no_snapshot")
            bots = host_month_bots.get(key, {})

            if not bots:
                # No observable data
                row_data = {
                    "host": host, "year_month": ym,
                    "any_block": "NA", "search_block": "NA",
                    "search_full_block": "NA", "search_block_specific": "NA",
                    "training_block": "NA",
                    "n_search_root_blocked": "NA", "n_training_root_blocked": "NA",
                    "fetch_status": status,
                }
            else:
                # Tier 0: any of 8 treatment bots has blocked_any=1
                any_block = 1 if any(
                    bots.get(b, {}).get("blocked_any", 0) for b in TREATMENT_BOTS if b in bots
                ) else 0

                # Tier 1: any of 3 search bots has blocked_any=1
                search_block = 1 if any(
                    bots.get(b, {}).get("blocked_any", 0) for b in SEARCH_BOTS if b in bots
                ) else 0

                # search_full_block: all 3 search bots root-blocked
                search_root = [bots.get(b, {}).get("root_block", 0) for b in SEARCH_BOTS if b in bots]
                search_full_block = 1 if len(search_root) == 3 and all(r == 1 for r in search_root) else 0

                # search_block_specific: any search bot blocked via specific rule
                search_block_specific = 1 if any(
                    bots.get(b, {}).get("specific_rule", 0) and bots.get(b, {}).get("blocked_any", 0)
                    for b in SEARCH_BOTS if b in bots
                ) else 0

                # training_block: any training bot root-blocked
                training_block = 1 if any(
                    bots.get(b, {}).get("root_block", 0) for b in TRAINING_BOTS if b in bots
                ) else 0

                n_search_root = sum(bots.get(b, {}).get("root_block", 0) for b in SEARCH_BOTS if b in bots)
                n_training_root = sum(bots.get(b, {}).get("root_block", 0) for b in TRAINING_BOTS if b in bots)

                row_data = {
                    "host": host, "year_month": ym,
                    "any_block": any_block, "search_block": search_block,
                    "search_full_block": search_full_block,
                    "search_block_specific": search_block_specific,
                    "training_block": training_block,
                    "n_search_root_blocked": n_search_root,
                    "n_training_root_blocked": n_training_root,
                    "fetch_status": status,
                }

            for gvkey in sorted(gvkeys):
                firm_row = {"gvkey": gvkey}
                firm_row.update(row_data)
                firm_rows.append(firm_row)
                gvkey_month_data[gvkey][ym] = row_data

    # Write firm panel
    firm_fields = [
        "gvkey", "host", "year_month",
        "any_block", "search_block", "search_full_block",
        "search_block_specific", "training_block",
        "n_search_root_blocked", "n_training_root_blocked",
        "fetch_status",
    ]
    with open(FIRM_PANEL_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=firm_fields)
        writer.writeheader()
        writer.writerows(firm_rows)
    print(f"\nWrote {FIRM_PANEL_CSV}: {len(firm_rows)} rows")

    # === Firm treatment timing (gvkey × bot + search-level onset) ===
    # Part A: Read host-level treatment_timing.csv and join with gvkey
    host_timing = []
    with open(HOST_TIMING_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            host_timing.append(row)

    # Build bot-level rows: one per gvkey × bot
    firm_timing_bot_rows = []
    for ht_row in host_timing:
        host = ht_row["host"]
        gvkeys = host_to_gvkeys.get(host, set())
        for gvkey in sorted(gvkeys):
            r = {"gvkey": gvkey}
            r.update(ht_row)
            firm_timing_bot_rows.append(r)

    # Part B: Search-level aggregated onset per gvkey (one row per gvkey)
    firm_onset_rows = []
    for gvkey in sorted(gvkey_month_data.keys()):
        months = gvkey_month_data[gvkey]
        yms = sorted(months.keys())

        first_search_block = "NA"
        first_search_full = "NA"
        first_search_specific = "NA"
        first_any_block = "NA"

        for ym in yms:
            d = months[ym]
            if d["search_block"] != "NA" and int(d["search_block"]) == 1 and first_search_block == "NA":
                first_search_block = ym
            if d["search_full_block"] != "NA" and int(d["search_full_block"]) == 1 and first_search_full == "NA":
                first_search_full = ym
            if d["search_block_specific"] != "NA" and int(d["search_block_specific"]) == 1 and first_search_specific == "NA":
                first_search_specific = ym
            if d["any_block"] != "NA" and int(d["any_block"]) == 1 and first_any_block == "NA":
                first_any_block = ym

        host = months[yms[0]]["host"] if yms else "NA"
        firm_onset_rows.append({
            "gvkey": gvkey, "host": host,
            "first_month_search_block": first_search_block,
            "first_month_search_full_block": first_search_full,
            "first_month_search_block_specific": first_search_specific,
            "first_month_any_block": first_any_block,
        })

    # Write both parts to firm_treatment_timing.csv:
    # Bot-level rows first, then a blank separator concept via "type" column
    timing_bot_fields = [
        "gvkey", "host", "bot", "bot_group",
        "first_month_mentioned", "first_month_root_blocked",
        "first_month_any_restriction", "last_month_root_blocked",
        "never_root_blocked", "always_root_blocked",
        "switcher_root", "switcher_any", "n_months_observed",
    ]
    timing_onset_fields = [
        "gvkey", "host",
        "first_month_search_block", "first_month_search_full_block",
        "first_month_search_block_specific", "first_month_any_block",
    ]

    # Write bot-level file
    bot_timing_path = PANEL_DIR / "firm_treatment_timing_bot.csv"
    with open(bot_timing_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=timing_bot_fields)
        writer.writeheader()
        writer.writerows(firm_timing_bot_rows)
    print(f"Wrote {bot_timing_path}: {len(firm_timing_bot_rows)} rows (gvkey × bot)")

    # Write search-level onset file
    with open(FIRM_TIMING_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=timing_onset_fields)
        writer.writeheader()
        writer.writerows(firm_onset_rows)
    print(f"Wrote {FIRM_TIMING_CSV}: {len(firm_onset_rows)} rows (gvkey search-level onset)")

    # === Summary stats ===
    total_obs = len(firm_rows)
    with_data = sum(1 for r in firm_rows if r["fetch_status"] == "ok")

    # Switcher analysis at firm level
    firms_switched_search = 0
    firms_switched_any = 0
    always_allow = 0
    always_block = 0
    firms_pre_post = 0

    for gvkey in sorted(gvkey_month_data.keys()):
        months = gvkey_month_data[gvkey]
        yms = sorted(months.keys())

        search_vals = [int(months[ym]["search_block"]) for ym in yms
                       if months[ym]["search_block"] != "NA"]
        any_vals = [int(months[ym]["any_block"]) for ym in yms
                    if months[ym]["any_block"] != "NA"]

        if search_vals and len(set(search_vals)) > 1:
            firms_switched_search += 1
        if any_vals and len(set(any_vals)) > 1:
            firms_switched_any += 1

        if any_vals and all(v == 0 for v in any_vals):
            always_allow += 1
        if any_vals and all(v == 1 for v in any_vals):
            always_block += 1

        observed_yms = [ym for ym in yms if months[ym]["any_block"] != "NA"]
        has_pre = any(ym < "2023-08" for ym in observed_yms)
        has_post = any(ym >= "2023-08" for ym in observed_yms)
        if has_pre and has_post:
            firms_pre_post += 1

    print(f"\n=== Panel Summary ===")
    print(f"Total firm × month observations: {total_obs}")
    print(f"With data: {with_data}")
    print(f"Firms that switched (search_block): {firms_switched_search}")
    print(f"Firms that switched (any_block): {firms_switched_any}")
    print(f"Always-allow: {always_allow}")
    print(f"Always-block: {always_block}")
    print(f"Firms with pre+post 2023.08: {firms_pre_post}")

    # Write summary
    summary = [
        {"metric": "total_firm_month_obs", "value": total_obs},
        {"metric": "with_data", "value": with_data},
        {"metric": "firms_switched_search_block", "value": firms_switched_search},
        {"metric": "firms_switched_any_block", "value": firms_switched_any},
        {"metric": "always_allow", "value": always_allow},
        {"metric": "always_block", "value": always_block},
        {"metric": "firms_pre_post_202308", "value": firms_pre_post},
    ]
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        writer.writerows(summary)
    print(f"Wrote {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
