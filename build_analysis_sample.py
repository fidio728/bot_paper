"""
Build analysis-ready sample by merging robots outcome with Compustat financials.

Input files:
    robots_sitemap_intensity_firm.csv   — main sample (10,062 rows)
    compustat_2025_clean.csv            — identifiers + SIC
    2024_firm_char.csv                  — Compustat Fundamentals Annual (fyear=2024)
    2025_firm_char.csv                  — Compustat Fundamentals Annual (fyear=2025)
    robots_bot_panel.csv                — bot-level panel (for search treatment)

Output:
    analysis_sample.csv                 — deduplicated, with three-tier treatment + controls
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
DIR = Path(__file__).resolve().parent

# ── 1. Load main sample & dedup ────────────────────────────────────────────
firm = pd.read_csv(DIR / "robots_sitemap_intensity_firm.csv")
n_before = len(firm)
firm = firm.drop_duplicates()
n_after = len(firm)
print(f"Main sample: {n_before} → {n_after} after dropping {n_before - n_after} exact duplicates")
print(f"Unique gvkeys: {firm['gvkey'].nunique()}")

# ── 2. Add SIC + flags ───────────────────────────────────────────────────
clean = pd.read_csv(DIR / "compustat_2025_clean.csv", usecols=["gvkey", "sic", "naics", "exchg", "fic", "loc"])
clean = clean.drop_duplicates(subset="gvkey")

firm = firm.merge(clean, on="gvkey", how="left")
firm["fund_flag"] = firm["sic"].isin([6722, 6726]).astype(int)
firm["fin_flag"] = ((firm["sic"] >= 6000) & (firm["sic"] <= 6999)).astype(int)

print(f"Fund/ETF (sic 6722/6726): {firm['fund_flag'].sum()}")
print(f"Non-fund: {(firm['fund_flag'] == 0).sum()}")
print(f"Financial (sic 6000-6999): {firm['fin_flag'].sum()}")
print(f"Non-financial: {(firm['fin_flag'] == 0).sum()}")

# ── 3. Prepare firm_char lookup tables ─────────────────────────────────────
ACCT_VARS = ["at", "ceq", "che", "dlc", "dltt", "intan", "ppegt",
             "ni", "oibdp", "revt", "xrd", "capx", "csho", "emp", "prcc_f"]

def load_firm_char(path, suffix):
    df = pd.read_csv(path)
    df = df[(df["costat"] == "A") & (df["datafmt"] == "STD") & (df["indfmt"] == "INDL")]
    df = df[["gvkey"] + ACCT_VARS].copy()
    df = df.rename(columns={v: f"{v}_{suffix}" for v in ACCT_VARS})
    assert df["gvkey"].duplicated().sum() == 0, f"Duplicate gvkeys in {path} after filter!"
    return df

char24 = load_firm_char(DIR / "2024_firm_char.csv", "2024")
char25 = load_firm_char(DIR / "2025_firm_char.csv", "2025")
print(f"\n2024 firm_char (filtered): {len(char24)} rows")
print(f"2025 firm_char (filtered): {len(char25)} rows")

# ── 4. Merge financials ───────────────────────────────────────────────────
firm = firm.merge(char24, on="gvkey", how="left")
firm = firm.merge(char25, on="gvkey", how="left")

matched_24 = firm["at_2024"].notna().sum()
matched_25 = firm["at_2025"].notna().sum()
print(f"\nMatched to 2024: {matched_24} / {len(firm)} ({100*matched_24/len(firm):.1f}%)")
print(f"Matched to 2025: {matched_25} / {len(firm)} ({100*matched_25/len(firm):.1f}%)")

nf = firm[firm["fund_flag"] == 0]
print(f"\nNon-fund matched to 2024 at: {nf['at_2024'].notna().sum()} / {len(nf)} ({100*nf['at_2024'].notna().mean():.1f}%)")
print(f"Non-fund matched to 2025 at: {nf['at_2025'].notna().sum()} / {len(nf)} ({100*nf['at_2025'].notna().mean():.1f}%)")

# ── 5a. Derived control variables ─────────────────────────────────────────
for yr in ["2024", "2025"]:
    at = f"at_{yr}"
    firm[f"log_at_{yr}"] = np.log(firm[at].clip(lower=0.001))
    firm[f"roa_{yr}"] = firm[f"ni_{yr}"] / firm[at]
    firm[f"leverage_{yr}"] = (firm[f"dltt_{yr}"].fillna(0) + firm[f"dlc_{yr}"].fillna(0)) / firm[at]
    firm[f"cash_ratio_{yr}"] = firm[f"che_{yr}"] / firm[at]
    firm[f"rd_intensity_{yr}"] = firm[f"xrd_{yr}"] / firm[at]
    firm[f"intan_ratio_{yr}"] = firm[f"intan_{yr}"] / firm[at]
    firm[f"mkcap_{yr}"] = firm[f"csho_{yr}"] * firm[f"prcc_f_{yr}"]
    firm[f"log_mkcap_{yr}"] = np.log(firm[f"mkcap_{yr}"].clip(lower=0.001))

# ── 5b. Training vs Search intensity aggregates ──────────────────────────
TRAINING_BOTS = ["GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "Meta-ExternalAgent"]
SEARCH_BOTS = ["OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"]

firm["training_intensity"] = firm[[f"{b}_intensity" for b in TRAINING_BOTS]].mean(axis=1)
firm["search_intensity"] = firm[[f"{b}_intensity" for b in SEARCH_BOTS]].mean(axis=1)

print(f"\ntraining_intensity non-NA: {firm['training_intensity'].notna().sum()}")
print(f"search_intensity non-NA: {firm['search_intensity'].notna().sum()}")

# ── 5c. Broad search treatment (search_block, search_treatment) ──────────
bot_panel = pd.read_csv(DIR / "robots_bot_panel.csv",
                        usecols=["gvkey", "bot", "root_block", "has_nonroot_disallow", "effective_source"])
search_panel = bot_panel[bot_panel["bot"].isin(SEARCH_BOTS)].copy()
search_panel = search_panel.drop_duplicates(subset=["gvkey", "bot"])

search_by_firm = search_panel.groupby("gvkey").agg(
    n_search_root_blocked=("root_block", "sum"),
    n_search_any_blocked=("root_block", lambda x: (x.fillna(0) + search_panel.loc[x.index, "has_nonroot_disallow"].fillna(0)).clip(upper=1).sum()),
    n_search_bots_valid=("root_block", "count"),
    any_search_root_na=("root_block", lambda x: x.isna().any()),
).reset_index()

def classify_search(row):
    if row["any_search_root_na"]:
        return "search_fetch_error"
    if row["n_search_root_blocked"] == row["n_search_bots_valid"] == 3:
        return "search_full_block"
    elif row["n_search_root_blocked"] > 0 or row["n_search_any_blocked"] > 0:
        return "search_partial_block"
    return "search_allow"

search_by_firm["search_treatment"] = search_by_firm.apply(classify_search, axis=1)
search_by_firm["search_block"] = search_by_firm["search_treatment"].isin(
    ["search_partial_block", "search_full_block"]).astype(int)
search_by_firm["search_full_block"] = (search_by_firm["search_treatment"] == "search_full_block").astype(int)

# Training bot aggregates (for descriptives only)
training_panel = bot_panel[bot_panel["bot"].isin(TRAINING_BOTS)].copy()
training_panel = training_panel.drop_duplicates(subset=["gvkey", "bot"])
training_by_firm = training_panel.groupby("gvkey").agg(
    n_training_root_blocked=("root_block", "sum"),
    any_training_root_na=("root_block", lambda x: x.isna().any()),
).reset_index()
training_by_firm["training_block"] = (
    (~training_by_firm["any_training_root_na"]) & (training_by_firm["n_training_root_blocked"] > 0)
).astype(int)

# ── 5d. Specific AI search bot rules (Tier 2) ───────────────────────────
# Per bot: effective_source=="specific" AND (root_block=1 OR nonroot_disallow=1)
# Preserve NA for fetch_error firms
search_spec = search_panel.copy()
is_specific = (
    (search_spec["effective_source"] == "specific") &
    ((search_spec["root_block"].fillna(0) + search_spec["has_nonroot_disallow"].fillna(0)) > 0)
).astype(float)
is_specific[search_spec["root_block"].isna()] = np.nan
search_spec["is_specific_block"] = is_specific

specific_by_firm = search_spec.groupby("gvkey")["is_specific_block"].max().reset_index()
specific_by_firm.columns = ["gvkey", "search_block_specific"]

search_by_firm = search_by_firm.merge(specific_by_firm, on="gvkey", how="left")

# ── 5e. Per-platform broad + specific (for future heterogeneity) ─────────
PLATFORM_BOTS = {
    "oai": "OAI-SearchBot",
    "perplexity": "PerplexityBot",
    "claude_search": "Claude-SearchBot",
}

for platform, bot_name in PLATFORM_BOTS.items():
    bot_data = bot_panel[bot_panel["bot"] == bot_name][
        ["gvkey", "root_block", "has_nonroot_disallow", "effective_source"]
    ].copy()
    bot_data = bot_data.drop_duplicates(subset="gvkey")

    # Broad: any rule (including wildcard /admin/)
    bot_data[f"block_{platform}_broad"] = (
        (bot_data["root_block"].fillna(0) + bot_data["has_nonroot_disallow"].fillna(0)) > 0
    ).astype(int)
    bot_data.loc[bot_data["root_block"].isna(), f"block_{platform}_broad"] = pd.NA

    # Specific: AI-specific intent
    bot_data[f"block_{platform}_specific"] = (
        (bot_data["effective_source"] == "specific") &
        ((bot_data["root_block"].fillna(0) + bot_data["has_nonroot_disallow"].fillna(0)) > 0)
    ).astype(int)
    bot_data.loc[bot_data["root_block"].isna(), f"block_{platform}_specific"] = pd.NA

    firm = firm.merge(
        bot_data[["gvkey", f"block_{platform}_broad", f"block_{platform}_specific"]],
        on="gvkey", how="left"
    )

# ── 5f. Merge all search/training aggregates ─────────────────────────────
firm = firm.merge(search_by_firm[["gvkey", "search_treatment", "search_block", "search_full_block",
                                   "n_search_root_blocked", "search_block_specific"]],
                  on="gvkey", how="left")
firm = firm.merge(training_by_firm[["gvkey", "training_block", "n_training_root_blocked"]],
                  on="gvkey", how="left")

# ── 5g. Tier 3: search_public_block (effect-based, MAIN TREATMENT) ──────
# 1 if search_full_block=1 OR search_intensity > 0 (rules actually block public pages)
# 0 if search_allow OR (search_partial_block AND search_intensity == 0)
# NA if fetch_error OR no sitemap data to evaluate effect
def compute_public_block(row):
    st = row["search_treatment"]
    if st == "search_fetch_error":
        return pd.NA
    if st == "search_allow":
        return 0
    if row["search_full_block"] == 1:
        return 1
    # search_partial_block: check if rules actually affect public pages
    si = row.get("search_intensity")
    if pd.notna(si) and si > 0:
        return 1
    elif pd.notna(si) and si == 0:
        return 0
    return pd.NA  # no sitemap data → can't determine

firm["search_public_block"] = firm.apply(compute_public_block, axis=1)

# ── Print summary ────────────────────────────────────────────────────────
print(f"\n--- Three-tier treatment summary ---")
spb = firm["search_public_block"]
print(f"  search_public_block=1 (main treatment): {(spb == 1).sum()}")
print(f"  search_public_block=0: {(spb == 0).sum()}")
print(f"  search_public_block=NA: {spb.isna().sum()}")
print(f"  search_block (broad)=1: {firm['search_block'].sum()}")
print(f"  search_block_specific=1: {firm['search_block_specific'].sum()}")
print(f"  search_full_block=1: {firm['search_full_block'].sum()}")
print(f"  training_block=1: {firm['training_block'].sum()}")

print(f"\n--- Per-platform broad ---")
for p in PLATFORM_BOTS:
    print(f"  block_{p}_broad=1: {(firm[f'block_{p}_broad'] == 1).sum()}")

print(f"\n--- Per-platform specific ---")
for p in PLATFORM_BOTS:
    print(f"  block_{p}_specific=1: {(firm[f'block_{p}_specific'] == 1).sum()}")

# ── 6. Write output ───────────────────────────────────────────────────────
out_path = DIR / "analysis_sample.csv"
firm.to_csv(out_path, index=False)
print(f"\nWrote {len(firm)} rows to {out_path}")
print(f"Columns: {len(firm.columns)}")

# ── Summary stats for non-fund 2024 ───────────────────────────────────────
print("\n--- Non-fund 2024 derived variable coverage ---")
nf = firm[firm["fund_flag"] == 0]
for v in ["log_at_2024", "roa_2024", "leverage_2024", "cash_ratio_2024",
          "rd_intensity_2024", "intan_ratio_2024", "log_mkcap_2024"]:
    n = nf[v].notna().sum()
    print(f"  {v:25s}  {n:5d} / {len(nf)}  ({100*n/len(nf):.1f}%)")
