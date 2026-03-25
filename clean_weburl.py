"""
clean_weburl.py — Extract canonical hosts from Compustat weburl column.

Reads compustat_2025.csv, normalizes each weburl to a clean host,
adds deduplication metadata, and writes compustat_2025_clean.csv.
"""

import argparse
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


def detect_scheme(raw: str) -> str:
    """Detect the original scheme in a raw URL string."""
    low = raw.lower()
    if low.startswith("https://") or low.startswith("https%3a"):
        return "https"
    if low.startswith("http://") or low.startswith("http%3a"):
        return "http"
    if low.startswith("//"):
        return "missing_scheme"
    return "missing_scheme"


def clean_host(raw_url: str) -> tuple:
    """Extract canonical host from a raw weburl string.

    Returns (host_clean, url_parse_error, host_source_scheme).
    """
    if not isinstance(raw_url, str) or not raw_url.strip():
        return ("", False, "")  # missing, not a parse error

    raw = raw_url.strip()
    scheme = detect_scheme(raw)

    # Prepend scheme if missing so urlparse works
    if raw.startswith("//"):
        to_parse = "https:" + raw
    elif "://" not in raw:
        to_parse = "https://" + raw
    else:
        to_parse = raw

    try:
        parsed = urlparse(to_parse)
        host = parsed.hostname  # lowercase, no port
    except Exception:
        return ("", True, scheme)

    if not host:
        return ("", True, scheme)

    # Strip trailing dots
    host = host.rstrip(".")

    # Remove default ports (urlparse already strips port from hostname,
    # but handle edge cases where port leaks into hostname)
    for suffix in (":80", ":443"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]

    # Flag hosts with spaces or obviously invalid characters
    if " " in host or "\t" in host:
        return (host, True, scheme)

    return (host, False, scheme)


def load_data(path: str) -> pd.DataFrame:
    """Load compustat CSV, preserving all columns as strings."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in ("gvkey", "tic", "conm", "weburl"):
        if col not in df.columns:
            raise ValueError(f"Expected column '{col}' not found in {path}")
    return df


def clean_hosts(df: pd.DataFrame) -> pd.DataFrame:
    """Apply host normalization to every row."""
    results = df["weburl"].apply(clean_host)
    df["host_clean"] = results.apply(lambda x: x[0])
    df["url_parse_error"] = results.apply(lambda x: x[1])
    df["host_source_scheme"] = results.apply(lambda x: x[2])
    df["weburl_missing"] = (df["weburl"].str.strip() == "") | (df["weburl"].isna())
    return df


def add_dedup_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add shared_host_flag and host_duplicate_count."""
    # Count duplicates per host (only for non-empty hosts)
    counts = df.loc[df["host_clean"] != "", "host_clean"].value_counts()
    df["host_duplicate_count"] = df["host_clean"].map(counts).fillna(0).astype(int)
    df["shared_host_flag"] = (df["host_duplicate_count"] > 1) & (~df["weburl_missing"])
    return df


def print_summary(df: pd.DataFrame):
    """Print summary statistics to console."""
    total = len(df)
    missing = df["weburl_missing"].sum()
    parse_errors = df["url_parse_error"].sum()
    valid = df.loc[(~df["weburl_missing"]) & (df["host_clean"] != "")]
    unique_hosts = valid["host_clean"].nunique()
    shared = df["shared_host_flag"].sum()
    shared_hosts = valid.loc[valid["shared_host_flag"], "host_clean"].nunique()

    print("=" * 60)
    print("clean_weburl.py — Summary")
    print("=" * 60)
    print(f"Total rows:            {total:,}")
    print(f"Missing weburl:        {missing:,} ({missing/total*100:.1f}%)")
    print(f"Parse errors:          {parse_errors:,}")
    valid_count = len(valid)
    print(f"Valid hosts:           {valid_count:,}")
    print(f"Unique hosts:          {unique_hosts:,}")
    print(f"Shared hosts:          {shared_hosts:,} (hosts used by >1 firm)")
    print(f"Firms on shared hosts: {shared:,}")
    print()

    # Scheme distribution
    scheme_counts = df.loc[~df["weburl_missing"], "host_source_scheme"].value_counts()
    print("Scheme distribution (non-missing):")
    for s, c in scheme_counts.items():
        print(f"  {s}: {c:,}")
    print()

    # Top 10 most shared hosts
    top = valid["host_clean"].value_counts().head(10)
    print("Top 10 most shared hosts:")
    for host, count in top.items():
        print(f"  {host}: {count:,} firms")

    # Sample of URLs that had paths stripped
    has_path = df.loc[
        (~df["weburl_missing"])
        & (df["weburl"].str.contains("/", na=False))
        & (df["host_clean"] != ""),
        ["weburl", "host_clean"],
    ]
    if len(has_path) > 0:
        print(f"\nURLs with paths stripped: {len(has_path):,}")
        print("  Sample:")
        for _, row in has_path.head(5).iterrows():
            print(f"    {row['weburl']} -> {row['host_clean']}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Clean Compustat weburl column.")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).parent / "compustat_2025.csv"),
        help="Input CSV path (default: compustat_2025.csv in same directory)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default: compustat_2025_clean.csv in same directory)",
    )
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or str(
        Path(input_path).parent / "compustat_2025_clean.csv"
    )

    print(f"Reading: {input_path}")
    df = load_data(input_path)
    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns.")

    df = clean_hosts(df)
    df = add_dedup_columns(df)

    print(f"Writing: {output_path}")
    df.to_csv(output_path, index=False)

    print_summary(df)


if __name__ == "__main__":
    main()
