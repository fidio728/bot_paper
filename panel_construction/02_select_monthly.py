"""
02_select_monthly.py — Select one snapshot per host × month.

For each of the 63 months (2021-01 to 2026-03), pick the snapshot closest
to the 15th. Track content_changed via digest comparison.

Input:  cdx_snapshots.json
Output: monthly_snapshots.csv
"""

import json
import csv
import sys
from pathlib import Path
from datetime import datetime

PANEL_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("D:/anoconda/bot_paper_data")
CDX_JSONL = DATA_DIR / "cdx_snapshots.jsonl"
CDX_JSON = DATA_DIR / "cdx_snapshots.json"  # legacy fallback
OUTPUT_CSV = DATA_DIR / "monthly_snapshots.csv"

# Generate all months from 2021-01 to 2026-03
ALL_MONTHS = []
for y in range(2021, 2027):
    for m in range(1, 13):
        ym = f"{y:04d}-{m:02d}"
        if ym > "2026-03":
            break
        ALL_MONTHS.append(ym)


def load_cdx_data():
    """Load CDX data from JSONL (preferred) or legacy JSON."""
    data = {}
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
    with open(CDX_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    snapshots = load_cdx_data()

    print(f"Hosts in CDX data: {len(snapshots)}")
    print(f"Months in panel: {len(ALL_MONTHS)} ({ALL_MONTHS[0]} to {ALL_MONTHS[-1]})")

    rows = []
    total_cells = 0
    filled_cells = 0
    all_digests = set()

    for host in sorted(snapshots.keys()):
        snaps = snapshots[host]

        # Index snapshots by month
        by_month = {}
        for row in snaps:
            ts = row[0]
            ym = ts[:4] + "-" + ts[4:6]
            if ym not in by_month:
                by_month[ym] = []
            by_month[ym].append(row)

        prev_digest = None
        prev_had_snapshot = False
        for ym in ALL_MONTHS:
            total_cells += 1

            if ym not in by_month:
                rows.append({
                    "host": host,
                    "year_month": ym,
                    "snapshot_timestamp": "NA",
                    "statuscode": "NA",
                    "digest": "NA",
                    "original_url": "NA",
                    "has_snapshot": 0,
                    "content_changed": "NA",
                })
                # Gap: reset prev so next observed month doesn't compare across gap
                prev_digest = None
                prev_had_snapshot = False
                continue

            # Pick closest to 15th
            candidates = by_month[ym]
            target_day = 15
            best = None
            best_dist = 999

            for snap in candidates:
                ts = snap[0]
                day = int(ts[6:8])
                dist = abs(day - target_day)
                if dist < best_dist:
                    best_dist = dist
                    best = snap

            # best = [timestamp, statuscode, digest, length, original]
            ts, status, digest, length, original = best
            filled_cells += 1
            if status == "200":
                all_digests.add(digest)

            # content_changed: only compare to immediately preceding month
            content_changed = "NA"
            if prev_had_snapshot:
                content_changed = str(digest != prev_digest)
            prev_digest = digest
            prev_had_snapshot = True

            rows.append({
                "host": host,
                "year_month": ym,
                "snapshot_timestamp": ts,
                "statuscode": status,
                "digest": digest,
                "original_url": original,
                "has_snapshot": 1,
                "content_changed": content_changed,
            })

    # Write output
    fieldnames = ["host", "year_month", "snapshot_timestamp", "statuscode",
                  "digest", "original_url", "has_snapshot", "content_changed"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    print(f"\nTotal cells (host × month): {total_cells}")
    print(f"Filled cells (has snapshot): {filled_cells} ({100*filled_cells/total_cells:.1f}%)")
    print(f"Unique digests (status 200 only): {len(all_digests)}")

    # Coverage by year
    year_stats = {}
    for r in rows:
        y = r["year_month"][:4]
        if y not in year_stats:
            year_stats[y] = {"total": 0, "filled": 0}
        year_stats[y]["total"] += 1
        year_stats[y]["filled"] += int(r["has_snapshot"])

    print("\nCoverage by year:")
    for y in sorted(year_stats):
        s = year_stats[y]
        pct = 100 * s["filled"] / s["total"] if s["total"] > 0 else 0
        print(f"  {y}: {s['filled']}/{s['total']} ({pct:.1f}%)")

    print(f"\nOutput: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
