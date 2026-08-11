from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: float
    cors_origins: tuple[str, ...]
    log_level: str
    llm_json_mode: bool = True
    llm_disable_thinking: bool = False
    model_config_master_key: str = ""

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        root = Path(__file__).resolve().parents[1]
        load_dotenv(env_file or root / ".env", override=False)

        def configured_path(name: str, default: Path) -> Path:
            value = Path(os.getenv(name, str(default)))
            return (value if value.is_absolute() else root / value).resolve()

        return cls(
            data_dir=configured_path("DATA_DIR", root / "data"),
            database_path=configured_path("DATABASE_PATH", root / "runtime" / "app.db"),
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
            cors_origins=_csv_env("CORS_ORIGINS", "http://localhost:3000"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            llm_json_mode=_bool_env("LLM_JSON_MODE", True),
            llm_disable_thinking=_bool_env("LLM_DISABLE_THINKING", False),
            model_config_master_key=os.getenv("MODEL_CONFIG_MASTER_KEY", "").strip(),
        )
