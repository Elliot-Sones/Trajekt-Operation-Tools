#!/usr/bin/env python3
"""Field health for Trajekt_Dev: empty / sparse / abandoned fields, wrong-looking values, hygiene. READ-ONLY.
Usage: python3 health.py [--full] [--table "Work Orders"] [--days 90]
Prints a scoreboard (worst table first) then findings: 🔴 wrong-looking data, 🟡 hygiene. Full detail in last_run/health.json."""
import json, os, re, sys, time, statistics, datetime as dt, urllib.request, urllib.parse, urllib.error
from collections import Counter, defaultdict
from fdc_env import DASH, OUT, load_env
BASE='appAqIfICwLXNquzF'
env=load_env()
AH={'Authorization':'Bearer '+env['AIRTABLE_WRITE_TOKEN']}
FULL='--full' in sys.argv
ONLY=sys.argv[sys.argv.index('--table')+1] if '--table' in sys.argv else None
DAYS=int(sys.argv[sys.argv.index('--days')+1]) if '--days' in sys.argv else 90
NOW=dt.datetime.now(dt.timezone.utc); RECENT=NOW-dt.timedelta(days=DAYS)
def get(u):
    for i in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=AH)))
        except urllib.error.HTTPError as e:
            if e.code in(429,503): time.sleep(2*(i+1)); continue
            raise
sch=get(f'https://api.airtable.com/v0/meta/bases/{BASE}/tables')
tid={t['id']:t['name'] for t in sch['tables']}
def rows_of(t):
    recs=[];off=None
    while True:
        d=get(f"https://api.airtable.com/v0/{BASE}/{t['id']}?pageSize=100"+(f'&offset={off}' if off else ''))
        recs+=d.get('records',[]); off=d.get('offset')
        if not off: break
    for r in recs: r['_ts']=dt.datetime.fromisoformat(r['createdTime'].replace('Z','+00:00'))
    return recs
# ---------- validators
EMAIL=re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$'); URL=re.compile(r'^https?://\S+$',re.I)
PHONE=re.compile(r'^\+?[\d\s().-]{7,}$'); NUMLIKE=re.compile(r'^\s*[-+$]?\s*\d[\d,]*(\.\d+)?\s*%?\s*$')
DATELIKE=re.compile(r'^\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})'); ISO=re.compile(r'^\d{4}-\d{2}-\d{2}')
PLACEHOLDER={'n/a','na','tbd','tba','test','none','null','nil','-','?','x','xx','asdf','todo','unknown','.','0'}
TYPO={'dowtime':'Downtime','accomadation':'Accommodation','reciept':'Receipt','aknowledged':'Acknowledged','filllout':'Fillout','adress':'Address','recieved':'Received','seperate':'Separate','occured':'Occurred','untill':'Until','instal ':'Install','spings':'Springs','invenotry':'Inventory','managment':'Management','calender':'Calendar','definately':'Definitely','recomend':'Recommend','schedual':'Schedule'}
LEFTOVER=re.compile(r'(\bcopy\b|\s\d+$|\(temp\)|^dep[-_]|^DEP[-_]|^TEMP_|\(old|\bold\b|\btest\b)',re.I)
def is_empty(v): return v in (None,'',[],False) or (isinstance(v,dict) and not v)
def pretty_pct(a,b): return f"{(100*a/b):.0f}%" if b else "–"
findings=[]   # dicts: table, field, sev, code, msg, n
def add(table,field,sev,code,msg,n=None): findings.append({'table':table,'field':field,'sev':sev,'code':code,'msg':msg,'n':n})
def is_hourlike(name): return re.search(r'hour|hrs|qty|quantity|count|nights|cost|expense|wage|price|amount|fee|payment|total|usd|min\b|weeks|distance',name,re.I)
def date_pairs(names):
    pairs=[]
    for a in names:
        for b in names:
            if a==b: continue
            la,lb=a.lower(),b.lower()
            if ('start' in la and ('end' in lb or 'stop' in lb or 'expiry' in lb or 'expire' in lb) and re.sub(r'start','',la)==re.sub(r'end|stop|expiry|expire','',lb)) or ('pickup' in la and 'dropoff' in lb) or (la.endswith('downtimestart') and 'dow' in lb and 'stop' in lb):
                pairs.append((a,b))
    return pairs
tables=[t for t in sch['tables'] if not ONLY or t['name']==ONLY]
score=[]; FSTAT={}
for t in tables:
    tn=t['name']; recs=rows_of(t); n=len(recs)
    recent=[r for r in recs if r['_ts']>=RECENT]; nrec=len(recent)
    fields=t['fields']; prim=t['primaryFieldId']
    fstat={}; FSTAT[tn]=fstat
    # primary duplicates + test rows
    pf=[f for f in fields if f['id']==prim][0]
    pv=[str(r['fields'].get(pf['name'],'')).strip().lower() for r in recs]
    dup=Counter(v for v in pv if v); dups={k:c for k,c in dup.items() if c>1}
    if dups and pf['type'] not in ('formula',): add(tn,pf['name'],'🟡','dup-primary',f"{sum(dups.values())} rows share a primary value with another row ({len(dups)} values, e.g. \"{next(iter(dups))[:40]}\")",len(dups))
    tests=[v for v in pv if re.match(r'^(test|testing|tst|asdf|dummy|sample)(\s*[-_#]?\s*\d+)?$',v) or v.startswith('test ')]
    if tests: add(tn,pf['name'],'🟡','test-rows',f"{len(tests)} rows look like test rows (\"{tests[0][:40]}\")",len(tests))
    dnames=[f['name'] for f in fields if f['type'] in('date','dateTime')]
    for a,b in date_pairs(dnames):
        bad=0
        for r in recs:
            va,vb=r['fields'].get(a),r['fields'].get(b)
            if va and vb and str(vb)<str(va): bad+=1
        if bad: add(tn,b,'🔴','end-before-start',f"{bad} rows where {b} is before {a}",bad)
    for f in fields:
        nm=f['name']; ty=f['type']; vals=[r['fields'].get(nm) for r in recs]; filled=[v for v in vals if not is_empty(v)]
        nf=len(filled); rf=[r['fields'].get(nm) for r in recent]; nrf=sum(1 for v in rf if not is_empty(v))
        st={'type':ty,'filled':nf,'rows':n,'recent_filled':nrf,'recent_rows':nrec,'issues':[]}; fstat[nm]=st
        ro=ty in('formula','multipleLookupValues','rollup','count','autoNumber','createdTime','lastModifiedTime','createdBy','lastModifiedBy')
        # errors from formulas/lookups
        errs=sum(1 for v in filled if (isinstance(v,dict) and 'error' in v) or (isinstance(v,list) and any(isinstance(x,dict) and 'error' in x for x in v)) or (isinstance(v,str) and v.startswith('#')))
        if errs: add(tn,nm,'🔴','errors',f"{errs} rows show an error value (#ERROR / #N/A)",errs)
        # fill health
        if n>=10 and not ro:
            if nf==0: add(tn,nm,'🟡','empty',f"empty on all {n} rows")
            elif nf<=max(2,round(0.02*n)): add(tn,nm,'🟡','sparse',f"filled on {nf} of {n} rows")
            elif nrec>=10 and nrf==0 and nf/n>=0.3: add(tn,nm,'🟡','abandoned',f"filled on {pretty_pct(nf,n)} of rows overall but on none of the {nrec} rows created in the last {DAYS} days")
        # constant
        if nf>=10 and ty in('singleSelect','singleLineText','number','currency','multilineText'):
            distinct={json.dumps(v,sort_keys=True) for v in filled}
            if len(distinct)==1: add(tn,nm,'🟡','constant',f"same value on all {nf} filled rows ({str(filled[0])[:30]})")
        # by type
        if ty in('singleLineText','multilineText','richText') and nf>=5:
            strs=[str(v) for v in filled]
            idlike=re.search(r'zip|postal|code|\bid\b|id$|number|serial|\bmac|\bip\b|tax|sku|part|phone|hts|acronym',nm,re.I)
            for lbl,rx in (('numbers',NUMLIKE),('dates',DATELIKE),('emails',EMAIL),('URLs',URL)):
                if lbl=='numbers' and idlike: continue
                k=sum(1 for v in strs if rx.match(v.strip()))
                if k>=0.8*nf and k>=5: add(tn,nm,'🟡','typed-as-text',f"{pretty_pct(k,nf)} of values are {lbl} stored as text"); break
            if ty=='singleLineText':
                ws=sum(1 for v in strs if v!=v.strip() or '  ' in v)
            else:   # multi-line / rich text: Airtable returns rich text with one trailing newline, and markdown uses spaces deliberately
                def _bad(v):
                    body=v[:-1] if v.endswith('\n') else v
                    if body!=body.lstrip() or body!=body.rstrip(): return True
                    return any('  ' in ln.strip() for ln in body.split('\n'))
                ws=sum(1 for v in strs if _bad(v))
            if ws: add(tn,nm,'🟡','whitespace',f"{ws} values have leading/trailing whitespace or doubled spaces inside the text",ws)
            ph=sum(1 for v in strs if v.strip().lower() in PLACEHOLDER)
            if ph: add(tn,nm,'🟡','placeholder',f"{ph} placeholder values (n/a, tbd, test, -, …)",ph)
        if ty=='email':
            bad=sum(1 for v in filled if not EMAIL.match(str(v).strip()))
            if bad: add(tn,nm,'🔴','invalid-email',f"{bad} values are not valid email addresses",bad)
        if ty=='url':
            bad=sum(1 for v in filled if not URL.match(str(v).strip()))
            if bad: add(tn,nm,'🔴','invalid-url',f"{bad} values are not http(s) URLs",bad)
        if ty=='phoneNumber':
            bad=sum(1 for v in filled if not PHONE.match(str(v).strip()))
            if bad: add(tn,nm,'🔴','invalid-phone',f"{bad} values do not look like phone numbers",bad)
        if ty in('number','currency','percent','duration'):
            nums=[v for v in filled if isinstance(v,(int,float))]
            if nums:
                neg=sum(1 for v in nums if v<0)
                if neg and is_hourlike(nm): add(tn,nm,'🔴','negative',f"{neg} negative values",neg)
                if len(nums)>=20:
                    med=statistics.median([abs(v) for v in nums if v]) if any(nums) else 0
                    if med:
                        out=[v for v in nums if abs(v)>20*med]
                        if out: add(tn,nm,'🟡','outliers',f"{len(out)} values more than 20× the median ({med:g}); max {max(out,key=abs):g}",len(out))
                rz=[v for v in rf if isinstance(v,(int,float))]
                older=[r['fields'].get(nm) for r in recs if r['_ts']<RECENT]; oz=[v for v in older if isinstance(v,(int,float))]
                # only meaningful when there ARE older rows to compare with (a bulk-created table has none)
                if nrec>=10 and len(rz)>=10 and len(oz)>=10 and sum(1 for v in rz if v==0)>=0.8*len(rz) and sum(1 for v in oz if v!=0)>=0.5*len(oz):
                    add(tn,nm,'🟡','recent-zeros',f"{pretty_pct(sum(1 for v in rz if v==0),len(rz))} of the last {DAYS} days' rows are 0 while {pretty_pct(sum(1 for v in oz if v!=0),len(oz))} of older rows have real values (automation default 0?)")
        if ty in('date','dateTime'):
            ds=[str(v)[:10] for v in filled if ISO.match(str(v))]
            horizon=6*365 if re.search(r'contract|expir|renew|target|accept|construction|readiness|latest|earliest|due|warranty|lease|amort',nm,re.I) else 400
            fut=sum(1 for d in ds if d>(NOW+dt.timedelta(days=horizon)).strftime('%Y-%m-%d')); past=sum(1 for d in ds if d<'2015-01-01')
            if fut: add(tn,nm,'🔴','far-future',f"{fut} dates more than {horizon//365 if horizon>=365 else horizon} {'years' if horizon>=365 else 'days'} ahead (max {max(ds)})",fut)
            if past: add(tn,nm,'🔴','far-past',f"{past} dates before 2015 (min {min(ds)})",past)
        if ty in('singleSelect','multipleSelects'):
            opts=[c['name'] for c in f.get('options',{}).get('choices',[])]
            used=Counter()
            for v in filled:
                for x in (v if isinstance(v,list) else [v]): used[x]+=1
            unused=[o for o in opts if used[o]==0]
            if unused and nf>=10: add(tn,nm,'🟡','unused-options',f"{len(unused)} of {len(opts)} options never used ({', '.join(unused[:4])}{'…' if len(unused)>4 else ''})",len(unused))
            norm=defaultdict(list)
            for o in opts: norm[re.sub(r'\s+',' ',o.strip().lower())].append(o)
            twins=[v for v in norm.values() if len(v)>1]
            if twins: add(tn,nm,'🟡','option-twins',f"options that differ only by case/spacing: "+'; '.join(' / '.join(repr(x) for x in tw) for tw in twins[:3]),len(twins))
            ws=[o for o in opts if o!=o.strip()]
            if ws: add(tn,nm,'🟡','option-whitespace',f"options with stray spaces: {', '.join(repr(o) for o in ws[:4])}",len(ws))
        if ty=='multipleAttachments':
            junk=0; tot=0
            for v in filled:
                for a in v:
                    tot+=1
                    if str(a.get('type','')).startswith('text/html') or 'uploads?id' in str(a.get('url','')) or a.get('size')==0: junk+=1
            if junk: add(tn,nm,'🔴','junk-attachments',f"{junk} of {tot} attachments are HTML pages or empty files",junk)
        # schema hygiene
        if not (f.get('description') or '').strip(): add(tn,nm,'🟡','no-description',"no description in Airtable")
        low=nm.lower()
        for bad,good in TYPO.items():
            if bad in low: add(tn,nm,'🟡','name-typo',f"field name looks misspelled ({bad.strip()} → {good})"); break
        if LEFTOVER.search(nm): add(tn,nm,'🟡','name-leftover',"field name looks like a leftover (copy / numbered / temp / dep / old / test)")
        if nm!=nm.strip() or '  ' in nm: add(tn,nm,'🟡','name-whitespace',"field name has stray spaces")
    red=len({x['field'] for x in findings if x['table']==tn and x['sev']=='🔴'}); yel=len({x['field'] for x in findings if x['table']==tn and x['sev']=='🟡' and x['code']!='no-description'})
    nodesc=sum(1 for x in findings if x['table']==tn and x['code']=='no-description')
    flagged={x['field'] for x in findings if x['table']==tn and x['code']!='no-description'}
    score.append({'table':tn,'rows':n,'fields':len(fields),'ok':len(fields)-len(flagged),'red':red,'yellow':yel,'no_description':nodesc})
json.dump({'generated':NOW.isoformat(),'days':DAYS,'score':score,'findings':findings,'fields':FSTAT},open(f'{OUT}/health.json','w'),indent=1,ensure_ascii=False)
# ---------- print
score.sort(key=lambda s:(-s['red'],-(s['yellow']/max(s['fields'],1)),s['table']))
print(f"FIELD HEALTH  Trajekt_Dev  {NOW.strftime('%Y-%m-%d')}   (recent = last {DAYS} days; read-only)")
print(f"{'table':26}{'rows':>6}{'fields':>8}{'healthy':>9}{'🔴':>5}{'🟡':>5}{'no desc':>9}")
for s in score: print(f"{s['table']:26}{s['rows']:>6}{s['fields']:>8}{s['ok']:>8} {s['red']:>4} {s['yellow']:>4} {s['no_description']:>8}")
CAP=None if FULL else 6
for sev,title in (('🔴','WRONG-LOOKING DATA'),('🟡','HYGIENE')):
    items=[x for x in findings if x['sev']==sev and x['code']!='no-description']
    if not items: continue
    print(f"\n{sev} {title} ({len(items)})")
    for s in score:
        mine=[x for x in items if x['table']==s['table']]
        if not mine: continue
        print(f"  {s['table']}")
        for x in (mine if CAP is None else mine[:CAP]): print(f"    {x['field']}: {x['msg']}")
        if CAP is not None and len(mine)>CAP: print(f"    … +{len(mine)-CAP} more ({', '.join(sorted({x['code'] for x in mine[CAP:]}))}) — run with --full")
nd=[x for x in findings if x['code']=='no-description']
if nd: print(f"\nℹ {len(nd)} fields have no description in Airtable (listed in health.json).")
print(f"\n(nothing was written; details in {OUT}/health.json)")

# ---------- what a "Health" cell per field says (scripts/health_cells.py is the single source; write_health.py / build_all_tabs.py use it)
from health_cells import cells_from, is_flagged
CELLS=cells_from({'days':DAYS,'generated':NOW.isoformat(),'findings':findings,'fields':FSTAT})
def health_cell(table,field): return CELLS.get(table,{}).get(field,'')
if '--docs-preview' in sys.argv:
    print('\n=== DOCS PREVIEW: the Health cell each field gets (only flagged fields shown; every other field gets ✅)')
    tot=0; flagged=0
    for t in tables:
        lines=[]
        for f in t['fields']:
            c=health_cell(t['name'],f['name']); tot+=1
            if is_flagged(c): flagged+=1; lines.append(f"    {f['name'][:36].ljust(36)} | "+c.replace('\n',' | '))
        if lines: print(f"  {t['name']} ({len(lines)} flagged of {len(t['fields'])})"); [print(l[:200]) for l in lines[:8]]; 
        if len(lines)>8: print(f"    … +{len(lines)-8} more")
    print(f"\n{flagged} of {tot} fields carry a flag; the rest get ✅.")
