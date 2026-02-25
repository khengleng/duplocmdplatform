from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Thin CMDB Core"
    app_env: str = "dev"
    app_debug: bool = False
    api_docs_enabled: bool = False
    api_docs_require_auth: bool = True
    max_request_body_bytes: int = 1048576
    max_bulk_items: int = 500
    request_timeout_seconds: int = 30
    global_rate_limit_per_minute: int = 600
    mutating_rate_limit_per_minute: int = 120
    mutating_rate_limit_ingest_per_minute: int = 60
    mutating_rate_limit_integrations_per_minute: int = 60
    mutating_rate_limit_relationships_per_minute: int = 90
    mutating_rate_limit_cis_per_minute: int = 90
    mutating_rate_limit_governance_per_minute: int = 60
    mutating_rate_limit_lifecycle_per_minute: int = 30
    mutating_rate_limit_approvals_per_minute: int = 60
    approver_mutating_rate_limit_per_minute: int = 30
    mutating_payload_limit_default_bytes: int = 65536
    mutating_payload_limit_ingest_bytes: int = 1048576
    mutating_payload_limit_integrations_bytes: int = 8192
    mutating_payload_limit_relationships_bytes: int = 16384
    mutating_payload_limit_cis_bytes: int = 16384
    mutating_payload_limit_governance_bytes: int = 8192
    mutating_payload_limit_lifecycle_bytes: int = 4096
    mutating_payload_limit_approvals_bytes: int = 65536
    maker_checker_enabled: bool = False
    maker_checker_default_ttl_minutes: int = 30
    maker_checker_bind_requester: bool = True
    approval_cleanup_interval_seconds: int = 60
    sync_job_max_attempts: int = 3
    sync_job_retry_base_seconds: int = 5
    sync_worker_poll_seconds: int = 2
    sync_scheduler_enabled: bool = True
    sync_schedule_netbox_import_enabled: bool = False
    sync_schedule_netbox_import_interval_seconds: int = 900
    sync_schedule_netbox_import_limit: int = 500
    sync_schedule_backstage_sync_enabled: bool = False
    sync_schedule_backstage_sync_interval_seconds: int = 900
    sync_schedule_backstage_sync_limit: int = 500

    database_url: str = "sqlite:///./cmdb.db"
    database_auto_migrate: bool = True

    source_precedence: List[str] = ["manual", "azure", "vcenter", "zabbix", "k8s"]

    lifecycle_staging_days: int = 30
    lifecycle_review_days: int = 90
    lifecycle_retired_days: int = 120

    jira_enabled: bool = False
    jira_base_url: str = ""
    jira_project_key: str = "CMDB"
    jira_email: str = ""
    jira_api_token: str = ""
    jira_token: str = ""

    unified_cmdb_name: str = "unifiedCMDB"
    service_auth_mode: str = "static"
    service_auth_tokens: str = ""
    service_viewer_tokens: str = ""
    service_operator_tokens: str = ""
    service_approver_tokens: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: str = "RS256"
    oidc_scope_viewer: str = "cmdb.viewer"
    oidc_scope_operator: str = "cmdb.operator"
    oidc_scope_approver: str = "cmdb.approver"
    netbox_sync_enabled: bool = False
    netbox_sync_url: str = ""
    netbox_sync_token: str = ""
    netbox_api_url: str = ""
    netbox_api_token: str = ""
    backstage_sync_enabled: bool = False
    backstage_sync_url: str = ""
    backstage_sync_token: str = ""
    backstage_sync_secret: str = ""
    backstage_catalog_url: str = ""
    backstage_catalog_token: str = ""

    @field_validator("source_precedence", mode="before")
    @classmethod
    def parse_precedence(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("service_auth_mode")
    @classmethod
    def validate_service_auth_mode(cls, value: str) -> str:
        mode = (value or "static").strip().lower()
        allowed = {"static", "hybrid", "oidc"}
        if mode not in allowed:
            raise ValueError(f"service_auth_mode must be one of {sorted(allowed)}")
        return mode



@lru_cache
def get_settings() -> Settings:
    return Settings()
