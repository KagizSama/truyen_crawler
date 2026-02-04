from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    BASE_URL: str = "https://truyenfull.vision"
    DATA_DIR: Path = Path("data")
    CONCURRENT_REQUESTS: int = 5
    BATCH_SIZE: int = 30
    CHAPTER_DELAY: float = 0.3
    REQUEST_TIMEOUT: int = 30
    RETRIES: int = 3
    RETRY_BACKOFF: float = 1.5
    DATABASE_URL: str = ""
    SAVE_TO_JSON: bool = False
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    ELASTICSEARCH_USER: str = ""
    ELASTICSEARCH_PASSWORD: str = ""
    ELASTICSEARCH_INDEX: str = "stories"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()