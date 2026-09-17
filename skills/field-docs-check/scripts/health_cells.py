"""The text of a Health cell per field, computed from last_run/health.json (written by health.py).
Single source of truth for health.py --docs-preview, write_health.py and build_all_tabs.py.
Cell = '✅' when the field has no finding, else one line per 🔴/🟡 finding in the script's own words (no fill count:
Elliot 2026-09-17, "just a green check if everything looks good"). 'no description in Airtable' is left out
(it is the "no desc" count on the scoreboard)."""
from collections import defaultdict
OK='✅'
def cells_from(h):
    flags=defaultdict(list)
    for x in h.get('findings',[]):
        if x['code']!='no-description': flags[(x['table'],x['field'])].append(f"{x['sev']} {x['msg']}")
    return {tn:{fn:('\n'.join(flags[(tn,fn)]) if flags.get((tn,fn)) else OK) for fn in fs} for tn,fs in h.get('fields',{}).items()}
def health_date(h): return (h.get('generated') or '')[:10]
def header_text(h): return f"Health (as of {health_date(h)})" if health_date(h) else 'Health'
def is_flagged(cell): return '🔴' in cell or '🟡' in cell
