#!/usr/bin/env python3
"""Data integrity for Trajekt_Prod: duplicates, impossible values, broken or missing links, cost rows missing information.
READ-ONLY. Writes only last_run/integrity.json (read by report_html.py). Every finding lists each record it touches, so the
HTML page can link each one to Airtable.

Fields are read by the ids pinned in integrity_fields.json, so an Airtable rename does not break a check. When a pinned field
no longer exists, every check that needs it is skipped and listed under "skipped" (never reported as empty data).

Rules this script follows on purpose (Elliot's decisions; do not "fix" them into findings):
- A Moving Parts line is a reusable "part x quantity" line. Many work orders share one line when each used that part.
  The WO parts rollup counting it on every WO is correct. Shared lines are never a finding.
- Dual-role people (tech and staff) are not flagged for a visit Type that differs from their ContactRole.
- known.json lists cases Elliot already reviewed; they stay in the report with a "reviewed" tag.
Usage: python3 integrity.py"""
import json, os, re, sys, time, difflib, datetime as dt, urllib.request, urllib.error
from collections import defaultdict, Counter
from fdc_env import OUT, load_env
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = 'appAqIfICwLXNquzF'
env = load_env(); AH = {'Authorization': 'Bearer ' + env['AIRTABLE_WRITE_TOKEN']}
PINS = json.load(open(os.path.join(HERE, 'integrity_fields.json')))
KNOWN = json.load(open(os.path.join(HERE, 'known.json'))) if os.path.exists(os.path.join(HERE, 'known.json')) else {}
TODAY = dt.date.today().isoformat()

def get(u):
    for i in range(6):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=AH)))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503): time.sleep(3 * (i + 1)); continue
            raise

# ---------- load every table, fields keyed by pinned name
sch = get(f'https://api.airtable.com/v0/meta/bases/{BASE}/tables')
live_ids = {t['id']: {f['id']: f for f in t['fields']} for t in sch['tables']}
T = {}; missing_fields = []
for tn, tid in PINS['tables'].items():
    if tid not in live_ids: missing_fields.append(f"table {tn} ({tid})"); continue
    pin = PINS['fields'].get(tn, {}); byid = {v: k for k, v in pin.items()}
    for name, fid in pin.items():
        if fid not in live_ids[tid]: missing_fields.append(f"{tn}.{name} ({fid})")
    recs = []; off = None
    while True:
        d = get(f"https://api.airtable.com/v0/{BASE}/{tid}?pageSize=100&returnFieldsByFieldId=true" + (f'&offset={off}' if off else ''))
        recs += d['records']; off = d.get('offset'); time.sleep(0.22)
        if not off: break
    rows = []
    for r in recs:
        row = {byid[k]: v for k, v in r['fields'].items() if k in byid}
        row['_id'] = r['id']; row['_created'] = r['createdTime']
        rows.append(row)
    prim = next((byid[t['primaryFieldId']] for t in sch['tables'] if t['id'] == tid and t['primaryFieldId'] in byid), None)
    T[tn] = {'id': tid, 'rows': rows, 'by': {r['_id']: r for r in rows}, 'prim': prim}
GONE = {m.split(' (')[0] for m in missing_fields}
def have(*refs):   # refs like 'Contact.ContactPhone'; False (and the check is skipped) when a table or field is gone
    return all(r.split('.')[0] in T and r not in GONE for r in refs)

# ---------- helpers
first = lambda v: (v or [None])[0]
num = lambda v: v if isinstance(v, (int, float)) else 0
norm = lambda s: re.sub(r'[^a-z0-9]', '', str(s or '').lower())
digits = lambda s: re.sub(r'\D', '', str(s or ''))
iso = lambda s: dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
def name(tn, rid):
    r = T[tn]['by'].get(rid)
    if not r: return rid
    v = r.get(T[tn]['prim']); return str(v).strip() if v not in (None, '', []) else f'(blank name) {rid}'
def names(tn, ids): return ', '.join(name(tn, x) for x in (ids or [])) or '-'
def rec(tn, r, detail=''):
    return {'table': tn, 'tableId': T[tn]['id'], 'id': r['_id'], 'name': name(tn, r['_id']), 'detail': detail}
FINDINGS = []; SKIPPED = []
def finding(fid, group, sev, title, why, cases, needs=()):
    if needs and not have(*needs):
        SKIPPED.append({'id': fid, 'title': title, 'missing': [n for n in needs if not have(n)]}); return
    kn = KNOWN.get(fid, {})
    for c in cases:
        key = c.get('key')
        if key is not None and str(key) in kn: c['known'] = kn[str(key)]
    if cases: FINDINGS.append({'id': fid, 'group': group, 'sev': sev, 'title': title, 'why': why, 'cases': cases})
def case(label, records, key=None): return {'label': label, 'records': records, 'key': key}
def dup_groups(tn, keyfn):
    g = defaultdict(list)
    for r in T[tn]['rows']:
        k = keyfn(r)
        if k: g[k].append(r)
    return [v for v in g.values() if len(v) > 1]
def rows(tn): return T[tn]['rows'] if tn in T else []

def contact_detail(r):
    return f"{r.get('ContactRole') or 'no role'}; customer {names('Customer', r.get('CustomerName'))}; email {r.get('ContactEmail') or '-'}; phone {r.get('ContactPhone') or '-'}; active {'yes' if r.get('ContactActive') else 'no'}; made {r['_created'][:10]}"

# ======================= DUPLICATES
if have('Contact.ContactName'):
    cs = [case(f"{v[0].get('ContactName','').strip()} ({len(v)} rows)", [rec('Contact', r, contact_detail(r)) for r in v], key=norm(v[0].get('ContactName')))
          for v in dup_groups('Contact', lambda r: norm(r.get('ContactName')))]
    # near-same names: same last name and one first name starts with the other (Norm / Norman)
    by_last = defaultdict(list)
    for r in rows('Contact'):
        nm = (r.get('ContactName') or '').strip().split()
        if len(nm) >= 2: by_last[norm(nm[-1])].append(r)
    for last, v in by_last.items():
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                a, b = norm(v[i]['ContactName'].split()[0]), norm(v[j]['ContactName'].split()[0])
                if a != b and len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
                    cs.append(case(f"{v[i]['ContactName'].strip()} / {v[j]['ContactName'].strip()} (similar names)", [rec('Contact', v[i], contact_detail(v[i])), rec('Contact', v[j], contact_detail(v[j]))], key=f"{norm(v[i]['ContactName'])}|{norm(v[j]['ContactName'])}"))
    finding('contact-same-name', 'Contacts', 'wrong', 'Contacts that appear more than once',
            'Same person on two rows, or two people with one name. Compare email and phone on each row, keep one, and move its links.', cs, needs=('Contact.ContactName',))
if have('Contact.ContactPhone', 'Contact.CustomerName'):
    same_team, cross = [], []
    for g in dup_groups('Contact', lambda r: digits(r.get('ContactPhone'))[-10:] if len(digits(r.get('ContactPhone'))) >= 7 else None):
        k = digits(g[0].get('ContactPhone'))[-10:]
        c = case(f"Phone ending {k[-4:]} ({len(g)} rows)", [rec('Contact', r, contact_detail(r)) for r in g], key=k)
        custs = {tuple(sorted(r.get('CustomerName') or [])) for r in g}
        (same_team if len(custs) == 1 and custs != {()} and len({norm(r.get('ContactName')) for r in g}) > 1 else cross).append(c)
    finding('contact-same-phone', 'Contacts', 'wrong', 'Same phone number on contacts of different teams, on a technician, or on one person twice',
            'A number cannot belong to a customer contact and a Trajekt technician, or to two teams. One row in each group carries the wrong number, or the rows are one person.', cross)
    finding('contact-same-phone-team', 'Contacts', 'check', 'Same phone number on two people of the same team',
            'Can be a shared team office line. If it is a mobile, one row carries the wrong number.', same_team)
finding('contact-same-email', 'Contacts', 'check', 'Different contact rows with the same email',
        'A shared inbox is fine for a customer, but a workflow that emails a person by address reaches both.',
        [case(f"{v[0].get('ContactEmail')} ({len(v)} rows)", [rec('Contact', r, contact_detail(r)) for r in v], key=norm(v[0].get('ContactEmail')))
         for v in dup_groups('Contact', lambda r: (r.get('ContactEmail') or '').strip().lower() or None)], needs=('Contact.ContactEmail',))
finding('contact-same-slack', 'Contacts', 'wrong', 'Different contact rows with the same Slack ID', 'A Slack ID belongs to one person.',
        [case(f"{v[0].get('ContactSlackID')}", [rec('Contact', r, contact_detail(r)) for r in v]) for v in dup_groups('Contact', lambda r: (r.get('ContactSlackID') or '').strip() or None)], needs=('Contact.ContactSlackID',))

cust_d = lambda r: f"active {'yes' if r.get('CustomerActive') else 'no'}; QuickBooks {r.get('CustomerQuickbooksID') or '-'}; legal name {r.get('CustomerLegal Name') or '-'}; machines {len(r.get('MachineID') or [])}"
for fid, fld, label in (('customer-same-name', 'CustomerName', 'name'), ('customer-same-qb', 'CustomerQuickbooksID', 'QuickBooks ID'), ('customer-same-tax', 'CustomerTaxID', 'tax ID'), ('customer-same-acronym', 'CustomerAcronym', 'acronym')):
    finding(fid, 'Customers', 'wrong', f'Customers with the same {label}', f'A {label} must point to one customer.' + (' Invoices can go to the wrong account.' if label == 'QuickBooks ID' else ''),
            [case(f"{label} {v[0].get(fld)}", [rec('Customer', r, cust_d(r)) for r in v]) for v in dup_groups('Customer', lambda r, fld=fld: norm(r.get(fld)) if norm(r.get(fld)) not in ('', '0', 'na', 'none', 'tbd') else None)], needs=(f'Customer.{fld}',))

fac_d = lambda r: f"customer {names('Customer', r.get('CustomerName'))}; machines {names('Machines', r.get('MachinesID'))}; address {r.get('FacilityAddress') or '-'}"
finding('facility-same-name', 'Facilities', 'wrong', 'Facilities with the same name',
        'People pick the wrong row from a list of identical names. Where two teams share a complex, put the team in the name (for example "Peoria Sports Complex (Padres)") or keep one row linked to both teams.',
        [case(f"{v[0]['FacilityName'].strip()} ({len(v)} rows)", [rec('Facility', r, fac_d(r)) for r in v]) for v in dup_groups('Facility', lambda r: norm(r.get('FacilityName')))], needs=('Facility.FacilityName',))
finding('facility-same-address', 'Facilities', 'check', 'Facilities with the same address but a different name', 'Probably one place entered twice.',
        [case(f"{v[0].get('FacilityAddress')}", [rec('Facility', r, fac_d(r)) for r in v]) for v in dup_groups('Facility', lambda r: norm(r.get('FacilityAddress')) or None) if len({norm(r['FacilityName']) for r in v}) > 1], needs=('Facility.FacilityAddress',))

wh_d = lambda r: f"type {r.get('WarehouseType') or '-'}; contact {r.get('WarehouseContactName') or '-'}; email {r.get('WarehouseEmail') or '-'}; phone {r.get('WarehousePhone') or '-'}; parts {len(r.get('InventoryName') or [])}"
wcases = [case(f"{v[0]['WarehouseName']} ({len(v)} rows)", [rec('Warehouse', r, wh_d(r)) for r in v]) for v in dup_groups('Warehouse', lambda r: norm(r.get('WarehouseName')))]
wcases += [case(f"Same email {v[0].get('WarehouseEmail')}", [rec('Warehouse', r, wh_d(r)) for r in v]) for v in dup_groups('Warehouse', lambda r: (r.get('WarehouseEmail') or '').lower().strip() or None)]
wcases += [case(f"Same phone {v[0].get('WarehousePhone')}", [rec('Warehouse', r, wh_d(r)) for r in v]) for v in dup_groups('Warehouse', lambda r: digits(r.get('WarehousePhone'))[-10:] or None)]
wh = rows('Warehouse')
for i in range(len(wh)):
    for j in range(i + 1, len(wh)):
        a, b = norm(wh[i].get('WarehouseName')), norm(wh[j].get('WarehouseName'))
        if a != b and min(len(a), len(b)) >= 5 and (a in b or b in a):
            wcases.append(case(f"{wh[i]['WarehouseName']} / {wh[j]['WarehouseName']} (one name contains the other)", [rec('Warehouse', wh[i], wh_d(wh[i])), rec('Warehouse', wh[j], wh_d(wh[j]))]))
finding('warehouse-dupes', 'Warehouses', 'check', 'Warehouses or vendors that look like the same company', 'Same name, same email or phone, or one name inside the other. Keep one row per company unless they are real separate accounts.', wcases, needs=('Warehouse.WarehouseName',))

finding('scope-same-name', 'Scope (SOPs)', 'wrong', 'Scopes with the same name', 'Work orders can link either copy, so SOP history splits in two.',
        [case(f"{v[0]['ScopeName'].strip()}", [rec('Scope', r, f"SOP title {r.get('ScopeSOPTitle') or '-'}; WOs linked {len(r.get('WorkOrderID') or [])}; URL {'yes' if r.get('ScopeURL') else 'no'}") for r in v]) for v in dup_groups('Scope', lambda r: norm(r.get('ScopeName')))], needs=('Scope.ScopeName',))
finding('scope-same-url', 'Scope (SOPs)', 'check', 'Scopes that point to the same SOP document or title', 'Different scopes should open different SOPs. A shared placeholder title means the real title was never filled.',
        [case(f"{k}", [rec('Scope', r, f"SOP title {r.get('ScopeSOPTitle') or '-'}") for r in v]) for k, v in [(g[0].get('ScopeSOPTitle'), g) for g in dup_groups('Scope', lambda r: norm(r.get('ScopeSOPTitle')) or None)] + [(g[0].get('ScopeURL'), g) for g in dup_groups('Scope', lambda r: (r.get('ScopeURL') or '').strip() or None)]], needs=('Scope.ScopeSOPTitle', 'Scope.ScopeURL'))

inv_d = lambda r: f"Trajekt P/N {r.get('InventoryTrajektPartNumber') or '-'}; vendor P/N {r.get('InventoryVendorPartNumber') or '-'}; cost {r.get('InventoryCostUSD') if r.get('InventoryCostUSD') is not None else '-'}; status {r.get('Status') or '-'}"
finding('inventory-dupes', 'Inventory', 'wrong', 'Parts that share a name or a Trajekt part number', 'A part number must identify one part.',
        [case(f"Name {v[0]['InventoryPartName']}", [rec('Inventory', r, inv_d(r)) for r in v]) for v in dup_groups('Inventory', lambda r: norm(r.get('InventoryPartName')))] +
        [case(f"Trajekt P/N {v[0]['InventoryTrajektPartNumber']}", [rec('Inventory', r, inv_d(r)) for r in v]) for v in dup_groups('Inventory', lambda r: norm(r.get('InventoryTrajektPartNumber')) or None)],
        needs=('Inventory.InventoryPartName', 'Inventory.InventoryTrajektPartNumber'))
finding('po-dupes', 'Purchase orders', 'wrong', 'Purchase order numbers entered more than once', 'Spend totals count each copy.',
        [case(f"PO {v[0]['PO Number']}", [rec('Purchase order history', r, f"{r.get('Date')}; {r.get('Vendor')}; {r.get('Amount')} {r.get('Currency') or ''}") for r in v]) for v in dup_groups('Purchase order history', lambda r: norm(r.get('PO Number')) or None)], needs=('Purchase order history.PO Number',))
inst_d = lambda r: f"type {r.get('InstallType') or '-'}; pick-up {r.get('InstallPickupDate') or '-'}; drop-off {r.get('InstallDropoffDate') or '-'}; target {r.get('InstallTargetDate') or '-'}; WOs {names('Work Orders', r.get('WorkOrderID'))}; made {r['_created'][:10]}"
finding('install-twins', 'Installs', 'wrong', 'Install rows that are exact twins', 'Same machine, same type and same date. One row of each pair is extra.',
        [case(f"{name('Installs', v[0]['_id'])}", [rec('Installs', r, inst_d(r)) for r in v]) for v in dup_groups('Installs', lambda r: (first(r.get('MachineID')), r.get('InstallType'), r.get('InstallDropoffDate') or r.get('InstallPickupDate') or r.get('InstallTargetDate')) if r.get('MachineID') and r.get('InstallType') and (r.get('InstallDropoffDate') or r.get('InstallPickupDate') or r.get('InstallTargetDate')) else None)],
        needs=('Installs.MachineID', 'Installs.InstallType', 'Installs.InstallDropoffDate', 'Installs.InstallPickupDate'))
wos_d = lambda r: f"start {str(r.get('WorkOrderSummaryStartDate') or '-')[:16]}; end {str(r.get('WorkOrderSummaryEndDate') or '-')[:16]}; type {r.get('WorkOrderSummaryType') or '-'}; support {r.get('WorkOrderSummarySupportType') or '-'}; made {r['_created'][:10]}"
finding('visit-twins', 'Visits', 'check', 'Two visit rows for the same person, WO and day', 'Often a double form submit. Same start time to the minute is almost always a duplicate.',
        [case(f"WO {names('Work Orders', v[0].get('WorkOrderID'))}, {names('Contact', v[0].get('ContactName-Onsite'))}, {v[0]['WorkOrderSummaryStartDate'][:10]}", [rec('Work Order Summary', r, wos_d(r)) for r in v], key=names('Work Orders', v[0].get('WorkOrderID')))
         for v in dup_groups('Work Order Summary', lambda r: (first(r.get('WorkOrderID')), first(r.get('ContactName-Onsite')), str(r.get('WorkOrderSummaryStartDate'))[:10]) if r.get('WorkOrderID') and r.get('ContactName-Onsite') and r.get('WorkOrderSummaryStartDate') else None)],
        needs=('Work Order Summary.WorkOrderID', 'Work Order Summary.ContactName-Onsite', 'Work Order Summary.WorkOrderSummaryStartDate'))
woc_total = lambda r: num(r.get('WOCostTotalWages')) + num(r.get('WOCostTotalExpense'))
woc_d = lambda r: f"wages ${num(r.get('WOCostTotalWages')):,.2f}; expenses ${num(r.get('WOCostTotalExpense')):,.2f}; on-site {num(r.get('WOCostHoursOnSite')):g} h; Fillout id {'yes' if r.get('FilloutSubmissionID') else 'no'}; made {r['_created'][:10]}"
finding('cost-twins', 'Cost rows', 'check', 'Two cost rows for the same person on the same work order', 'Fine when the person made two trips. Otherwise one row is a double invoice.',
        [case(f"WO {names('Work Orders', v[0].get('WorkOrderID'))}, {names('Contact', v[0].get('ContactName'))}", [rec('Work Order Cost', r, woc_d(r)) for r in v], key=names('Work Orders', v[0].get('WorkOrderID')))
         for v in dup_groups('Work Order Cost', lambda r: (first(r.get('WorkOrderID')), first(r.get('ContactName'))) if r.get('WorkOrderID') and r.get('ContactName') else None)],
        needs=('Work Order Cost.WorkOrderID', 'Work Order Cost.ContactName'))
for tn, fld, label in (('Work Orders', 'WorkOrderFilloutSubmissionID', 'Fillout submission id'), ('Work Orders', 'WorkOrderSlackChannel', 'Slack channel'), ('Work Orders', 'WorkOrderBriefEmailID', 'brief email id'),
                       ('Work Order Summary', 'WorkOrderSummaryFilloutID', 'Fillout id'), ('Work Order Cost', 'FilloutSubmissionID', 'Fillout submission id'), ('Installs', 'InstallFilloutID', 'Fillout id')):
    finding(f'unique-{norm(tn)}-{norm(fld)}', 'Unique ids', 'wrong', f'{tn}: the same {label} on more than one row', 'This id comes from one form submission or one Slack channel, so it must be on one row. Automations find rows by it.',
            [case(f"{v[0].get(fld)}", [rec(tn, r, f"made {r['_created'][:10]}") for r in v]) for v in dup_groups(tn, lambda r, fld=fld: str(r.get(fld) or '').strip() or None)], needs=(f'{tn}.{fld}',))

# ======================= MACHINES
mach_d = lambda r: f"status {r.get('MachineStatus') or '-'}; customer {names('Customer', r.get('CustomerName'))}; facility {names('Facility', r.get('LocationName'))}"
if have('Machines.MachineW1Serial', 'Machines.MachineW2Serial', 'Machines.MachineW3Serial'):
    cs = []; slots = ('MachineW1Serial', 'MachineW2Serial', 'MachineW3Serial')
    for r in rows('Machines'):
        c = Counter(norm(r.get(f)) for f in slots if r.get(f))
        for k, n in c.items():
            if n > 1: cs.append(case(f"{r['MachineID']}: one serial in {n} wheel slots", [rec('Machines', r, ' / '.join(f"{f[7:9]} {r.get(f) or '-'}" for f in slots))]))
    g = defaultdict(list)
    for r in rows('Machines'):
        for f in slots:
            if norm(r.get(f)): g[norm(r.get(f))].append(r)
    for k, v in g.items():
        ms = {r['_id']: r for r in v}
        if len(ms) > 1:
            linked = all(any(x in (ms[a].get('MachinePreviousID') or []) + (ms[a].get('MachineNextID') or []) for x in ms if x != a) for a in ms)   # a rebuild shares its wheels
            if not linked: cs.append(case(f"Serial {v[0].get(next(f for f in slots if norm(v[0].get(f)) == k))} on {len(ms)} machines", [rec('Machines', r, ' / '.join(f"{f[7:9]} {r.get(f) or '-'}" for f in slots)) for r in ms.values()]))
    finding('machine-wheel-serials', 'Machines', 'wrong', 'Wheel serial numbers used twice', 'A wheel sits in one slot on one machine. (A machine and its rebuild, linked by Previous/Next, may share wheels and are left out.)', cs)
for fld, label, sev in (('MachineMACAddress', 'computer MAC address', 'check'), ('MachineComputerSerial', 'computer serial', 'wrong'), ('MachineTeamViewerID', 'TeamViewer ID', 'wrong'), ('MachineIPAddress', 'IP address', 'tidy')):
    finding(f'machine-same-{norm(fld)}', 'Machines', sev, f'The same {label} on more than one machine',
            'Private 10.x addresses repeat across sites, so treat IP matches as a hint only.' if 'IP' in label else 'One computer can be in one machine. If it moved, clear it on the old machine.',
            [case(f"{v[0].get(fld)}", [rec('Machines', r, mach_d(r)) for r in v]) for v in dup_groups('Machines', lambda r, fld=fld: norm(r.get(fld)) if norm(r.get(fld)) not in ('', 'na', 'none', 'tbd', 'unknown') else None)], needs=(f'Machines.{fld}',))
cs = []
for r in rows('Machines'):
    for a, b in (('MachineBuildStartDate', 'MachineFATPassed'), ('MachineFATPassed', 'MachineInstallComplete'), ('MachineBuildStartDate', 'MachineInstallComplete')):
        if r.get(a) and r.get(b) and r[b] < r[a]: cs.append(case(f"{r['MachineID']}: {b} {r[b]} is before {a} {r[a]}", [rec('Machines', r, f"build {r.get('MachineBuildStartDate') or '-'}; FAT {r.get('MachineFATPassed') or '-'}; install {r.get('MachineInstallComplete') or '-'}")]))
finding('machine-date-order', 'Machines', 'wrong', 'Machine dates in the wrong order', 'Build, then FAT, then install. A year typo is the usual cause.', cs, needs=('Machines.MachineBuildStartDate', 'Machines.MachineFATPassed', 'Machines.MachineInstallComplete'))
cs = []
if have('Machines.CustomerName', 'Machines.MachineStatus', 'Customer.CustomerActive', 'Machines.LocationName', 'Facility.CustomerName'):
    for r in rows('Machines'):
        c = first(r.get('CustomerName')); fac = first(r.get('LocationName')); st = r.get('MachineStatus')
        cust = T['Customer']['by'].get(c, {})
        if st == 'Active' and not c: cs.append(case(f"{r['MachineID']}: Active with no customer", [rec('Machines', r, mach_d(r))]))
        if st == 'Active' and c and not cust.get('CustomerActive'): cs.append(case(f"{r['MachineID']}: Active, but its customer is inactive", [rec('Machines', r, mach_d(r)), rec('Customer', cust, cust_d(cust))]))
        if st == 'Active' and not fac: cs.append(case(f"{r['MachineID']}: Active with no facility", [rec('Machines', r, mach_d(r))]))
        if len(r.get('CustomerName') or []) > 1 or len(r.get('LocationName') or []) > 1: cs.append(case(f"{r['MachineID']}: linked to more than one customer or facility", [rec('Machines', r, mach_d(r))]))
        if fac and c:
            fr = T['Facility']['by'].get(fac, {})
            if fr.get('CustomerName') and c not in fr['CustomerName']: cs.append(case(f"{r['MachineID']}: its facility belongs to another customer", [rec('Machines', r, mach_d(r)), rec('Facility', fr, fac_d(fr))]))
finding('machine-links', 'Machines', 'check', 'Machine status, customer and facility do not fit together', 'An Active machine needs an active customer and a facility of that customer.', cs)
cs = []
for r in rows('Machines'):
    for a, b in (('MachinePreviousID', 'MachineNextID'), ('MachineNextID', 'MachinePreviousID')):
        for x in r.get(a) or []:
            o = T['Machines']['by'].get(x)
            if o and r['_id'] not in (o.get(b) or []): cs.append(case(f"{r['MachineID']}.{a} = {o['MachineID']}, but {o['MachineID']}.{b} does not point back", [rec('Machines', r, mach_d(r)), rec('Machines', o, mach_d(o))]))
finding('machine-prev-next', 'Machines', 'wrong', 'Previous / Next machine links do not match', 'A rebuild link must be set on both machines.', cs, needs=('Machines.MachinePreviousID', 'Machines.MachineNextID'))
cs = []
if have('Machines.MachineDownStatus', 'Machines.WorkOrderID', 'Work Orders.WorkOrderMachineDowntimeStart', 'Work Orders.WorkOrderMachineDowntimeStop'):
    for r in rows('Machines'):
        opn = [T['Work Orders']['by'][w] for w in (r.get('WorkOrderID') or []) if w in T['Work Orders']['by'] and T['Work Orders']['by'][w].get('WorkOrderMachineDowntimeStart') and not T['Work Orders']['by'][w].get('WorkOrderMachineDowntimeStop')]
        if opn and r.get('MachineDownStatus') != 'Down': cs.append(case(f"{r['MachineID']} says {r.get('MachineDownStatus') or 'blank'}, but a WO downtime clock is still running", [rec('Machines', r, mach_d(r))] + [rec('Work Orders', w, f"downtime start {w['WorkOrderMachineDowntimeStart'][:16]}") for w in opn]))
        if r.get('MachineDownStatus') == 'Down' and not opn: cs.append(case(f"{r['MachineID']} says Down, but no WO has a running downtime clock", [rec('Machines', r, mach_d(r))]))
        if not r.get('MachineDownStatus'): cs.append(case(f"{r['MachineID']}: MachineDownStatus blank ({r.get('MachineStatus')})", [rec('Machines', r, mach_d(r))]))
finding('machine-down-status', 'Machines', 'check', 'MachineDownStatus does not match the work orders', 'The dashboards read MachineDownStatus; the WO downtime clock is the source.', cs)

# ======================= WORK ORDERS
wo_d = lambda r: f"type {', '.join(r.get('WorkOrderType') or []) or '-'}; complete {r.get('WorkOrderComplete?') or '-'}; machine {names('Machines', r.get('MachineID'))}; customer {names('Customer', r.get('CustomerName'))}; requested {str(r.get('WorkOrderRequestedStartDateAndTime') or '-')[:10]}; made {r['_created'][:10]}"
cs = []
if have('Work Orders.MachineID', 'Work Orders.CustomerName', 'Work Orders.LocationName'):
    for r in rows('Work Orders'):
        miss = [lab for lab, f in (('machine', 'MachineID'), ('customer', 'CustomerName'), ('facility', 'LocationName'), ('type', 'WorkOrderType')) if not r.get(f)]
        many = [lab for lab, f in (('machines', 'MachineID'), ('customers', 'CustomerName'), ('facilities', 'LocationName')) if len(r.get(f) or []) > 1]
        if miss or many: cs.append(case(f"WO {r['WorkOrderID']}: " + ', '.join([f'no {m}' for m in miss] + [f'more than one of {m}' for m in many]), [rec('Work Orders', r, wo_d(r))]))
finding('wo-missing-links', 'Work orders', 'check', 'Work orders missing a machine, customer, facility or type', 'Tech Briefs need the facility for the address and time zone. Reports group by customer and machine.', cs)
cs = []
if have('Work Orders.CustomerName', 'Work Orders.LocationName', 'Facility.CustomerName'):
    for r in rows('Work Orders'):
        c, fac = first(r.get('CustomerName')), first(r.get('LocationName'))
        fr = T['Facility']['by'].get(fac, {})
        if c and fr.get('CustomerName') and c not in fr['CustomerName']: cs.append(case(f"WO {r['WorkOrderID']}: customer {name('Customer', c)}, facility row belongs to {names('Customer', fr['CustomerName'])}", [rec('Work Orders', r, wo_d(r)), rec('Facility', fr, fac_d(fr))]))
finding('wo-facility-customer', 'Work orders', 'wrong', "Work orders that point at another customer's facility row", "The site contacts on that facility row belong to the other customer. Usually caused by two facilities with the same name.", cs)
cs = []
if have('Work Orders.WorkOrderComplete?', 'Work Orders.WorkOrderSummaryName'):
    for r in rows('Work Orders'):
        if r.get('WorkOrderComplete?') == 'Yes' and not r.get('WorkOrderSummaryName'): cs.append(case(f"WO {r['WorkOrderID']}", [rec('Work Orders', r, wo_d(r) + f"; ref {r.get('WorkOrderReferenceNumber') or '-'}")]))
finding('wo-complete-no-visit', 'Work orders', 'check', 'Complete work orders with no visit (summary) row', 'Nothing records who went, when, or what was done. Reports date these by the requested start.', cs)
cs = []
for r in rows('Work Orders'):
    s, e = r.get('WorkOrderMachineDowntimeStart'), r.get('WorkOrderMachineDowntimeStop')
    d = f"downtime {str(s or '-')[:16]} to {str(e or '-')[:16]}; not operable {'ticked' if r.get('WorkOrderMachineNotOperable') else 'unticked'}; complete {r.get('WorkOrderComplete?') or '-'}"
    if s and e and e < s: cs.append(case(f"WO {r['WorkOrderID']}: downtime stop before start", [rec('Work Orders', r, d)]))
    if e and not s: cs.append(case(f"WO {r['WorkOrderID']}: downtime stop with no start", [rec('Work Orders', r, d)]))
    if s and e and (iso(e) - iso(s)).days > 60: cs.append(case(f"WO {r['WorkOrderID']}: downtime longer than 60 days", [rec('Work Orders', r, d)]))
finding('wo-downtime', 'Work orders', 'wrong', 'Downtime dates that contradict each other', 'A stop before its start, a stop with no start, or a clock longer than 60 days. The dashboards compute downtime from these two dates.', cs, needs=('Work Orders.WorkOrderMachineDowntimeStart', 'Work Orders.WorkOrderMachineDowntimeStop'))
cs = []
for r in rows('Work Orders'):
    s, e = r.get('WorkOrderMachineDowntimeStart'), r.get('WorkOrderMachineDowntimeStop')
    d = f"downtime {str(s or '-')[:16]} to {str(e or '-')[:16]}; not operable {'ticked' if r.get('WorkOrderMachineNotOperable') else 'unticked'}; complete {r.get('WorkOrderComplete?') or '-'}"
    if s and not r.get('WorkOrderMachineNotOperable'): cs.append(case(f"WO {r['WorkOrderID']}: downtime start, but 'Not Operable' is unticked", [rec('Work Orders', r, d)]))
    if s and not e and r.get('WorkOrderComplete?') == 'Yes': cs.append(case(f"WO {r['WorkOrderID']}: complete, but its downtime clock never stopped", [rec('Work Orders', r, d)]))
finding('wo-downtime-flag', 'Work orders', 'check', "Downtime clock and the 'Not Operable' box or Complete status disagree", 'Not every workflow that sets the downtime dates also ticks the box, so this may be normal. Check before fixing.', cs, needs=('Work Orders.WorkOrderMachineDowntimeStart', 'Work Orders.WorkOrderMachineNotOperable'))
cs = []
if have('Work Orders.WorkOrderSummaryName', 'Work Orders.WorkOrderRequestedStartDateAndTime', 'Work Order Summary.WorkOrderSummaryStartDate'):
    for r in rows('Work Orders'):
        vs = [T['Work Order Summary']['by'][s].get('WorkOrderSummaryStartDate') for s in (r.get('WorkOrderSummaryName') or []) if s in T['Work Order Summary']['by']]
        vs = [v for v in vs if v]; rs = r.get('WorkOrderRequestedStartDateAndTime')
        if vs and rs and (iso(min(vs)) - iso(rs)).days < -30: cs.append(case(f"WO {r['WorkOrderID']}: first visit {min(vs)[:10]}, requested start {rs[:10]}", [rec('Work Orders', r, wo_d(r))]))
finding('wo-visit-before-request', 'Work orders', 'tidy', 'First visit more than 30 days before the requested start', 'The requested start is normally the booked visit date. On WOs imported from Notion the requested start is less reliable, so these are usually import leftovers, not live mistakes.', cs)
finding('wo-intercom-not-intercom', 'Work orders', 'tidy', 'Intercom ticket field holds something that is not an Intercom link', 'Placeholders like https://www.na.com, or Slack / form / doc links.',
        [case(f"WO {r['WorkOrderID']}: {r['WorkOrderIntercomTicket'][:90]}", [rec('Work Orders', r, '')]) for r in rows('Work Orders') if r.get('WorkOrderIntercomTicket') and 'intercom' not in r['WorkOrderIntercomTicket'].lower()],
        needs=('Work Orders.WorkOrderIntercomTicket',))

# ======================= VISITS
cs = []
for r in rows('Work Order Summary'):
    s, e = r.get('WorkOrderSummaryStartDate'), r.get('WorkOrderSummaryEndDate')
    if s and e and e < s: cs.append(case(f"{name('Work Order Summary', r['_id'])}: end before start", [rec('Work Order Summary', r, wos_d(r))]))
    elif s and e and (iso(e) - iso(s)).days > 14: cs.append(case(f"{name('Work Order Summary', r['_id'])}: {(iso(e) - iso(s)).days} days", [rec('Work Order Summary', r, wos_d(r))]))
    for f in ('WorkOrderSummaryStartDate', 'WorkOrderSummaryEndDate'):
        if r.get(f) and str(r[f])[:10] > TODAY: cs.append(case(f"{name('Work Order Summary', r['_id'])}: {f} is in the future", [rec('Work Order Summary', r, wos_d(r))]))
    if s and r.get('SubmittedDate') and r['SubmittedDate'] < s[:10]: cs.append(case(f"{name('Work Order Summary', r['_id'])}: submitted before the visit started", [rec('Work Order Summary', r, wos_d(r) + f"; submitted {r['SubmittedDate']}")]))
cs.sort(key=lambda c: -int(re.search(r'(\d+) days', c['label']).group(1)) if re.search(r'(\d+) days', c['label']) else 0)
finding('visit-dates', 'Visits', 'wrong', 'Visit dates that cannot be right', 'End before start, a date in the future, or one "visit" longer than 14 days (usually a wrong end month). Hours and downtime reports use these dates.', cs,
        needs=('Work Order Summary.WorkOrderSummaryStartDate', 'Work Order Summary.WorkOrderSummaryEndDate'))
cs = []
if have('Work Order Summary.ContactName-Onsite', 'Work Order Summary.WorkOrderSummaryStartDate', 'Work Order Summary.WorkOrderSummaryEndDate', 'Work Orders.LocationName'):
    by = defaultdict(list)
    for r in rows('Work Order Summary'):
        p, s, e = first(r.get('ContactName-Onsite')), r.get('WorkOrderSummaryStartDate'), r.get('WorkOrderSummaryEndDate')
        if p and s and e and r.get('WorkOrderSummarySupportType') != 'On Call/ Slack messages' and (iso(e) - iso(s)).days <= 3: by[p].append(r)
    for p, vs in by.items():
        vs.sort(key=lambda r: r['WorkOrderSummaryStartDate'])
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                a, b = vs[i], vs[j]
                if b['WorkOrderSummaryStartDate'] >= a['WorkOrderSummaryEndDate']: break
                wa, wb = first(a.get('WorkOrderID')), first(b.get('WorkOrderID'))
                fa = first(T['Work Orders']['by'].get(wa, {}).get('LocationName')); fb = first(T['Work Orders']['by'].get(wb, {}).get('LocationName'))
                if wa != wb and fa and fb and fa != fb:
                    cs.append(case(f"{name('Contact', p)}: {name('Facility', fa)} and {name('Facility', fb)} at the same time", [rec('Work Order Summary', a, wos_d(a) + f"; facility {name('Facility', fa)}"), rec('Work Order Summary', b, wos_d(b) + f"; facility {name('Facility', fb)}")]))
finding('visit-overlap', 'Visits', 'check', 'One person at two different facilities at the same time', 'The times on one row of each pair are wrong (often a copied start time). Fillout stores times in the typing person\'s time zone, so check the zone first.', cs)
cs = []
if have('Work Order Summary.ContactName-Onsite', 'Work Order Summary.WorkOrderID'):
    for r in rows('Work Order Summary'):
        miss = [lab for lab, f in (('person', 'ContactName-Onsite'), ('work order', 'WorkOrderID'), ('start date', 'WorkOrderSummaryStartDate'), ('type', 'WorkOrderSummaryType')) if not r.get(f)]
        if miss: cs.append(case(f"{name('Work Order Summary', r['_id'])}: no {', no '.join(miss)}", [rec('Work Order Summary', r, wos_d(r))]))
finding('visit-missing', 'Visits', 'check', 'Visit rows missing the person, work order, date or type', 'A visit with no person cannot be paid or counted.', cs)

# ======================= COST ROWS
EXP = ('WOCostExpenseAccomodation', 'WOCostExpenseFlights', 'WOCostExpenseLand', 'WOCostExpenseTools', 'WOCostExpenseMeals', 'WOCostExpenseOther')
HRS = ('WOCostHoursOnSite', 'WOCostHoursTravellingLand', 'WOCostHoursTravellingAir', 'WoCostHoursTravelLayover')
WG = ('WOCostWageOnSite', 'WOCostWageTravelLand', 'WOCostWageTravelAir', 'WOCostWageTravelLayover')
cost_rows = rows('Work Order Cost')
cs = []
for r in cost_rows:
    miss = [lab for lab, f in (('work order', 'WorkOrderID'), ('person', 'ContactName')) if not r.get(f)]
    many = [lab for lab, f in (('work orders', 'WorkOrderID'), ('people', 'ContactName')) if len(r.get(f) or []) > 1]
    h = sum(num(r.get(f)) for f in HRS); w = sum(num(r.get(f)) for f in WG); x = sum(num(r.get(f)) for f in EXP)
    probs = [f'no {m}' for m in miss] + [f'more than one of {m}' for m in many]
    if h == 0 and w == 0 and x == 0: probs.append('0 hours, $0 wages and $0 expenses')
    if w > 0 and h == 0: probs.append('wages with 0 hours')
    if h > 0 and w == 0: probs.append('hours with $0 wages')
    if any(num(r.get(f)) < 0 for f in HRS + WG + EXP): probs.append('a negative value')
    if probs: cs.append(case(f"{name('Work Order Cost', r['_id'])}: {'; '.join(probs)}", [rec('Work Order Cost', r, woc_d(r))]))
finding('cost-missing', 'Cost rows', 'wrong', 'Cost rows with missing or impossible information', 'Every cost row needs one work order, one person, and hours that match the wages.', cs, needs=('Work Order Cost.WorkOrderID', 'Work Order Cost.ContactName'))
cs = []
if have('Work Order Cost.ContactName', 'Contact.ContactRateOnSite', 'Contact.ContactRateLandTravel', 'Contact.ContactRateAirTravel'):
    for r in cost_rows:
        p = T['Contact']['by'].get(first(r.get('ContactName')), {}) if len(r.get('ContactName') or []) == 1 else {}
        if not p: continue
        ron, rl, ra = p.get('ContactRateOnSite'), p.get('ContactRateLandTravel'), p.get('ContactRateAirTravel')
        bad = []
        if ron is not None and abs(num(r.get('WOCostHoursOnSite')) * ron - num(r.get('WOCostWageOnSite'))) > 1: bad.append(f"on-site {num(r.get('WOCostHoursOnSite')):g} h x ${ron} = ${num(r.get('WOCostHoursOnSite')) * ron:,.2f}, stored ${num(r.get('WOCostWageOnSite')):,.2f}")
        if rl is not None and abs(num(r.get('WOCostHoursTravellingLand')) * rl - num(r.get('WOCostWageTravelLand'))) > 1: bad.append(f"land {num(r.get('WOCostHoursTravellingLand')):g} h x ${rl} = ${num(r.get('WOCostHoursTravellingLand')) * rl:,.2f}, stored ${num(r.get('WOCostWageTravelLand')):,.2f}")
        if ra is not None and abs(num(r.get('WOCostHoursTravellingAir')) * ra - num(r.get('WOCostWageTravelAir'))) > 1: bad.append(f"air {num(r.get('WOCostHoursTravellingAir')):g} h x ${ra} = ${num(r.get('WOCostHoursTravellingAir')) * ra:,.2f}, stored ${num(r.get('WOCostWageTravelAir')):,.2f}")
        if ra is not None and abs(min(num(r.get('WoCostHoursTravelLayover')), 3) * ra - num(r.get('WOCostWageTravelLayover'))) > 1: bad.append(f"layover min({num(r.get('WoCostHoursTravelLayover')):g} h, 3) x ${ra}, stored ${num(r.get('WOCostWageTravelLayover')):,.2f}")
        if ron is None and sum(num(r.get(f)) for f in HRS) > 0: bad.append('the person has no on-site rate')
        if bad: cs.append(case(f"{name('Work Order Cost', r['_id'])}", [rec('Work Order Cost', r, '; '.join(bad)), rec('Contact', p, f"rates on-site {ron}, land {rl}, air {ra}")]))
finding('cost-hand-made', 'Cost rows', 'tidy', 'Cost rows made by hand (no Fillout submission id)',
        'Since 2026-09-10 cost rows come from the invoice form, which stamps a submission id. Rows without one were made by hand: fine when it was a deliberate back-fill, but they cannot be traced to a form.',
        [case(f"{name('Work Order Cost', r['_id'])}", [rec('Work Order Cost', r, woc_d(r))], key=name('Work Order Cost', r['_id'])) for r in cost_rows if r['_created'] > '2026-09-11' and not r.get('FilloutSubmissionID')],
        needs=('Work Order Cost.FilloutSubmissionID',))
finding('cost-rate-math', 'Cost rows', 'check', "Wages that do not equal hours x the person's current rate", 'The workflow stores wages when the invoice is submitted. A mismatch means a wrong rate on the invoice, or a rate that changed later.', cs)
cs = []
for r in cost_rows:
    fl, ov = r.get('WOCostFlight'), r.get('WOCostOvernight'); p = []
    if fl == 'No' and (num(r.get('WOCostExpenseFlights')) > 0 or num(r.get('WOCostHoursTravellingAir')) > 0): p.append('Flight = No, but flight cost or air hours')
    if fl == 'Yes' and num(r.get('WOCostExpenseFlights')) == 0 and num(r.get('WOCostHoursTravellingAir')) == 0: p.append('Flight = Yes, but no flight cost and 0 air hours')
    if ov == 'No' and (num(r.get('WOCostExpenseAccomodation')) > 0 or num(r.get('WOCostNightsInHotel')) > 0): p.append('Overnight = No, but hotel cost or nights')
    if ov == 'Yes' and num(r.get('WOCostExpenseAccomodation')) == 0 and num(r.get('WOCostNightsInHotel')) == 0: p.append('Overnight = Yes, but 0 nights and $0 hotel')
    if p: cs.append(case(f"{name('Work Order Cost', r['_id'])}: {'; '.join(p)}", [rec('Work Order Cost', r, f"flights ${num(r.get('WOCostExpenseFlights')):,.2f}; air {num(r.get('WOCostHoursTravellingAir')):g} h; hotel ${num(r.get('WOCostExpenseAccomodation')):,.2f}; nights {num(r.get('WOCostNightsInHotel')):g}")]))
finding('cost-yes-no', 'Cost rows', 'wrong', 'Flight or Overnight answers that contradict the money', 'The Yes/No answer and the amounts come from the same form, so one of them is wrong.', cs, needs=('Work Order Cost.WOCostFlight', 'Work Order Cost.WOCostOvernight'))
cs = []
for r in cost_rows:
    n, a = num(r.get('WOCostNightsInHotel')), num(r.get('WOCostExpenseAccomodation'))
    if (n > 0) != (a > 0): cs.append(case(f"{name('Work Order Cost', r['_id'])}: {n:g} nights, ${a:,.2f} hotel", [rec('Work Order Cost', r, woc_d(r))]))
finding('cost-hotel', 'Cost rows', 'check', 'Hotel nights and hotel cost do not agree', 'Nights with $0 hotel is fine if Trajekt booked the room. Hotel cost with 0 nights is mostly Notion-era rows, where nights were not asked.', cs, needs=('Work Order Cost.WOCostNightsInHotel', 'Work Order Cost.WOCostExpenseAccomodation'))
finding('cost-no-receipt', 'Cost rows', 'check', 'Expenses claimed with no receipt attached', 'Finance needs a receipt for each expense.',
        [case(f"{name('Work Order Cost', r['_id'])}: ${sum(num(r.get(f)) for f in EXP):,.2f}", [rec('Work Order Cost', r, woc_d(r))]) for r in cost_rows if sum(num(r.get(f)) for f in EXP) > 0 and not r.get('WOCostReceipts')],
        needs=('Work Order Cost.WOCostReceipts',))
if have('Work Order Summary.WorkOrderID', 'Work Order Summary.ContactName-Onsite', 'Work Order Cost.WorkOrderID', 'Work Order Cost.ContactName'):
    vis = {(first(r.get('WorkOrderID')), first(r.get('ContactName-Onsite'))) for r in rows('Work Order Summary')}
    cst = {(first(r.get('WorkOrderID')), first(r.get('ContactName'))) for r in cost_rows}
    finding('cost-no-visit', 'Cost rows', 'check', 'Cost rows with no visit row for the same work order and person', 'Money with no record of the visit (dates, notes, photos).',
            [case(f"{name('Work Order Cost', r['_id'])}", [rec('Work Order Cost', r, woc_d(r))], key=name('Work Order Cost', r['_id'])) for r in cost_rows if first(r.get('WorkOrderID')) and first(r.get('ContactName')) and (first(r.get('WorkOrderID')), first(r.get('ContactName'))) not in vis])
    finding('visit-no-cost', 'Cost rows', 'check', 'Technician visits with no cost row', 'The technician has not invoiced, or the invoice is linked to another work order or person.',
            [case(f"{name('Work Order Summary', r['_id'])}", [rec('Work Order Summary', r, wos_d(r))]) for r in rows('Work Order Summary') if r.get('WorkOrderSummaryType') == 'Technician' and first(r.get('WorkOrderID')) and first(r.get('ContactName-Onsite')) and (first(r.get('WorkOrderID')), first(r.get('ContactName-Onsite'))) not in cst])

# ======================= CONTACTS
cs = []
for r in rows('Contact'):
    fn, ln, nm = r.get('ContactFirstName'), r.get('ContactLastName'), r.get('ContactName') or ''
    p = []
    if nm != nm.strip() or '  ' in nm: p.append('name has extra spaces')
    if fn and ln and norm(fn + ln) != norm(nm): p.append(f'first/last say "{fn} {ln}"')
    if not fn or not ln: p.append('first or last name missing')
    if not r.get('ContactRole'): p.append('no role')
    if r.get('ContactRole') == 'Customer Contact' and not r.get('CustomerName'): p.append('customer contact with no customer')
    if set(r.get('CustomerName') or []) and r.get('Customer') and set(r['Customer']) != set(r['CustomerName']): p.append('its two customer links (CustomerName, Customer) disagree')
    if p: cs.append(case(f"{nm.strip()}: {'; '.join(p)}", [rec('Contact', r, contact_detail(r))]))
finding('contact-name-fields', 'Contacts', 'check', 'Contact name, role or customer does not add up', 'The full name should equal first + last name. Spelling differences mean one of them is a typo.', cs, needs=('Contact.ContactFirstName', 'Contact.ContactLastName', 'Contact.ContactRole'))
cs = []
for r in rows('Contact'):
    p = []
    if not r.get('ContactEmail'): p.append('no email' + (' (ACTIVE technician: invoice and brief emails stop)' if r.get('ContactRole') == 'Technician' and r.get('ContactActive') else ''))
    if r.get('ContactRole') == 'Trajekt' and r.get('ContactActive') and not r.get('ContactSlackID'): p.append('active staff with no Slack ID (not invited to WO channels)')
    if r.get('ContactRole') == 'Technician' and r.get('ContactActive') and r.get('ContactRateOnSite') in (None, 0): p.append('active technician with no on-site rate')
    if r.get('ContactActive') and r.get('CustomerName') and all(not T['Customer']['by'].get(c, {}).get('CustomerActive') for c in r['CustomerName']): p.append('active, but its customer is inactive')
    if p: cs.append(case(f"{(r.get('ContactName') or '').strip()}: {'; '.join(p)}", [rec('Contact', r, contact_detail(r))]))
finding('contact-missing', 'Contacts', 'check', 'Contacts missing what the automations need', 'Tech Briefs and the invoice workflow use email, Slack ID and rates.', cs, needs=('Contact.ContactEmail', 'Contact.ContactSlackID', 'Contact.ContactActive'))
finding('contact-phone-format', 'Contacts', 'tidy', 'Phone numbers not in +country format', 'Mixed formats (416-…, (416) …, plain digits) make matching and dialing harder.',
        [case(f"{(r.get('ContactName') or '').strip()}: {r['ContactPhone']}", [rec('Contact', r, '')]) for r in rows('Contact') if r.get('ContactPhone') and not str(r['ContactPhone']).startswith('+')], needs=('Contact.ContactPhone',))

# ======================= CUSTOMERS
cs = []
for r in rows('Customer'):
    p = []
    t, l = r.get('CustomerChampion'), [name('Contact', x) for x in r.get('CustomerChampionName') or []]
    if t and l and norm(t) not in [norm(x) for x in l]: p.append(f'champion text "{t}" but champion link {", ".join(l)}')
    if (r.get('CustomerName') or '') != (r.get('CustomerName') or '').strip(): p.append('name has a trailing or leading space')
    if str(r.get('CustomerQuickbooksID') or '').strip() in ('0', 'n/a', 'N/A', '-'): p.append(f"placeholder QuickBooks ID {r.get('CustomerQuickbooksID')!r}")
    if r.get('CustomerActive') and not r.get('MachineID'): p.append('active with no machine')
    if not r.get('CustomerActive') and any(T['Machines']['by'].get(m, {}).get('MachineStatus') == 'Active' for m in r.get('MachineID') or []): p.append('inactive, but has Active machines')
    if p: cs.append(case(f"{(r.get('CustomerName') or '').strip()}: {'; '.join(p)}", [rec('Customer', r, cust_d(r))]))
finding('customer-fields', 'Customers', 'check', 'Customer fields that disagree', 'The champion text and the champion link should name the same person; keep one of the two fields.', cs, needs=('Customer.CustomerChampion', 'Customer.CustomerChampionName', 'Customer.CustomerActive'))

# ======================= FACILITIES
US = set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())
MISSPELL = {'acadamy': 'academy', 'cincinatti': 'cincinnati', 'angles': 'angels', 'entreprizes': 'enterprises', 'gaustello': 'guastello', 'cusotmer': 'customer'}
cs = []
for r in rows('Facility'):
    st, co, rg = r.get('FacilityState'), r.get('FacilityCountry'), r.get('FacilityRegion'); p = []
    if not r.get('CustomerName'): p.append('no customer')
    if not r.get('FacilityAddress'): p.append('no address')
    if not co: p.append('no country')
    if st in US and co and co != 'USA': p.append(f'state {st} but country {co}')
    if co and rg and rg != {'USA': 'NORAM', 'Canada': 'NORAM', 'Japan': 'ASIA', 'South Korea': 'ASIA', 'Taiwan': 'ASIA', 'Dominican Republic': 'LATAM', 'Mexico': 'LATAM'}.get(co, rg): p.append(f'country {co} but region {rg}')
    typo = [f'"{k}" (should be {v})' for k, v in MISSPELL.items() if k in (r.get('FacilityName') or '').lower()]
    if typo: p.append('spelling ' + ', '.join(typo))
    if p: cs.append(case(f"{(r.get('FacilityName') or '').strip()}: {'; '.join(p)}", [rec('Facility', r, fac_d(r) + f"; state {st or '-'}; country {co or '-'}; region {rg or '-'}")]))
finding('facility-fields', 'Facilities', 'check', 'Facilities missing an address, country or customer, or with mismatched location', 'Tech Briefs and the UPS label need the address. The time zone falls back to Eastern without a state or country.', cs, needs=('Facility.FacilityAddress', 'Facility.FacilityCountry', 'Facility.FacilityState'))

# ======================= INSTALLS
cs = []
for r in rows('Installs'):
    p = []
    if r.get('InstallPickupDate') and r.get('InstallDropoffDate') and r['InstallDropoffDate'] < r['InstallPickupDate']: p.append('drop-off before pick-up')
    if r.get('InstallEarliestAcceptDate') and r.get('InstallLatestAcceptDate') and r['InstallLatestAcceptDate'] < r['InstallEarliestAcceptDate']: p.append('latest accept date before earliest')
    if len(r.get('MachineID') or []) > 1: p.append('more than one machine')
    if p: cs.append(case(f"{name('Installs', r['_id'])}: {'; '.join(p)}", [rec('Installs', r, inst_d(r))]))
finding('install-impossible', 'Installs', 'wrong', 'Install rows with impossible dates or two machines', 'A machine cannot arrive before it leaves, and one install row moves one machine.', cs, needs=('Installs.InstallPickupDate', 'Installs.InstallDropoffDate', 'Installs.MachineID'))
cs = []
for r in rows('Installs'):
    p = []
    if not r.get('MachineID'): p.append('no machine')
    if not r.get('CustomerName'): p.append('no customer')
    if r.get('InstallType') in ('New Installation', 'Machine Reassembly', 'Reconditioned Installation') and not r.get('InstallDropoffLocation'): p.append('no drop-off location')
    if r.get('InstallType') == 'Machine Disassembly' and not r.get('InstallPickupLocation'): p.append('no pick-up location')
    if p: cs.append(case(f"{name('Installs', r['_id'])}: {'; '.join(p)}", [rec('Installs', r, inst_d(r))]))
finding('install-missing', 'Installs', 'check', 'Install rows missing a machine, customer or location', "The drop-off / pick-up automations fill the location only when the install type changes, so rows made with the type already set stay blank.", cs, needs=('Installs.InstallDropoffLocation', 'Installs.InstallPickupLocation', 'Installs.CustomerName'))

# ======================= CONTRACTS
k_d = lambda r: f"machine {names('Machines', r.get('MachineID'))}; customer {names('Customer', r.get('CustomerName'))}; start {r.get('ContractStartDate') or '-'}; expiry {r.get('ContractExpiryDate') or '-'}; return {r.get('ContractReturnDate') or '-'}"
cs = []; bym = defaultdict(list)
for r in rows('Contracts'):
    for m in r.get('MachineID') or []: bym[m].append(r)
for r in rows('Contracts'):
    p = []
    for lab, f in (('start date', 'ContractStartDate'), ('expiry date', 'ContractExpiryDate'), ('machine', 'MachineID'), ('customer', 'CustomerName')):
        if not r.get(f): p.append(f'no {lab}')
    if r.get('ContractStartDate') and r.get('ContractExpiryDate') and r['ContractExpiryDate'] < r['ContractStartDate']: p.append('expiry before start')
    if r.get('ContractStartDate') and r.get('ContractReturnDate') and r['ContractReturnDate'] < r['ContractStartDate']: p.append('return before start')
    if r.get('ContractMonthlyPaymentStart') and r.get('Contract2ndMonthlyPMTstart') and r['Contract2ndMonthlyPMTstart'] < r['ContractMonthlyPaymentStart']: p.append('2nd payment start before 1st')
    exp = r.get('ContractExpiryDate')
    if exp and exp < TODAY and not r.get('ContractReturnDate'):
        ms = [T['Machines']['by'].get(m, {}) for m in r.get('MachineID') or []]
        if any(m.get('MachineStatus') == 'Active' for m in ms) and not any(c.get('ContractExpiryDate', '') > exp for m in r.get('MachineID') or [] for c in bym[m]): p.append('expired, machine still Active, no newer contract and no return date')
    if p: cs.append(case(f"Contract {r.get('ContractID')} ({name('Contracts', r['_id'])}): {'; '.join(p)}", [rec('Contracts', r, k_d(r))]))
for m, v in bym.items():
    v = sorted([c for c in v if c.get('ContractStartDate') and c.get('ContractExpiryDate')], key=lambda c: c['ContractStartDate'])
    for a, b in zip(v, v[1:]):
        if b['ContractStartDate'] < a['ContractExpiryDate']: cs.append(case(f"{name('Machines', m)}: contracts {a.get('ContractID')} and {b.get('ContractID')} overlap", [rec('Contracts', a, k_d(a)), rec('Contracts', b, k_d(b))]))
finding('contract-fields', 'Contracts', 'check', 'Contracts with missing or impossible dates, or no machine / customer', 'Revenue math skips a contract with no dates.', cs, needs=('Contracts.ContractStartDate', 'Contracts.ContractExpiryDate', 'Contracts.MachineID'))

# ======================= INVENTORY, PARTS, LOGS, POs
cs = []
onh = [n for n in PINS['fields'].get('Inventory', {}) if re.search(r'on ?hand|staging', n, re.I)]
for r in rows('Inventory'):
    p = [f'{f} = {r[f]}' for f in onh if isinstance(r.get(f), (int, float)) and r[f] < 0]
    if p: cs.append(case(f"{r.get('InventoryPartName')}: {'; '.join(p)}", [rec('Inventory', r, inv_d(r))]))
finding('inventory-negative', 'Inventory', 'wrong', 'Negative stock on hand', 'Stock cannot go below zero. A part was logged out without a matching log in.', cs)
cs = []
for r in rows('Inventory'):
    p = []
    if r.get('InventoryCostUSD') in (None, 0): p.append('no cost (WOs using it show $0 parts)')
    if r.get('Status') == 'End of Life' and any(num(r.get(f)) > 0 for f in ('InventoryHQMin', 'InventoryAZMin', 'InventoryFLMin', 'InventoryJapanMin', 'InventoryNauticalMin')): p.append('End of Life but still has a reorder minimum')
    if p: cs.append(case(f"{r.get('InventoryPartName')}: {'; '.join(p)}", [rec('Inventory', r, inv_d(r))]))
finding('inventory-fields', 'Inventory', 'check', 'Parts with no cost, or End-of-Life parts that can still trigger a reorder', 'The low-stock alert reads the minimums.', cs, needs=('Inventory.InventoryCostUSD', 'Inventory.Status'))
finding('parts-line-incomplete', 'Parts', 'check', 'Part lines missing the part or the quantity', 'A line with no part or no quantity costs $0 on every work order that uses it.',
        [case(f"{name('Moving Parts', r['_id'])}: " + ('no part and no quantity' if not r.get('InventoryName') and not r.get('PartsQuantity') else 'no part' if not r.get('InventoryName') else 'no quantity'),
              [rec('Moving Parts', r, f"WOs {names('Work Orders', r.get('WorkOrderID'))}; made {r['_created'][:10]}")]) for r in rows('Moving Parts') if not r.get('InventoryName') or not r.get('PartsQuantity')],
        needs=('Moving Parts.InventoryName', 'Moving Parts.PartsQuantity'))
finding('parts-line-negative', 'Parts', 'wrong', 'Part lines with a quantity of 0 or less', 'A used part has a quantity of at least 1.',
        [case(name('Moving Parts', r['_id']), [rec('Moving Parts', r, '')]) for r in rows('Moving Parts') if isinstance(r.get('PartsQuantity'), (int, float)) and r['PartsQuantity'] <= 0], needs=('Moving Parts.PartsQuantity',))
ml_d = lambda r: f"type {r.get('MovementLogsType') or '-'}; date {str(r.get('MovementLogsDate') or '-')[:10]}; parts {len(r.get('MovementLogsParts') or [])}; from {names('Warehouse', r.get('WarehouseName'))}; to {names('Warehouse', r.get('WarehouseName-To'))}; made {r['_created'][:10]}"
cs = []
for r in rows('Movement Logs'):
    p = []
    if r.get('MovementLogsType') in ('Work Order', 'Work Order return') and not r.get('WorkOrderID'): p.append('work-order log with no work order')
    if r.get('MovementLogsType') == 'Purchase Order' and not r.get('PurchaseOrderID'): p.append('purchase-order log with no PO')
    if not r.get('MovementLogsParts'): p.append('no parts')
    if r.get('WarehouseName') and r.get('WarehouseName-To') and set(r['WarehouseName']) == set(r['WarehouseName-To']): p.append('from and to the same warehouse')
    if r.get('MovementLogsDate') and str(r['MovementLogsDate'])[:10] > TODAY: p.append('dated in the future')
    if p: cs.append(case(f"{name('Movement Logs', r['_id'])}: {'; '.join(p)}", [rec('Movement Logs', r, ml_d(r))]))
finding('movement-logs', 'Movement logs', 'check', 'Movement logs with no work order, no PO or no parts', 'A movement log with no parts records nothing. Many of these were made on the same few days, which points at one workflow run.', cs, needs=('Movement Logs.MovementLogsType', 'Movement Logs.WorkOrderID', 'Movement Logs.MovementLogsParts'))
cs = []
vend = defaultdict(set)
for r in rows('Purchase order history'):
    p = []
    if not r.get('Currency'): p.append('no currency')
    if r.get('Date') and r['Date'] > TODAY: p.append('dated in the future')
    if isinstance(r.get('Amount'), (int, float)) and r['Amount'] <= 0: p.append('amount 0 or less')
    if not r.get('Vendor'): p.append('no vendor')
    if r.get('Vendor'): vend[re.sub(r'and|&|[^a-z0-9]', '', r['Vendor'].lower())].add(r['Vendor'].strip())
    if p: cs.append(case(f"PO {r.get('PO Number')}: {'; '.join(p)}", [rec('Purchase order history', r, f"{r.get('Date')}; {r.get('Vendor')}; {r.get('Amount')} {r.get('Currency') or ''}")]))
for k, v in vend.items():
    if len(v) > 1:
        cs.append(case(f"Vendor spelled {len(v)} ways: {' / '.join(sorted(v))}", [rec('Purchase order history', r, f"{r.get('Vendor')}") for r in rows('Purchase order history') if (r.get('Vendor') or '').strip() in v][:12]))
finding('po-fields', 'Purchase orders', 'check', 'Purchase orders with no currency, a future date or a vendor spelled two ways', 'Totals mix CAD and USD, so a PO with no currency cannot be summed.', cs, needs=('Purchase order history.Currency', 'Purchase order history.Vendor'))

# ======================= TEST DATA
TEST = re.compile(r'^\s*(test|testing|demo|dummy|sample|fake)\b|\bdemo cus|\btesting facility\b', re.I)
finding('test-rows', 'Test data', 'wrong', 'Test or demo records in the production base', 'They show up in pickers, dashboards and counts.',
        [case(f"{tn}: {name(tn, r['_id'])}", [rec(tn, r, f"made {r['_created'][:10]}")]) for tn in T for r in T[tn]['rows'] if T[tn]['prim'] and TEST.search(str(r.get(T[tn]['prim']) or ''))])

# ---------- write
SEV_ORDER = {'wrong': 0, 'check': 1, 'tidy': 2}
FINDINGS.sort(key=lambda f: (SEV_ORDER[f['sev']], f['group']))
out = {'generated': dt.datetime.now(dt.timezone.utc).isoformat(), 'base': BASE, 'rows': sum(len(t['rows']) for t in T.values()), 'tables': len(T),
       'findings': FINDINGS, 'skipped': SKIPPED, 'missing_fields': missing_fields}
json.dump(out, open(f'{OUT}/integrity.json', 'w'), indent=1, ensure_ascii=False)
cnt = Counter(f['sev'] for f in FINDINGS)
print(f"DATA INTEGRITY  {out['tables']} tables, {out['rows']} rows: {cnt['wrong']} wrong, {cnt['check']} check, {cnt['tidy']} tidy finding types")
for f in FINDINGS: print(f"  [{f['sev']}] {f['group']}: {f['title']} ({len(f['cases'])})")
if SKIPPED: print('  skipped (field gone):', ', '.join(f"{s['title']} [{', '.join(s['missing'])}]" for s in SKIPPED))
print(f"(nothing was written to Airtable; details in {OUT}/integrity.json)")
