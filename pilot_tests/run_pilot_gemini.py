"""
Automated Pilot Test — Gemini API with Google Search Grounding
Same 300 queries, same recording logic, different AI search backend.

Usage:
    # Set your API key first (PowerShell):
    #   $env:GEMINI_API_KEY="AIza..."
    # Then run:
    #   python run_pilot_gemini.py
    #
    # To resume:
    #   python run_pilot_gemini.py --resume
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
    from google import genai
    from google.genai import types
except ImportError:
    print("Install google-genai: pip install google-genai")
    sys.exit(1)

# ── paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
SHEET_PATH = BASE.parent / "stata" / "stata-mcp-folder" / "stata-mcp-result" / "pilot_recording_sheet.csv"
OUTPUT_DIR = BASE / "gemini"
FILLED_SHEET = BASE / "pilot_recording_sheet_gemini.csv"

OUTPUT_DIR.mkdir(exist_ok=True)

# ── config ─────────────────────────────────────────────────────────────────
MODEL = "gemini-2.5-flash-lite"
DELAY_BETWEEN_CALLS = 2


# ── helpers ────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:]).lower()
        return host.lower()
    except Exception:
        return ""


def is_official(url: str, host_domain: str) -> bool:
    root = extract_domain("https://" + host_domain)
    url_domain = extract_domain(url)
    return url_domain == root


def compute_metrics(sources: list, host_domain: str):
    """sources is a list of (domain_name, uri) tuples."""
    seen_domains = []
    official_rank = 999
    official_cited = 0
    root = extract_domain("https://" + host_domain)

    for domain_name, uri in sources:
        # domain_name is from chunk.web.title (e.g., "arhaus.com" or "wikipedia.org")
        # normalize it
        domain = domain_name.lower().strip()
        if not domain:
            continue
        if domain not in seen_domains:
            seen_domains.append(domain)
            if domain == root or domain.endswith("." + root):
                official_cited = 1
                if official_rank == 999:
                    official_rank = len(seen_domains)

    return {
        "OfficialCited": official_cited,
        "OfficialListed": official_cited,
        "OfficialRank": official_rank,
        "n_cited_sources": len(seen_domains),
        "source_domains": ", ".join(seen_domains),
    }


def make_filename(row: dict) -> str:
    pair = str(row["pair_id"]).zfill(2)
    group = row["pilot_group"]
    ticker = row["ticker"]
    qnum = row["query_id"].split("_")[0].upper()
    return f"Pair{pair}_{group}_{ticker}_{qnum}.md"


def query_gemini(client, prompt: str) -> tuple:
    """
    Call Gemini API with Google Search grounding.
    Returns (response_text, list_of_cited_urls).
    """
    try:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(tools=[grounding_tool])

        response = client.models.generate_content(
            model=MODEL,
            contents=f"Search the web: {prompt}",
            config=config,
        )

        full_text = response.text or ""
        sources = []  # list of (domain_name, uri)

        # Extract sources from grounding chunks
        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.grounding_metadata:
            meta = candidate.grounding_metadata
            if meta.grounding_chunks:
                for chunk in meta.grounding_chunks:
                    if hasattr(chunk, 'web') and chunk.web:
                        title = getattr(chunk.web, 'title', '') or ''
                        uri = getattr(chunk.web, 'uri', '') or ''
                        sources.append((title, uri))

        return full_text, sources

    except Exception as e:
        print(f"  ERROR: {e}")
        return f"[ERROR] {e}", []


def save_markdown(filename: str, prompt: str, response_text: str, sources: list):
    filepath = OUTPUT_DIR / filename
    sources_list = "\n".join(f"- [{t}]({u})" for t, u in sources) if sources else "(no sources)"

    content = f"""> From: Gemini API (automated, Google Search grounding)

# you asked

{prompt}

---

# gemini response

{response_text}

---

# grounding sources

{sources_list}
"""
    filepath.write_text(content, encoding="utf-8")


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip rows whose .md file already exists")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable first.")
        print('  PowerShell:  $env:GEMINI_API_KEY="AIza..."')
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    with open(SHEET_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Loaded {len(rows)} queries.")
    print(f"Model: {MODEL}")
    print(f"Output: {OUTPUT_DIR}")
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

        if args.resume and (OUTPUT_DIR / filename).exists():
            print(f"[{i+1}/{total}] SKIP (exists): {filename}")
            existing_text = (OUTPUT_DIR / filename).read_text(encoding="utf-8")
            # Parse "[domain](url)" from saved sources
            existing_sources = re.findall(r'- \[([^\]]+)\]\(([^\)]+)\)', existing_text)
            metrics = compute_metrics(existing_sources, host)
            row.update(metrics)
            row["timestamp"] = ""
            row["notes"] = "resumed from existing file"
            results.append(row)
            continue

        print(f"[{i+1}/{total}] Pair {pair_id} {group} {ticker} -- {row['query_id']}")

        response_text, sources = query_gemini(client, prompt)
        metrics = compute_metrics(sources, host)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        print(f"  -> OfficialCited={metrics['OfficialCited']}, "
              f"Rank={metrics['OfficialRank']}, "
              f"n_sources={metrics['n_cited_sources']}")

        save_markdown(filename, prompt, response_text, sources)

        row.update(metrics)
        row["timestamp"] = timestamp
        row["notes"] = "automated via Gemini API"
        results.append(row)

        if i < total - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    # Write filled CSV
    fieldnames = list(results[0].keys())
    with open(FILLED_SHEET, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone! Filled sheet saved to: {FILLED_SHEET}")

    treated = [r for r in results if r["pilot_group"] == "treated"]
    control = [r for r in results if r["pilot_group"] == "control"]
    t_cite = sum(int(r["OfficialCited"]) for r in treated) / max(len(treated), 1)
    c_cite = sum(int(r["OfficialCited"]) for r in control) / max(len(control), 1)
    print(f"\nQuick stats (Gemini + Google Search):")
    print(f"  Control OfficialCited rate: {c_cite:.1%}")
    print(f"  Treated OfficialCited rate: {t_cite:.1%}")


if __name__ == "__main__":
    main()
