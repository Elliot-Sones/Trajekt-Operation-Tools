#!/usr/bin/env python3
"""Print a Google Sheets/Drive access token for the sheets-editor service account.

Usage:  python3 sheets_token.py [scope ...]
Default scope: spreadsheets + drive. Token lives ~1h.
Key: google-sheets-sa.json (same directory) = sheets-editor@trajekt-sheets-1148.
Share any new spreadsheet with that address (writer) before editing it.
"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_DASH = os.environ.get('FDC_DASH_DIR', '/Users/elliot18/Projects/trajekt/trajekt/trajekt-revenue-dashboard')
SA = json.load(open(os.environ.get('GOOGLE_SHEETS_SA_JSON', os.path.join(_DASH, 'google-sheets-sa.json'))))
scopes = sys.argv[1:] or ['https://www.googleapis.com/auth/spreadsheets',
                          'https://www.googleapis.com/auth/drive']

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=')

now = int(time.time())
header = b64u(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
claims = b64u(json.dumps({'iss': SA['client_email'], 'scope': ' '.join(scopes),
                          'aud': 'https://oauth2.googleapis.com/token',
                          'iat': now, 'exp': now + 3600}).encode())
signing_input = header + b'.' + claims
with tempfile.NamedTemporaryFile('w', suffix='.pem', delete=False) as f:
    f.write(SA['private_key']); pem = f.name
try:
    sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', pem],
                         input=signing_input, capture_output=True, check=True).stdout
finally:
    os.remove(pem)
jwt = (signing_input + b'.' + b64u(sig)).decode()
body = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                               'assertion': jwt}).encode()
tok = json.load(urllib.request.urlopen(
    urllib.request.Request('https://oauth2.googleapis.com/token', data=body)))
print(tok['access_token'])
