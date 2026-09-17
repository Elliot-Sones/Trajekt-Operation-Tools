"""The text of a Health cell per field, computed from last_run/health.json (written by health.py).
Single source of truth for health.py --docs-preview, write_health.py and build_all_tabs.py.
Cell = 'filled N/M' (+ ' · last <days>d n/m' when the recent window is a real subset), then one line per
🔴/🟡 finding in the script's own words. Read-only field types (formula, lookup, rollup, count, autoNumber,
created/modified stamps) carry no fill line. 'no description in Airtable' is left out (it is the "no desc" count)."""
from collections import defaultdict
RO=('formula','multipleLookupValues','rollup','count','autoNumber','createdTime','lastModifiedTime','createdBy','lastModifiedBy')
def cells_from(h):
    days=h.get('days',90); flags=defaultdict(list)
    for x in h.get('findings',[]):
        if x['code']!='no-description': flags[(x['table'],x['field'])].append(f"{x['sev']} {x['msg']}")
    out={}
    for tn,fs in h.get('fields',{}).items():
        d={}
        for fn,st in fs.items():
            parts=[]
            if st['type'] not in RO and st['rows']:
                parts.append(f"filled {st['filled']}/{st['rows']}"+(f" · last {days}d {st['recent_filled']}/{st['recent_rows']}" if 10<=st['recent_rows']<st['rows'] else ''))
            parts+=flags.get((tn,fn),[])
            d[fn]='\n'.join(parts)
        out[tn]=d
    return out
def health_date(h): return (h.get('generated') or '')[:10]
def header_text(h): return f"Health (as of {health_date(h)})" if health_date(h) else 'Health'
def is_flagged(cell): return '🔴' in cell or '🟡' in cell
