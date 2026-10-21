from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import HistoryResponse, RunListItem, RunResponse


class RunStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    terminal_assets_p50 REAL NOT NULL,
                    joint_shortfall_probability REAL NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )

    def save(self, response: RunResponse) -> None:
        payload = response.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, created_at, name, terminal_assets_p50,
                    joint_shortfall_probability, response_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    response.run_id,
                    response.created_at,
                    response.request.name,
                    response.metrics.terminal_assets.p50,
                    response.metrics.joint_shortfall_probability,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])

    def list_recent(self, limit: int = 20) -> list[RunListItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, created_at, name, terminal_assets_p50,
                       joint_shortfall_probability
                FROM runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            RunListItem(
                run_id=row["run_id"],
                created_at=row["created_at"],
                name=row["name"],
                terminal_assets_p50=row["terminal_assets_p50"],
                joint_shortfall_probability=row["joint_shortfall_probability"],
            )
            for row in rows
        ]


class HistoryStore:
    """Persistence for historical DCA backtests (separate from scenario runs)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS history_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    terminal_value REAL NOT NULL,
                    total_invested REAL NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )

    def save(self, response: HistoryResponse) -> None:
        payload = response.model_dump(mode="json")
        name = (
            response.request.asset
            if response.request.mode == "single"
            else "组合"
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO history_runs (
                    run_id, created_at, name, terminal_value,
                    total_invested, response_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    response.run_id,
                    response.created_at,
                    name,
                    response.terminal_value,
                    response.total_invested,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM history_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])
