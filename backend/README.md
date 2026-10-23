# Legal Cockpit — Triage Service (FastAPI)

AI-assisted email triage for Legal. Mail arrives through Microsoft Graph, passes a
deterministic keyword gate, gets an AI suggestion (category + risk), and is then
either forwarded automatically or sent to the mailbox owner for consent.

## How an email flows

1. **Arrives** — Graph notifies `/webhook/graph`; the service fetches the message
   and attachments in the background (attachments go through Document Intelligence).
2. **Excluded** if this service sent it (stops notification loops) or Legal is
   already a recipient.
3. **De-duplicated** on the internet message id, which is the same in every
   recipient's copy, so a mail sent to five AGMs reaches Legal once.
4. **Stage 1 keyword gate** — English, Hindi and Kannada terms across body and
   attachments. No match → `dropped`.
5. **Stage 2 AI intent** — Azure OpenAI returns category, risk, rationale and
   confidence. A suggestion only.
6. **Stage 3 disposition**
   - POSH / whistleblower → `held`, in **both** modes. Never forwarded automatically.
   - `auto` → forwarded to Legal with the original attachments; owner is told afterwards.
     A low-confidence suggestion falls back to consent.
   - `human_in_loop` → owner gets an email with a review link → `pending_consent`.

Every step is written to an append-only audit log.

## The consent step

The owner's email has one **Review and decide** link. It opens a page with the
email, the suggestion and two buttons. The link is signed (HMAC), bound to that
matter and that owner, and expires after `CONSENT_TTL_HOURS`.

Opening the page decides nothing; only the button (a POST) does. That matters
because Defender Safe Links and similar scanners open every link in an email:
an "approve" GET link would be approved by the scanner.

For Teams, `GET /matters/{id}/teams-card` returns an Adaptive Card pointing at the
same review page. Post it with a Teams Workflows webhook; a bot is only needed if
you later want in-card buttons.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs. With nothing configured it runs fully stubbed:
outbound mail is logged instead of sent, and a rule-based classifier stands in
for Azure OpenAI.

```bash
pytest -q        # 24 tests: both modes, safeguards, consent links, webhook
```

## Try it

```bash
# human-in-the-loop → pending_consent (the log shows the consent email)
curl -s -X POST localhost:8000/ingest -H 'content-type: application/json' -d '{
  "message_id":"<m1@vendor>","sender":"vendor@ex.com","owner":"agm@ex.com",
  "subject":"Notice of termination","body":"We terminate for breach; liquidated damages follow."}'

# automatic
curl -s -X POST localhost:8000/ingest -H 'content-type: application/json' -d '{
  "message_id":"<m2@reg>","sender":"n@ex.com","owner":"sec@ex.com","mode":"auto",
  "subject":"Possible data breach","body":"Regulatory notification may be required."}'

# sensitive → held, even in auto mode
curl -s -X POST localhost:8000/ingest -H 'content-type: application/json' -d '{
  "message_id":"<m3@hr>","sender":"x@ex.com","owner":"hr@ex.com","mode":"auto",
  "subject":"Formal complaint","body":"Raising a POSH complaint confidentially."}'

curl -s localhost:8000/dashboard
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/webhook/graph` | Graph change notifications (validation echo + background processing) |
| POST | `/subscriptions` | Subscribe one in-scope mailbox |
| POST | `/subscriptions/{id}/renew` | Renew (call daily; subscriptions expire in under 3 days) |
| GET  | `/consent/{token}` | Owner review page |
| POST | `/consent/{token}/approve` · `/decline` | Owner decision |
| GET  | `/matters/{id}/teams-card` | Adaptive Card for Teams |
| POST | `/ingest` | Submit one email directly |
| GET  | `/matters` · `/matters/{id}` | Inspect matters (`?status=` filter) |
| POST | `/matters/{id}/approve` · `/decline` | Admin decision path |
| GET  | `/dashboard` | Counts by status, risk, category |
| GET  | `/health` | Mode, and whether Graph / OpenAI are live or stubbed |

## Azure setup

1. **App registration** (Entra ID) with application permissions `Mail.Read` and
   `Mail.Send`, admin-consented.
2. **Scope it.** Application permissions cover every mailbox in the tenant until
   you restrict them. Put the in-scope AGM+ mailboxes and the Legal intake mailbox
   in a mail-enabled security group and apply an Exchange application access
   policy (or RBAC for Applications):

   ```powershell
   New-ApplicationAccessPolicy -AppId <client-id> -AccessRight RestrictAccess `
     -PolicyScopeGroupId SG-LegalCockpit-Scope@contoso.com `
     -Description "Legal Cockpit: in-scope mailboxes only"
   Test-ApplicationAccessPolicy -AppId <client-id> -Identity someone.outofscope@contoso.com
   ```

   The test against out-of-scope mailboxes must return **Denied** before the app
   gets production credentials.
3. **Host** on Azure Container Apps or App Service behind HTTPS, set
   `PUBLIC_BASE_URL`, and call `POST /subscriptions` once per in-scope mailbox.
4. **Renew** subscriptions daily from a timer (Azure Function or Logic App).
5. **Secrets** (`GRAPH_CLIENT_SECRET`, `AZURE_OPENAI_API_KEY`, `CONSENT_SIGNING_KEY`)
   from Key Vault.

## Still to do before production

- Replace the in-memory `MATTERS` / `SEEN_KEYS` with Cosmos DB or Azure SQL.
  With more than one replica, de-duplication must use the shared store.
- Move background processing to a queue (Service Bus) so a restart mid-email
  loses nothing; keep the webhook answering fast.
- Put the keyword lists and risk taxonomy in configuration Legal can edit.
- Retention and deletion rules for stored email content and the audit log, once
  agreed in the BRD.
- Authentication on `/matters`, `/dashboard` and the admin approve/decline
  endpoints (Entra ID, Legal team only).

## Legal Cockpit API (`/api/*`)

Everything the frontend uses lives under `/api` and requires sign-in.

| Method | Path | Who |
|---|---|---|
| GET | `/api/me` | everyone — role and who you can assign to |
| GET | `/api/dashboard` | Super Admin, Admin |
| GET | `/api/matters?view=all\|unclassified\|held` | everyone, filtered by role |
| GET | `/api/matters/{id}` · `/audit` | per visibility rules · audit for staff |
| POST | `/api/matters/{id}/classify` | Super Admin, Admin |
| POST | `/api/matters/{id}/tasks` | Super Admin → Admins; Admin → direct reports |
| GET | `/api/tasks?scope=mine\|all` | everyone, filtered by role |
| PATCH | `/api/tasks/{id}` | assignee, assigner, or Super Admin |
| POST | `/api/dev/seed` | dev mode only — loads fictitious sample data |

Visibility: held (sensitive) matters are Super Admin only. Users see only matters
they have a task on. Emails that were dropped, declined or are still waiting for
consent are never shown to anyone — only counted.

Sign-in: `AUTH_MODE=entra` validates Entra ID tokens; roles come from the app
roles `Legal.SuperAdmin`, `Legal.Admin`, `Legal.User`. Reporting lines come from
`directory.json`. `AUTH_MODE=dev` simulates sign-in with a sample team.

Operational endpoints outside `/api` (`/ingest`, `/matters`, `/dashboard`,
`/subscriptions`) require Super Admin.

## Gmail POC connector

The POC can connect one Gmail account using Google OAuth and feed selected Inbox messages into the same `process(EmailIn)` pipeline used by the existing Microsoft Graph integration.

Flow:

1. `GET /gmail/auth` returns the Google authorization URL.
2. User grants Gmail read/send access.
3. Google redirects to `/gmail/callback`; the OAuth token is stored locally at `GMAIL_TOKEN_PATH`.
4. `GET /gmail/messages` lists recent Inbox messages.
5. `POST /gmail/ingest/{message_id}` fetches the message and attachments and calls the existing triage pipeline.
6. If the matter is auto-forwarded or approved, Gmail is used to send the Legal copy/owner notification.

Required environment variables:

```text
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REDIRECT_URI=http://127.0.0.1:8000/gmail/callback
GMAIL_TOKEN_PATH=.gmail-token.json
```

The token file is deliberately local for the POC. Production should use encrypted secret/token storage and support multiple connected mailboxes.
