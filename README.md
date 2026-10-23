# Legal Cockpit

AI-assisted email triage for Legal: emails in the in-scope mailboxes are
screened, the legally relevant ones reach Legal (automatically or with the
mailbox owner's consent), and Legal classifies them and assigns work.

```
legal-cockpit/
├── backend/    FastAPI service — Graph webhook, triage pipeline, consent pages, Legal API
└── frontend/   React app — the Legal team's cockpit
```

## Who uses what

| Person | Where | What they do |
|---|---|---|
| Mailbox owner (AGM+) | Their own Outlook / Teams | Gets a "Review and decide" link; approves or declines forwarding. The page is served by the backend. |
| Legal team | Legal Cockpit (frontend) | Dashboard, matters, final classification, tasks and deadlines. |
| Nobody | — | Mail fetch, keyword gate, AI suggestion and forwarding run on their own. |

Roles in the cockpit: **Super Admin** (assigns to Admins, sees everything
including held sensitive matters), **Admin** (assigns to direct reports, sees
own and reports' tasks), **User** (works their assigned tasks).

## Run it locally (demo sign-in)

Two terminals.

```bash
# 1 — backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # AUTH_MODE=dev is preset
uvicorn main:app --reload                              # http://127.0.0.1:8000/docs
```

```bash
# 2 — frontend
cd frontend
npm install
cp .env.example .env.local                             # VITE_AUTH_MODE=dev is preset
npm run dev                                            # http://localhost:5173
```

In the cockpit, the top-right menu switches between sample people (Super Admin,
Admin, User). As the Super Admin, choose **Load sample data** to fill it with
fictitious emails and tasks.

Tests: `cd backend && pytest -q`.

## Host it on Azure

| Piece | Azure service |
|---|---|
| Backend (Docker image) | Azure Container Apps, HTTPS ingress, managed identity |
| Frontend (static build) | Azure Static Web Apps |
| Secrets | Key Vault (Graph secret, Azure OpenAI key, consent signing key) |
| AI | Azure OpenAI, Azure AI Document Intelligence |
| Data (next step) | Cosmos DB or Azure SQL; Service Bus for intake |
| Monitoring | Application Insights |

### 1. App registrations (Entra ID)

**API** — `legal-cockpit-api`
- Expose an API: Application ID URI `api://legal-cockpit-api`, scope `access_as_user`.
- App roles (assignable to users/groups): `Legal.SuperAdmin`, `Legal.Admin`, `Legal.User`.
- In Enterprise applications, turn on "Assignment required" and assign the
  Legal team members to their roles. Nobody else can get a token.
- Application permissions `Mail.Read` and `Mail.Send` (admin consent), then
  restrict them to the in-scope mailboxes with an Exchange application access
  policy — see `backend/README.md`. Test that an out-of-scope mailbox is denied.

**Frontend** — `legal-cockpit-web`
- Single-page application platform, redirect URI = the Static Web App URL.
- API permission: `api://legal-cockpit-api/access_as_user` (delegated).

### 2. Backend → Container Apps

```bash
az group create -n rg-legal-cockpit -l centralindia

az containerapp up \
  --name legal-cockpit-api \
  --resource-group rg-legal-cockpit \
  --source ./backend \
  --ingress external --target-port 8000 \
  --env-vars AUTH_MODE=entra \
             ENTRA_TENANT_ID=<tenant-id> \
             ENTRA_API_AUDIENCE=api://legal-cockpit-api \
             LEGAL_MAILBOX=legal.intake@contoso.com \
             PUBLIC_BASE_URL=https://<api-fqdn> \
             ALLOWED_ORIGINS=https://<static-web-app-host> \
             AZURE_OPENAI_ENDPOINT=https://<aoai>.openai.azure.com \
             AZURE_OPENAI_DEPLOYMENT=<deployment>
```

Add the secrets as Container Apps secrets referencing Key Vault
(`GRAPH_CLIENT_SECRET`, `AZURE_OPENAI_API_KEY`, `CONSENT_SIGNING_KEY`,
`GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_WEBHOOK_CLIENT_STATE`), and mount
`directory.json` from a secret or storage volume.

Keep **one replica** until the in-memory store is replaced with Cosmos DB / SQL:
with more than one, each replica would hold different data.

Then subscribe each in-scope mailbox once (`POST /subscriptions`) and add a
daily timer (Logic App or Azure Function) calling `/subscriptions/{id}/renew`.

### 3. Frontend → Static Web Apps

```bash
cd frontend
cat > .env.production <<EOF
VITE_API_BASE=https://<api-fqdn>
VITE_AUTH_MODE=entra
VITE_ENTRA_TENANT_ID=<tenant-id>
VITE_ENTRA_CLIENT_ID=<legal-cockpit-web client id>
VITE_API_SCOPE=api://legal-cockpit-api/access_as_user
EOF
npm ci && npm run build

az staticwebapp create -n legal-cockpit-web -g rg-legal-cockpit -l centralindia --sku Standard
npx @azure/static-web-apps-cli deploy ./dist \
  --deployment-token "$(az staticwebapp secrets list -n legal-cockpit-web -g rg-legal-cockpit --query properties.apiKey -o tsv)" \
  --env production
```

The Standard tier allows private endpoints if the cockpit should be reachable
only from the corporate network.

### Exposure

The backend has two kinds of traffic:
- **Public, no sign-in:** `/webhook/graph` (Graph calls it; checked with the
  client state) and `/consent/*` (protected by the signed, expiring link).
- **Signed-in only:** everything under `/api`, plus the operational endpoints.

Put Azure Front Door with WAF in front of the Container App. When the POC
grows, split it into a small public intake app and an internal API app.

## Never in production

- `AUTH_MODE=dev` / `VITE_AUTH_MODE=dev` — anyone could act as anyone.
- A committed `.env` or `directory.json`.
