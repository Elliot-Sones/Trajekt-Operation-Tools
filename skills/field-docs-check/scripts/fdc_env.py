"""Shared config for the field-docs-check scripts. Override with env vars; defaults match Elliot's machine.
FDC_DASH_DIR  folder holding .env.local (AIRTABLE_WRITE_TOKEN, N8N_API_KEY, FILLOUT_API_KEY) and google-sheets-sa.json
FDC_OUT       scratch folder for fetched data + reports (default: <skill>/last_run, gitignored)
Tokens can also be given directly as env vars: AIRTABLE_WRITE_TOKEN, N8N_API_KEY, FILLOUT_API_KEY, GOOGLE_SHEETS_SA_JSON."""
import os, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__))
DASH=os.environ.get('FDC_DASH_DIR','/Users/elliot18/Projects/trajekt/trajekt/trajekt-revenue-dashboard')
OUT=os.environ.get('FDC_OUT', os.path.normpath(os.path.join(HERE,'..','last_run')))
os.makedirs(OUT, exist_ok=True)
def load_env():
    env={}
    p=os.path.join(DASH,'.env.local')
    if os.path.exists(p):
        for l in open(p):
            if '=' in l and not l.startswith('#'):
                k,v=l.split('=',1); env[k.strip()]=v.strip().strip('"')
    for k in ('AIRTABLE_WRITE_TOKEN','N8N_API_KEY','FILLOUT_API_KEY'):
        if os.environ.get(k): env[k]=os.environ[k]
    missing=[k for k in ('AIRTABLE_WRITE_TOKEN',) if not env.get(k)]
    if missing: sys.exit(f"missing {missing}: set FDC_DASH_DIR to the folder with .env.local, or export the variables")
    return env
def sheets_token():
    return subprocess.check_output([sys.executable, os.path.join(HERE,'sheets_token.py')]).decode().strip()
