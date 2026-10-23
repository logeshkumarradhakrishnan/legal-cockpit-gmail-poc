import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Run fully stubbed: no Graph, no Azure OpenAI, fixed signing key.
for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
          "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY"):
    os.environ[k] = ""
os.environ["CONSENT_SIGNING_KEY"] = "test-key"
os.environ["GRAPH_WEBHOOK_CLIENT_STATE"] = "test-state"
os.environ["LEGAL_MAILBOX"] = "legal.intake@example.com"
os.environ["LEGAL_TEAM_ADDRESSES"] = "counsel@example.com"
os.environ["DEFAULT_MODE"] = "human_in_loop"
os.environ["AUTH_MODE"] = "dev"
os.environ["DIRECTORY_PATH"] = "does-not-exist.json"

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    main.MATTERS.clear()
    main.SEEN_KEYS.clear()
    main.TASKS.clear()
    main.AUDIT.clear()
    monkeypatch.setattr(main.settings, "audit_log_path", str(tmp_path / "audit.jsonl"))
    yield


@pytest.fixture
def client():
    return TestClient(main.app)


def email(**over):
    base = {
        "message_id": "<m1@vendor.example>",
        "sender": "vendor@vendor.example",
        "owner": "agm.commercial@example.com",
        "recipients": ["agm.commercial@example.com"],
        "subject": "Notice of termination — Supply Agreement SA-4471",
        "body": "We intend to terminate for breach and will pursue liquidated damages.",
    }
    base.update(over)
    return base
