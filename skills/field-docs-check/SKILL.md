---
name: field-docs-check
description: Use when asked whether the Airtable field documentation is up to date, what changed in Trajekt_Dev (new fields, renamed or removed fields, new tables), to refresh the "Trajekt_Dev Field Documentation" Google Sheet or the ERP Documentation Index, or about the health of the fields (empty or unused fields, weird or wrong-looking values, duplicates, bad attachments). Also when an Airtable rename may have broken an n8n write.
---

# Field docs check

Compares the live Trajekt_Dev base to the two documentation sheets and reports the differences. **Reporting is the deliverable. Writing is a separate, gated step.**

## The rule

`$SKILL_DIR` = this skill's folder (the base directory printed when the skill loads). Scripts read `.env.local` and the Google service-account key from `FDC_DASH_DIR` (default: Elliot's revenue-dashboard checkout); see `scripts/fdc_env.py`.

Run `check.py` first, every time. Show Elliot the list. Do not touch the sheets until he replies **yes** to that list. A "yes" from earlier in the conversation, or to a different list, does not count.

## Steps

1. Run the check (writes nothing). One command does both the documentation drift AND the field-health pass:
   ```bash
   python3 "$SKILL_DIR"/scripts/check.py --health
   ```
   Takes 3–5 minutes (n8n REST + Fillout submissions + every Airtable row). `--no-usage` skips the Automations/Forms recompute; `--full` lists every health finding instead of 6 per table; `--data`/`--n8n` add the raw empty-field and dead-column scans if he asks for them.
2. Reply in exactly this shape, using the script's own lines:
   ```
   Documentation: <first line of the script: "up to date" or "needs updating: N change(s)">
   - <change list verbatim, if any>
   Say yes and I'll apply these.            <- only when there are changes

   Field health (<date>)
   <scoreboard table verbatim>
   🔴 <the wrong-looking-data lines verbatim>
   🟡 <the hygiene lines as the script prints them, capped>
   <the script's last line verbatim: "Sheet Health column: as of <date> on N of N tabs" (+ "stale …") or "none yet">
   Say yes and I'll refresh the Health column.   <- only when that line says stale or none yet
   Fixing any finding is an Airtable write and needs a yes per item.
   ```
   No other commentary. Renames are labeled exact (by field id) or guess; keep the label.
3. Only after his **yes** to the documentation list: refresh the tabs. Add a description for every NEW field to `scripts/descriptions.json` first (`"Table::Field": "text"`, optional `"NOTE Table::Field"`, `"TABLE Name"` blurb); fields without one get a name-derived placeholder.
   ```bash
   python3 "$SKILL_DIR"/scripts/prepare.py                   # gathers n8n usage + Fillout matches into last_run/
   python3 "$SKILL_DIR"/scripts/build_all_tabs.py            # dry run: per-table counts
   python3 "$SKILL_DIR"/scripts/build_all_tabs.py --apply    # rewrites every tab, creates tabs for new tables
   ```
   `--apply` creates a tab per new table: that is a tab add, so name the new tables in the list he says yes to.
   Run the apply straight after the yes. Never run `check.py` in between: it refreshes `last_run/schema.json`, and the apply would then write field changes he has not seen. For a cosmetic re-apply (notes, wording, formatting) use `build_all_tabs.py --apply --same-fields`, which refuses to write if any tab's field set no longer matches Airtable.
4. Then the ERP index (`14CzW0F0heH5FnMfKI0Si5i-XrJK4mwkNXJa9tE1oMTM`, tab Sheet1, rows 12–30): field counts in column D, date in F, chip in E. Status column C is Elliot's; never change it.
5. Health column = column I on every table tab (added 2026-09-17 on Elliot's yes; header `Health (as of <date>)`, one cell per field: `filled N/M` + one line per 🔴/🟡 finding). Refreshing it is a sheet write: only after his **yes** to that.
   ```bash
   python3 "$SKILL_DIR"/scripts/write_health.py            # dry run: rows / flagged per tab, unmatched rows
   python3 "$SKILL_DIR"/scripts/write_health.py --apply    # writes ONLY column I (cells, header date, width, format)
   ```
   It aligns each cell to the tab's CURRENT Field name rows and never rewrites columns A–H, so it is safe while documentation changes are still pending. Source = `last_run/health.json`; it refuses when that file is older than 24 h (`--force` overrides). `build_all_tabs.py --apply` rewrites column I from the same file, so run `check.py --health` (or `health.py`) before a full apply or the column is written blank.

## Field health (what `--health` runs; standalone when he asks only about the data)

Standalone use:
```bash
python3 "$SKILL_DIR"/scripts/health.py            # scoreboard + capped findings
python3 "$SKILL_DIR"/scripts/health.py --full     # every finding
python3 "$SKILL_DIR"/scripts/health.py --table "Installs"
```
It writes nothing; findings are evidence, not fixes: every repair is an Airtable write that needs his yes per item.
`health.py --docs-preview` shows the per-field Health cell text the sheet's Health column carries (fill count + flags; built in `scripts/health_cells.py`, the one place that text is defined). Checks: empty / sparse / abandoned fields (no value
on recent rows), constant fields, numbers or dates stored as text, invalid emails / URLs / phones, negative hours or costs, outliers
(>20× median), far-future or far-past dates, end-before-start on date pairs, formula errors, HTML or empty attachments, recent rows all
zero (automation default-0 pattern), unused select options, option twins (case / spacing), stray whitespace, placeholder values,
duplicate primary values, test rows, leftover or misspelled field names, missing Airtable descriptions. `--days N` sets the recent
window (default 90). Contract-style dates are allowed 6 years ahead; other dates 400 days.

## What "changed" means

| Signal | Source |
|---|---|
| NEW / REMOVED field | live field names vs the tab's Field name column |
| RENAMED | a removed + a new field with the same Type and a similar name (guess) |
| TYPE | Type column differs from the live type (mapped vocabulary: link, select, multiSelect, text, longText, lookup…) |
| RELATED DRIFT | the tab's Related cell no longer matches the live options / link target / formula |
| AUTOMATIONS / FORMS changed | the Automations or Forms cell differs from a fresh recompute. Automations: active n8n workflow JSON via REST. Forms: `form_bindings.py` derives question → table.field from REAL submissions (the row each submission created, found by its stamped submission id or by creation time + matching values; only writable field types; Yes/No coincidences need two agreeing rows). Fillout's API exposes no mapping, so evidence from data is the only true source. Name-matching + the hand map are the fallback for forms with no recent submissions |
| EMPTY / SPARSE | 0 rows filled / ≤5 rows filled (tables with ≥20 rows) |
| n8n dead columns | an ACTIVE workflow's Airtable node maps a column that no longer exists (the rename-zeroes-invoices failure mode) |
| HEALTH STALE | the Health column's header date on the sheet is older than the latest health run (last line of the check) |

## Never

- Write to a sheet or Airtable from the check.
- Add a tab, row or column without Elliot naming it and saying yes.
- Delete tabs for deleted tables: rename them `(deleted) …` instead.
- Change the ERP index Status column.

## Access

Sheets: service account `sheets-editor@trajekt-sheets-1148.iam.gserviceaccount.com` via `trajekt/trajekt-revenue-dashboard/sheets_token.py` (the rclone token cannot use the Sheets API). Airtable: `AIRTABLE_WRITE_TOKEN` in that repo's `.env.local` (read token is dead). n8n: `N8N_API_KEY`, same file.
