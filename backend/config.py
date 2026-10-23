"""
Configuration for the Legal Cockpit triage service.

All secrets and environment-specific values come from environment variables
(or a local .env file). Nothing sensitive is hard-coded. In Azure, source
GRAPH_CLIENT_SECRET / AZURE_OPENAI_API_KEY / CONSENT_SIGNING_KEY from Key Vault.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Processing mode -------------------------------------------------
    # "human_in_loop": pause for the mailbox owner's consent before forwarding.
    # "auto":          forward automatically and notify the owner afterwards.
    default_mode: Literal["human_in_loop", "auto"] = "human_in_loop"
    min_confidence: float = 0.55

    # --- Destinations and exclusions -------------------------------------
    legal_mailbox: str = "legal.intake@example.com"
    # Comma-separated. Mail where any of these is already a recipient is
    # excluded (Legal is already in the loop), per the workshop decision.
    legal_team_addresses: str = ""

    # --- Public URL of this service (used in consent links) --------------
    public_base_url: str = "http://127.0.0.1:8000"

    # --- Consent links ---------------------------------------------------
    # HMAC key for signed approve/decline links. If blank, a random key is
    # generated at startup (links then stop working after a restart).
    consent_signing_key: str = ""
    consent_ttl_hours: int = 72

    # --- Microsoft Graph (ingestion + send). Leave blank to run stubbed. -
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_webhook_client_state: str = "change-me"

    # --- Gmail OAuth / API (single connected mailbox for the POC) ---------
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_redirect_uri: str = "http://127.0.0.1:8000/gmail/callback"
    gmail_token_path: str = ".gmail-token.json"

    # --- Azure OpenAI (classification). Leave blank to run stubbed. ------
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str = "gpt-4o"

    # --- Azure AI Document Intelligence (attachment OCR). Optional. ------
    doc_intelligence_endpoint: str = ""
    doc_intelligence_api_key: str = ""

    # --- Audit -----------------------------------------------------------
    audit_log_path: str = "audit.log.jsonl"

    # --- Legal Cockpit sign-in --------------------------------------------
    # "entra": validate Entra ID access tokens (production).
    # "dev":   trust an X-Dev-User header from a built-in sample directory.
    #          Local development and demos only; never deploy with "dev".
    auth_mode: Literal["entra", "dev"] = "entra"
    entra_tenant_id: str = ""
    # The API's Application ID URI or client id, e.g. api://legal-cockpit-api
    entra_api_audience: str = ""
    # JSON file listing Legal team members: [{email, name, role, manager}]
    directory_path: str = "directory.json"

    # Comma-separated frontend origins allowed to call the API (CORS)
    allowed_origins: str = "http://localhost:5174"

    @property
    def graph_configured(self) -> bool:
        return bool(self.graph_tenant_id and self.graph_client_id and self.graph_client_secret)

    @property
    def gmail_configured(self) -> bool:
        return bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_redirect_uri)

    @property
    def gmail_connected(self) -> bool:
        if not self.gmail_configured:
            return False
        try:
            import gmail_auth
            return gmail_auth.credentials() is not None
        except Exception:
            return False

    @property
    def openai_configured(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def legal_team_set(self) -> set[str]:
        return {a.strip().lower() for a in self.legal_team_addresses.split(",") if a.strip()}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    print("\n" + "=" * 60)
    print("🔍 LEGAL COCKPIT CONFIG DEBUG")
    print("=" * 60)

    # print("GMAIL_CLIENT_ID     :", settings.gmail_client_id)
    # print("GMAIL_CLIENT_SECRET :", "***SET***" if settings.gmail_client_secret else "❌ EMPTY")
    print("GMAIL_REDIRECT_URI  :", repr(settings.gmail_redirect_uri))
    print("GMAIL_TOKEN_PATH    :", settings.gmail_token_path)

    print("-" * 60)
    print("GMAIL CONFIGURED    :", settings.gmail_configured)
    print("ENV FILE            : .env")
    print("=" * 60 + "\n")

    return settings