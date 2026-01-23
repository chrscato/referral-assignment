"""
Configuration management for Referral CRM.
Supports .env files and environment variables.
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite:///referral_crm.db"
    database_echo: bool = False

    # Microsoft Graph API (for email integration)
    graph_client_id: Optional[str] = None
    graph_client_secret: Optional[str] = None
    graph_tenant_id: Optional[str] = None
    shared_mailbox: Optional[str] = None
    graph_mailbox: Optional[str] = None
    ms_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Claude API (for LLM extraction)
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-4-20250514"

    # FileMaker Integration
    filemaker_server: Optional[str] = None
    filemaker_database: Optional[str] = None
    filemaker_layout: Optional[str] = None
    filemaker_username: Optional[str] = None
    filemaker_password: Optional[str] = None

    # Application settings
    app_name: str = "Referral CRM"
    debug: bool = False
    attachments_dir: Path = Path("./attachments")

    # Email polling
    email_poll_interval_seconds: int = 60
    email_inbox_folder: str = "Inbox"

    # S3 Storage
    s3_bucket: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    aws_endpoint_url: Optional[str] = None  # For S3-compatible services (MinIO, etc.)

    def get_db_path(self) -> Path:
        """Extract the database file path from the URL."""
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.replace("sqlite:///", ""))
        return Path("referral_crm.db")


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings
