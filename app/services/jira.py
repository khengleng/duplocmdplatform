import logging
from base64 import b64encode
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def create_issue(self, summary: str, details: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.jira_enabled or not self.settings.jira_base_url:
            logger.info("Jira disabled; skipped issue", extra={"summary": summary})
            return {"status": "skipped", "reason": "jira_disabled", "summary": summary}

        payload = {
            "fields": {
                "project": {"key": self.settings.jira_project_key},
                "summary": summary,
                "description": str(details),
                "issuetype": {"name": "Task"},
            }
        }

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.jira_email and self.settings.jira_api_token:
            credentials = f"{self.settings.jira_email}:{self.settings.jira_api_token}".encode("utf-8")
            headers["Authorization"] = f"Basic {b64encode(credentials).decode('utf-8')}"
        elif self.settings.jira_token:
            headers["Authorization"] = f"Bearer {self.settings.jira_token}"

        url = self.settings.jira_base_url.rstrip("/") + "/rest/api/2/issue"
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Jira issue rejected",
                extra={"status_code": exc.response.status_code, "summary": summary},
            )
            return {"status": "failed", "reason": "jira_rejected", "status_code": exc.response.status_code}
        except Exception:
            logger.exception("Jira issue request failed", extra={"summary": summary})
            return {"status": "failed", "reason": "jira_request_failed"}


jira_client = JiraClient()
