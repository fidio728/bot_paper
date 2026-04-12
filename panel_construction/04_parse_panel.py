"""
04_parse_panel.py — Parse robots.txt content and build the raw bot-level panel.

For each host × month × bot, classify blocking status using the shared parser.
Also computes treatment_timing.csv and policy_changes.csv.

Input:  monthly_snapshots.csv, robots_content.json
Output: robots_panel_monthly.csv, treatment_timing.csv, policy_changes.csv
"""

import json
import csv
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from robots_parser import parse_robots, classify_bot, get_applicable_rules

PANEL_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("D:/anoconda/bot_paper_data")
MONTHLY_CSV = DATA_DIR / "monthly_snapshots.csv"
CONTENT_JSON = DATA_DIR / "robots_content.json"
PANEL_CSV = DATA_DIR / "robots_panel_monthly.csv"
TIMING_CSV = PANEL_DIR / "treatment_timing.csv"
CHANGES_CSV = PANEL_DIR / "policy_changes.csv"

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

PANEL_FIELDS = [
    "host", "year_month", "snapshot_timestamp", "snapshot_date",
    "bot", "bot_group", "fetch_status", "http_status", "robots_hash",
    "root_block", "has_nonroot_disallow", "blocked_any",
    "specific_rule", "effective_source", "n_disallow_rules",
]


def make_na_row(host, year_month, ts, snapshot_date, bot, bot_group, fetch_status, http_status, digest):
    """Create a row with NA for all bot classification fields."""
    return {
        "host": host, "year_month": year_month,
        "snapshot_timestamp": ts, "snapshot_date": snapshot_date,
        "bot": bot, "bot_group": bot_group,
        "fetch_status": fetch_status, "http_status": http_status,
        "robots_hash": digest,
        "root_block": "NA", "has_nonroot_disallow": "NA",
        "blocked_any": "NA", "specific_rule": "NA",
        "effective_source": "NA", "n_disallow_rules": "NA",
    }


def make_allow_row(host, year_month, ts, snapshot_date, bot, bot_group, http_status, digest):
    """Create a row for no_robots_file (404/410 = allow-all per RFC 9309)."""
    return {
        "host": host, "year_month": year_month,
        "snapshot_timestamp": ts, "snapshot_date": snapshot_date,
        "bot": bot, "bot_group": bot_group,
        "fetch_status": "no_robots_file", "http_status": http_status,
        "robots_hash": digest,
        "root_block": 0, "has_nonroot_disallow": 0,
        "blocked_any": 0, "specific_rule": 0,
        "effective_source": "no_robots_file", "n_disallow_rules": 0,
    }


def build_panel():
    """Build the full bot-level panel."""
    # Load content
    with open(CONTENT_JSON, "r", encoding="utf-8") as f:
        content_data = json.load(f)
    # Remove internal tracking keys
    content_data.pop("__failed_digests__", None)
    content_data.pop("__retry_counts__", None)

    print(f"Loaded {len(content_data)} unique digests with content")

    # Parse all unique content once (cache)
    parsed_cache = {}
    for digest, text in content_data.items():
        parsed_cache[digest] = parse_robots(text)

    print(f"Parsed {len(parsed_cache)} unique robots.txt files")

    # Read monthly snapshots
    with open(MONTHLY_CSV, "r", encoding="utf-8") as f:
        monthly_rows = list(csv.DictReader(f))

    print(f"Monthly snapshot rows: {len(monthly_rows)}")

    panel_rows = []
    status_counts = defaultdict(int)

    for snap in monthly_rows:
        host = snap["host"]
        year_month = snap["year_month"]
        ts = snap["snapshot_timestamp"]
        digest = snap["digest"]
        has_snapshot = int(snap["has_snapshot"])
        statuscode = snap["statuscode"]

        snapshot_date = "NA"
        if ts != "NA" and len(ts) >= 8:
            snapshot_date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"

        for bot_name, bot_info in BOT_TAXONOMY.items():
            bot_group = bot_info["group"]
            aliases = bot_info["aliases"]

            if not has_snapshot:
                # No Wayback snapshot for this month
                row = make_na_row(host, year_month, "NA", "NA", bot_name, bot_group,
                                  "no_snapshot", "NA", "NA")
                status_counts["no_snapshot"] += 1

            elif statuscode in ("404", "410"):
                # Host exists but no robots.txt → allow-all
                row = make_allow_row(host, year_month, ts, snapshot_date,
                                     bot_name, bot_group, statuscode, digest)
                status_counts["no_robots_file"] += 1

            elif statuscode == "200":
                if digest in parsed_cache:
                    groups = parsed_cache[digest]
                    cls = classify_bot(groups, bot_name, aliases)
                    rules, _, _ = get_applicable_rules(groups, aliases)
                    n_disallow = sum(1 for d, _ in rules if d == "disallow")
                    blocked_any = 1 if (cls["root_block"] or cls["has_nonroot_disallow"]) else 0

                    row = {
                        "host": host, "year_month": year_month,
                        "snapshot_timestamp": ts, "snapshot_date": snapshot_date,
                        "bot": bot_name, "bot_group": bot_group,
                        "fetch_status": "ok_200", "http_status": statuscode,
                        "robots_hash": digest,
                        "root_block": cls["root_block"],
                        "has_nonroot_disallow": cls["has_nonroot_disallow"],
                        "blocked_any": blocked_any,
                        "specific_rule": cls["specific_rule"],
                        "effective_source": cls["effective_source"],
                        "n_disallow_rules": n_disallow,
                    }
                    status_counts["ok_200"] += 1
                else:
                    # Content not downloaded
                    row = make_na_row(host, year_month, ts, snapshot_date, bot_name, bot_group,
                                      "content_missing", statuscode, digest)
                    status_counts["content_missing"] += 1

            elif statuscode and statuscode.startswith("3"):
                # 3xx redirect — common for http->https or naked->www.
                # The redirect target may have valid robots.txt but we don't
                # have the content here. Mark separately for transparency.
                row = make_na_row(host, year_month, ts, snapshot_date, bot_name, bot_group,
                                  "archived_redirect", statuscode, digest)
                status_counts["archived_redirect"] += 1

            else:
                # Other HTTP status (5xx, etc.)
                row = make_na_row(host, year_month, ts, snapshot_date, bot_name, bot_group,
                                  "archived_http_error", statuscode, digest)
                status_counts["archived_http_error"] += 1

            panel_rows.append(row)

    print(f"\nPanel rows: {len(panel_rows)}")
    print("Status distribution (bot-level rows):")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Report redirect scale separately for decision-making
    n_redirect = status_counts.get("archived_redirect", 0)
    if n_redirect > 0:
        redirect_hosts = set()
        for row in panel_rows:
            if row["fetch_status"] == "archived_redirect":
                redirect_hosts.add(row["host"])
        redirect_pct = 100 * n_redirect / len(panel_rows) if panel_rows else 0
        print(f"\n>>> 3xx redirects: {n_redirect} bot-rows ({redirect_pct:.1f}%) across {len(redirect_hosts)} hosts")
        print(f">>> These months are treated as missing. If this is large,")
        print(f">>> consider following redirects in 03_download_content.py.")

    return panel_rows


def compute_treatment_timing(panel_rows):
    """Compute treatment_timing.csv from the panel."""
    # Index: (host, bot) -> list of (year_month, root_block, blocked_any, specific_rule)
    bot_series = defaultdict(list)

    for row in panel_rows:
        if row["root_block"] == "NA":
            continue
        key = (row["host"], row["bot"])
        bot_series[key].append({
            "year_month": row["year_month"],
            "root_block": int(row["root_block"]),
            "blocked_any": int(row["blocked_any"]),
            "specific_rule": int(row["specific_rule"]),
        })

    timing_rows = []

    # Get all unique (host, bot) combos including those with no observations
    all_keys = set()
    for row in panel_rows:
        all_keys.add((row["host"], row["bot"]))

    for (host, bot) in sorted(all_keys):
        bot_group = BOT_TAXONOMY[bot]["group"]
        obs = bot_series.get((host, bot), [])
        obs.sort(key=lambda x: x["year_month"])

        n_observed = len(obs)

        if n_observed == 0:
            timing_rows.append({
                "host": host, "bot": bot, "bot_group": bot_group,
                "first_month_mentioned": "NA",
                "first_month_root_blocked": "NA",
                "first_month_any_restriction": "NA",
                "last_month_root_blocked": "NA",
                "never_root_blocked": "NA",
                "always_root_blocked": "NA",
                "switcher_root": "NA",
                "switcher_any": "NA",
                "n_months_observed": 0,
            })
            continue

        first_mentioned = next((o["year_month"] for o in obs if o["specific_rule"] == 1), "NA")
        first_root = next((o["year_month"] for o in obs if o["root_block"] == 1), "NA")
        first_any = next((o["year_month"] for o in obs if o["blocked_any"] == 1), "NA")

        root_blocks = [o["root_block"] for o in obs]
        any_blocks = [o["blocked_any"] for o in obs]

        last_root = "NA"
        for o in reversed(obs):
            if o["root_block"] == 1:
                last_root = o["year_month"]
                break

        never_root = 1 if all(r == 0 for r in root_blocks) else 0
        always_root = 1 if all(r == 1 for r in root_blocks) else 0

        switcher_root = 1 if len(set(root_blocks)) > 1 else 0
        switcher_any = 1 if len(set(any_blocks)) > 1 else 0

        timing_rows.append({
            "host": host, "bot": bot, "bot_group": bot_group,
            "first_month_mentioned": first_mentioned,
            "first_month_root_blocked": first_root,
            "first_month_any_restriction": first_any,
            "last_month_root_blocked": last_root,
            "never_root_blocked": never_root,
            "always_root_blocked": always_root,
            "switcher_root": switcher_root,
            "switcher_any": switcher_any,
            "n_months_observed": n_observed,
        })

    return timing_rows


def compute_policy_changes(panel_rows):
    """Compute policy_changes.csv: track transitions in root_block and specific_rule."""
    # Index: (host, bot) -> sorted list of (year_month, root_block, blocked_any, specific_rule)
    bot_series = defaultdict(list)

    for row in panel_rows:
        if row["root_block"] == "NA":
            continue
        key = (row["host"], row["bot"])
        bot_series[key].append({
            "year_month": row["year_month"],
            "root_block": int(row["root_block"]),
            "blocked_any": int(row["blocked_any"]),
            "specific_rule": int(row["specific_rule"]),
        })

    changes = []

    for (host, bot), obs in sorted(bot_series.items()):
        obs.sort(key=lambda x: x["year_month"])

        for i in range(len(obs)):
            curr = obs[i]

            if i == 0:
                # Check for first_mention
                if curr["specific_rule"] == 1:
                    changes.append({
                        "host": host, "bot": bot,
                        "year_month": curr["year_month"],
                        "prev_year_month": "NA",
                        "change_type": "first_mention",
                        "gap_months": "NA",
                        "timing_interval_censored": "NA",
                    })
                continue

            prev = obs[i - 1]

            # Compute gap
            py, pm = int(prev["year_month"][:4]), int(prev["year_month"][5:7])
            cy, cm = int(curr["year_month"][:4]), int(curr["year_month"][5:7])
            gap = (cy - py) * 12 + (cm - pm)
            censored = 1 if gap > 1 else 0

            # Check for specific rule first appearance
            if curr["specific_rule"] == 1 and prev["specific_rule"] == 0:
                changes.append({
                    "host": host, "bot": bot,
                    "year_month": curr["year_month"],
                    "prev_year_month": prev["year_month"],
                    "change_type": "first_mention",
                    "gap_months": gap,
                    "timing_interval_censored": censored,
                })

            # Root block transitions
            if curr["root_block"] == 1 and prev["root_block"] == 0:
                changes.append({
                    "host": host, "bot": bot,
                    "year_month": curr["year_month"],
                    "prev_year_month": prev["year_month"],
                    "change_type": "allow_to_root_block",
                    "gap_months": gap,
                    "timing_interval_censored": censored,
                })
            elif curr["root_block"] == 0 and prev["root_block"] == 1:
                changes.append({
                    "host": host, "bot": bot,
                    "year_month": curr["year_month"],
                    "prev_year_month": prev["year_month"],
                    "change_type": "root_block_to_allow",
                    "gap_months": gap,
                    "timing_interval_censored": censored,
                })

            # Non-root transitions (only if root_block didn't change)
            if curr["root_block"] == prev["root_block"]:
                if curr["blocked_any"] == 1 and prev["blocked_any"] == 0:
                    changes.append({
                        "host": host, "bot": bot,
                        "year_month": curr["year_month"],
                        "prev_year_month": prev["year_month"],
                        "change_type": "allow_to_nonroot",
                        "gap_months": gap,
                        "timing_interval_censored": censored,
                    })
                elif curr["blocked_any"] == 0 and prev["blocked_any"] == 1:
                    changes.append({
                        "host": host, "bot": bot,
                        "year_month": curr["year_month"],
                        "prev_year_month": prev["year_month"],
                        "change_type": "nonroot_to_allow",
                        "gap_months": gap,
                        "timing_interval_censored": censored,
                    })

    return changes


def main():
    panel_rows = build_panel()

    # Write panel
    with open(PANEL_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PANEL_FIELDS)
        writer.writeheader()
        writer.writerows(panel_rows)
    print(f"\nWrote {PANEL_CSV}")

    # Treatment timing
    timing = compute_treatment_timing(panel_rows)
    timing_fields = [
        "host", "bot", "bot_group",
        "first_month_mentioned", "first_month_root_blocked",
        "first_month_any_restriction", "last_month_root_blocked",
        "never_root_blocked", "always_root_blocked",
        "switcher_root", "switcher_any", "n_months_observed",
    ]
    with open(TIMING_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=timing_fields)
        writer.writeheader()
        writer.writerows(timing)
    print(f"Wrote {TIMING_CSV}")

    # Policy changes
    changes = compute_policy_changes(panel_rows)
    changes_fields = [
        "host", "bot", "year_month", "prev_year_month",
        "change_type", "gap_months", "timing_interval_censored",
    ]
    with open(CHANGES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=changes_fields)
        writer.writeheader()
        writer.writerows(changes)
    print(f"Wrote {CHANGES_CSV}")

    # === Switcher Analysis ===
    # Aggregate at host level for any_block and search_block
    host_month = defaultdict(lambda: defaultdict(dict))
    for row in panel_rows:
        if row["blocked_any"] == "NA":
            continue
        host_month[row["host"]][row["year_month"]][row["bot"]] = {
            "blocked_any": int(row["blocked_any"]),
            "specific_rule": int(row["specific_rule"]),
            "root_block": int(row["root_block"]),
        }

    SEARCH_BOTS = {"OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"}
    TREATMENT_BOTS = set(BOT_TAXONOMY.keys()) - {"Googlebot", "ChatGPT-User", "Perplexity-User", "Meta-ExternalFetcher"}

    # Build index of interval-censored transitions from policy_changes
    censored_hosts = set()  # hosts whose switch timing is uncertain
    for ch in changes:
        if ch["timing_interval_censored"] == 1:
            censored_hosts.add(ch["host"])

    any_block_switchers = 0
    any_block_switchers_precise = 0  # consecutive-month observations only
    search_block_switchers = 0
    search_block_switchers_precise = 0
    gptbot_specific_appeared = 0
    oai_search_specific_appeared = 0
    host_with_pre_post = 0

    for host in sorted(host_month.keys()):
        months_data = host_month[host]
        months_sorted = sorted(months_data.keys())

        any_block_series = []
        search_block_series = []

        for ym in months_sorted:
            bots = months_data[ym]
            ab = 1 if any(bots.get(b, {}).get("blocked_any", 0) for b in TREATMENT_BOTS if b in bots) else 0
            sb = 1 if any(bots.get(b, {}).get("blocked_any", 0) for b in SEARCH_BOTS if b in bots) else 0
            any_block_series.append(ab)
            search_block_series.append(sb)

        is_any_switcher = len(set(any_block_series)) > 1
        is_search_switcher = len(set(search_block_series)) > 1
        is_precisely_timed = host not in censored_hosts

        if is_any_switcher:
            any_block_switchers += 1
            if is_precisely_timed:
                any_block_switchers_precise += 1
        if is_search_switcher:
            search_block_switchers += 1
            if is_precisely_timed:
                search_block_switchers_precise += 1

        # GPTBot specific first appeared
        gpt_specific = [months_data[ym].get("GPTBot", {}).get("specific_rule", 0) for ym in months_sorted]
        if any(s == 1 for s in gpt_specific) and gpt_specific[0] == 0:
            gptbot_specific_appeared += 1

        # OAI-SearchBot specific first appeared
        oai_specific = [months_data[ym].get("OAI-SearchBot", {}).get("specific_rule", 0) for ym in months_sorted]
        if any(s == 1 for s in oai_specific) and oai_specific[0] == 0:
            oai_search_specific_appeared += 1

        # Pre+post around a switch
        has_pre = any(ym < "2023-08" for ym in months_sorted)
        has_post = any(ym >= "2023-08" for ym in months_sorted)
        if has_pre and has_post and is_any_switcher:
            host_with_pre_post += 1

    print(f"\n=== Switcher Analysis ===")
    print(f"Hosts where any_block changed:    {any_block_switchers} (precise timing: {any_block_switchers_precise})")
    print(f"Hosts where search_block changed: {search_block_switchers} (precise timing: {search_block_switchers_precise})")
    print(f"Hosts where GPTBot specific_rule first appeared: {gptbot_specific_appeared}")
    print(f"Hosts where OAI-SearchBot specific_rule first appeared: {oai_search_specific_appeared}")
    print(f"Hosts with pre+post around a switch: {host_with_pre_post}")
    if search_block_switchers < 200:
        print(">>> WARNING: <200 switchers for search_block. DID may be underpowered.")
    else:
        print(">>> Switcher count OK for DID.")
    if search_block_switchers_precise < 100:
        print(">>> WARNING: <100 precisely-timed search_block switchers. Event study timing may be noisy.")


if __name__ == "__main__":
    main()
