# trajekt-stack (private)

Per-context bundle for **Trajekt** work: skills + MCP servers, installed into the
Trajekt project only so nothing loads in unrelated sessions.

## Install
```bash
./install.sh /path/to/your/trajekt/project     # or run from inside that project
cp .env.example /path/to/project/.env          # then fill in real values (gitignored)
```
Restart Claude Code in that project and approve the project MCP servers when prompted.

## Skills
| Skill | What it does |
|---|---|
| `field-docs-check` | Reports whether the **Trajekt_Dev Field Documentation** sheet and the **ERP Documentation Index** still match the live Airtable base (new / removed / renamed fields, type and option drift, Automations recomputed from the active n8n workflows, Forms proven from real Fillout submissions) and runs a **field-health** pass (empty / sparse / abandoned fields, wrong-looking values, duplicates, bad attachments, hygiene). Report first; the sheet refresh is a separate step that needs an explicit yes. Needs `FDC_DASH_DIR` (or the token env vars) — see `.env.example`. |

## MCP servers
| Server | Type | Notes |
|---|---|---|
| retool | http | trajektsports.retool.com/mcp |
| notion-trajekt | http | mcp.notion.com/mcp |
| airtable | http | mcp.airtable.com/mcp |
| n8n | http | trajektsports.app.n8n.cloud (production instance) |
| figma | http | mcp.figma.com/mcp |
| notion | stdio | needs `NOTION_TOKEN` |
| trajekt-db | stdio | local read-only Mongo bridge; needs `BASTION_KEY_PATH` (`~/.ssh/bastion.pem`) |
| google-workspace | stdio | **replaces the claude.ai Google connectors** (Gmail/Calendar/Drive). Needs a Google Cloud OAuth client. Package `workspace-mcp` verified on PyPI (v1.25.0, 2026-08). |

## Replacing the Google connectors (one-time)
1. Google Cloud Console → new project → enable Gmail, Calendar, Drive APIs.
2. Create OAuth 2.0 Client (Desktop). Put the client id/secret in `.env`.
3. First run opens a browser consent; token caches locally.
4. At claude.ai → Settings → Connectors, turn OFF the Google connectors so they stop loading globally.
