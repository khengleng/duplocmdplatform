import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

TEST_DB_PATH = Path(__file__).resolve().parent / f"cmdb_test_{uuid4().hex}.db"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
    os.environ["DATABASE_AUTO_MIGRATE"] = "true"
    os.environ["SERVICE_AUTH_MODE"] = "static"
    os.environ["SERVICE_OPERATOR_TOKENS"] = "operator-test-token"
    os.environ["SERVICE_VIEWER_TOKENS"] = "viewer-test-token"
    # Two approver tokens — needed to test the self-approval guard (same principal = same token)
    os.environ["SERVICE_APPROVER_TOKENS"] = "approver-test-token,approver-test-token-2"
    os.environ["SYNC_SCHEDULER_ENABLED"] = "false"
    os.environ["API_DOCS_ENABLED"] = "false"

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
