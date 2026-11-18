from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    cors_origins: str = "http://localhost:4200"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
