"""
Automated Pilot Test — ChatGPT Search via OpenAI API
Sends 300 queries, saves markdown responses, parses citations, fills recording sheet.

Usage:
    # Set your API key first (PowerShell):
    #   $env:OPENAI_API_KEY="sk-..."
    # Then run:
    #   python run_pilot.py
    #
    # To resume from where you left off (skips already-done rows):
    #   python run_pilot.py --resume
"""

import os
import sys
import csv
import time
import re
import argparse
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("Install openai: pip install openai")
    sys.exit(1)

# ── paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent                          # pilot_tests/
SHEET_PATH = BASE.parent / "stata" / "stata-mcp-folder" / "stata-mcp-result" / "pilot_recording_sheet.csv"
OUTPUT_DIR = BASE                                                # save .md here
FILLED_SHEET = BASE / "pilot_recording_sheet_filled.csv"         # output CSV

# ── config ─────────────────────────────────────────────────────────────────
MODEL = "gpt-4o"            # model with web search support
DELAY_BETWEEN_CALLS = 3     # seconds, to respect rate limits


# ── helpers ────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    """Return root domain from a URL (e.g., 'ir.arhaus.com' -> 'arhaus.com')."""
    try:
        host = urlparse(url).hostname or ""
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:]).lower()
        return host.lower()
    except Exception:
        return ""


def is_official(url: str, host_domain: str) -> bool:
    """Check if url belongs to the firm's official website."""
    root = extract_domain("https://" + host_domain)
    url_domain = extract_domain(url)
    return url_domain == root


def parse_citations_from_text(text: str):
    """Extract all markdown-link URLs from inline citations in the response text."""
    urls = re.findall(r'\[.*?\]\((https?://[^\s\)]+)\)', text)
    return urls


def compute_metrics(all_urls: list, host_domain: str):
    """
    Given a list of cited URLs (in order of appearance) and the firm's host domain,
    compute: OfficialCited, OfficialRank, n_cited_sources, source_domains.
    """
    seen_domains = []
    official_rank = 999
    official_cited = 0

    for url in all_urls:
        domain = extract_domain(url)
        if not domain or "chatgpt.com" in domain:
            continue
        if domain not in seen_domains:
            seen_domains.append(domain)
            if is_official(url, host_domain):
                official_cited = 1
                if official_rank == 999:
                    official_rank = len(seen_domains)

    return {
        "OfficialCited": official_cited,
        "OfficialListed": official_cited,  # API has no separate "sources panel"
        "OfficialRank": official_rank,
        "n_cited_sources": len(seen_domains),
        "source_domains": ", ".join(seen_domains),
    }


def make_filename(row: dict) -> str:
    pair = str(row["pair_id"]).zfill(2)
    group = row["pilot_group"]
    ticker = row["ticker"]
    qnum = row["query_id"].split("_")[0].upper()  # e.g., Q1
    return f"Pair{pair}_{group}_{ticker}_{qnum}.md"


def query_chatgpt(client: OpenAI, prompt: str) -> tuple:
    """
    Call OpenAI API with web search enabled.
    Returns (response_text, list_of_cited_urls).
    """
    try:
        response = client.responses.create(
            model=MODEL,
            tools=[{"type": "web_search_preview", "search_context_size": "high"}],
            input=f"Search the web: {prompt}",
        )

        full_text = ""
        annotation_urls = []

        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        full_text += content.text
                        if hasattr(content, 'annotations') and content.annotations:
                            for ann in content.annotations:
                                if hasattr(ann, 'url'):
                                    annotation_urls.append(ann.url)

        # Also parse markdown links from the text itself
        text_urls = parse_citations_from_text(full_text)

        # Annotations are more reliable; text links as fallback
        all_urls = annotation_urls if annotation_urls else text_urls

        return full_text, all_urls

    except Exception as e:
        print(f"  ERROR: {e}")
        return f"[ERROR] {e}", []


def save_markdown(filename: str, prompt: str, response_text: str, urls: list):
    """Save the response as a markdown file matching the manual format."""
    filepath = OUTPUT_DIR / filename
    sources_list = "\n".join(f"- {u}" for u in urls) if urls else "(no sources)"

    content = f"""> From: OpenAI API (automated)

# you asked

{prompt}

---

# chatgpt response

{response_text}

---

# sources panel

{sources_list}
"""
    filepath.write_text(content, encoding="utf-8")


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip rows whose .md file already exists")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: Set OPENAI_API_KEY environment variable first.")
        print('  PowerShell:  $env:OPENAI_API_KEY="sk-..."')
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # Read the recording sheet
    with open(SHEET_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Loaded {len(rows)} queries from recording sheet.")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Model: {MODEL}")
    print()

    results = []
    total = len(rows)

    for i, row in enumerate(rows):
        filename = make_filename(row)
        prompt = row["prompt"]
        host = row["host"]
        pair_id = row["pair_id"]
        group = row["pilot_group"]
        ticker = row["ticker"]

        # Skip if already done (resume mode)
        if args.resume and (OUTPUT_DIR / filename).exists():
            print(f"[{i+1}/{total}] SKIP (exists): {filename}")
            existing_text = (OUTPUT_DIR / filename).read_text(encoding="utf-8")
            existing_urls = parse_citations_from_text(existing_text)
            metrics = compute_metrics(existing_urls, host)
            row.update(metrics)
            row["timestamp"] = ""
            row["notes"] = "resumed from existing file"
            results.append(row)
            continue

        print(f"[{i+1}/{total}] Pair {pair_id} {group} {ticker} -- {row['query_id']}")

        # Call the API
        response_text, urls = query_chatgpt(client, prompt)

        # Compute citation metrics
        metrics = compute_metrics(urls, host)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        print(f"  -> OfficialCited={metrics['OfficialCited']}, "
              f"Rank={metrics['OfficialRank']}, "
              f"n_sources={metrics['n_cited_sources']}")

        # Save markdown
        save_markdown(filename, prompt, response_text, urls)

        # Update row
        row.update(metrics)
        row["timestamp"] = timestamp
        row["notes"] = "automated via API"
        results.append(row)

        # Rate limit
        if i < total - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    # Write filled CSV
    fieldnames = list(results[0].keys())
    with open(FILLED_SHEET, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone! Filled sheet saved to: {FILLED_SHEET}")
    print(f"Markdown files saved in: {OUTPUT_DIR}")

    # Quick summary
    treated = [r for r in results if r["pilot_group"] == "treated"]
    control = [r for r in results if r["pilot_group"] == "control"]
    t_cite = sum(int(r["OfficialCited"]) for r in treated) / max(len(treated), 1)
    c_cite = sum(int(r["OfficialCited"]) for r in control) / max(len(control), 1)
    print(f"\nQuick stats:")
    print(f"  Control OfficialCited rate: {c_cite:.1%}")
    print(f"  Treated OfficialCited rate: {t_cite:.1%}")


if __name__ == "__main__":
    main()
