"""
scan_robots.py — Batch robots.txt scanner for Compustat firms.

Reads compustat_2025_clean.csv, scans robots.txt for each unique host,
parses per RFC 9309, and outputs:
  - robots_bot_panel.csv   (one row per firm x bot)
  - robots_firm_summary.csv (one row per firm)

Features:
  - Deduplicates by host (scans each unique host once)
  - Incremental checkpoint + output (resume-safe)
  - Distinct status types (ok_200, missing_404, timeout, etc.)
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Add current directory to path for robots_parser import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robots_parser import classify_bot, parse_robots

# ---------------------------------------------------------------------------
# Bot taxonomy
# ---------------------------------------------------------------------------

BOT_TAXONOMY = {
    # Training crawlers
    "GPTBot":              {"group": "training",  "aliases": ["gptbot"]},
    "ClaudeBot":           {"group": "training",  "aliases": ["claudebot"]},
    "Google-Extended":     {"group": "training",  "aliases": ["google-extended"]},
    "CCBot":               {"group": "training",  "aliases": ["ccbot"]},
    "Meta-ExternalAgent":  {"group": "training",  "aliases": ["meta-externalagent"]},
    # Search/index crawlers
    "OAI-SearchBot":       {"group": "search",    "aliases": ["oai-searchbot"]},
    "Claude-SearchBot":    {"group": "search",    "aliases": ["claude-searchbot"]},
    "PerplexityBot":       {"group": "search",    "aliases": ["perplexitybot"]},
    # User-triggered fetchers (may ignore robots.txt per official docs)
    "ChatGPT-User":        {"group": "user",      "aliases": ["chatgpt-user"]},
    "Perplexity-User":     {"group": "user",      "aliases": ["perplexity-user"]},
    "Meta-ExternalFetcher": {"group": "user",     "aliases": ["meta-externalfetcher"]},
    # Control (not AI)
    "Googlebot":           {"group": "control",   "aliases": ["googlebot"]},
}

TRAINING_BOTS = [b for b, v in BOT_TAXONOMY.items() if v["group"] == "training"]
SEARCH_BOTS = [b for b, v in BOT_TAXONOMY.items() if v["group"] == "search"]
USER_BOTS = [b for b, v in BOT_TAXONOMY.items() if v["group"] == "user"]
# Treatment denominator: training + search only. User-triggered bots are tracked
# separately because they may ignore robots.txt per official documentation.
TREATMENT_BOTS = TRAINING_BOTS + SEARCH_BOTS
AI_BOTS = [b for b, v in BOT_TAXONOMY.items() if v["group"] != "control"]

# ---------------------------------------------------------------------------
# HTTP config
# ---------------------------------------------------------------------------

UA_RESEARCH = "Mozilla/5.0 (compatible; AcademicResearchBot/1.0)"
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_CONTENT_BYTES = 1_000_000  # 1 MB cap on robots.txt

# ---------------------------------------------------------------------------
# Status type helpers
# ---------------------------------------------------------------------------

def classify_status_type(status_code, fetch_error):
    """Map HTTP result to robots_status_type."""
    if fetch_error:
        if "timeout" in fetch_error.lower():
            return "timeout"
        if "ssl" in fetch_error.lower():
            return "ssl_error"
        if "redirect" in fetch_error.lower():
            return "too_many_redirects"
        return "connection_error"
    if status_code is None:
        return "connection_error"
    if status_code == 200:
        return "ok_200"
    if status_code == 404:
        return "missing_404"
    if 400 <= status_code < 500:
        return "http_error_4xx"
    if 500 <= status_code < 600:
        return "http_error_5xx"
    return "http_error_other"


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_robots(host, timeout=15):
    """Fetch robots.txt from a host.

    Returns dict: status_code, content, final_url, fetch_error, ua_used.
    """
    https_url = f"https://{host}/robots.txt"
    http_url = f"http://{host}/robots.txt"
    https_failed_reason = None  # track why HTTPS failed, for auditing

    # --- HTTPS attempt ---
    for ua, ua_label in [(UA_RESEARCH, "research"), (UA_BROWSER, "browser")]:
        try:
            resp = requests.get(
                https_url,
                headers={"User-Agent": ua},
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code == 403 and ua_label == "research":
                continue  # retry with browser UA

            content = resp.text[:MAX_CONTENT_BYTES] if resp.status_code == 200 else ""
            return {
                "status_code": resp.status_code,
                "content": content,
                "final_url": resp.url,
                "fetch_error": "",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.SSLError:
            # Only SSL errors trigger HTTP fallback
            https_failed_reason = "ssl_error"
            break
        except requests.exceptions.Timeout:
            if ua_label == "research":
                continue
            # Timeout is NOT an SSL issue — do not fallback to HTTP
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": "timeout",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.TooManyRedirects:
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": "too_many_redirects",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.ConnectionError:
            # ConnectionError is ambiguous — do NOT fallback to HTTP
            # (could be DNS failure, firewall, temporary network issue)
            if ua_label == "research":
                continue
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": "connection_error",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.RequestException as e:
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": str(type(e).__name__),
                "ua_used": ua_label,
                "http_fallback": False,
            }

    # --- HTTP fallback (only after SSLError) ---
    if https_failed_reason == "ssl_error":
        for ua, ua_label in [(UA_RESEARCH, "research"), (UA_BROWSER, "browser")]:
            try:
                resp = requests.get(
                    http_url,
                    headers={"User-Agent": ua},
                    timeout=timeout,
                    allow_redirects=True,
                )
                if resp.status_code == 403 and ua_label == "research":
                    continue
                content = resp.text[:MAX_CONTENT_BYTES] if resp.status_code == 200 else ""
                return {
                    "status_code": resp.status_code,
                    "content": content,
                    "final_url": resp.url,
                    "fetch_error": "",
                    "ua_used": ua_label,
                    "http_fallback": True,
                }
            except requests.exceptions.Timeout:
                if ua_label == "research":
                    continue
                return {
                    "status_code": None,
                    "content": "",
                    "final_url": http_url,
                    "fetch_error": "timeout_after_ssl_fallback",
                    "ua_used": ua_label,
                    "http_fallback": True,
                }
            except requests.exceptions.RequestException as e:
                if ua_label == "research":
                    continue
                return {
                    "status_code": None,
                    "content": "",
                    "final_url": http_url,
                    "fetch_error": f"{type(e).__name__}_after_ssl_fallback",
                    "ua_used": ua_label,
                    "http_fallback": True,
                }

    return {
        "status_code": None,
        "content": "",
        "final_url": https_url,
        "fetch_error": https_failed_reason or "all_attempts_failed",
        "ua_used": "",
        "http_fallback": https_failed_reason == "ssl_error",
    }


# ---------------------------------------------------------------------------
# Scan one host
# ---------------------------------------------------------------------------

def scan_host(host, timeout=15):
    """Scan a single host: fetch + parse robots.txt for all bots.

    Returns dict suitable for JSON serialization.
    """
    now = datetime.now(timezone.utc)
    fetch = fetch_robots(host, timeout)

    status_code = fetch["status_code"]
    fetch_error = fetch["fetch_error"]
    status_type = classify_status_type(status_code, fetch_error)

    bots_result = {}

    if status_type == "ok_200":
        groups = parse_robots(fetch["content"])
        for bot_name, bot_info in BOT_TAXONOMY.items():
            bots_result[bot_name] = classify_bot(groups, bot_name, bot_info["aliases"])
    elif status_type == "missing_404":
        for bot_name in BOT_TAXONOMY:
            bots_result[bot_name] = {
                "specific_rule": 0,
                "effective_source": "no_robots_file",
                "root_block": 0,
                "has_nonroot_disallow": 0,
            }
    else:
        # Unknown — all NA
        for bot_name in BOT_TAXONOMY:
            bots_result[bot_name] = {
                "specific_rule": None,
                "effective_source": "fetch_error",
                "root_block": None,
                "has_nonroot_disallow": None,
            }

    return {
        "host": host,
        "status_code": status_code,
        "fetch_error": fetch_error,
        "robots_status_type": status_type,
        "robots_final_url": fetch["final_url"],
        "ua_used": fetch["ua_used"],
        "http_fallback": fetch.get("http_fallback", False),
        "scan_utc": now.isoformat(),
        "scan_date": now.strftime("%Y-%m-%d"),
        "bots": bots_result,
    }


# ---------------------------------------------------------------------------
# Progress / checkpoint
# ---------------------------------------------------------------------------

def load_progress(path):
    """Load checkpoint from JSON file."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"scan_start_utc": datetime.now(timezone.utc).isoformat(), "completed_hosts": {}}


def save_progress(path, progress):
    """Save checkpoint directly (no tmp file — OneDrive interferes with atomic rename)."""
    progress["last_update_utc"] = datetime.now(timezone.utc).isoformat()
    for attempt in range(5):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=1)
            return
        except (PermissionError, OSError):
            time.sleep(0.5)
    # If all retries fail, raise so we don't silently lose progress
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=1)


# ---------------------------------------------------------------------------
# Incremental CSV writing
# ---------------------------------------------------------------------------

BOT_PANEL_COLUMNS = [
    "scan_utc", "scan_date", "firm", "ticker", "host", "gvkey",
    "bot", "bot_group",
    "root_block", "has_nonroot_disallow", "specific_rule", "effective_source",
    "googlebot_block",
    "status_code", "robots_status_type", "fetch_error", "robots_final_url",
]


def ensure_panel_header(path):
    """Create bot panel CSV with header if it doesn't exist."""
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(BOT_PANEL_COLUMNS)


def append_host_to_panel(path, host_result, firms_for_host):
    """Append bot-level rows for one host to the panel CSV.

    firms_for_host: list of dicts with keys (firm, ticker, gvkey).
    """
    googlebot_data = host_result["bots"].get("Googlebot", {})
    googlebot_block = googlebot_data.get("root_block")

    rows = []
    for firm_info in firms_for_host:
        for bot_name, bot_info in BOT_TAXONOMY.items():
            bot_data = host_result["bots"][bot_name]
            rows.append([
                host_result["scan_utc"],
                host_result["scan_date"],
                firm_info["firm"],
                firm_info["ticker"],
                host_result["host"],
                firm_info["gvkey"],
                bot_name,
                bot_info["group"],
                bot_data["root_block"],
                bot_data["has_nonroot_disallow"],
                bot_data["specific_rule"],
                bot_data["effective_source"],
                googlebot_block,
                host_result["status_code"],
                host_result["robots_status_type"],
                host_result["fetch_error"],
                host_result["robots_final_url"],
            ])

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Firm summary (generated at the end)
# ---------------------------------------------------------------------------

FIRM_SUMMARY_COLUMNS = [
    "scan_date", "firm", "ticker", "gvkey",
    "weburl_original", "host", "shared_host_flag", "host_duplicate_count",
    "status_code", "robots_status_type",
    "googlebot_block", "any_ai_specific_rule",
    "n_training_bots_root_blocked", "n_training_bots_has_nonroot_disallow",
    "n_search_bots_root_blocked", "n_search_bots_has_nonroot_disallow",
    "n_treatment_bots_root_blocked", "n_treatment_bots_has_nonroot_disallow",
    "n_user_bots_root_blocked", "n_user_bots_has_nonroot_disallow",
    "treatment_category",
]


def assign_treatment_v1(host_result):
    """Assign treatment category based on training + search bot results.

    Treatment denominator = TREATMENT_BOTS (training + search only).
    User-triggered bots are tracked separately because they may ignore
    robots.txt per official documentation (ChatGPT-User, Perplexity-User,
    Meta-ExternalFetcher).

    Returns (treatment_category, summary_stats).
    """
    status_type = host_result["robots_status_type"]

    if status_type not in ("ok_200", "missing_404"):
        return "fetch_error", {
            "any_ai_specific_rule": None,
            "n_training_bots_root_blocked": None,
            "n_training_bots_has_nonroot_disallow": None,
            "n_search_bots_root_blocked": None,
            "n_search_bots_has_nonroot_disallow": None,
            "n_treatment_bots_root_blocked": None,
            "n_treatment_bots_has_nonroot_disallow": None,
            "n_user_bots_root_blocked": None,
            "n_user_bots_has_nonroot_disallow": None,
        }

    bots = host_result["bots"]

    any_ai_specific_rule = 0
    n_train_root = 0
    n_train_nonroot = 0
    n_search_root = 0
    n_search_nonroot = 0
    n_user_root = 0
    n_user_nonroot = 0

    for bot_name in AI_BOTS:
        bd = bots[bot_name]
        if bd["specific_rule"]:
            any_ai_specific_rule = 1
        if bd["root_block"]:
            if bot_name in TRAINING_BOTS:
                n_train_root += 1
            elif bot_name in SEARCH_BOTS:
                n_search_root += 1
            elif bot_name in USER_BOTS:
                n_user_root += 1
        if bd["has_nonroot_disallow"]:
            if bot_name in TRAINING_BOTS:
                n_train_nonroot += 1
            elif bot_name in SEARCH_BOTS:
                n_search_nonroot += 1
            elif bot_name in USER_BOTS:
                n_user_nonroot += 1

    n_treatment_root = n_train_root + n_search_root
    n_treatment_nonroot = n_train_nonroot + n_search_nonroot

    # Treatment classification based on training + search bots only
    if n_treatment_root == len(TREATMENT_BOTS):
        treatment = "full_disallow"
    elif n_treatment_root > 0 or n_treatment_nonroot > 0:
        treatment = "partial_disallow"
    else:
        treatment = "allow"

    stats = {
        "any_ai_specific_rule": any_ai_specific_rule,
        "n_training_bots_root_blocked": n_train_root,
        "n_training_bots_has_nonroot_disallow": n_train_nonroot,
        "n_search_bots_root_blocked": n_search_root,
        "n_search_bots_has_nonroot_disallow": n_search_nonroot,
        "n_treatment_bots_root_blocked": n_treatment_root,
        "n_treatment_bots_has_nonroot_disallow": n_treatment_nonroot,
        "n_user_bots_root_blocked": n_user_root,
        "n_user_bots_has_nonroot_disallow": n_user_nonroot,
    }
    return treatment, stats


def build_firm_summary(df, progress, output_path):
    """Build and write firm-level summary CSV."""
    valid = df.loc[
        (df["weburl_missing"] != "True") & (df["host_clean"] != "")
    ].copy()

    rows = []
    completed = progress["completed_hosts"]

    for _, firm_row in valid.iterrows():
        host = firm_row["host_clean"]
        if host not in completed:
            continue

        host_result = completed[host]
        googlebot_data = host_result["bots"].get("Googlebot", {})
        googlebot_block = googlebot_data.get("root_block")

        treatment, stats = assign_treatment_v1(host_result)

        rows.append([
            host_result["scan_date"],
            firm_row["conm"],
            firm_row["tic"],
            firm_row["gvkey"],
            firm_row["weburl"],
            host,
            firm_row["shared_host_flag"],
            firm_row["host_duplicate_count"],
            host_result["status_code"],
            host_result["robots_status_type"],
            googlebot_block,
            stats["any_ai_specific_rule"],
            stats["n_training_bots_root_blocked"],
            stats["n_training_bots_has_nonroot_disallow"],
            stats["n_search_bots_root_blocked"],
            stats["n_search_bots_has_nonroot_disallow"],
            stats["n_treatment_bots_root_blocked"],
            stats["n_treatment_bots_has_nonroot_disallow"],
            stats["n_user_bots_root_blocked"],
            stats["n_user_bots_has_nonroot_disallow"],
            treatment,
        ])

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIRM_SUMMARY_COLUMNS)
        writer.writerows(rows)

    return len(rows)


# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------

def print_scan_summary(progress):
    """Print scan statistics."""
    completed = progress["completed_hosts"]
    total = len(completed)

    status_counts = {}
    treatment_counts = {}

    for host, result in completed.items():
        st = result["robots_status_type"]
        status_counts[st] = status_counts.get(st, 0) + 1
        t, _ = assign_treatment_v1(result)
        treatment_counts[t] = treatment_counts.get(t, 0) + 1

    print("\n" + "=" * 60)
    print("scan_robots.py — Scan Summary")
    print("=" * 60)
    print(f"Total unique hosts scanned: {total:,}")
    print(f"\nStatus type distribution:")
    for st in sorted(status_counts, key=status_counts.get, reverse=True):
        print(f"  {st}: {status_counts[st]:,}")
    print(f"\nTreatment distribution (host-level):")
    for t in sorted(treatment_counts, key=treatment_counts.get, reverse=True):
        print(f"  {t}: {treatment_counts[t]:,}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Batch scan robots.txt for Compustat firms.")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).parent / "compustat_2025_clean.csv"),
    )
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--delay-min", type=float, default=0.3)
    parser.add_argument("--delay-max", type=float, default=0.5)
    parser.add_argument(
        "--progress-file",
        default=str(Path(__file__).parent / "scan_progress.json"),
    )
    parser.add_argument(
        "--panel-output",
        default=str(Path(__file__).parent / "robots_bot_panel.csv"),
    )
    parser.add_argument(
        "--summary-output",
        default=str(Path(__file__).parent / "robots_firm_summary.csv"),
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of hosts to scan (0 = all, useful for testing).",
    )
    args = parser.parse_args()

    import pandas as pd

    # Load cleaned data
    print(f"Reading: {args.input}")
    df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    valid = df.loc[(df["weburl_missing"] != "True") & (df["host_clean"] != "")]
    print(f"Firms with valid host: {len(valid):,}")

    # Build host -> firms mapping
    host_to_firms = {}
    for _, row in valid.iterrows():
        host = row["host_clean"]
        if host not in host_to_firms:
            host_to_firms[host] = []
        host_to_firms[host].append({
            "firm": row["conm"],
            "ticker": row["tic"],
            "gvkey": row["gvkey"],
        })

    all_hosts = sorted(host_to_firms.keys())
    print(f"Unique hosts to scan: {len(all_hosts):,}")

    # Load progress
    progress = load_progress(args.progress_file)
    completed_set = set(progress["completed_hosts"].keys())
    remaining = [h for h in all_hosts if h not in completed_set]

    if args.limit > 0:
        remaining = remaining[: args.limit]

    print(f"Already completed: {len(completed_set):,}")
    print(f"Remaining to scan: {len(remaining):,}")

    if not remaining:
        print("Nothing to scan.")
    else:
        # Ensure panel CSV exists with header
        # If resuming and panel exists, we append; if fresh, create with header
        if not completed_set:
            # Fresh start — create new panel file
            ensure_panel_header(args.panel_output)
        elif not os.path.exists(args.panel_output):
            # Progress exists but panel was deleted — rebuild header + past results
            ensure_panel_header(args.panel_output)
            print("Rebuilding panel CSV from progress...")
            for host in sorted(completed_set):
                if host in host_to_firms:
                    append_host_to_panel(
                        args.panel_output,
                        progress["completed_hosts"][host],
                        host_to_firms[host],
                    )

        # Scan remaining hosts
        for i, host in enumerate(remaining, 1):
            print(f"  [{i}/{len(remaining)}] {host} ... ", end="", flush=True)
            result = scan_host(host, args.timeout)
            print(f"{result['robots_status_type']} ({result['status_code']})")

            # Write results first, then mark progress (safe ordering)
            if host in host_to_firms:
                append_host_to_panel(args.panel_output, result, host_to_firms[host])
            progress["completed_hosts"][host] = result
            save_progress(args.progress_file, progress)

            # Polite delay
            if i < len(remaining):
                time.sleep(random.uniform(args.delay_min, args.delay_max))

    # Build firm summary from complete progress
    print(f"\nBuilding firm summary...")
    n_firms = build_firm_summary(df, progress, args.summary_output)
    print(f"Wrote {n_firms:,} rows to {args.summary_output}")

    print_scan_summary(progress)


if __name__ == "__main__":
    main()
