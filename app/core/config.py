from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Thin CMDB Core"
    app_env: str = "dev"
    app_debug: bool = False
    max_request_body_bytes: int = 1048576
    max_bulk_items: int = 500
    mutating_rate_limit_per_minute: int = 120

    database_url: str = "sqlite:///./cmdb.db"

    source_precedence: List[str] = ["manual", "azure", "vcenter", "zabbix", "k8s"]

    lifecycle_staging_days: int = 30
    lifecycle_review_days: int = 90
    lifecycle_retired_days: int = 120

    jira_enabled: bool = False
    jira_base_url: str = ""
    jira_project_key: str = "CMDB"
    jira_token: str = ""

    unified_cmdb_name: str = "unifiedCMDB"
    service_auth_tokens: str = ""
    netbox_sync_enabled: bool = False
    netbox_sync_url: str = ""
    netbox_sync_token: str = ""
    netbox_api_url: str = ""
    netbox_api_token: str = ""
    backstage_sync_enabled: bool = False
    backstage_sync_url: str = ""
    backstage_sync_token: str = ""
    backstage_sync_secret: str = ""

    @field_validator("source_precedence", mode="before")
    @classmethod
    def parse_precedence(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]



@lru_cache
def get_settings() -> Settings:
    return Settings()
