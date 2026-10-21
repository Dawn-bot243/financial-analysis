from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..models import HistoryResponse, RunResponse


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def code_fingerprint() -> str:
    """Hash the calculation code so every run is traceable to an implementation."""
    core_dir = Path(__file__).resolve().parent
    app_dir = core_dir.parent
    files = sorted(core_dir.glob("*.py")) + [app_dir / "models.py"]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def make_run_id(
    request_payload: dict,
    code_version: str,
    fingerprint: str,
    data_version: str = "none",
    explanation_mode: str = "llm",
) -> str:
    payload = {
        "request": request_payload,
        "code_version": code_version,
        "code_fingerprint": fingerprint,
        "data_version": data_version,
        "explanation_mode": explanation_mode,
    }
    return sha256_hex(canonical_json(payload))[:16]


def export_snapshot(response: RunResponse, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{response.run_id}.json"
    path.write_text(
        json.dumps(
            response.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def export_history_snapshot(response: HistoryResponse, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"history-{response.run_id}.json"
    path.write_text(
        json.dumps(
            response.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path
