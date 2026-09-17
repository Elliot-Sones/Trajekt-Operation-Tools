#!/usr/bin/env python3
"""Report-only: what changed in Trajekt_Dev vs the 'Trajekt_Dev Field Documentation' sheet + ERP index.
Writes NOTHING. Usage: python3 check.py            -> documentation drift only (default)
                        python3 check.py --data     -> also empty/sparse fields
                        python3 check.py --n8n      -> also active workflows writing dead columns
                        python3 check.py --health   -> also run the field-health pass (health.py) after the verdict
                        python3 check.py --no-usage -> skip the n8n/Fillout recompute of the Automations + Forms columns (faster)
"""
import json, re, sys, os, subprocess, urllib.request, urllib.parse, time
from fdc_env import DASH, OUT, load_env, sheets_token
BASE='appAqIfICwLXNquzF'; DOC='1nAA16LbtfpEacVcrteYJbHBP3iKDgpm_-cJD7Td8agA'; ERP='14CzW0F0heH5FnMfKI0Si5i-XrJK4mwkNXJa9tE1oMTM'
env=load_env()
AT_TOKEN=env['AIRTABLE_WRITE_TOKEN']; N8N=env.get('N8N_API_KEY')
SHEETS=sheets_token()
def get(u,h):
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=h)))
        except urllib.error.HTTPError as e:
            if e.code in(429,503): time.sleep(2*(i+1)); continue
            raise
AH={'Authorization':'Bearer '+AT_TOKEN}; SH={'Authorization':'Bearer '+SHEETS}
# ---------- live schema
sch=get(f'https://api.airtable.com/v0/meta/bases/{BASE}/tables',AH); json.dump(sch,open(f'{OUT}/schema.json','w'))
tid={t['id']:t['name'] for t in sch['tables']}; allf={f['id']:(t['name'],f['name']) for t in sch['tables'] for f in t['fields']}
TYPE={'multipleRecordLinks':'link','singleSelect':'select','multipleSelects':'multiSelect','singleLineText':'text','multilineText':'longText','multipleLookupValues':'lookup','multipleAttachments':'attachment','phoneNumber':'phone','aiText':'aiText','richText':'richText','autoNumber':'autoNumber','createdTime':'createdTime','lastModifiedTime':'lastModified'}
def related(t,f):  # same rules as build_all_tabs.py
    o=f.get('options',{}); ty=f['type']; names={x['id']:x['name'] for x in t['fields']}
    deref=lambda s: re.sub(r'\{(fld[A-Za-z0-9]+)\}',lambda m:'{'+names.get(m.group(1),allf.get(m.group(1),('','?'))[1])+'}',s)
    if ty=='multipleRecordLinks': return f"Links to: {tid.get(o.get('linkedTableId'),'?')} (reverse: {allf.get(o.get('inverseLinkFieldId'),('','?'))[1]})"
    if ty in('singleSelect','multipleSelects'):
        ch=[c['name'] for c in o.get('choices',[])]
        if len(ch)>12 or sum(map(len,ch))>220: return f"Options: {len(ch)} (e.g. {', '.join(x[:40] for x in ch[:3])} …) — full list in Airtable"
        return 'Options: '+', '.join(ch)
    if ty=='formula': return 'Formula: '+re.sub(r'\s+',' ',deref(o.get('formula','')))[:400]
    if ty=='multipleLookupValues': return f"Lookup: {allf.get(o.get('fieldIdInLinkedTable'),('','?'))[1]} via {names.get(o.get('recordLinkFieldId'),'?')}"
    if ty=='rollup':
        fn=re.sub(r'\s+',' ',o.get('formula','')).replace('values','').strip('() ') or 'SUM'
        return f"Rollup: {fn}({allf.get(o.get('fieldIdInLinkedTable'),('','?'))[1]}) via {names.get(o.get('recordLinkFieldId'),'?')}"
    if ty=='dateTime': return 'Zone: '+str(o.get('timeZone','')).replace('client','respondent browser')
    return None
# ---------- sheet
sh=get(f'https://sheets.googleapis.com/v4/spreadsheets/{DOC}?includeGridData=true&fields=sheets(properties(sheetId,title),data.rowData.values.formattedValue)',SH)
tabs={}
for s in sh['sheets']:
    rows=[[c.get('formattedValue','') for c in r.get('values',[])] for r in s['data'][0].get('rowData',[])]
    hdr=next((i for i,r in enumerate(rows) if r and r[0]=='Field name'),None)
    cols={h:i for i,h in enumerate(rows[hdr])} if hdr is not None else {}
    tabs[s['properties']['title']]={'gid':s['properties']['sheetId'],'cols':cols,'fields':{(r+['']*8)[0]:(r+['']*8)[:8] for r in rows[hdr+1:] if r and r[0]} if hdr is not None else {}}
json.dump({k:{'gid':v['gid'],'fields':v['fields']} for k,v in tabs.items()},open(f'{OUT}/sheet.json','w'))
R={'tables':{},'new_tables':[],'tabs_without_table':[],'summary':{}}
live={t['name']:t for t in sch['tables']}
R['new_tables']=[n for n in live if n not in tabs]
R['tabs_without_table']=[n for n in tabs if n not in live and n not in('README',) and not n.startswith('(deleted)')]
for tn,t in live.items():
    tab=tabs.get(tn,{'fields':{}})['fields']; ln={f['name']:f for f in t['fields']}
    new=[n for n in ln if n not in tab]; gone=[n for n in tab if n not in ln]
    renames=[]; recreated=[]
    fi=tabs.get(tn,{}).get('cols',{}).get('Field ID')
    sheet_ids={row[fi]:name for name,row in tab.items() if fi is not None and len(row)>fi and row[fi]}
    if sheet_ids:   # exact: the sheet carries field ids
        for n in list(new):
            fid=ln[n]['id']
            if fid in sheet_ids and sheet_ids[fid] in gone:
                renames.append((sheet_ids[fid],n,'exact')); gone.remove(sheet_ids[fid]); new.remove(n)
        for n in ln:
            if n in tab and tab[n][fi] and tab[n][fi]!=ln[n]['id']: recreated.append((n,tab[n][fi],ln[n]['id']))
    for g in list(gone):   # fallback guess when no id is available
        cand=[n for n in new if TYPE.get(ln[n]['type'],ln[n]['type'])==tab[g][1] and (re.sub(r'[^a-z0-9]','',n.lower())[:6]==re.sub(r'[^a-z0-9]','',g.lower())[:6] or n.lower() in g.lower() or g.lower() in n.lower())]
        if len(cand)==1: renames.append((g,cand[0],'guess')); gone.remove(g); new.remove(cand[0])
    typechg=[(n,tab[n][1],TYPE.get(ln[n]['type'],ln[n]['type'])) for n in ln if n in tab and tab[n][1]!=TYPE.get(ln[n]['type'],ln[n]['type'])]
    reldrift=[]
    for n in ln:
        if n in tab:
            want=related(t,ln[n])
            if want and tab[n][3] and tab[n][3]!=want: reldrift.append((n,tab[n][3],want))
    order_changed=[n for n in ln if n in tab]!=[n for n in tab if n in ln]
    R['tables'][tn]={'field_count':len(ln),'sheet_count':len(tab),'new':new,'removed':gone,'renamed':renames,'recreated':recreated,'type_changed':typechg,'related_drift':reldrift,'order_changed':order_changed}
# ---------- data population (empty / near-empty fields)
if '--data' in sys.argv:
    for tn,t in live.items():
        recs=[];off=None
        while True:
            u=f"https://api.airtable.com/v0/{BASE}/{t['id']}?pageSize=100"+(f'&offset={off}' if off else '')
            d=get(u,AH); recs+=d['records']; off=d.get('offset')
            if not off: break
        n=len(recs); fill={}
        for f in t['fields']:
            fill[f['name']]=sum(1 for r in recs if r['fields'].get(f['name']) not in (None,'',[],0,False))
        R['tables'][tn]['rows']=n
        R['tables'][tn]['empty_fields']=[k for k,v in fill.items() if v==0 and n>0]
        R['tables'][tn]['sparse_fields']=[(k,v) for k,v in fill.items() if 0<v<=5 and n>=20]
        R['tables'][tn]['fill']=fill
# ---------- n8n dead references (workflows naming fields that no longer exist)
if '--n8n' in sys.argv and N8N:
    NH={'X-N8N-API-KEY':N8N}; B='https://trajektsports.app.n8n.cloud/api/v1'
    wl=get(f'{B}/workflows?limit=250',NH)['data']; dead=[]
    livenames={f['name'] for t in sch['tables'] for f in t['fields']}
    for w in wl:
        if not w['active']: continue
        wf=get(f"{B}/workflows/{w['id']}",NH)
        for nd in wf['nodes']:
            if 'airtable' not in nd.get('type','').lower(): continue
            prm=nd.get('parameters',{}); cols=prm.get('columns') if isinstance(prm.get('columns'),dict) else None
            if cols and isinstance(cols.get('value'),dict):
                tbl=prm.get('table',{}).get('value') if isinstance(prm.get('table'),dict) else None
                tf={f['name'] for f in live[tid[tbl]]['fields']} if tbl in tid else livenames
                for col in cols['value']:
                    if col!='id' and col not in tf: dead.append((w['name'],nd['name'],col,tid.get(tbl,'?')))
    R['n8n_dead_columns']=dead
# ---------- ERP index counts
erp=get(f"https://sheets.googleapis.com/v4/spreadsheets/{ERP}/values/Sheet1!A12:F30",SH).get('values',[])
R['erp_index']=[]
for r in erp:
    r=(r+['']*6)[:6]; tn=r[0]
    m=re.match(r'(\d+) fields',r[3] or '')
    if tn in live: R['erp_index'].append((tn,int(m.group(1)) if m else None,len(live[tn]['fields']),r[5]))
json.dump(R,open(f'{OUT}/report.json','w'),indent=1,default=list)
# ---------- Automations / Forms drift (recompute both columns exactly as build_all_tabs does, diff vs sheet)
if '--no-usage' not in sys.argv:
    import subprocess as _sp
    _sp.run(['python3',os.path.join(os.path.dirname(os.path.abspath(__file__)),'prepare.py')],check=True,capture_output=True,env={**os.environ,'FDC_OUT':OUT})
    sys.argv.append('--dry'); sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
    os.environ['FDC_OUT']=OUT
    import importlib.util
    spec=importlib.util.spec_from_file_location('bat',os.path.join(os.path.dirname(os.path.abspath(__file__)),'build_all_tabs.py'))
    bat=importlib.util.module_from_spec(spec)
    try: spec.loader.exec_module(bat)   # dry run: prints counts, exits before any write
    except SystemExit: pass
    plan=json.load(open(f'{OUT}/plan_all.json'))
    for p_ in plan:
        tab=tabs.get(p_['table'],{'fields':{}})['fields']; x=R['tables'].get(p_['table'])
        if not x: continue
        x['automations_drift']=[]; x['forms_drift']=[]
        for r in p_['rows']:
            old=tab.get(r[0])
            if not old: continue
            cols=tabs.get(p_['table'],{}).get('cols',{}); ai=cols.get('Automations',4); fmi=cols.get('Forms',5)
            if (old[ai] or '').strip()!=(r[4] or '').strip(): x['automations_drift'].append((r[0],old[ai],r[4]))
            if (old[fmi] or '').strip()!=(r[5] or '').strip(): x['forms_drift'].append((r[0],old[fmi],r[5]))
# ---------- print: one answer first, then only what needs updating
changes=[]
for tn in R['new_tables']: changes.append(f"NEW TABLE {tn}: add a tab")
for tn in R['tabs_without_table']:
    if tn!='Monthly Log': changes.append(f"TAB {tn}: table no longer exists (rename tab to '(deleted) {tn}')")
for tn,x in R['tables'].items():
    for n in x['new']: changes.append(f"{tn}: new field {n}")
    for n in x['removed']: changes.append(f"{tn}: field removed {n}")
    for a,b,how in x['renamed']: changes.append(f"{tn}: renamed {a} → {b}"+(" (exact, by field id)" if how=='exact' else " (guess: same type, similar name)"))
    for n,a,b in x.get('recreated',[]): changes.append(f"{tn}: {n} was deleted and re-created (field id {a} → {b})")
    for n,a,b in x['type_changed']: changes.append(f"{tn}: {n} type {a} → {b}")
    for n,a,b in x['related_drift']: changes.append(f"{tn}: {n} options/link/formula changed")
    if x['order_changed']: changes.append(f"{tn}: field order changed")
    for n,a,b in x.get('automations_drift',[]): changes.append(f"{tn}: {n} automations changed  [sheet: {(a or '-').replace(chr(10),' / ')[:70]}]  [live: {(b or '-').replace(chr(10),' / ')[:70]}]")
    for n,a,b in x.get('forms_drift',[]): changes.append(f"{tn}: {n} forms changed  [sheet: {(a or '-').replace(chr(10),' / ')[:70]}]  [live: {(b or '-').replace(chr(10),' / ')[:70]}]")
for tn,idx,livec,date in R['erp_index']:
    if idx!=livec: changes.append(f"ERP index: {tn} says {idx} fields, live has {livec}")
if changes:
    print(f"DOCUMENTATION NEEDS UPDATING: {len(changes)} change(s)")
    for c in changes: print("  -",c)
else:
    print("DOCUMENTATION IS UP TO DATE. Nothing to change.")
if '--data' in sys.argv:
    print("\nEmpty / sparse fields (informational, not a documentation change):")
    for tn,x in R['tables'].items():
        if x.get('empty_fields'): print(f"  {tn}: EMPTY {', '.join(x['empty_fields'])}")
if R.get('n8n_dead_columns'):
    print("\nActive n8n nodes writing columns that no longer exist (informational):")
    for w,nd,col,tb in R['n8n_dead_columns']: print(f"  {w} :: {nd} :: {col}")
print(f"\n(nothing was written; details in {OUT}/report.json)")

if '--health' in sys.argv:
    import subprocess as _sp; print(); sys.stdout.flush(); _sp.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),'health.py')]+([ '--full'] if '--full' in sys.argv else []), env={**os.environ,'FDC_OUT':OUT})
