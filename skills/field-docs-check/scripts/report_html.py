#!/usr/bin/env python3
"""Build last_run/report.html: one readable page from the last check.py run. READ-ONLY (reads last_run/*.json, writes one file).
Inputs: report.json (documentation drift, from check.py), health.json (health.py), integrity.json (integrity.py),
schema.json and sheet_full.json (the documentation sheet, every column). Missing inputs leave their section out.
Every record in a finding gets its own "Open in Airtable" link. Publish the file with the Artifact tool."""
import json, os, re, sys, html, datetime as dt
from collections import Counter, defaultdict
from fdc_env import OUT
from health_cells import cells_from
E = html.escape
def load(n):
    p = os.path.join(OUT, n)
    return json.load(open(p)) if os.path.exists(p) else None
R = load('report.json') or {}; H = load('health.json'); I = load('integrity.json'); SCH = load('schema.json') or {'tables': []}; SF = load('sheet_full.json') or {}
BASE = (I or {}).get('base', 'appAqIfICwLXNquzF'); BASE_NAME = R.get('base_name', 'Trajekt_Prod')
TID = {t['name']: t['id'] for t in SCH['tables']}
LIVE = {t['name']: {f['id']: f for f in t['fields']} for t in SCH['tables']}
ALLNAMES = {f['name'] for t in SCH['tables'] for f in t['fields']}
link = lambda tid, rid: f"https://airtable.com/{BASE}/{tid}/{rid}"
SEV = {'wrong': ('Wrong', 'impossible or duplicate data'), 'check': ('Check', 'a person must look'), 'tidy': ('Tidy', 'low risk')}
nl = lambda s: E(s or '').replace('\n', '<br>')

# ---------------- Phase 1: integrity
def rec_html(r):
    return (f"<li class=\"rec\"><a class=\"open\" href=\"{E(link(r['tableId'], r['id']))}\" target=\"_blank\" rel=\"noopener\">Open</a>"
            f"<span class=\"rn\">{E(r['name'])}</span> <span class=\"rt\">{E(r['table'])} · {E(r['id'])}</span>"
            + (f"<div class=\"rd\">{E(r['detail'])}</div>" if r.get('detail') else '') + "</li>")
def case_html(c):
    kn = f" <span class=\"known\">{E(c['known'])}</span>" if c.get('known') else ''
    return f"<li class=\"case\"><div class=\"cl\">{E(c['label'])}{kn}</div><ul class=\"recs\">{''.join(rec_html(r) for r in c['records'])}</ul></li>"
def finding_html(f):
    n = len(f['cases']); body = ''.join(case_html(c) for c in f['cases'])
    lst = (f"<ol class=\"cases\">{body}</ol>" if n <= 12 else f"<details><summary>Show all {n} cases</summary><ol class=\"cases\">{body}</ol></details>")
    return (f"<article class=\"f {f['sev']}\" id=\"f-{E(f['id'])}\"><div class=\"fh\"><span class=\"chip {f['sev']}\">{SEV[f['sev']][0]}</span>"
            f"<h4>{E(f['title'])}</h4><span class=\"n\">{n}</span></div><p class=\"why\">{E(f['why'])}</p>{lst}</article>")
p1 = ''; toc = []; idx_wrong = ''
if I:
    groups = []
    for f in I['findings']:
        if f['group'] not in groups: groups.append(f['group'])
    order = {'wrong': 0, 'check': 1, 'tidy': 2}
    for g in sorted(groups, key=lambda g: min(order[f['sev']] for f in I['findings'] if f['group'] == g)):
        fs = sorted([f for f in I['findings'] if f['group'] == g], key=lambda f: order[f['sev']])
        gid = 'g-' + re.sub(r'[^a-z]+', '-', g.lower()).strip('-'); toc.append((gid, g))
        cnt = Counter(f['sev'] for f in fs)
        p1 += f"<section class=\"grp\" id=\"{gid}\"><h3>{E(g)} <small>{' · '.join(f'{cnt[s]} {SEV[s][0].lower()}' for s in ('wrong', 'check', 'tidy') if cnt[s])}</small></h3>{''.join(finding_html(f) for f in fs)}</section>"
    idx_wrong = ''.join(f"<li><a href=\"#f-{E(f['id'])}\">{E(f['title'])}</a> <span class=\"n\">{len(f['cases'])}</span> <span class=\"muted\">{E(f['group'])}</span></li>" for f in I['findings'] if f['sev'] == 'wrong')
    if I.get('skipped'):
        p1 += "<div class=\"box warnbox\"><b>Checks skipped because a field is gone:</b><ul class=\"plain\">" + ''.join(f"<li>{E(s['title'])}: {E(', '.join(s['missing']))}</li>" for s in I['skipped']) + "</ul><p>Re-pin the field in <code>integrity_fields.json</code> if it was deleted and re-created.</p></div>"

# ---------------- Phase 1b: field health
hsec = ''
if H:
    rows = ''.join(f"<tr><td>{E(s['table'])}</td><td class=\"num\">{s['rows']}</td><td class=\"num\">{s['fields']}</td><td class=\"num\">{s['ok']}</td><td class=\"num red\">{s['red'] or ''}</td><td class=\"num yel\">{s['yellow'] or ''}</td><td class=\"num\">{s['no_description']}</td></tr>"
                   for s in sorted(H['score'], key=lambda s: (-s['red'], -s['yellow'], s['table'])))
    by = defaultdict(list)
    for x in H['findings']:
        if x['code'] != 'no-description': by[x['table']].append(x)
    per = ''
    for tn in sorted(by, key=lambda t: (-sum(1 for x in by[t] if x['sev'] == '🔴'), t)):
        xs = sorted(by[tn], key=lambda x: x['sev'] != '🔴')
        red = [x for x in xs if x['sev'] == '🔴']; yel = [x for x in xs if x['sev'] != '🔴']
        per += (f"<div class=\"htab\"><h5>{E(tn)}</h5>" + ''.join(f"<div class=\"hl red\">🔴 <code>{E(x['field'])}</code> {E(x['msg'])}</div>" for x in red)
                + (f"<details><summary>{len(yel)} hygiene flags</summary>" + ''.join(f"<div class=\"hl\">🟡 <code>{E(x['field'])}</code> {E(x['msg'])}</div>" for x in yel) + "</details>" if yel else '') + "</div>")
    hsec = (f"<section id=\"health\"><h3>Field health, per field <small>run {E(H['generated'][:16].replace('T', ' '))} UTC · recent = last {H['days']} days</small></h3>"
            "<p>Automatic checks on each field: empty or abandoned fields, outliers, bad emails, URLs and phones, error values, junk attachments, unused options, stray spaces. These are the lines the sheet's Health column carries.</p>"
            f"<div class=\"tbl\"><table><thead><tr><th>Table</th><th>Rows</th><th>Fields</th><th>Healthy</th><th>🔴</th><th>🟡</th><th>No description</th></tr></thead><tbody>{rows}</tbody></table></div>{per}</section>")

# ---------------- Phase 2: documentation drift
doc = ''; nchanges = len(R.get('changes', []))
if R:
    parts = []
    for tn, x in sorted(R.get('tables', {}).items()):
        items = []
        items += [f"<li><span class=\"tag new\">New field</span> <code>{E(n)}</code></li>" for n in x.get('new', [])]
        items += [f"<li><span class=\"tag gone\">Removed</span> <code>{E(n)}</code></li>" for n in x.get('removed', [])]
        items += [f"<li><span class=\"tag\">Renamed</span> <code>{E(a)}</code> → <code>{E(b)}</code> ({'exact, by field id' if how == 'exact' else 'guess'})</li>" for a, b, how in x.get('renamed', [])]
        items += [f"<li><span class=\"tag gone\">Re-created</span> <code>{E(n)}</code> field id {E(a)} → {E(b)}</li>" for n, a, b in x.get('recreated', [])]
        items += [f"<li><span class=\"tag\">Type</span> <code>{E(n)}</code> {E(a)} → {E(b)}</li>" for n, a, b in x.get('type_changed', [])]
        items += [f"<li><span class=\"tag\">Changed</span> <code>{E(n)}</code><div class=\"diff\"><div><b>Sheet</b> {E(a)}</div><div><b>Live</b> {E(b)}</div></div></li>" for n, a, b in x.get('related_drift', [])]
        if x.get('order_changed'): items.append("<li><span class=\"tag\">Order</span> field order differs from Airtable</li>")
        for d in x.get('usage_diff', []):
            add = ''.join(f"<div class=\"add\">+ {E(a['text'])} <span class=\"src {'weak' if 'unproven' in a['source'] else ''}\">{E(a['source'])}</span></div>" for a in d['added'])
            rem = ''.join(f"<div class=\"rem\">− {E(r)}</div>" for r in d['removed'])
            items.append(f"<li><span class=\"tag\">{E(d['column'])}</span> <code>{E(d['field'])}</code><div class=\"diff\">{add}{rem}</div></li>")
        if items: parts.append(f"<div class=\"dtab\"><h5>{E(tn)} <small>{x.get('sheet_count')} on sheet · {x.get('field_count')} live</small></h5><ul class=\"plain\">{''.join(items)}</ul></div>")
    erp = [(tn, a, b) for tn, a, b, d in R.get('erp_index', []) if a != b]
    doc = (f"<p class=\"verdict-line\">{'Documentation needs updating: ' + str(nchanges) + ' change(s).' if nchanges else 'Documentation is up to date.'}</p>"
           "<p class=\"muted\">Forms lines tagged <span class=\"src weak\">name match only (unproven)</span> come from matching a question name to a field name, not from real submissions. Check them before trusting them.</p>"
           + ''.join(parts)
           + (("<div class=\"dtab\"><h5>ERP Documentation Index</h5><ul class=\"plain\">" + ''.join(f"<li><code>{E(tn)}</code> says {a} fields, live has {b}</li>" for tn, a, b in erp) + "</ul></div>") if erp else ''))

# ---------------- Phase 2: Health column audit
hcol = ''; nstale = nmiss = nmis = 0
if SF and H:
    new = cells_from(H); stale = []; missing = []; misal = []; nohdr = []
    CHK = {'attachments are HTML': ('multipleAttachments',), 'options never used': ('singleSelect', 'multipleSelects'), 'differ only by case': ('singleSelect', 'multipleSelects'),
           'options with stray': ('singleSelect', 'multipleSelects'), '× the median': ('number', 'currency', 'percent', 'duration'), 'not valid email': ('email',), 'not http(s) URLs': ('url',),
           'do not look like phone': ('phoneNumber',), 'dates more than': ('date', 'dateTime'), 'dates before 2015': ('date', 'dateTime'), 'stored as text': ('singleLineText', 'multilineText', 'richText'),
           'whitespace': ('singleLineText', 'multilineText', 'richText'), 'placeholder values': ('singleLineText', 'multilineText', 'richText')}
    for tn, rows in SF.items():
        hi = next((i for i, r in enumerate(rows) if r and r[0] == 'Field name'), None)
        if hi is None or tn not in LIVE: continue
        hdr = rows[hi]; hc = next((i for i, h in enumerate(hdr) if str(h).startswith('Health')), None)
        if hc is None: nohdr.append(tn); continue
        fc = hdr.index('Field ID') if 'Field ID' in hdr else None
        body = [(r + [''] * 16) for r in rows[hi + 1:] if r and r[0]]
        for i, r in enumerate(body):
            rowno = hi + 2 + i; cell = (r[hc] or '').strip(); fname = r[0]; fid = r[fc] if fc is not None else ''
            f = LIVE[tn].get(fid) or next((v for v in LIVE[tn].values() if v['name'] == fname), None)
            if fid and fid in LIVE[tn] and LIVE[tn][fid]['name'] != fname: misal.append((tn, rowno, fname, f"Field ID {fid} is the live field {LIVE[tn][fid]['name']}"))
            if f:
                for k, types in CHK.items():
                    if k in cell and f['type'] not in types: misal.append((tn, rowno, fname, f"cell says \"{k}\", which cannot apply to a {f['type']} field"))
                for a, b in re.findall(r'rows where (\S+) is before (\S+)', cell):
                    if fname not in (a, b): misal.append((tn, rowno, fname, f"cell talks about {a} / {b}"))
            n = new.get(tn, {}).get(fname)
            if n is None or cell == n: continue
            sf = {x for x in cell.split('\n') if x and x != '✅'}; nf = {x for x in n.split('\n') if x and x != '✅'}
            code = lambda s: re.sub(r'\d[\d,.]*', 'N', s); sc = {code(x) for x in sf}; nc = {code(x) for x in nf}
            if nf and not sf: k = 'New flag (sheet still shows ✅)'
            elif sf and not nf: k = 'Fixed (sheet still shows the old flag)'
            elif sc == nc: k = 'Same flag, numbers changed'
            elif nc < sc: k = 'Partly fixed'
            elif nc > sc: k = 'New flag added'
            else: k = 'Wording changed' if all('leading/trailing' in x for x in sf ^ nf) else 'Flag changed'
            stale.append((k, tn, rowno, fname, cell, n))
        on = {r[fc] for r in body} if fc is not None else set()
        for fid, f in LIVE[tn].items():
            if fid not in on and f['name'] not in {r[0] for r in body}: missing.append((tn, f['name'], new.get(tn, {}).get(f['name'], '')))
    nstale, nmiss, nmis = len(stale), len(missing), len(misal)
    KORD = ['New flag (sheet still shows ✅)', 'New flag added', 'Flag changed', 'Fixed (sheet still shows the old flag)', 'Partly fixed', 'Same flag, numbers changed', 'Wording changed']
    kinds = Counter(s[0] for s in stale)
    hdates = sorted({h for h in (R.get('health_column') or {}).values()})
    hcol = (f"<div class=\"box {'verdict' if not misal and not nohdr else 'warnbox'}\"><p><b>{'No Health cell is on the wrong row.' if not misal else str(len(misal)) + ' Health cell(s) look misplaced.'}</b> "
            f"Checked on every tab: the Health column is present ({', '.join(E(h) for h in hdates) or 'none'}), each row's Field ID is the live field of that name, each flag fits its field's type, and each cell that names a field sits on that field.</p>"
            + (''.join(f"<div class=\"hl red\">{E(t)} row {r} <code>{E(fn)}</code>: {E(why)}</div>" for t, r, fn, why in misal)) + (f"<p>No Health column on: {E(', '.join(nohdr))}</p>" if nohdr else '') + "</div>")
    if missing:
        hcol += ("<div class=\"box warnbox\"><p><b>Next documentation update:</b> <code>build_all_tabs.py --apply --keep-health</code> keeps every Health cell with its field (by field id), so new rows cannot shift it. "
                 f"But it gives the {len(missing)} new rows below a <b>blank</b> Health cell. Without <code>--keep-health</code> the whole column is rewritten from today's run.</p></div>")
    hcol += (f"<h4 class=\"sub\">Health cells out of date ({len(stale)})</h4><ul class=\"plain\">" + ''.join(f"<li><b>{kinds[k]}</b> {E(k)}</li>" for k in KORD if kinds[k]) + "</ul>"
             + (f"<div class=\"tbl scroll\"><table><thead><tr><th>Change</th><th>Tab</th><th>Row</th><th>Field</th><th>Sheet says</th><th>Today</th></tr></thead><tbody>"
                + ''.join(f"<tr><td>{E(k)}</td><td>{E(t)}</td><td class=\"num\">{r}</td><td><code>{E(fn)}</code></td><td>{nl(c)}</td><td>{nl(n)}</td></tr>" for k, t, r, fn, c, n in sorted(stale, key=lambda z: (KORD.index(z[0]), z[1], z[2])))
                + "</tbody></table></div>" if stale else '')
             + (f"<h4 class=\"sub\">Live fields with no row on their tab, so no Health cell ({len(missing)})</h4><div class=\"tbl\"><table><thead><tr><th>Tab</th><th>Field</th><th>Health today</th></tr></thead><tbody>"
                + ''.join(f"<tr><td>{E(t)}</td><td><code>{E(fn)}</code></td><td>{nl(c)}</td></tr>" for t, fn, c in missing) + "</tbody></table></div>" if missing else ''))

# ---------------- Phase 2: other documentation issues
other = []
if R.get('wip_active'):
    other.append("<li><b>Active workflows the docs leave out.</b> The Automations column skips workflows with [WIP] in the name, but these are active and touch this base: "
                 + '; '.join(f"<code>{E(w['name'])}</code> ({E(', '.join(w['tables']) or 'base')})" for w in R['wip_active']) + '.</li>')
if R.get('n8n_dead_columns'):
    other.append("<li><b>Active workflows that map columns that no longer exist:</b> " + '; '.join(f"<code>{E(w)}</code> → {E(nd)} → <code>{E(col)}</code>" for w, nd, col, tb in R['n8n_dead_columns']) + '.</li>')
readme = SF.get('README', [])
if BASE_NAME != 'Trajekt_Dev' and 'Trajekt_Dev' in json.dumps([readme, R.get('erp_rows', [])]):
    other.append(f"<li><b>The base is now called {E(BASE_NAME)}</b>, but the documentation still calls it Trajekt_Dev.</li>")
own = {}; hi = next((i for i, r in enumerate(readme) if r and r[0] == 'Table Name'), None)
if hi is not None:
    h = readme[hi]; si = h.index('Status') if 'Status' in h else None
    for r in readme[hi + 1:]:
        if not r or not r[0]: break
        if si is not None and len(r) > si: own[r[0]] = r[si]
erpst = {r[0]: r[2] for r in R.get('erp_rows', []) if r and r[0]}
mism = [(t, own[t], erpst[t]) for t in own if t in erpst and own[t] and erpst[t] and own[t] != erpst[t]]
if mism:
    other.append("<li><b>README Status and ERP index Status disagree</b> (both columns are yours):<div class=\"tbl\"><table><thead><tr><th>Table</th><th>README</th><th>ERP index</th></tr></thead><tbody>"
                 + ''.join(f"<tr><td>{E(t)}</td><td>{E(a)}</td><td>{E(b)}</td></tr>" for t, a, b in mism) + "</tbody></table></div></li>")
pref = re.compile(r'\b((?:WorkOrder|WOCost|WoCost|Machine|Contact|Customer|Facility|Location|Warehouse|Contract|Install|Inventory|Scope|MovementLogs|Parts|OOBF|Invoice)[A-Za-z0-9()?&-]{3,})')
dead = []
for t in SCH['tables']:
    for f in t['fields']:
        for m in sorted(set(pref.findall(f.get('description') or ''))):
            m2 = m.rstrip('.,)?')
            if m2 not in ALLNAMES and not any(n.startswith(m2) for n in ALLNAMES) and m2 not in TID: dead.append((t['name'], f['name'], m2))
if dead:
    other.append("<li><b>Airtable field descriptions that name fields that no longer exist:</b><ul class=\"plain\">" + ''.join(f"<li><code>{E(t)}.{E(f)}</code> mentions <code>{E(m)}</code></li>" for t, f, m in dead) + "</ul></li>")
if H:
    nd = Counter(x['table'] for x in H['findings'] if x['code'] == 'no-description')
    if nd: other.append(f"<li><b>{sum(nd.values())} fields have no Airtable description:</b> " + ', '.join(f"{E(t)} {n}" for t, n in nd.most_common()) + '.</li>')
    names_ = [x for x in H['findings'] if x['code'] in ('name-typo', 'name-leftover', 'name-whitespace')]
    if names_: other.append("<li><b>Field names that look misspelled or left over:</b> " + ', '.join(f"<code>{E(x['table'])}.{E(x['field'])}</code>" for x in names_) + '.</li>')
opt = []
for t in SCH['tables']:
    for f in t['fields']:
        for c in (f.get('options') or {}).get('choices', []) or []:
            if c['name'] == '': opt.append(f"{t['name']}.{f['name']}: a blank option")
            elif c['name'] != c['name'].strip(): opt.append(f"{t['name']}.{f['name']}: option {c['name']!r} has a stray space")
if opt: other.append("<li><b>Select options to tidy:</b> " + '; '.join(E(o) for o in opt) + '.</li>')
othersec = f"<div class=\"box\"><ul class=\"plain\">{''.join(other)}</ul></div>" if other else "<p>Nothing else found.</p>"

# ---------------- page
cnt = Counter(f['sev'] for f in (I or {}).get('findings', []))
gen = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
CSS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report.css')).read()
page = f"""<title>{E(BASE_NAME)} Data Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
 <div class="eyebrow">Airtable {E(BASE_NAME)} · {E(BASE)} · built {E(gen)}</div>
 <h1>{E(BASE_NAME)} Data Review</h1>
 <p class="lede">Phase 1 checks that the data is correct and possible{f" ({(I or {}).get('tables')} tables, {(I or {}).get('rows'):,} rows read)" if I else ''}. Phase 2 checks that the field documentation sheet and its Health column match the base. Each record has its own link to Airtable.</p>
 <div class="safe">Read only. This run changed nothing in Airtable, the documentation sheet or the ERP index.</div>
 <div class="phase">Phase 1 · data</div>
 <div class="tiles"><a class="tile wrong" href="#p1"><b>{cnt['wrong']}</b><span>Wrong: impossible or duplicate data</span></a><a class="tile check" href="#p1"><b>{cnt['check']}</b><span>Check: a person must look</span></a><a class="tile tidy" href="#p1"><b>{cnt['tidy']}</b><span>Tidy</span></a><a class="tile" href="#health"><b>{sum(s['red'] for s in H['score']) if H else '-'}</b><span>fields with a 🔴 health flag</span></a></div>
 <div class="phase">Phase 2 · documentation</div>
 <div class="tiles"><a class="tile check" href="#doc"><b>{nchanges}</b><span>documentation changes</span></a><a class="tile check" href="#hcol"><b>{nstale}</b><span>Health cells out of date</span></a><a class="tile check" href="#hcol"><b>{nmiss}</b><span>fields with no Health cell</span></a><a class="tile {'ok' if not nmis else 'wrong'}" href="#hcol"><b>{nmis}</b><span>Health cells on the wrong row</span></a></div>
 <nav class="toc" aria-label="Sections"><a href="#first">Wrong data</a><a href="#p1">Phase 1</a>{''.join(f'<a href="#{g}">{E(n)}</a>' for g, n in toc)}<a href="#health">Field health</a><a href="#p2">Phase 2</a><a href="#doc">Doc changes</a><a href="#hcol">Health column</a><a href="#other">Other</a></nav>
</header>
<section id="first" class="first"><h3>Wrong data, by type</h3><ol>{idx_wrong or '<li>None found.</li>'}</ol></section>
<h2 id="p1">Phase 1 · Data integrity</h2>
<p class="lede">One card per kind of problem. The number is how many cases. Each case lists every record involved, with its own <b>Open</b> link to Airtable. A grey tag means Elliot already reviewed that case.</p>
<div class="legend"><span><span class="chip wrong">Wrong</span> impossible or duplicate data</span><span><span class="chip check">Check</span> a person must decide</span><span><span class="chip tidy">Tidy</span> low risk</span></div>
{p1 or '<p>integrity.json not found: run integrity.py.</p>'}
{hsec}
<h2 id="p2">Phase 2 · Documentation</h2>
<section id="doc"><h3>Documentation changes</h3>{doc or '<p>report.json not found: run check.py.</p>'}</section>
<section id="hcol"><h3>Health column</h3>{hcol or '<p>Needs sheet_full.json and health.json: run check.py --health.</p>'}</section>
<section id="other"><h3>Other documentation issues</h3>{othersec}</section>
<footer>
 <p><b>Rules this report follows.</b> Moving Parts lines are reusable "part x quantity" lines: many work orders share one line when each used that part, and each WO's parts cost is correct. Shared lines are never flagged. Dual-role people (tech and staff) are not flagged for a visit Type that differs from their role. Cases in <code>known.json</code> keep their review note.</p>
 <p>Built by field-docs-check (check.py → integrity.py → report_html.py) from last_run/*.json. Nothing here was written to Airtable or the sheets; each fix is an Airtable write that needs a yes.</p>
</footer>
</div>"""
open(os.path.join(OUT, 'report.html'), 'w').write(page.replace(' — ', ' - ').replace('—', '-'))
print(f"HTML page: {os.path.join(OUT, 'report.html')}  ({cnt['wrong']} wrong / {cnt['check']} check / {cnt['tidy']} tidy; {nchanges} doc changes; {nstale} stale Health cells; {nmiss} fields without a Health cell; {nmis} misplaced)")
