#!/usr/bin/env python3
"""Refresh every tab of 'Trajekt_Dev Field Documentation' from the live Trajekt_Dev schema. Dry-run default; --apply writes.
Columns A..I: Field name, Type, Description, Related, Automations, Forms, Field ID, Notes, Health (I = from last_run/health.json)."""
import json, re, sys, urllib.request, subprocess, os, glob
from fdc_env import DASH, OUT as S, sheets_token
ID='1nAA16LbtfpEacVcrteYJbHBP3iKDgpm_-cJD7Td8agA'; WO_GID=751011509
APPLY='--apply' in sys.argv
sch=json.load(open(f'{S}/schema.json')); tabs={k:v['rows'] for k,v in json.load(open(f'{S}/tabs.json')).items()}
usage=json.load(open(f'{S}/usage_all.json'))
from health_cells import cells_from, header_text   # column I (Health): from last_run/health.json, blank when absent
HC={}; HDR='Health'
if os.path.exists(f'{S}/health.json'):
    _h=json.load(open(f'{S}/health.json')); HC=cells_from(_h); HDR=header_text(_h)
import glob as _g
wf_tables={}
for _p in _g.glob(f'{S}/wf/*.json'):
    _d=json.load(open(_p)); _txt=json.dumps(_d)
    wf_tables[_d['name']]={tt for tt in re.findall(r'tbl[A-Za-z0-9]{14}',_txt)}
name_count={}
for _t in sch['tables']:
    for _f in _t['fields']: name_count[_f['name']]=name_count.get(_f['name'],0)+1; fauto=json.load(open(f'{S}/formmap_auto.json'))
fbind={}   # proven bindings from form_bindings.py: "Table::Field" -> ['Form — "question"', ...]
if os.path.exists(f'{S}/form_bindings.json'):
    for fid,fm in json.load(open(f'{S}/form_bindings.json')).items():
        for qn,b in fm['bindings'].items():
            fbind.setdefault(f"{b['table']}::{b['field']}",[]).append(f"{fm['form']} — \"{qn.strip()}\"")
tid={t['id']:t['name'] for t in sch['tables']}; allf={f['id']:(t['name'],f['name']) for t in sch['tables'] for f in t['fields']}
TYPE={'multipleRecordLinks':'link','singleSelect':'select','multipleSelects':'multiSelect','singleLineText':'text','multilineText':'longText','multipleLookupValues':'lookup','multipleAttachments':'attachment','phoneNumber':'phone','aiText':'aiText','richText':'richText','autoNumber':'autoNumber','createdTime':'createdTime','lastModifiedTime':'lastModified'}
SKIPWF={'Trajekt Internal — Slack Alerts'}
WIP=re.compile(r'\[\s*WIP\s*\]',re.I)   # work-in-progress workflows are not documented
inbound={}
for t in sch['tables']:
    for f in t['fields']:
        if f['type']=='multipleRecordLinks': inbound.setdefault(tid[f['options']['linkedTableId']],{}).setdefault(t['name'],[]).append(f['name'])

def tabrows(name):
    tab=tabs.get(name) or []
    for i,r in enumerate(tab):
        if r and r[0]=='Field name': return {r2[0]:(r2+['']*7)[:7] for r2 in tab[i+1:] if r2 and r2[0]}
    return {}
def tabcols(name):
    tab=tabs.get(name) or []
    for r in tab:
        if r and r[0]=='Field name': return {h:i for i,h in enumerate(r)}
    return {}
def tabdesc(name):
    tab=tabs.get(name) or []
    return (tab[2][0] if len(tab)>2 and tab[2] else '') or ''

def related(t,f):
    o=f.get('options',{}); ty=f['type']; names={x['id']:x['name'] for x in t['fields']}
    deref=lambda s: re.sub(r'\{(fld[A-Za-z0-9]+)\}',lambda m:'{'+names.get(m.group(1),allf.get(m.group(1),('','?'))[1])+'}',s)
    if ty=='multipleRecordLinks':
        inv=allf.get(o.get('inverseLinkFieldId'),('','?'))[1]; return f"Links to: {tid.get(o.get('linkedTableId'),'?')} (reverse: {inv})"
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
    if ty=='count': return f"Count: via {names.get(o.get('recordLinkFieldId'),'?')}"
    if f['id']==t['primaryFieldId'] and t['name'] in inbound:
        return 'Used by: '+'; '.join(f"{tn} ({', '.join(fs)})" for tn,fs in inbound[t['name']].items())
    return '-'

def automations(t,f):
    h=usage.get(f"{t['name']}::{f['name']}",{}); out=[]
    for wn,d in h.items():
        if wn in SKIPWF or WIP.search(wn): continue
        if name_count.get(f['name'],1)>1 and t['id'] not in wf_tables.get(wn,set()): continue
        lbl=wn+(' (inactive)' if wn.startswith('Daily') else '')
        parts=[]
        if d['w']: parts.append('writes: '+', '.join(d['w'][:3]))
        if d['r']: parts.append('reads')
        out.append(f"{lbl} ({'; '.join(parts)})")
    return '\n'.join(f"{i}. {s}" for i,s in enumerate(sorted(out),1))

WOF='Work Order Forms'; SUM='Work Order Summary Form'; INV='Work Order Invoice Form'; MC='Maintenance Checklist forms'
q=lambda form,qq:f'{form} — "{qq}"'
FORMS={
'Work Orders':{"WorkOrderID": ["Work Order Summary Form — \"Work Order ID\"", "Work Order Invoice Form — \"Work Order\"", "Maintenance Checklist forms — \"Work Order\"", "Shipment Forms (idle since Aug 2026) — \"Work Orders\""], "WorkOrderType": ["Work Order Forms — \"Work Order Types\""], "MachineID": ["Work Order Forms — \"Machine ID\""], "WorkOrderTechnicianName": ["Work Order Forms — \"Technician\""], "WorkOrderSummaryName": ["Work Order Summary Form (creates the row)"], "CustomerName": ["Work Order Forms — \"Customer\""], "LocationName": ["Work Order Forms — \"Customer Facility Name\""], "WorkOrderServiceRequestCategory": ["Work Order Forms — \"Work Order Service Request Category\""], "WorkOrderSubcategory": ["Work Order Forms — \"Work Order Sub-Categories\""], "ScopeName": ["Work Order Forms — \"Scope of Work\""], "WorkOrderScopeNotes": ["Work Order Forms — \"Additional Scope Notes\""], "WorkOrderPartsRequired": ["Work Order Forms — \"Parts\" › sub-form Moving Parts - WorkOrder"], "MovementLogName": ["Shipment Forms (idle since Aug 2026)"], "WorkOrderReferenceNumber": ["Work Order Forms — \"Reference Number\""], "ContactName-Engineer": ["Work Order Forms — \"Trajekt Engineer - Point Of Contact\""], "ContactName-Logistics": ["Work Order Forms — \"Trajekt Logistics - Point of Contact\""], "WorkOrderToolsNeeded": ["Work Order Forms — \"Work Order Tools Needed\""], "ContactName-Customer": ["Work Order Forms — \"Work Order Customer Contact\" › sub-form Work Order Forms - Create Customer Contact"], "WorkOrderReturningParts": ["Work Order Forms — \"Work Order Returning Parts\" › sub-form Moving Parts - WorkOrderReturn"], "Maintenance Submissions": ["Maintenance Checklist forms (creates the row)"], "WorkOrderIntercomTicket": ["Work Order Forms — \"Intercom Ticket\""], "WorkOrderFilloutSubmissionID": ["Work Order Forms (submission id, hidden mapping)"], "WorkOrderRequestedStartDateAndTime": ["Work Order Forms — \"Requested Start Date & Time\""], "WorkOrderMachineNotOperable": ["Work Order Forms — \"Is the machine down?\""], "WorkOrderMachineDowntimeStart": ["Work Order Forms — \"Machine Downtime Start\""], "OOBF Checks": ["Work Order Summary Form › sub-form Work Order Summary Form - Create OOBF"], "Work Order Invoicing": ["Work Order Invoice Form (creates the row)"]},
'Work Order Summary':{'WorkOrderSummaryType':[q(SUM,'Summary Type')],'WorkOrderID':[q(SUM,'Work Order ID')],'ContactName-Onsite':[q(SUM,'Name')],'WorkOrderSummaryStartDate':[q(SUM,'Start Date')],'WorkOrderSummaryEndDate':[q(SUM,'End Date')],'WorkOrderSummaryInstallChallenges':[q(SUM,'Install Challenges')],'ScopeName':[q(SUM,'Tasks Completed')],'WorkOrderSummaryMachineOperable':[q(SUM,'Machine Operable?')],'WorkOrderSummaryScopeNotes':[q(SUM,'Tasks Completed Notes')],'Repeatability Report':[q(SUM,'Repeatability Report')],'Final Lane Picture':[q(SUM,'Final Lane Picture')],'Wheel Photos':[q(SUM,'Pictures of current wheels')],'WorkOrderSummarySummaryNotes':[q(SUM,'Tech Feedback/ Recommendations')],'OOBFName':[q(SUM,'OOBF Checklist')+' › sub-form Work Order Summary Form - Create OOBF'],'WorkOrderSummaryFillloutID':[SUM+' (submission id, hidden mapping)'],'WorkOrderSummaryName':[SUM+' (creates the row)']},
'Work Order Cost':{'WorkOrderID':[q(INV,'Work Order')],'ContactName':[q(INV,'Technician Name')],'WOCostHoursOnSite':[q(INV,'Total time On-site (# of HRS)')],'WOCostHoursFiring':[q(INV,'Time On-site firing pitches (# of HRS)')],'WOCostHoursTravellingLand':[q(INV,'Travel Time - Land (# of hrs)')],'WOCostExpenseLand':[q(INV,'Travel Expense - Land (USD)')],'WOCostFlight':[q(INV,'Did you take a flight for this job?')],'WOCostHoursTravellingAir':[q(INV,'Travel Time - Air (#of hrs)')],'WoCostHoursTravelLayover':[q(INV,'Travel Time - Layover (# of hrs)')],'WOCostExpenseFlights':[q(INV,'Travel Expense - Air (USD)')],'WOCostOvernight':[q(INV,'Did you stay overnight for this job?')],'WOCostNightsInHotel':[q(INV,'How many nights did you stay in a hotel?')],'WOCostExpenseAccomadation':[q(INV,'Accommodation Expense (USD)')],'WOCostExpenseTools':[q(INV,'Tool Expense (USD)')],'WOCostExpenseMeals':[q(INV,'Meal Expense (USD)')],'WOCostExpenseOther':[q(INV,'Other Expenses (USD)')],'WOCostReciepts':[q(INV,'Receipts')],'FilloutSubmissionID':[INV+' (submission id, hidden mapping)'],'WOCostName':[INV+' (creates the row)']},
'Maintenance Submissions':{'Work Order':[q(MC,'Work Order')],'Maintenance Checklist Type':[q(MC,'Maintenance Checklist Type')],'Result':[q(MC,'Result')],'Failed Checks':[q(MC,'Failed Checks')],'Notes':[q(MC,'Notes')]},
'OOBF Checks':{'WorkOrderSummaryName':[SUM+' › sub-form Work Order Summary Form - Create OOBF (creates the row)'],'OOBFLoadingIn':[q('… - Create OOBF','Loading In')],'OOBFMachineonTrack':[q('… - Create OOBF','Machine on Track')],'OOBFMachineCablingCheck':[q('… - Create OOBF','Machine Cabling Check')],'OOBFMachineMechanicalCheck':[q('… - Create OOBF','Machine Mechanical Check')],'OOBFInternetandPower':[q('… - Create OOBF','Internet and Power')],'OOBFProjectorSetUp':[q('… - Create OOBF','Projector Set Up')],'OOBFTestFiring&Re-Alignment':[q('… - Create OOBF','Test Firing & Re-Alignment')],'OOBFTrackingDeviceSetUp':[q('… - Create OOBF','Tracking Device Set Up')],'OOBFTrainingModel':[q('… - Create OOBF','Training Model')],'OOBFFailureCategory':[q('… - Create OOBF','Failure Category')],'OOBFNotes':[q('… - Create OOBF','Notes')]},
}
def forms(t,f,old=None):
    key=f"{t['name']}::{f['name']}"
    proven=fbind.get(key,[])
    hand=FORMS.get(t['name'],{}).get(f['name'],[])
    items=proven+[h for h in hand if h not in proven] if proven else (hand if hand else ([] if t['name']=='Work Orders' else fauto.get(key,[])))   # no name-matching fallback on Work Orders
    items=[re.sub(r' - (Create|Update) \([A-Za-z0-9]{4}\)','',x) for x in items if not any(bad in x for bad in ('MOCK ENVIRONMENT','My form','test'))]
    seen=[]; [seen.append(x) for x in items if x not in seen]; items=seen[:4]
    return '\n'.join(f"{i}. {s}" for i,s in enumerate(items,1))

DESC=json.load(open(os.path.join(os.path.dirname(__file__),'descriptions.json')))
def humanize(t,f):
    n=f['name']
    for p in ('WorkOrderSummary','WorkOrder','WOCost','WoCost','Machine','Contact','Customer','Facility','Install','Inventory','Contract','Scope','OOBF','MovementLogs','Warehouse','Product','Parts'):
        if n.startswith(p) and len(n)>len(p): n=n[len(p):]; break
    n=re.sub(r'([a-z])([A-Z])',r'\1 \2',n).replace('(', ' (').strip()
    return n[0].upper()+n[1:]
def description(t,f,old):
    d=DESC.get(f"{t['name']}::{f['name']}")
    if d: return d
    if old and old[2]: return old[2]
    if f['type']=='multipleLookupValues': return f"{allf.get(f['options'].get('fieldIdInLinkedTable'),('','?'))[1]} (lookup)"
    return humanize(t,f)
def notes(t,f,old):
    n=DESC.get(f"NOTE {t['name']}::{f['name']}")
    if n is not None: return n
    if t['name']=='Work Orders':
        ni=tabcols(t['name']).get('Notes',6)
        return (old[ni] if old and len(old)>ni else '')
    rel=(old[3] if old else '').strip()
    if rel.startswith('Referenced by') or (related(t,f).startswith('Options:') and '/' in rel and len(rel)<=70): return ''
    if not rel or rel=='-' or re.match(r'^(→|Linked to|options?:|\d+ options|Yes / No|primary key|lookup|rollup|formula|"|[A-Z_]+\()',rel,re.I): return ''
    return rel

sheet_ids={k:v['gid'] for k,v in json.load(open(f'{S}/sheet.json')).items()}
plan=[]
for t in sch['tables']:
    tn=t['name']; oldname=tn if tn in tabs else ('Location' if tn=='Facility' else tn)
    old=tabrows(oldname)
    if tn=='Facility' and oldname=='Location': old={k.replace('Location','Facility',1):v for k,v in old.items()}
    rows=[]
    for f in t['fields']:
        o=old.get(f['name'])
        rows.append([f['name'],TYPE.get(f['type'],f['type']),description(t,f,o),related(t,f),automations(t,f),forms(t,f,o),f['id'],notes(t,f,o),HC.get(tn,{}).get(f['name'],'')])
    desc=DESC.get(f"TABLE {tn}") or tabdesc(oldname) or ''
    plan.append({'table':tn,'tableId':t['id'],'oldtab':oldname,'sheetId':sheet_ids.get(oldname),'rows':rows,'desc':desc,'oldcount':len(old)})
json.dump(plan,open(f'{S}/plan_all.json','w'),indent=1)
# --keep-health: carry each tab's CURRENT Health cells forward instead of rewriting them from last_run/health.json
# (Elliot 2026-09-17: "don't change the field health"). Cells follow their field by id (rename-proof), else by name;
# each tab keeps its own header text. Removed fields drop with their row; a field with no cell on the sheet gets ''.
if '--keep-health' in sys.argv:
    import urllib.parse as _up
    _H={'Authorization':'Bearer '+sheets_token()}; _live=[p for p in plan if p['sheetId'] is not None]
    _q='&'.join('ranges='+_up.quote(f"'{p['oldtab']}'!A8:I600") for p in _live)
    _vr=json.load(urllib.request.urlopen(urllib.request.Request(f'https://sheets.googleapis.com/v4/spreadsheets/{ID}/values:batchGet?{_q}',headers=_H)))['valueRanges']
    kept=0
    for p,vr in zip(_live,_vr):
        rows=vr.get('values',[]); hdr=rows[0] if rows else []
        p['health_hdr']=next((c for c in hdr if str(c).startswith('Health')),None)
        byid={}; byname={}
        for r in rows[1:]:
            if not r or not r[0]: break
            r=(r+['']*9)[:9]; byname[r[0]]=r[8]
            if r[6]: byid[r[6]]=r[8]
        for r in p['rows']:
            r[8]=byid.get(r[6],byname.get(r[0],'')); kept+=bool(r[8])
    print(f"--keep-health: Health cells carried over from the sheet as they are ({kept} cells); headers kept")
# --same-fields: refuse to write when the field set on any tab differs from Airtable (use for cosmetic re-applies,
# so a schema change that Elliot has not said yes to cannot slip in through a rewrite)
if '--same-fields' in sys.argv:
    drift=[]
    for p in plan:
        old=tabrows(p['oldtab']) if p['oldtab'] in tabs else {}
        a=[r[0] for r in p['rows']]; b=list(old.keys())
        if a!=b: drift.append(f"{p['table']}: sheet {len(b)} fields vs live {len(a)}"+('' if set(a)==set(b) else f" (new {sorted(set(a)-set(b))}, gone {sorted(set(b)-set(a))})"))
    if drift:
        print('REFUSING --apply: field set changed since the sheet was last approved:'); [print('   ',d) for d in drift]; sys.exit(2)

for p in ([] if '--dry' in sys.argv else plan):
    fresh=sum(1 for r in p['rows'] if f"{p['table']}::{r[0]}" in DESC); auto=sum(1 for r in p['rows'] if r[4]); fm=sum(1 for r in p['rows'] if r[5])
    print(f"{p['table'].ljust(24)} tab={'NEW' if p['sheetId'] is None else p['oldtab']:<10} fields={len(p['rows']):3} (was {p['oldcount']:3}) hand-desc={fresh:3} automations={auto:3} forms={fm:3}")
if '--dry' not in sys.argv: print("Health column (I): kept as it is on the sheet (--keep-health)" if '--keep-health' in sys.argv else f"Health column (I): {HDR}, from last_run/health.json" if HC else "Health column (I): NO last_run/health.json → would be written BLANK; run health.py (or check.py --health) first")
if not APPLY:
    if '--dry' not in sys.argv: print('\nDRY RUN')
    sys.exit()

AT=sheets_token()
def call(url,body,method='POST'):
    req=urllib.request.Request(url,data=json.dumps(body).encode(),method=method,headers={'Authorization':'Bearer '+AT,'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req))
BU=f'https://sheets.googleapis.com/v4/spreadsheets/{ID}:batchUpdate'
# 1. structural: create missing tabs, rename Location→Facility, flag deleted-table tabs
reqs=[]
for p in plan:
    if p['sheetId'] is None: reqs.append({'addSheet':{'properties':{'title':p['table'],'gridProperties':{'rowCount':1000,'columnCount':26}}}})
    elif p['oldtab']!=p['table']: reqs.append({'updateSheetProperties':{'properties':{'sheetId':p['sheetId'],'title':p['table']},'fields':'title'}})
for dead in ('Trajekt Summary','Trajekt Personnel','Maintenance Checks'):
    if dead in sheet_ids: reqs.append({'updateSheetProperties':{'properties':{'sheetId':sheet_ids[dead],'title':f'(deleted) {dead}'},'fields':'title'}})
r=call(BU,{'requests':reqs}) if reqs else {}
for rep in r.get('replies',[]):
    if 'addSheet' in rep: pr=rep['addSheet']['properties']; sheet_ids[pr['title']]=pr['sheetId']
for p in plan: p['sheetId']=sheet_ids.get(p['table'],p['sheetId'])
# 2. values
data=[]
for p in plan:
    n=len(p['rows']); tn=p['table'].replace("'","''")
    data.append({'range':f"'{tn}'!A1",'values':[[p['table']]]})
    data.append({'range':f"'{tn}'!A3",'values':[[p['desc']]]})
    data.append({'range':f"'{tn}'!A8:I8",'values':[['Field name','Type','Description','Related','Automations','Forms','Field ID','Notes',p.get('health_hdr') or HDR]]})
    data.append({'range':f"'{tn}'!A9:I{8+n}",'values':p['rows']})
    data.append({'range':f"'{tn}'!A{9+n}:I{9+n+80}",'values':[['']*9]*81})
for dead in ('Trajekt Summary','Trajekt Personnel','Maintenance Checks'):
    if dead in sheet_ids: data.append({'range':f"'(deleted) {dead}'!A3",'values':[[f'TABLE DELETED from Trajekt_Dev (before 2026-09-08). This tab is a historical snapshot; remove when no longer needed.']]})
r=call(f'https://sheets.googleapis.com/v4/spreadsheets/{ID}/values:batchUpdate',{'valueInputOption':'RAW','data':data})
print('cells written',r.get('totalUpdatedCells'))
# 3. formats: copy WO tab title/desc/header/banding + column widths to every tab
rng=lambda sid,r0,r1,c0,c1:{'sheetId':sid,'startRowIndex':r0,'endRowIndex':r1,'startColumnIndex':c0,'endColumnIndex':c1}
fr=[]
for p in plan:
    if p['table']=='Work Orders': continue
    sid=p['sheetId']; n=len(p['rows']); even=n-(n%2)
    fr.append({'copyPaste':{'source':rng(WO_GID,0,8,0,9),'destination':rng(sid,0,8,0,9),'pasteType':'PASTE_FORMAT'}})
    if even: fr.append({'copyPaste':{'source':rng(WO_GID,8,10,0,9),'destination':rng(sid,8,8+even,0,9),'pasteType':'PASTE_FORMAT'}})
    if n%2: fr.append({'copyPaste':{'source':rng(WO_GID,8,9,0,9),'destination':rng(sid,8+even,9+even,0,9),'pasteType':'PASTE_FORMAT'}})
    fr.append({'copyPaste':{'source':rng(WO_GID,8+n,8+n+80,0,7),'destination':rng(sid,8+n,8+n+80,0,7),'pasteType':'PASTE_FORMAT'}}) if False else None
    for ci,w in enumerate([300,110,300,470,307,195,170,420,360]): fr.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
    if p['oldtab'] in sheet_ids and any(sheet_ids[p['oldtab']]==sid for _ in [0]):
        pass
# the Work Orders tab is the template: give its own column H (Notes) column G's old format, and G the same, before tiling
wo=[p for p in plan if p['table']=='Work Orders'][0]; won=len(wo['rows'])
fr.insert(0,{'copyPaste':{'source':rng(WO_GID,7,8+won,6,7),'destination':rng(WO_GID,7,8+won,7,8),'pasteType':'PASTE_FORMAT'}})
fr.insert(1,{'copyPaste':{'source':rng(WO_GID,7,8+won,7,8),'destination':rng(WO_GID,7,8+won,8,9),'pasteType':'PASTE_FORMAT'}})   # column I (Health) takes H's format
for ci,w in enumerate([300,110,300,470,307,195,170,420,360]): fr.insert(1,{'updateDimensionProperties':{'range':{'sheetId':WO_GID,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
fr=[x for x in fr if x]
# merge A1:F1 → A1:G1 title like WO tab (WO has merge A1:F2)
for p in plan:
    if False: fr.append({'mergeCells':{'range':rng(p['sheetId'],0,2,0,6),'mergeType':'MERGE_ALL'}})
call(BU,{'requests':fr}); print('formats applied to',len(plan)-1,'tabs')

for p in plan:
    try: call(BU,{'requests':[{'unmergeCells':{'range':rng(p['sheetId'],0,2,0,8)}},{'mergeCells':{'range':rng(p['sheetId'],0,2,0,8),'mergeType':'MERGE_ALL'}}]})
    except Exception as e: print('title merge skipped',p['table'],str(e)[:80])
