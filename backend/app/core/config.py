from functools import lru_cache
import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    database_url: str
    secret_key: str
    debug: bool = False

    cloudflare_api_key: str | None = None
    cloudflare_email: str | None = None
    cloudflare_account_id: str | None = None

    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_tenant_id: str | None = None
    
    # Microsoft Graph API - Device Code Flow
    MS_CLIENT_ID: str = ""  # From Azure App Registration

    # Security
    encryption_key: str = ""  # For encrypting sensitive data
    
    # Selenium
    screenshot_dir: str = "/tmp/screenshots"  # Directory for browser screenshots
    
    # Parallel Processing for Step 5
    # Controls how many browser instances run simultaneously
    # Start conservative at 3, can increase to 5-6 once confirmed stable
    # Each headless Chrome uses ~200-300MB RAM, so 3 = ~1GB RAM needed
    max_parallel_browsers: int = 3

    allowed_origins: str = ""
    
    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse allowed_origins as comma-separated string or JSON array."""
        if not self.allowed_origins:
            return []
        # Handle both comma-separated and JSON array formats
        if self.allowed_origins.startswith('['):
            return json.loads(self.allowed_origins)
        return [origin.strip() for origin in self.allowed_origins.split(',') if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()