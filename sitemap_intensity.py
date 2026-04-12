"""
sitemap_intensity.py — Step 4: Sitemap-based blocking intensity for partial_disallow firms.

For each unique partial_disallow host:
  1. Re-fetch robots.txt
  2. Extract declared Sitemap: URLs
  3. Fetch and parse sitemap XML (handles index files, gzip, namespaces)
  4. For each of 8 treatment bots, calculate fraction of sitemap URLs blocked

Outputs:
  robots_sitemap_intensity_host.csv  — host-level detail (partial_disallow hosts only)
  robots_sitemap_intensity_firm.csv  — firm-level, 10,062 rows, regression-ready

Design notes:
  - Intensity is computed at host level then mapped to all firms sharing that host.
  - intensity_final is a lower-bound proxy based on sitemap-listed URLs only.
  - No URL cap: all sitemap-listed URLs are processed (url_cap_hit always 0).
    Safety fuse: MAX_COMPARISON_URLS = 200_000; exceeding this sets url_cap_hit = 1.
  - Host-scope filter: only URLs whose hostname matches the scanned host are counted.
"""

import argparse
import csv
import gzip
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robots_parser import parse_robots, get_applicable_rules, is_path_blocked, extract_sitemap_urls
from fetch_utils import fetch_robots, fetch_url

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TREATMENT_BOTS = [
    ("GPTBot",             ["gptbot"]),
    ("ClaudeBot",          ["claudebot"]),
    ("Google-Extended",    ["google-extended"]),
    ("CCBot",              ["ccbot"]),
    ("Meta-ExternalAgent", ["meta-externalagent"]),
    ("OAI-SearchBot",      ["oai-searchbot"]),
    ("Claude-SearchBot",   ["claude-searchbot"]),
    ("PerplexityBot",      ["perplexitybot"]),
]

MAX_COMPARISON_URLS = 200_000   # safety fuse; expected to trigger rarely
MAX_CHILD_SITEMAPS  = 20        # max child sitemaps fetched from a sitemap index
MAX_SITEMAP_DEPTH   = 2         # max recursion depth for sitemap index files

# XML namespaces for sitemap standard
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

VALID_INTENSITY_SOURCES = {
    "allow_zero",
    "full_one",
    "partial_sitemap",
    "partial_no_sitemap_na",
    "partial_sitemap_error_na",
    "partial_no_urls_na",
    "partial_refetch_error_na",
    "fetch_error_na",
}

# ---------------------------------------------------------------------------
# Host-level output columns
# ---------------------------------------------------------------------------

HOST_COLUMNS = (
    ["host", "step4_scan_utc", "robots_refetch_status",
     "sitemap_url", "sitemap_fetch_status",
     "n_urls_before_host_filter", "n_urls_after_host_filter",
     "n_urls_dropped_by_host_filter", "n_sitemap_urls",
     "url_cap_hit", "n_urls_dropped_by_cap", "sitemaps_truncated"]
    + [f"{bot}_n_blocked"  for bot, _ in TREATMENT_BOTS]
    + [f"{bot}_intensity"  for bot, _ in TREATMENT_BOTS]
    + ["mean_treatment_intensity", "max_treatment_intensity"]
)

FIRM_COLUMNS = (
    ["scan_date", "firm", "ticker", "gvkey", "host",
     "treatment_category", "intensity_final", "intensity_source"]
    + HOST_COLUMNS[1:]   # all host columns except "host" (already have it)
)

# ---------------------------------------------------------------------------
# Sitemap fetching and parsing
# ---------------------------------------------------------------------------

def _parse_xml_locs(raw_bytes):
    """Parse <loc> URLs from sitemap XML bytes.

    Returns (root_tag_local, list_of_loc_strings).
    root_tag_local is "sitemapindex" or "urlset" (without namespace prefix).
    Returns (None, []) on parse error.
    """
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError:
        return None, []

    # Strip namespace from tag for comparison
    tag = root.tag
    if "}" in tag:
        tag = tag.split("}", 1)[1]

    locs = []
    for child in root:
        child_tag = child.tag
        if "}" in child_tag:
            child_tag = child_tag.split("}", 1)[1]

        # Both sitemapindex (<sitemap><loc>) and urlset (<url><loc>) have <loc> one level down
        for loc_el in child:
            loc_tag = loc_el.tag
            if "}" in loc_tag:
                loc_tag = loc_tag.split("}", 1)[1]
            if loc_tag == "loc" and loc_el.text:
                locs.append(loc_el.text.strip())

    return tag, locs


def _fetch_and_decompress(url):
    """Fetch a URL and decompress if gzip. Returns (raw_bytes, fetch_error)."""
    result = fetch_url(url, as_bytes=True, timeout=30)
    if result["fetch_error"] or result["status_code"] != 200:
        err = result["fetch_error"] or f"http_{result['status_code']}"
        return None, err

    raw = result["content"]

    # Detect gzip by URL extension or content
    is_gz = url.lower().endswith(".gz")
    if not is_gz and raw[:2] == b"\x1f\x8b":
        is_gz = True

    if is_gz:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            return None, "decompress_error"

    return raw, ""


def fetch_sitemap_locs(sitemap_urls, host):
    """Fetch all sitemap URLs for a host, collecting <loc> comparison strings.

    Args:
        sitemap_urls: List of Sitemap: URLs declared in robots.txt.
        host: The scanned host (for host-scope filter).

    Returns dict:
        locs_raw: list of <loc> URL strings (before host filter)
        locs_filtered: list of comparison strings (after filter + dedup on comparison)
        n_before_host_filter: int
        n_urls_dropped_by_host_filter: int
        url_cap_hit: bool
        n_urls_dropped_by_cap: int
        sitemaps_truncated: bool
        sitemap_fetch_status: "ok" | "partial_ok" | "none" | "all_errors" | specific error
        first_sitemap_url: str (first declared URL, for output column)
    """
    host_norm = host.lower().rstrip(".")

    all_locs_raw = []          # full URL strings before dedup/filter
    visited_sitemaps = set()   # prevent circular references
    sitemaps_truncated = False
    at_least_one_ok = False
    all_errors = []

    def fetch_one(url, depth):
        nonlocal sitemaps_truncated, at_least_one_ok

        if url in visited_sitemaps:
            return
        visited_sitemaps.add(url)

        raw, err = _fetch_and_decompress(url)
        if err:
            all_errors.append(err)
            return

        root_tag, locs = _parse_xml_locs(raw)
        if root_tag is None:
            all_errors.append("parse_error")
            return

        at_least_one_ok = True

        if root_tag == "sitemapindex" and depth < MAX_SITEMAP_DEPTH:
            # Child sitemaps
            child_count = 0
            for child_url in locs:
                if len(visited_sitemaps) > MAX_CHILD_SITEMAPS:
                    sitemaps_truncated = True
                    break
                # Stop fetching new child sitemaps if already at cap
                if len(all_locs_raw) >= MAX_COMPARISON_URLS:
                    sitemaps_truncated = True
                    break
                fetch_one(child_url, depth + 1)
                child_count += 1
            if child_count < len(locs):
                sitemaps_truncated = True
        else:
            # Regular urlset — collect locs
            all_locs_raw.extend(locs)

    for sm_url in sitemap_urls:
        if len(all_locs_raw) >= MAX_COMPARISON_URLS:
            sitemaps_truncated = True
            break
        fetch_one(sm_url, depth=0)

    # Determine sitemap_fetch_status
    if not sitemap_urls:
        sitemap_fetch_status = "none"
    elif at_least_one_ok and all_errors:
        sitemap_fetch_status = "partial_ok"
    elif at_least_one_ok:
        sitemap_fetch_status = "ok"
    elif all_errors:
        sitemap_fetch_status = all_errors[0]  # first error type
    else:
        sitemap_fetch_status = "none"

    # Host-scope filter: deduplicate full URLs first, then filter by hostname
    seen_full = set()
    unique_locs = []
    for loc in all_locs_raw:
        if loc not in seen_full:
            seen_full.add(loc)
            unique_locs.append(loc)

    n_before_filter = len(unique_locs)

    filtered = []
    for loc in unique_locs:
        try:
            parsed_hostname = urlparse(loc).hostname or ""
            if parsed_hostname.lower().rstrip(".") == host_norm:
                filtered.append(loc)
        except Exception:
            pass  # malformed URL — skip

    n_after_filter = len(filtered)
    n_dropped_by_filter = n_before_filter - n_after_filter

    # Extract comparison strings and deduplicate
    seen_cmp = set()
    comparison_strings = []
    for loc in filtered:
        p = urlparse(loc)
        cmp = (p.path or "/") + ("?" + p.query if p.query else "")
        if cmp not in seen_cmp:
            seen_cmp.add(cmp)
            comparison_strings.append(cmp)

    # Apply safety cap
    url_cap_hit = False
    n_dropped_by_cap = 0
    if len(comparison_strings) > MAX_COMPARISON_URLS:
        url_cap_hit = True
        n_dropped_by_cap = len(comparison_strings) - MAX_COMPARISON_URLS
        comparison_strings = comparison_strings[:MAX_COMPARISON_URLS]

    return {
        "comparison_strings": comparison_strings,
        "n_before_host_filter": n_before_filter,
        "n_after_host_filter": n_after_filter,
        "n_urls_dropped_by_host_filter": n_dropped_by_filter,
        "n_sitemap_urls": len(comparison_strings),
        "url_cap_hit": url_cap_hit,
        "n_urls_dropped_by_cap": n_dropped_by_cap,
        "sitemaps_truncated": sitemaps_truncated,
        "sitemap_fetch_status": sitemap_fetch_status,
        "first_sitemap_url": sitemap_urls[0] if sitemap_urls else "",
    }


# ---------------------------------------------------------------------------
# Per-host intensity calculation
# ---------------------------------------------------------------------------

def compute_host_intensity(host, scan_utc):
    """Fetch robots.txt, get sitemap locs, compute per-bot blocking intensity.

    Returns a dict suitable for one row in the host-level output CSV.
    """
    result = {
        "host": host,
        "step4_scan_utc": scan_utc,
        "robots_refetch_status": "",
        "sitemap_url": "",
        "sitemap_fetch_status": "",
        "n_urls_before_host_filter": 0,
        "n_urls_after_host_filter": 0,
        "n_urls_dropped_by_host_filter": 0,
        "n_sitemap_urls": 0,
        "url_cap_hit": 0,
        "n_urls_dropped_by_cap": 0,
        "sitemaps_truncated": 0,
        "intensity_source": "",
        "mean_treatment_intensity": None,
        "max_treatment_intensity": None,
    }
    for bot, _ in TREATMENT_BOTS:
        result[f"{bot}_n_blocked"] = None
        result[f"{bot}_intensity"] = None

    # Step 1: Re-fetch robots.txt
    fetch = fetch_robots(host)
    status_code = fetch["status_code"]
    fetch_error = fetch["fetch_error"]

    if fetch_error or status_code != 200:
        result["robots_refetch_status"] = fetch_error or f"http_{status_code}"
        result["intensity_source"] = "partial_refetch_error_na"
        return result

    result["robots_refetch_status"] = "ok_200"
    content = fetch["content"]

    # Step 2: Parse groups + extract sitemap URLs
    groups = parse_robots(content)
    sitemap_urls = extract_sitemap_urls(content)

    if not sitemap_urls:
        result["intensity_source"] = "partial_no_sitemap_na"
        return result

    result["sitemap_url"] = sitemap_urls[0]

    # Step 3: Fetch sitemap(s)
    sm = fetch_sitemap_locs(sitemap_urls, host)
    result["sitemap_fetch_status"]        = sm["sitemap_fetch_status"]
    result["n_urls_before_host_filter"]   = sm["n_before_host_filter"]
    result["n_urls_after_host_filter"]    = sm["n_after_host_filter"]
    result["n_urls_dropped_by_host_filter"] = sm["n_urls_dropped_by_host_filter"]
    result["n_sitemap_urls"]              = sm["n_sitemap_urls"]
    result["url_cap_hit"]                 = 1 if sm["url_cap_hit"] else 0
    result["n_urls_dropped_by_cap"]       = sm["n_urls_dropped_by_cap"]
    result["sitemaps_truncated"]          = 1 if sm["sitemaps_truncated"] else 0

    # Determine intensity_source based on sitemap fetch outcome
    if sm["sitemap_fetch_status"] not in ("ok", "partial_ok"):
        if sm["n_sitemap_urls"] == 0:
            result["intensity_source"] = "partial_sitemap_error_na"
            return result

    if sm["n_sitemap_urls"] == 0:
        result["intensity_source"] = "partial_no_urls_na"
        return result

    # Step 4: Compute per-bot intensity
    comparison_strings = sm["comparison_strings"]
    n_total = len(comparison_strings)
    intensities = []

    for bot, aliases in TREATMENT_BOTS:
        rules, _, _ = get_applicable_rules(groups, aliases)
        n_blocked = sum(1 for cmp in comparison_strings if is_path_blocked(rules, cmp))
        intensity = n_blocked / n_total
        result[f"{bot}_n_blocked"] = n_blocked
        result[f"{bot}_intensity"] = round(intensity, 6)
        intensities.append(intensity)

    result["mean_treatment_intensity"] = round(sum(intensities) / len(intensities), 6)
    result["max_treatment_intensity"]  = round(max(intensities), 6)
    result["intensity_source"] = "partial_sitemap"

    return result


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def load_progress(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_hosts": {}}


def save_progress(path, progress):
    progress["last_update_utc"] = datetime.now(timezone.utc).isoformat()
    for attempt in range(5):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=1)
            return
        except (PermissionError, OSError):
            time.sleep(0.5)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=1)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def ensure_host_csv(path):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HOST_COLUMNS)


def append_host_row(path, row_dict):
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([row_dict.get(col, "") for col in HOST_COLUMNS])


# ---------------------------------------------------------------------------
# Build firm-level output
# ---------------------------------------------------------------------------

def build_firm_output(summary_df, progress, output_path):
    """Merge host-level intensity into firm-level summary (10,062 row anchor).

    Fills intensity_final:
      allow         -> 0
      full_disallow -> 1
      partial + partial_sitemap intensity_source -> mean_treatment_intensity
      everything else -> NA (empty string)
    """
    completed = progress["completed_hosts"]

    rows = []
    for _, row in summary_df.iterrows():
        host = row["host"]
        treatment = row["treatment_category"]

        # Determine intensity_source and intensity_final
        if treatment == "allow":
            intensity_source = "allow_zero"
            intensity_final = 0
            host_data = {}
        elif treatment == "full_disallow":
            intensity_source = "full_one"
            intensity_final = 1
            host_data = {}
        elif treatment == "fetch_error":
            intensity_source = "fetch_error_na"
            intensity_final = ""
            host_data = {}
        else:
            # partial_disallow
            if host in completed:
                host_data = completed[host]
                intensity_source = host_data.get("intensity_source", "partial_refetch_error_na")
                if intensity_source == "partial_sitemap" and host_data.get("mean_treatment_intensity") is not None:
                    intensity_final = host_data["mean_treatment_intensity"]
                else:
                    intensity_final = ""
            else:
                host_data = {}
                intensity_source = "partial_refetch_error_na"
                intensity_final = ""

        firm_row = {
            "scan_date": row.get("scan_date", ""),
            "firm": row.get("firm", ""),
            "ticker": row.get("ticker", ""),
            "gvkey": row.get("gvkey", ""),
            "host": host,
            "treatment_category": treatment,
            "intensity_final": intensity_final,
            "intensity_source": intensity_source,
        }
        # Merge all host-level columns (skip "host" to avoid dup)
        for col in HOST_COLUMNS:
            if col == "host":
                continue
            firm_row[col] = host_data.get(col, "")

        rows.append([firm_row.get(col, "") for col in FIRM_COLUMNS])

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIRM_COLUMNS)
        writer.writerows(rows)

    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Step 4: compute sitemap blocking intensity for partial_disallow firms."
    )
    parser.add_argument(
        "--input-summary",
        default=str(Path(__file__).parent / "robots_firm_summary.csv"),
    )
    parser.add_argument(
        "--progress-file",
        default=str(Path(__file__).parent / "sitemap_progress.json"),
    )
    parser.add_argument(
        "--output-host",
        default=str(Path(__file__).parent / "robots_sitemap_intensity_host.csv"),
    )
    parser.add_argument(
        "--output-firm",
        default=str(Path(__file__).parent / "robots_sitemap_intensity_firm.csv"),
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of partial_disallow hosts to scan (0 = all).",
    )
    parser.add_argument("--delay-min", type=float, default=0.3)
    parser.add_argument("--delay-max", type=float, default=0.5)
    args = parser.parse_args()

    import pandas as pd

    print(f"Reading: {args.input_summary}")
    summary_df = pd.read_csv(args.input_summary, dtype=str, keep_default_na=False)
    print(f"Firms in summary: {len(summary_df):,}")

    # Identify unique partial_disallow hosts
    partial = summary_df[summary_df["treatment_category"] == "partial_disallow"]
    unique_partial_hosts = list(partial["host"].unique())
    # Filter out empty hosts
    unique_partial_hosts = [h for h in unique_partial_hosts if h]
    print(f"Unique partial_disallow hosts: {len(unique_partial_hosts):,}")

    # Load checkpoint
    progress = load_progress(args.progress_file)
    completed_set = set(progress["completed_hosts"].keys())
    remaining = [h for h in unique_partial_hosts if h not in completed_set]

    if args.limit > 0:
        remaining = remaining[:args.limit]

    print(f"Already completed: {len(completed_set):,}")
    print(f"Remaining to scan: {len(remaining):,}")

    if remaining:
        ensure_host_csv(args.output_host)

        for i, host in enumerate(remaining, 1):
            print(f"  [{i}/{len(remaining)}] {host} ... ", end="", flush=True)
            scan_utc = datetime.now(timezone.utc).isoformat()
            row = compute_host_intensity(host, scan_utc)
            print(f"{row['intensity_source']} (n_urls={row['n_sitemap_urls']})")

            # Write host-level row first, then update checkpoint
            append_host_row(args.output_host, row)
            progress["completed_hosts"][host] = row
            save_progress(args.progress_file, progress)

            if i < len(remaining):
                time.sleep(random.uniform(args.delay_min, args.delay_max))

    # Build firm-level output
    print("\nBuilding firm-level output...")
    n_rows = build_firm_output(summary_df, progress, args.output_firm)
    print(f"Wrote {n_rows:,} rows to {args.output_firm}")

    # Summary statistics
    completed = progress["completed_hosts"]
    source_counts = {}
    for h, d in completed.items():
        s = d.get("intensity_source", "unknown")
        source_counts[s] = source_counts.get(s, 0) + 1

    print("\n--- Partial host intensity_source distribution ---")
    for s, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {s}: {cnt:,}")

    # Verify intensity_source values are from the expected set
    unexpected = set(source_counts.keys()) - VALID_INTENSITY_SOURCES
    if unexpected:
        print(f"\nWARNING: unexpected intensity_source values: {unexpected}")
    else:
        print("\nAll intensity_source values are from the valid set.")


if __name__ == "__main__":
    main()
