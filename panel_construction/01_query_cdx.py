"""
01_query_cdx.py — Query Wayback Machine CDX API for robots.txt snapshots.

Queries all archived snapshots of /robots.txt for each host in the sample,
covering Jan 2021 to Mar 2026. NO collapse=digest (see INSTRUCTIONS.md §2).

Output:
  - cdx_snapshots.json: {host: [[timestamp, statuscode, digest, length, original], ...]}
  - cdx_coverage_summary.csv
"""

import json
import time
import sys
import csv
import functools
import requests

# Force unbuffered output so background runs show progress
print = functools.partial(print, flush=True)
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PANEL_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("D:/anoconda/bot_paper_data")  # large intermediate files on D drive
CDX_JSON = DATA_DIR / "cdx_snapshots.json"
CDX_JSONL = DATA_DIR / "cdx_snapshots.jsonl"
COVERAGE_CSV = PANEL_DIR / "cdx_coverage_summary.csv"
INPUT_CSV = PROJECT_ROOT / "compustat_2025_clean.csv"

CDX_URL = "https://web.archive.org/cdx/search/cdx"
USER_AGENT = "Mozilla/5.0 (compatible; AcademicResearchBot/1.0; robots-panel-study)"
RATE_LIMIT = 1.0  # seconds between requests


def load_hosts():
    """Load unique hosts from compustat file."""
    hosts = set()
    with open(INPUT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            h = row.get("host_clean", "").strip()
            # Skip empty, whitespace-only, or obviously invalid entries
            if not h or h.lower() == "nan" or "." not in h:
                continue
            hosts.add(h)
    return sorted(hosts)


def load_checkpoint():
    """Load existing data from JSONL (one {host: ..., snapshots: [...]} per line)."""
    data = {}
    # Try JSONL first (new format)
    if CDX_JSONL.exists():
        with open(CDX_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    data[obj["host"]] = obj["snapshots"]
                except (json.JSONDecodeError, KeyError):
                    continue
        return data
    # Fall back to old JSON format for migration
    if CDX_JSON.exists():
        try:
            with open(CDX_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate to JSONL
            with open(CDX_JSONL, "w", encoding="utf-8") as f:
                for host, snaps in data.items():
                    f.write(json.dumps({"host": host, "snapshots": snaps}) + "\n")
            print(f"Migrated {len(data)} hosts from JSON to JSONL format")
        except (json.JSONDecodeError, MemoryError):
            print("WARNING: Old JSON checkpoint is corrupted, starting from what JSONL has")
    return data


def append_host(host, snapshots):
    """Append a single host result to JSONL. Tiny write, crash-safe."""
    with open(CDX_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps({"host": host, "snapshots": snapshots}) + "\n")


def query_cdx(host, session, max_retries=2):
    """Query CDX for a single host. Returns list of [timestamp, statuscode, digest, length, original]."""
    params = {
        "url": f"{host}/robots.txt",
        "output": "json",
        "from": "20210101",
        "to": "20260401",
        "fl": "timestamp,statuscode,digest,length,original",
        "matchType": "exact",
    }
    for attempt in range(max_retries + 1):
        try:
            resp = session.get(CDX_URL, params=params, timeout=90)
            resp.raise_for_status()
            rows = resp.json()
            if len(rows) > 1:
                return rows[1:]
            return []
        except Exception as e:
            if attempt < max_retries:
                time.sleep(3)
                continue
            print(f"  ERROR {host}: {e}")
            return None


def compute_coverage(snapshots_dict):
    """Compute coverage summary stats."""
    rows = []
    for host, snaps in sorted(snapshots_dict.items()):
        if not snaps:
            rows.append({
                "host": host, "n_snapshots": 0, "n_distinct_months": 0,
                "first_snapshot_date": "", "last_snapshot_date": "",
                "has_pre_202308": 0, "has_post_202308": 0,
            })
            continue

        months = set()
        dates = []
        for row in snaps:
            ts = row[0]
            ym = ts[:4] + "-" + ts[4:6]
            months.add(ym)
            dates.append(ts[:8])

        dates_sorted = sorted(dates)
        first_d = f"{dates_sorted[0][:4]}-{dates_sorted[0][4:6]}-{dates_sorted[0][6:8]}" if dates_sorted else ""
        last_d = f"{dates_sorted[-1][:4]}-{dates_sorted[-1][4:6]}-{dates_sorted[-1][6:8]}" if dates_sorted else ""

        has_pre = 1 if any(m < "2023-08" for m in months) else 0
        has_post = 1 if any(m >= "2023-08" for m in months) else 0

        rows.append({
            "host": host, "n_snapshots": len(snaps),
            "n_distinct_months": len(months),
            "first_snapshot_date": first_d, "last_snapshot_date": last_d,
            "has_pre_202308": has_pre, "has_post_202308": has_post,
        })
    return rows


def main():
    hosts = load_hosts()
    print(f"Total unique hosts: {len(hosts)}")

    snapshots = load_checkpoint()
    already_done = set(snapshots.keys())
    remaining = [h for h in hosts if h not in already_done]
    print(f"Already queried: {len(already_done)}, remaining: {len(remaining)}")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    errors = []
    for i, host in enumerate(remaining):
        snaps = query_cdx(host, session)

        if snaps is None:
            errors.append(host)
            if (i + 1) % 50 == 0 or i == 0:
                print(f"  [{i+1}/{len(remaining)}] {host}: ERROR (will retry)")
        else:
            snapshots[host] = snaps
            # Append immediately — each host is one line, crash-safe
            append_host(host, snaps)
            if (i + 1) % 50 == 0 or i == 0:
                print(f"  [{i+1}/{len(remaining)}] {host}: {len(snaps)} snapshots")

        if (i + 1) % 100 == 0:
            print(f"  Progress: {len(snapshots)} hosts saved")

        time.sleep(RATE_LIMIT)

    print(f"\nDone. Total hosts saved: {len(snapshots)}")
    if errors:
        print(f"Failed hosts (not saved, will retry next run): {len(errors)}")
        for h in errors[:20]:
            print(f"  {h}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    # Coverage summary
    coverage = compute_coverage(snapshots)
    with open(COVERAGE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(coverage[0].keys()))
        writer.writeheader()
        writer.writerows(coverage)

    # Feasibility check
    has_any = sum(1 for r in coverage if r["n_snapshots"] > 0)
    has_12 = sum(1 for r in coverage if r["n_distinct_months"] >= 12)
    has_24 = sum(1 for r in coverage if r["n_distinct_months"] >= 24)
    has_both = sum(1 for r in coverage if r["has_pre_202308"] and r["has_post_202308"])

    print(f"\n=== Feasibility Check ===")
    print(f"Hosts with ≥1 snapshot:   {has_any}")
    print(f"Hosts with ≥12 months:    {has_12}")
    print(f"Hosts with ≥24 months:    {has_24}")
    print(f"Hosts with pre+post Aug 2023: {has_both}")
    if has_12 < 1000:
        print(">>> WARNING: <1,000 hosts have 12+ months. Consider stopping.")
    else:
        print(">>> Feasibility OK.")


if __name__ == "__main__":
    main()
