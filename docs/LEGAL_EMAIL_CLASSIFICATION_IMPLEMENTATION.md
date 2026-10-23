# Legal email classification implementation

The backend classification rules are transcribed from `legal-email-classification-source.txt`.

## Processing order

1. Existing source/recipient loop prevention and duplicate detection run first.
2. Personal-matter exclusions run before classification. A match is marked `excluded`, has no AI/legal category, and is audit-logged.
3. Negative/exclusion signals (webinar, training program, newsletter, unsubscribe, save the date, conference invitation, certificate of appreciation) suppress classification and are logged as `negative_exclusion`.
4. The deterministic keyword gate scans subject, sender, body, and extracted attachment text. It retains the pre-existing Hindi/Kannada gate terms as well as the document taxonomy.
5. When configured, Azure OpenAI receives the taxonomy, category keyword matches, urgency signals, and sender stakeholder-name matches. If unavailable, a deterministic best-fit category/risk fallback is used.
6. Urgency terms raise the fallback risk by one level (Low → Medium → High); they are also retained in the audit details. Sensitive matters remain held by the existing restricted-handling rule.
7. Audit records include classification method, matched categories, urgency matches, and stakeholder-name matches.

## Taxonomy

The rules cover the 16 document categories: contract management, litigation, compliance/regulatory, IP, employment, privacy, corporate, external counsel, tax/statutory demands, licensing/clearance, RTI, environmental, land/property, international aviation/regulatory, media/reputational risk, and passenger legal risk.

## Stakeholder registry limitation

The source document explicitly says stakeholder email domains still need to be collected. The implementation therefore detects organization names/aliases in the sender field only; it does not invent or assume domains. Populate verified domains in a maintained registry before relying on sender-based stakeholder matching in production.

## Deliberate scope boundary

The source document describes a run every three days and mentions Outlook, while this POC's connected source is Gmail (with existing Graph webhook support). This change updates classification and auditability; it does not add a scheduler or change mailbox ingestion cadence. Scheduling and a verified stakeholder-domain registry remain deployment decisions.

## Validation

Backend test suite: `pytest -q`.
