"""
03_download_content.py — Download robots.txt content for unique 200-status digests.

Only downloads content for snapshots with HTTP status 200.
404/410 are classified directly as no_robots_file in Step 4.

Input:  monthly_snapshots.csv
Output: robots_content.json: {digest: "content string", ...}
"""

import json
import csv
import time
import sys
import requests
from pathlib import Path

PANEL_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("D:/anoconda/bot_paper_data")
MONTHLY_CSV = DATA_DIR / "monthly_snapshots.csv"
CONTENT_JSON = DATA_DIR / "robots_content.json"

USER_AGENT = "Mozilla/5.0 (compatible; AcademicResearchBot/1.0; robots-panel-study)"
RATE_LIMIT = 1.0
CHECKPOINT_EVERY = 200
TIMEOUT = 15


def load_checkpoint():
    if CONTENT_JSON.exists():
        with open(CONTENT_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_checkpoint(data):
    with open(CONTENT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f)


def main():
    # Read monthly snapshots and find unique digests needing download
    digests_to_download = {}  # digest -> (timestamp, original_url, host)

    with open(MONTHLY_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        total_rows = 0
        status_200 = 0
        status_non200 = 0
        no_snapshot = 0

        for row in reader:
            total_rows += 1
            if row["has_snapshot"] == "0":
                no_snapshot += 1
                continue

            status = row["statuscode"]
            digest = row["digest"]

            if status == "200":
                status_200 += 1
                if digest not in digests_to_download:
                    digests_to_download[digest] = (row["snapshot_timestamp"], row["original_url"], row["host"])
            else:
                status_non200 += 1

    print(f"Total rows in monthly_snapshots: {total_rows}")
    print(f"  No snapshot: {no_snapshot}")
    print(f"  Status 200: {status_200}")
    print(f"  Status non-200 (skip download): {status_non200}")
    print(f"Unique 200-status digests to download: {len(digests_to_download)}")

    # Load checkpoint — content keyed by digest, plus retry counts metadata
    content = load_checkpoint()
    retry_key = "__retry_counts__"
    retry_counts = content.pop(retry_key, {})  # {digest: int}
    MAX_RETRIES = 3

    already_done = set(content.keys())
    remaining = {d: v for d, v in digests_to_download.items() if d not in already_done}

    # Skip digests that have exceeded max retries
    exhausted = {d for d, c in retry_counts.items() if c >= MAX_RETRIES}
    remaining = {d: v for d, v in remaining.items() if d not in exhausted}

    print(f"Already downloaded: {len(already_done)}")
    print(f"Exhausted (>={MAX_RETRIES} failures, skipped): {len(exhausted)}")
    print(f"Remaining to download: {len(remaining)}")

    if not remaining:
        print("Nothing to download.")
        # Save retry counts back
        content[retry_key] = retry_counts
        save_checkpoint(content)
        return

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    downloaded = 0
    failures = 0
    remaining_items = list(remaining.items())

    for i, (digest, (timestamp, original_url, host)) in enumerate(remaining_items):
        # Build Wayback URL candidates: try original_url first, then scheme fallback
        urls_to_try = []
        if original_url and original_url != "NA":
            urls_to_try.append(f"https://web.archive.org/web/{timestamp}id_/{original_url}")
        else:
            urls_to_try.append(f"https://web.archive.org/web/{timestamp}id_/https://{host}/robots.txt")
            urls_to_try.append(f"https://web.archive.org/web/{timestamp}id_/http://{host}/robots.txt")

        success = False
        for url in urls_to_try:
            try:
                resp = session.get(url, timeout=TIMEOUT)
                if resp.status_code == 200:
                    content[digest] = resp.text
                    downloaded += 1
                    success = True
                    break
            except Exception:
                pass

        if not success:
            retry_counts[digest] = retry_counts.get(digest, 0) + 1
            failures += 1
            count = retry_counts[digest]
            if count >= MAX_RETRIES:
                if failures <= 20:
                    print(f"  Exhausted {digest[:12]}... ({count}/{MAX_RETRIES} failures)")
            elif failures <= 20:
                print(f"  Failed {digest[:12]}... (attempt {count}/{MAX_RETRIES})")

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(remaining_items)}] downloaded={downloaded}, failures={failures}")

        if (i + 1) % CHECKPOINT_EVERY == 0:
            content[retry_key] = retry_counts
            save_checkpoint(content)
            content.pop(retry_key)  # keep working dict clean
            print(f"  Checkpoint saved")

        time.sleep(RATE_LIMIT)

    # Final save (include retry counts metadata)
    content[retry_key] = retry_counts
    save_checkpoint(content)

    n_exhausted_total = sum(1 for c in retry_counts.values() if c >= MAX_RETRIES)
    print(f"\n=== Summary ===")
    print(f"200-status digests downloaded (total): {len(content) - 1}")  # -1 for retry_key
    print(f"Exhausted digests (>={MAX_RETRIES} failures): {n_exhausted_total}")
    print(f"Non-200 skipped: {status_non200}")
    print(f"Download failures this run (will retry next run): {failures}")
    print(f"Output: {CONTENT_JSON}")


if __name__ == "__main__":
    main()
