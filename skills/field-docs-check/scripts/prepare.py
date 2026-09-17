#!/usr/bin/env python3
"""Gather the inputs build_all_tabs.py needs (run check.py first). Writes only into the last_run folder."""
import json, re, os, glob, time, urllib.request, urllib.error
from fdc_env import DASH, OUT, load_env, sheets_token
env=load_env()
def get(u,h):
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=h)))
        except urllib.error.HTTPError as e:
            if e.code in(429,503): time.sleep(2*(i+1)); continue
            raise
sch=json.load(open(f'{OUT}/schema.json'))
# tabs.json in the row-list shape build_all_tabs expects
sh=json.load(open(f'{OUT}/sheet.json'))
import subprocess
SHEETS=sheets_token()
full=get('https://sheets.googleapis.com/v4/spreadsheets/1nAA16LbtfpEacVcrteYJbHBP3iKDgpm_-cJD7Td8agA?includeGridData=true&fields=sheets(properties(sheetId,title),data.rowData.values.formattedValue)',{'Authorization':'Bearer '+SHEETS})
tabs={s['properties']['title']:{'rows':[[c.get('formattedValue','') for c in r.get('values',[])] for r in s['data'][0].get('rowData',[])]} for s in full['sheets']}
json.dump(tabs,open(f'{OUT}/tabs.json','w'))
# n8n usage (active workflows only)
NH={'X-N8N-API-KEY':env['N8N_API_KEY']}; B='https://trajektsports.app.n8n.cloud/api/v1'
os.makedirs(f'{OUT}/wf',exist_ok=True)
for f in glob.glob(f'{OUT}/wf/*.json'): os.remove(f)
for w in get(f'{B}/workflows?limit=250',NH)['data']:
    if re.search(r'\[\s*WIP\s*\]',w['name'],re.I): continue          # WIP workflows are not documented
    if w['active'] or w['name'].startswith('Daily'):
        json.dump(get(f"{B}/workflows/{w['id']}",NH),open(f"{OUT}/wf/{w['id']}.json",'w'))
def strip(o):
    if isinstance(o,dict): return {k:strip(v) for k,v in o.items() if k not in('schema','cachedResultName','cachedResultUrl')}
    if isinstance(o,list): return [strip(x) for x in o]
    return o
tid={t['id']:t['name'] for t in sch['tables']}; wfs=[]
for p in glob.glob(f'{OUT}/wf/*.json'):
    d=json.load(open(p))
    for n in d.get('nodes',[]):
        prm=strip(n.get('parameters',{})); cols=prm.get('columns') if isinstance(prm.get('columns'),dict) else {}
        tb=prm.get('table'); table=tb.get('value') if isinstance(tb,dict) else tb
        wfs.append((d['name'],n['name'],table if table in tid else None,json.dumps({k:v for k,v in prm.items() if k!='columns'}),json.dumps(cols.get('value',{})) if cols else ''))
usage={}
for t in sch['tables']:
    for f in t['fields']:
        nm=f['name']; pat=re.compile(r'(?<![A-Za-z0-9])'+re.escape(nm)+r'(?![A-Za-z0-9])'); distinctive=len(nm)>=9 or ' ' in nm; hits={}
        for wn,nn,table,rtxt,wtxt in wfs:
            w=f['id'] in wtxt or (pat.search(wtxt) and (table==t['id'] or (table is None and distinctive)))
            r=f['id'] in rtxt or (distinctive and pat.search(rtxt))
            if w or r:
                h=hits.setdefault(wn,{'w':[],'r':0})
                if w: h['w'].append(nn)
                if r: h['r']+=1
        if hits: usage[f"{t['name']}::{nm}"]=hits
json.dump(usage,open(f'{OUT}/usage_all.json','w'),indent=1)
# fillout auto-map (published forms; sequential to respect the rate limit)
FH={'Authorization':'Bearer '+env['FILLOUT_API_KEY']}
forms=get('https://api.fillout.com/v1/api/forms?limit=200',FH); forms=forms if isinstance(forms,list) else forms.get('forms',[])
norm=lambda s:re.sub(r'[^a-z0-9]','',s.lower()); byname={}
for t in sch['tables']:
    for f in t['fields']: byname.setdefault(norm(f['name']),[]).append((t['name'],f['name']))
fmap={}
for fm in forms:
    if not fm.get('isPublished'): continue
    meta=get(f"https://api.fillout.com/v1/api/forms/{fm['formId']}",FH); time.sleep(0.4)
    for q in meta.get('questions',[]):
        for tn,fn in byname.get(norm(q['name']),[]): fmap.setdefault(f'{tn}::{fn}',set()).add(f"{fm['name']} — \"{q['name']}\"")
json.dump({k:sorted(v) for k,v in fmap.items()},open(f'{OUT}/formmap_auto.json','w'),indent=1)
print('prepared:',len(tabs),'tabs |',len(glob.glob(f'{OUT}/wf/*.json')),'workflows |',len(usage),'field usages |',len(fmap),'form matches')

import subprocess as _sp, sys as _sys
_sp.run([_sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),'form_bindings.py')], check=True, env={**os.environ,'FDC_OUT':OUT}, stdout=_sp.DEVNULL)
print('form bindings derived from real submissions → form_bindings.json')
