from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def load_env(path: Path) -> None:
    """Load a simple KEY=VALUE .env file without adding a dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # Real environment variables win over .env.
        os.environ.setdefault(key, value)


load_env(ROOT_DIR / ".env")


def _resolve(path_value: str, default: str) -> Path:
    raw = Path(path_value or default)
    return raw if raw.is_absolute() else ROOT_DIR / raw


class Settings:
    code_version = "0.1.0"
    data_version = "none"

    def __init__(self) -> None:
        self.llm_api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        self.llm_base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").strip()
        self.llm_model = os.environ.get("LLM_MODEL", "deepseek-chat").strip()
        self.llm_timeout_seconds = float(os.environ.get("LLM_TIMEOUT_SECONDS", "45"))
        self.database_path = _resolve(
            os.environ.get("DATABASE_PATH", ""), "backend/data/finance.db"
        )
        self.runs_dir = _resolve(os.environ.get("RUNS_DIR", ""), "runs")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


settings = Settings()
