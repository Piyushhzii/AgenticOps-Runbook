# Agentic Operations Runbook Copilot

A human-in-the-loop operations copilot built with FastAPI, LangGraph, Groq, and SQLite.
It selects a runbook, gathers evidence, chooses an approved forward route, and pauses
for an operator before continuing. It does **not** execute shell commands, unlock
accounts, change payments, restart services, or create external tickets.

## What changed

- **Real LangGraph orchestration:** typed state and explicit selection, inspection,
  evidence collection, routing, and response nodes.
- **Evidence rather than simulation:** no hard-coded account/payment status. Context
  stores operator-reported observations, not independently verified system facts.
- **Human control:** both information requests and manual actions pause the workflow.
  An operator reports the actual outcome or enters `/escalate`.
  Manual `message` checkpoints use application-controlled wording and the reviewed
  runbook instruction, not LLM-generated text. They explicitly state that the
  copilot cannot access external systems or contact a team. Previously saved
  messages are retained unchanged; this applies to newly generated checkpoints.
- **Constrained decisions:** the LLM can only choose configured forward destinations;
  invalid answers fail explicitly instead of silently choosing a fallback.
- **Durable turns:** session state, runbook snapshot, and conversation messages commit
  together. Provider failures save no partial turn. Version checks prevent concurrent
  requests from advancing the same session twice.
- **Operational safeguards:** request size limits, a 48,000-character prompt budget,
  30-second provider request timeout, two provider retries, 4,096 output-token limit, API key protection,
  liveness/readiness endpoints, and node-level logs without issue/evidence text.
- **Validated ingestion:** reviewed JSON works without LLM extraction. Re-ingestion
  replaces steps atomically rather than duplicating them.

This is a hardened **single-operator/internal-service foundation**, not a certified
multi-tenant production system. See the deployment checklist below.

## Architecture

```text
New issue --> select_runbook --+
                              v
Existing session ------> inspect_step
                              |
              +---------------+----------------+
              | no new evidence                | new operator response
              v                                v
           respond                       collect_evidence
              |                                |
              |                            route_step
              |                                |
              |                         inspect_step --> respond
              v
        atomically save turn --> return next question / manual step / final status
```

The graph is compiled once per service instance. Each API request executes one
bounded graph turn (`recursion_limit=16`), then saves a durable checkpoint in the
application's session tables. A new process reloads that state for the next turn.
This intentionally uses **turn-boundary persistence**, not LangGraph's native
checkpointer or `interrupt()` API. A crash mid-turn requires retrying that turn;
it cannot repeat a real system side effect because no such tools are wired.

LLMs handle runbook selection, choosing between explicit routes, and support wording.
Code owns route validation, persistence, statuses, and all execution boundaries.
Node names in `trace` describe execution flow, not hidden model reasoning.

## Install and run on Windows

Python 3.11+ is required. From the repository directory:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -e ".[test]"
```

Configure `GROQ_API_KEY` through the process environment or a local, untracked `.env`.
Use an approved Groq model in [configs/llm_config.yaml](configs/llm_config.yaml).
Do not put real keys in source code or commit them.

### Ingest the reviewed example (no provider call)

```powershell
.\venv\Scripts\python.exe -m scripts.ingest_runbooks --file .\data\service_degradation.json
```

### Start the API

```powershell
.\venv\Scripts\python.exe -m scripts.run_api
```

The runner binds to `127.0.0.1:8000`, without auto-reload. OpenAPI is available at
`http://127.0.0.1:8000/docs`. For development with reload:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1
```

Alternatively, after installation use `support-agent-api` or `support-agent-cli`
from the activated virtual environment.

## React operations console

The separate [frontend/](frontend/) application uses React 19, TypeScript, Vite,
Lucide icons, and locally bundled fonts. It includes a responsive operations
dashboard, searchable live runbook library, and conversational agent workspace
with collected evidence, operator checkpoints, execution traces, escalation
confirmation, and session recovery by ID. There are no fabricated metrics:
session counts reflect only the current browser workspace.

### Start locally

Keep the Python API running on `127.0.0.1:8000`. Open a **second** PowerShell
terminal from the repository root:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Node.js 22.12+ is required. Open `http://127.0.0.1:5173`, select **Connect API**,
and paste the application's `OPS_API_KEY` from the backend's local `.env`.
Do not use the Groq key. Leave the field empty only if the backend intentionally
allows unauthenticated local development.

The browser sends requests to `/api`; Vite proxies them to the Python backend,
stripping that prefix. No wildcard CORS setting is necessary. For a different
local backend address, set `$env:OPS_API_TARGET` before `npm run dev`. This is a
server-side proxy setting, not a credential.

To try the console:

1. Connect and open **Runbook library** to inspect actual ingested workflows.
2. Select **New session** and describe an incident in natural language.
3. Answer the copilot's question, then report actual evidence for manual steps.
4. Inspect the saved evidence, current checkpoint, and execution trace.
5. Escalate explicitly when needed; this does not create an external ticket.
6. To resume the earlier Swagger investigation, choose **Resume by ID** and paste
   the session ID returned by that API. The console loads its latest version.

Keys and conversation data are held only in React memory, not localStorage,
sessionStorage, cookies, URLs, or frontend environment files. Refresh/disconnect
clears the browser workspace; saved backend sessions can be restored by ID.
Changing keys clears the previous session workspace. Save the session ID before
refreshing. Provider-bound session requests can take time; the UI preserves
failed response drafts and requires a reload before retrying an uncertain or
conflicted turn. Initial session creation is not idempotent: a timed-out create
may leave a saved session, so avoid blindly retrying.

### Build, test, and deploy

```powershell
Set-Location frontend
npm run build
npm test
npm run format:check
npm audit
```

Deploy the generated `frontend/dist` static files behind your trusted HTTPS
gateway. Configure that gateway to forward `/api/*` to the backend with the
`/api` prefix removed, preserving `X-API-Key`, request bodies, methods, and
response status codes. Serve the SPA for other application paths, **not** API
errors. Vite's development proxy is not included in the static build;
`npm run preview` is a static preview, not a production/API server.

Use gateway timeouts compatible with bounded provider retries, disable caching
for API responses, apply request-body limits/rate limits, and serve static assets
with appropriate cache policies. Bundle assets and fonts are self-hosted.
Configure CSP/security headers at the gateway (the app does not need third-party
scripts, fonts, or unsafe HTML rendering).

The console currently uses the backend's shared application key. This is an
internal operator interface, not a multi-tenant identity system. Before broad
production access, replace shared-key entry with an authenticated BFF/OIDC
session, enforce server-side ownership/RBAC, and move shared secrets out of the
browser entirely. A password field and in-memory storage do not protect a key
against malicious browser extensions or compromised JavaScript.

Backend-wide session discovery, automatic execution, live monitoring metrics,
and external ticket integrations are intentionally not invented in the UI;
the existing API does not expose them.

### CLI

```powershell
.\venv\Scripts\python.exe -m scripts.run_cli
```

Enter `exit` to leave the CLI without completing the session. Enter `/escalate`
when responding to any step to close it as requiring operator handoff.
There is no automatic external ticket dispatch.

## API usage

| Endpoint | Purpose |
|---|---|
| `GET /health` | Public liveness; does not call the database or provider |
| `GET /ready` | Database/schema, non-empty runbook catalog, and provider-key configuration |
| `GET /runbooks` | Available runbook IDs and descriptions |
| `POST /sessions` | Select a runbook and return the first pending step |
| `GET /sessions/{session_id}` | Retrieve a durable session and conversation |
| `POST /sessions/{session_id}/responses` | Report evidence and advance one step |

Readiness does not contact Groq or validate the key's validity/provider availability.
All endpoints except liveness require `X-API-Key` when `OPS_API_KEY` is configured.

Start:

```json
{"issue": "Checkout latency increased in production"}
```

Respond using the **latest returned version**:

```json
{"message": "Checkout production, started at 10:00, elevated p95 latency", "expected_version": 1}
```

Example PowerShell client, assuming `OPS_API_KEY` is configured:

```powershell
$headers = @{"X-API-Key" = $env:OPS_API_KEY}
$body = @{issue = "Checkout latency increased in production"} | ConvertTo-Json
$state = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/sessions" `
    -Headers $headers -ContentType "application/json" -Body $body
$reply = @{message = "Checkout production, incident began at 10:00"; expected_version = $state.version} | ConvertTo-Json
$state = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/sessions/$($state.session_id)/responses" `
    -Headers $headers -ContentType "application/json" -Body $reply
```

Response fields include `status`, `version`, `current_step`, `awaiting_user_input`,
`awaiting_confirmation`, `executed_steps`, `context`, `messages`, and `trace`.
`awaiting_confirmation` is true for manual `message` steps; the response must report
the authorized operator's actual result. `executed_steps` means acknowledged
runbook steps, **not automatically executed external actions**.

Statuses:

- `active`: waiting for input or operator-reported confirmation.
- `completed`: the runbook ended; this does not independently prove incident resolution.
- `escalated`: handoff is needed; evidence is saved but no ticket has been created.

Errors: `401` invalid/missing API key, `404` missing session or matching runbook,
`409` stale/concurrent version or closed session, `422` invalid request, `502`
provider/decision failure, `503` database/configuration/readiness failure. On a
failed turn, reload before retrying. Do not retry `409` blindly.

**Compatibility changes:** response requests now require `expected_version`;
manual steps no longer auto-advance; closed sessions reject further responses;
completion no longer claims resolution. Existing SQLite databases receive additive
migrations on startup. New sessions begin at version 1; migrated sessions can
start at version 0. Existing sessions acquire a runbook snapshot on their first
successful resumed turn; new sessions are pinned from creation.

## Add another use case

No Python changes are needed for a new **manual/evidence-driven** workflow:

1. Copy [data/service_degradation.json](data/service_degradation.json).
2. Set a unique `runbook_name`, category, and precise description for selection.
3. Give each step a unique `step_id` and positive, unique `step_order`.
4. Use `input` for questions and `message` for authorized manual checks/actions.
5. Set `next_steps` to approved forward step IDs, `END`, or `ESCALATE`.
   Omit it or use `null` for ordinary sequential progression. Include `ESCALATE`
   where evidence can be missing or ambiguous.
6. Review the instructions and routes, ingest the JSON, and test each branch with
   injected deterministic dependencies before relying on LLM routing.

The JSON validator rejects empty runbooks, unknown step types, duplicate IDs/orders,
unknown destinations, backward edges, and reserved step IDs. Routes refer to local
IDs in JSON; ingestion maps them to stored IDs such as `SERVICE_DEGRADATION_TRIAGE_2`.
Multiple destinations invoke the reasoner; a single destination is deterministic.
The model's choice is constrained, but its interpretation of evidence is not a
guarantee of operational correctness.

Example use cases:

| Use case | Collect evidence | Decide / hand off |
|---|---|---|
| Service degradation (included) | Service scope, error rate, p95 latency, alert state | Observe recovery or escalate |
| Kubernetes pod failures | Namespace, pod events, restart counts, recent changes | Authorized operator inspection or platform handoff |
| Disk capacity | Filesystem, utilization, growth rate, approved cleanup candidates | Approved manual cleanup or storage handoff |
| Certificate expiry | Hostname, expiry time, renewal-job result | Approved manual renewal or PKI handoff |
| Failed deployment | Release ID, health checks, rollout status | Approved operator rollback procedure or escalation |
| Payment reconciliation | Redacted reference and operator-observed gateway/order status | Reconciliation handoff, never automatic charging/refunds |

Document ingestion (TXT, MD, PDF, DOCX, XLSX, PPTX, HTML, CSV, LOG, or an http(s) URL)
parses the source to text and has the LLM derive the steps and branches:

```powershell
.\venv\Scripts\python.exe -m scripts.ingest_runbooks --file .\data\login_issue.txt
.\venv\Scripts\python.exe -m scripts.ingest_runbooks --file .\data\kb_article.pdf --dry-run
.\venv\Scripts\python.exe -m scripts.ingest_runbooks --url https://wiki.example.com/runbooks/vpn
```

`--dry-run` prints the extracted JSON for review without saving it. Scanned PDFs
need OCR first. Without `--file`/`--url`, ingestion processes the configured formats in
[configs/runbook_config.yaml](configs/runbook_config.yaml). Text extraction sends
the source to Groq and publishes structurally validated output; it is **not**
a semantic review. Prefer reviewed JSON in production. Existing text-derived
runbooks were flattened by the old extractor: re-author/re-ingest their branches
before depending on conditional behavior. Structural migrations cannot restore lost intent.

### Adding real tools later

Real integrations require Python changes, not just another runbook. Add a typed,
allowlisted adapter and separate graph nodes for **observe -> propose -> approve ->
execute -> verify**. Start with read-only monitoring/ticket queries. Before enabling
writes, require authenticated operator identity/RBAC, approval bound to the exact
action and session version, idempotency keys, a durable action ledger, timeouts,
redaction, and verification of the resulting system state. Never execute arbitrary
model-generated shell commands or retry non-idempotent operations blindly.

For long-running tools, adopt a production LangGraph checkpointer and native
interrupt/resume with an action ledger; the current turn-boundary persistence alone
is not sufficient for crash-safe external side effects.

## Deployment checklist and current limits

- Set `OPS_ENV=production` and a strong secret `OPS_API_KEY`. Startup fails without
  the key outside development. Development without a key is local-only.
- Place TLS, per-client rate limits, request-body limits, and upstream request
  timeouts at a trusted gateway. A provider call can take multiple 30-second
  attempts with backoff; a turn can make more than one call.
- Use a **local persistent volume**, not a OneDrive/network-synchronized SQLite
  file. Set `RUNBOOK_DB_PATH` to an absolute path, e.g.
  `C:\AgenticOpsData\runbook.db`; create its parent directory first.
  Start with one service instance; SQLite has bounded lock waits, not
  distributed scalability. Migrate to PostgreSQL for multi-instance deployment.
- Back up the database before upgrading. Run schema initialization as a controlled
  deployment step before starting concurrent workers.
- This shared API key protects an internal operator service, not individual tenant
  sessions. Add OIDC and per-session ownership/RBAC before multi-user exposure.
- Only send data to Groq with organizational approval. Prompts can include issues,
  runbooks, recent conversation, and collected evidence. No automatic PII/secret
  redaction is implemented; do not submit passwords, keys, or payment-card data.
- Restrict database file permissions, configure encryption/backups, and define
  retention/deletion policies for conversations. No retention scheduler is included.
- Review runbooks as trusted deployment assets. Prompt instructions and route
  validation reduce risk but do not solve prompt injection or establish truth.
- Monitor `agent_turn` logs (session ID, version, status, node names), error rates,
  and latency. Logs are operational traces, not a tamper-proof compliance audit.
- Serve from the installed editable/source checkout: configs/prompts/data are
  repository assets; standalone wheel asset packaging is not provided.
- Live Groq behavior, load capacity, external integrations, and tenant isolation
  still require environment-specific validation before production rollout.

## Tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -v
.\venv\Scripts\python.exe -m pip check
```

Tests use temporary databases and injected/mocked model dependencies; they do not
call external providers or modify the repository's operational database. Coverage
includes graph flow, manual pauses, invalid routes, explicit escalation, restart
recovery, immutable runbook snapshots, atomic rollback, concurrent version checks,
legacy migration, API authentication/validation, and gateway failure/budget limits.

## Code map

- [app/services/support_agent.py](app/services/support_agent.py): LangGraph and safety boundaries.
- [app/services/llm_gateway.py](app/services/llm_gateway.py): bounded model calls and prompts.
- [app/core/runbooks.py](app/core/runbooks.py): runbook schema and route validation.
- [app/repositories/](app/repositories/): SQLite runbooks and atomic session turns.
- [app/main.py](app/main.py): API, authentication, health, and error mapping.
- [scripts/ingest_runbooks.py](scripts/ingest_runbooks.py): reviewed JSON / text ingestion.
