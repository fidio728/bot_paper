# Pilot Test — Layer 1 Mechanism Validation

## Purpose

Test whether firms whose robots.txt rules block AI search crawlers from public pages (`search_public_block = 1`) have lower official website visibility in ChatGPT Search results compared to matched control firms (`search_public_block = 0`).

## Files

- `pilot_recording_sheet.csv` — 300 rows (60 firms × 5 queries), pre-filled with prompts. Located at: `bot_paper/stata/stata-mcp-folder/stata-mcp-result/pilot_recording_sheet.csv`
- `pilot_sample.csv` — 60 firms (30 pairs), same location
- This folder (`pilot_tests/`) — save all ChatGPT response markdown files here

## Sample

30 matched pairs (1:1 within SIC 2-digit × size tercile). Each pair has:
- 1 **control** firm (`search_public_block = 0`)
- 1 **treated** firm (`search_public_block = 1`)

The `host` column in `pilot_recording_sheet.csv` is the official website domain to look for in citations.

## Queries (5 per firm)

For each firm, run these 5 prompts in ChatGPT (with web search enabled):

```
Q1: What does [Company] ([TICKER]) do?
Q2: [Company] ([TICKER]) latest financial performance
Q3: [Company] ([TICKER]) investor relations
Q4: [Company] ([TICKER]) management team and leadership
Q5: [Company] ([TICKER]) recent news
```

The exact prompts (with company names and tickers filled in) are in the `prompt` column of `pilot_recording_sheet.csv`.

## Rules for Running Queries

1. **Turn off ChatGPT memory** — Go to Settings → Memory → turn off both "参考保存的记忆" and "参考历史聊天记录"
2. **New conversation for EVERY query** — do not ask multiple questions in one conversation
3. **Web search must be enabled** — ChatGPT should show citations with numbered references
4. **Same day, same account** — try to finish all queries in 1-2 sessions
5. **Include ticker for ambiguous names** — the prompts already include tickers
6. **Do not tell ChatGPT what you are testing**

## What to Save

For each query, save TWO things:

### 1. Response markdown (in this folder)

Copy the full ChatGPT response (with inline citation links) and save as a markdown file. Use this naming convention:

```
Pair{XX}_{control/treated}_{TICKER}_Q{N}.md
```

Example: `Pair01_control_ARHS_Q1.md`

Format inside the file:

```markdown
> From: [paste the ChatGPT share URL if available]

# you asked

[paste the prompt]

---

# chatgpt response

[paste the full response with inline citation links like [Source Name](url)]
```

### 2. Sources panel (append to the same file OR save separately)

After the response, click "Sources" at the bottom of ChatGPT's answer. Copy all listed sources and append them to the file:

```markdown
---

# sources panel

[paste all sources listed in the panel]
```

## What to Fill in the Excel

Open `pilot_recording_sheet.csv` in Excel. For each row (each firm × query), fill these columns:

| Column | What to record | How |
|---|---|---|
| `OfficialCited` | Does the firm's official website appear in **inline citations** (the numbered [1][2][3] references in the answer text)? | 0 or 1 |
| `OfficialListed` | Does the official website appear anywhere in the **Sources panel** (the expandable list at the bottom)? | 0 or 1 |
| `OfficialRank` | What position is the official website's FIRST appearance among inline citations? Count unique domains in order of appearance. | Number (1 = first cited). Put 999 if not cited. |
| `n_cited_sources` | How many unique domains are cited inline in the response? | Count unique domains |
| `source_domains` | List all domains cited inline, comma-separated | e.g., `reuters.com, yahoo.com, arhaus.com` |
| `timestamp` | When you ran this query | `YYYY-MM-DD HH:MM` |
| `notes` | Anything unusual (search didn't trigger, ambiguous company, etc.) | Free text |

### How to identify "official website"

The official website domain is in the `host` column of the spreadsheet. For example:
- If `host = www.arhaus.com`, then any citation from `arhaus.com` or `ir.arhaus.com` counts as official
- Subdomains count (e.g., `ir.arhaus.com` = official)
- Third-party sites do NOT count (e.g., `yahoo.com/quote/ARHS` is not official)

### How to count OfficialRank

Read through the response and note each inline citation in order. Count by unique domain:
- First citation is from reuters.com → rank 1
- Second citation is also reuters.com → skip (already counted)
- Third citation is from arhaus.com → rank 2
- So `OfficialRank = 2`

If the official website never appears in inline citations, `OfficialRank = 999`.

## Workflow Suggestion

Work pair by pair, doing all 5 queries for the control firm first, then all 5 for the treated firm:

1. Pair 1 control (ARHS) — Q1, Q2, Q3, Q4, Q5
2. Pair 1 treated (LEFUF) — Q1, Q2, Q3, Q4, Q5
3. Pair 2 control — Q1, Q2, Q3, Q4, Q5
4. Pair 2 treated — Q1, Q2, Q3, Q4, Q5
5. ...

This way you immediately see if there's a within-pair contrast.

## After Finishing

When all 300 queries are done:
1. Save the completed `pilot_recording_sheet.csv`
2. All markdown files should be in this `pilot_tests/` folder
3. Give both to Claude — it will extract variables, verify against the markdown files, and run the mechanism regression

## Total Workload

- 60 firms × 5 queries = 300 queries
- Each takes ~1-2 minutes
- Estimate: 5-8 hours total

## Example (Pair 1 control already done)

Arhaus (ARHS, control, search_public_block=0):

| Query | OfficialCited | OfficialRank | n_cited |
|---|---|---|---|
| Q1 (what does) | 1 | 6 | 6 |
| Q2 (financials) | 1 | 1 | 8 |
| Q3 (investor relations) | 1 | 1 | 4 |
| Q4 (management) | 1 | 1 | 7 |
| Q5 (recent news) | 1 | 3 | 3 |

OfficialCitedCoverage = 5/5 = 100%. Official site appeared in every query.
