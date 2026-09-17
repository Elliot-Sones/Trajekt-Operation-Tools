#!/usr/bin/env python3
"""Write or refresh the Health column (column I) on every table tab of 'Trajekt_Dev Field Documentation'.
Source: last_run/health.json (from health.py, or check.py --health). Touches ONLY column I: the header
'Health (as of <date>)', one cell per field aligned to the tab's CURRENT 'Field name' rows, column width and
the format copied from column H (PASTE_FORMAT carries H's alternating-colour banding into I by itself; never add banding on top, Sheets rejects overlaps). Other columns are never read for writing, so unapproved documentation
changes cannot slip in. Dry-run default; --apply writes (a sheet write: needs Elliot's yes first).
--force skips the "health.json older than 24 h" guard."""
import json, sys, datetime as dt, urllib.request, urllib.parse, urllib.error
from fdc_env import OUT as S, sheets_token
from health_cells import cells_from, header_text, health_date, is_flagged
ID='1nAA16LbtfpEacVcrteYJbHBP3iKDgpm_-cJD7Td8agA'; COL='I'; CI=8; WIDTH=360; PAD=80
APPLY='--apply' in sys.argv
h=json.load(open(f'{S}/health.json')); cells=cells_from(h); HDR=header_text(h)
age_h=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(h['generated'])).total_seconds()/3600
if age_h>24 and '--force' not in sys.argv: sys.exit(f"health.json is {age_h/24:.1f} days old (generated {h['generated'][:16]}Z): run health.py first, or pass --force")
AT=sheets_token(); H={'Authorization':'Bearer '+AT,'Content-Type':'application/json'}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=H)))
def post(u,body):
    try: return json.load(urllib.request.urlopen(urllib.request.Request(u,data=json.dumps(body).encode(),method='POST',headers=H)))
    except urllib.error.HTTPError as e: sys.exit(f"Sheets API {e.code} on {u.rsplit('/',1)[-1].split('?')[0]}: {e.read().decode()[:1500]}")
meta=get(f'https://sheets.googleapis.com/v4/spreadsheets/{ID}?fields=sheets(properties(sheetId,title,gridProperties(columnCount)))')
sheets={s['properties']['title']:s for s in meta['sheets']}
tabs=[t for t in sheets if t in cells]
skipped=[t for t in sheets if t not in cells and t!='README' and not t.startswith('(deleted)')]
q='&'.join('ranges='+urllib.parse.quote(f"'{t}'!A1:A600") for t in tabs)
vals=get(f'https://sheets.googleapis.com/v4/spreadsheets/{ID}/values:batchGet?{q}&majorDimension=COLUMNS')['valueRanges']
plan=[]; problems=[]
for t,vr in zip(tabs,vals):
    col=(vr.get('values') or [[]])[0]
    if 'Field name' not in col: problems.append(f"{t}: no 'Field name' header in column A"); continue
    hi=col.index('Field name'); names=[]
    for v in col[hi+1:]:
        if not v: break
        names.append(v)
    missing=[n for n in names if n not in cells[t]]; extra=[n for n in cells[t] if n not in names]
    if missing: problems.append(f"{t}: {len(missing)} row(s) on the tab have no health data (not on the live table?): {missing[:5]}")
    values=[[cells[t].get(n,'')] for n in names]
    plan.append({'tab':t,'sheetId':sheets[t]['properties']['sheetId'],'hdr_row':hi+1,'n':len(names),'flagged':sum(1 for v in values if is_flagged(v[0])),
                 'values':values,'extra':extra,'cols':sheets[t]['properties']['gridProperties'].get('columnCount',26)})
print(f"Health column ← health.json generated {h['generated'][:16]}Z  header: {HDR!r}  width {WIDTH}px, format = column H")
for p in plan:
    print(f"  {p['tab']:26} rows {p['n']:3}  flagged {p['flagged']:3}"+(f"  (+{len(p['extra'])} live field(s) not on the tab: skipped)" if p['extra'] else ''))
for s in skipped: print(f"  {s:26} SKIPPED: no health data for this tab")
for x in problems: print('  ⚠',x)
if not APPLY: print('\nDRY RUN (nothing written). Add --apply to write column I.'); sys.exit()
if problems and '--force' not in sys.argv: sys.exit('REFUSING --apply while rows are unmatched (pass --force to write blanks for them)')
data=[]
for p in plan:
    tn=p['tab'].replace("'","''"); r0=p['hdr_row']
    data.append({'range':f"'{tn}'!{COL}{r0}",'values':[[HDR]]})
    if p['n']: data.append({'range':f"'{tn}'!{COL}{r0+1}:{COL}{r0+p['n']}",'values':p['values']})
    data.append({'range':f"'{tn}'!{COL}{r0+1+p['n']}:{COL}{r0+p['n']+PAD}",'values':[['']]*PAD})
r=post(f'https://sheets.googleapis.com/v4/spreadsheets/{ID}/values:batchUpdate',{'valueInputOption':'RAW','data':data})
print('cells written',r.get('totalUpdatedCells'))
rng=lambda sid,r0,r1,c0,c1:{'sheetId':sid,'startRowIndex':r0,'endRowIndex':r1,'startColumnIndex':c0,'endColumnIndex':c1}
reqs=[]
for p in plan:
    sid=p['sheetId']; r0=p['hdr_row']-1; r1=r0+1+p['n']+PAD
    if p['cols']<CI+1: reqs.append({'appendDimension':{'sheetId':sid,'dimension':'COLUMNS','length':CI+1-p['cols']}})
    reqs.append({'copyPaste':{'source':rng(sid,r0,r1,CI-1,CI),'destination':rng(sid,r0,r1,CI,CI+1),'pasteType':'PASTE_FORMAT'}})
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':CI,'endIndex':CI+1},'properties':{'pixelSize':WIDTH},'fields':'pixelSize'}})
post(f'https://sheets.googleapis.com/v4/spreadsheets/{ID}:batchUpdate',{'requests':reqs})
print(f"formats applied to {len(plan)} tabs; Health column = {HDR}")
