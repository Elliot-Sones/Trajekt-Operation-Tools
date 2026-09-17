#!/usr/bin/env python3
"""Derive Fillout question -> Airtable table.field bindings from REAL submissions (values matched against the
row each submission created). Writes only last_run/form_bindings.json. Nothing is written to Fillout or Airtable.
How a row is found: (1) a submission-id field on the table equals the submissionId; else (2) a row created within
±240 s of the submission whose values agree with >=2 answers. A question binds to a field when its value equals the
field's value on every matched row (attachments: by filename set; links: by record ids; numbers: numeric equality)."""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error, datetime as dt
from fdc_env import DASH, OUT, load_env
BASE='appAqIfICwLXNquzF'
env=load_env()
FH={'Authorization':'Bearer '+env['FILLOUT_API_KEY']}; AH={'Authorization':'Bearer '+env['AIRTABLE_WRITE_TOKEN']}
SINCE=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=int(os.environ.get('FDC_DAYS','60')))).strftime('%Y-%m-%dT%H:%M:%SZ')
MAXSUB=int(os.environ.get('FDC_MAXSUB','6'))
def get(u,h):
    for i in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=h)))
        except urllib.error.HTTPError as e:
            if e.code in(429,503): time.sleep(2*(i+1)); continue
            return {'err':e.code}
sch=get(f'https://api.airtable.com/v0/meta/bases/{BASE}/tables',AH)
RO={'multipleLookupValues','rollup','formula','autoNumber','createdTime','lastModifiedTime','createdBy','lastModifiedBy','count','button','aiText'}
writable={t['name']:{f['name'] for f in t['fields'] if f['type'] not in RO} for t in sch['tables']}
# recent rows of every table, with createdTime
rows={}
for t in sch['tables']:
    recs=[];off=None
    while True:
        q={'pageSize':100,'filterByFormula':f"IS_AFTER(CREATED_TIME(),'{SINCE}')"}
        if off:q['offset']=off
        d=get(f"https://api.airtable.com/v0/{BASE}/{t['id']}?"+urllib.parse.urlencode(q),AH)
        recs+=d.get('records',[]); off=d.get('offset')
        if not off:break
    for r in recs: r['_ts']=dt.datetime.fromisoformat(r['createdTime'].replace('Z','+00:00'))
    rows[t['name']]=recs
print('recent rows:',{k:len(v) for k,v in rows.items() if v})
def norm(v):
    if isinstance(v,list):
        if v and isinstance(v[0],dict):
            if 'filename' in v[0] or 'url' in v[0] and 'recordID' not in v[0]:
                return ('att',sorted(os.path.basename(urllib.parse.urlparse(x.get('url','')).path) if not x.get('filename') else x['filename'] for x in v))
            return ('ids',sorted(str(x.get('recordID') or x.get('id')) for x in v))
        if v and isinstance(v[0],str) and v[0].startswith('rec'): return ('ids',sorted(v))
        return ('list',sorted(map(str,v)))
    if isinstance(v,bool): return ('s','Yes' if v else 'No')
    if isinstance(v,(int,float)): return ('n',round(float(v),4))
    s=str(v).strip()
    try: return ('n',round(float(s),4))
    except: pass
    m=re.match(r'^\d{4}-\d{2}-\d{2}',s)
    return ('s',s[:16] if m else s)
def norm_air(v):  # airtable side: attachments carry filename
    if isinstance(v,list) and v and isinstance(v[0],dict) and 'filename' in v[0]: return ('att',sorted(x['filename'] for x in v))
    return norm(v)
forms=get('https://api.fillout.com/v1/api/forms?limit=200',FH); forms=forms if isinstance(forms,list) else forms.get('forms',[])
bindings={}; report=[]
for fm in forms:
    if not fm.get('isPublished') or any(b in fm['name'] for b in ('MOCK','My form','test','My Airtable form')): continue
    time.sleep(0.4)
    sub=get(f"https://api.fillout.com/v1/api/forms/{fm['formId']}/submissions?limit=150&afterDate={SINCE}",FH)
    subs=(sub.get('responses',[]) if isinstance(sub,dict) else [])[-MAXSUB:]   # newest N
    if not subs: continue
    per_q={}   # question -> {(table,field): agree_count}, and total matched rows
    matched=0
    for s in subs:
        sid=s['submissionId']; sts=dt.datetime.fromisoformat(s['submissionTime'].replace('Z','+00:00'))
        answers={q['name']:norm(q['value']) for q in s['questions'] if q.get('value') not in (None,'',[],False)}
        if not answers: continue
        trivial=lambda a: a[0]=='s' and a[1] in('Yes','No','') or a[0]=='n' and a[1] in(0.0,1.0)
        strong={qn:a for qn,a in answers.items() if not trivial(a)}
        cands=[]; sidhit=[]
        for tn,recs in rows.items():
            for r in recs:
                f=r['fields']
                if any(str(v)==sid for v in f.values()): sidhit.append((tn,r,99)); continue
                if abs((r['_ts']-sts).total_seconds())<=240:
                    nf={k:norm_air(v) for k,v in f.items() if k in writable[tn]}
                    hits=sum(1 for a in strong.values() if a in nf.values())
                    if hits>=2: cands.append((tn,r,hits))
        cands=sidhit or cands
        if not cands: continue
        matched+=1
        for tn,r,_ in cands:
            nf={k:norm_air(v) for k,v in r['fields'].items() if k in writable[tn]}
            for qn,a in answers.items():
                for k,v in nf.items():
                    if v==a: per_q.setdefault(qn,{}).setdefault((tn,k),0); per_q[qn][(tn,k)]+=1
    if not matched: report.append((fm['name'],fm['formId'],len(subs),0,{})); continue
    fb={}
    for qn,d in per_q.items():
        best=max(d.items(),key=lambda x:x[1])
        if best[1]<2 and matched>=2: continue            # one coincidence out of several rows = not a binding
        if len([k for k,v in d.items() if v==best[1]])>1: continue   # tie = ambiguous, skip
        fb[qn]={'table':best[0][0],'field':best[0][1],'agree':best[1],'of':matched}
    bindings[fm['formId']]={'form':fm['name'],'matched_rows':matched,'submissions':len(subs),'bindings':fb}
    report.append((fm['name'],fm['formId'],len(subs),matched,fb))
json.dump(bindings,open(f'{OUT}/form_bindings.json','w'),indent=1)
for name,fid,n,m,fb in report:
    print(f"\n## {name} ({fid}) submissions={n} matched rows={m}")
    for qn,b in fb.items(): print(f"   {qn[:40].ljust(40)} → {b['table']}.{b['field']}  ({b['agree']}/{b['of']})")
print(f"\nsaved {OUT}/form_bindings.json")
