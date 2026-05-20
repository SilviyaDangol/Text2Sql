"""Environment configuration and application logging setup."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG_PATH = LOG_DIR / "app.log"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@db:5432/classicmodels",
        alias="DATABASE_URL",
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    max_sql_retries: int = Field(default=3, alias="MAX_SQL_RETRIES")
    sql_row_limit: int = Field(default=100, alias="SQL_ROW_LIMIT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")


settings = Settings()


def setup_logging(name: str | None = None) -> logging.Logger:
    """Configure root logging and return a named logger."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger(name or "app")

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root.setLevel(level)
    root.addHandler(console_handler)

    # Benchmark/CI: skip file handler when logs dir is not writable (e.g. Docker volume)
    if not os.getenv("BENCHMARK_CONSOLE_LOG_ONLY"):
        try:
            file_handler = logging.FileHandler(APP_LOG_PATH, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            root.addHandler(file_handler)
        except OSError:
            root.warning("File logging disabled | path=%s", APP_LOG_PATH)

    logger = logging.getLogger(name or "app")
    logger.info("Logging initialized | log_file=%s | level=%s", APP_LOG_PATH, settings.log_level)
    return logger


# Initialize logging on import
logger = setup_logging("app")
