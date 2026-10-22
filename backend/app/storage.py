from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    AnalysisResponse,
    CashflowBalance,
    CashflowBalanceInput,
    CashflowImportBatch,
    CashflowRule,
    CashflowRuleInput,
    CashflowTransaction,
    CashflowTransactionPatch,
    HistoryResponse,
    RunListItem,
    RunResponse,
)
from .core.cashflow import default_rules


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


class AnalysisStore:
    """Persistence for on-demand LLM analyses.

    Analyses are keyed by a deterministic id that includes the source run,
    model and what-if plan, so the same request can be replayed from the
    snapshot instead of calling the model again.
    """

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
                CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )

    def save(self, response: AnalysisResponse) -> None:
        payload = response.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO analyses (
                    analysis_id, created_at, mode, run_id, source, response_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    response.analysis_id,
                    response.created_at,
                    response.mode,
                    response.run_id,
                    response.source,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM analyses WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])


class CashflowStore:
    """Append-only transaction store plus editable rules and balance snapshots."""

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
                CREATE TABLE IF NOT EXISTS cashflow_imports (
                    import_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    account TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    imported_count INTEGER NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    skipped_count INTEGER NOT NULL,
                    mapping_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    raw_path TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cashflow_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    account TEXT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    direction TEXT NOT NULL,
                    category TEXT NOT NULL,
                    bucket TEXT,
                    investment_action TEXT,
                    counterparty TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    raw_category TEXT NOT NULL DEFAULT '',
                    is_one_off INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    category_source TEXT NOT NULL DEFAULT 'rule',
                    fingerprint TEXT NOT NULL UNIQUE,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cashflow_date ON cashflow_transactions(date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cashflow_direction ON cashflow_transactions(direction)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cashflow_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    priority INTEGER NOT NULL,
                    pattern TEXT NOT NULL,
                    match_field TEXT NOT NULL,
                    direction TEXT,
                    category TEXT NOT NULL,
                    bucket TEXT,
                    investment_action TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cashflow_balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    balance REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    updated_at TEXT NOT NULL,
                    UNIQUE(date, bucket)
                )
                """
            )
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM cashflow_rules"
            ).fetchone()["count"]
            if count == 0:
                for rule in default_rules():
                    self._insert_rule(connection, rule)

    @staticmethod
    def _insert_rule(connection: sqlite3.Connection, rule: CashflowRuleInput) -> None:
        connection.execute(
            """
            INSERT INTO cashflow_rules (
                priority, pattern, match_field, direction, category, bucket,
                investment_action, enabled, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule.priority,
                rule.pattern,
                rule.match_field,
                rule.direction,
                rule.category,
                rule.bucket,
                rule.investment_action,
                1 if rule.enabled else 0,
                rule.note,
            ),
        )

    def save_import(
        self,
        *,
        import_id: str,
        source: str,
        account: str,
        filename: str,
        row_count: int,
        imported: int,
        duplicates: int,
        skipped: int,
        mapping: dict[str, Any],
        warnings: list[str],
        raw_path: str,
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO cashflow_imports (
                    import_id, created_at, source, account, filename, row_count,
                    imported_count, duplicate_count, skipped_count, mapping_json,
                    warnings_json, raw_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    created_at,
                    source,
                    account,
                    filename,
                    row_count,
                    imported,
                    duplicates,
                    skipped,
                    json.dumps(mapping, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    raw_path,
                ),
            )

    def get_import_raw_path(self, import_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT raw_path FROM cashflow_imports WHERE import_id = ?",
                (import_id,),
            ).fetchone()
        return row["raw_path"] if row else None

    def list_imports(self, limit: int = 30) -> list[CashflowImportBatch]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM cashflow_imports
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            CashflowImportBatch(
                import_id=row["import_id"],
                created_at=row["created_at"],
                source=row["source"],
                account=row["account"],
                filename=row["filename"],
                row_count=row["row_count"],
                imported=row["imported_count"],
                duplicates=row["duplicate_count"],
                skipped=row["skipped_count"],
                warnings=json.loads(row["warnings_json"] or "[]"),
            )
            for row in rows
        ]

    def save_transactions(
        self, transactions: list[CashflowTransaction], created_at: str
    ) -> int:
        inserted = 0
        with self._connect() as connection:
            for transaction in transactions:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO cashflow_transactions (
                        import_id, source, account, date, amount, direction,
                        category, bucket, investment_action, counterparty,
                        description, raw_category, is_one_off, note,
                        category_source, fingerprint, raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction.import_id,
                        transaction.source,
                        transaction.account,
                        transaction.date.isoformat(),
                        transaction.amount,
                        transaction.direction,
                        transaction.category,
                        transaction.bucket,
                        transaction.investment_action,
                        transaction.counterparty,
                        transaction.description,
                        transaction.raw_category,
                        1 if transaction.is_one_off else 0,
                        transaction.note,
                        transaction.category_source,
                        transaction.fingerprint,
                        transaction.raw_json,
                        created_at,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> CashflowTransaction:
        return CashflowTransaction(
            id=row["id"],
            import_id=row["import_id"],
            source=row["source"],
            account=row["account"],
            date=date.fromisoformat(row["date"]),
            amount=row["amount"],
            direction=row["direction"],
            category=row["category"],
            bucket=row["bucket"],
            investment_action=row["investment_action"],
            counterparty=row["counterparty"],
            description=row["description"],
            raw_category=row["raw_category"],
            is_one_off=bool(row["is_one_off"]),
            note=row["note"],
            category_source=row["category_source"],
            fingerprint=row["fingerprint"],
            raw_json=row["raw_json"],
            created_at=row["created_at"],
        )

    def list_transactions(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 200,
        offset: int = 0,
        direction: str | None = None,
        category: str | None = None,
    ) -> tuple[list[CashflowTransaction], int]:
        clauses: list[str] = []
        values: list[Any] = []
        if from_date is not None:
            clauses.append("date >= ?")
            values.append(from_date.isoformat())
        if to_date is not None:
            clauses.append("date <= ?")
            values.append(to_date.isoformat())
        if direction:
            clauses.append("direction = ?")
            values.append(direction)
        if category:
            clauses.append("category = ?")
            values.append(category)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS count FROM cashflow_transactions{where}",
                values,
            ).fetchone()["count"]
            rows = connection.execute(
                f"""
                SELECT * FROM cashflow_transactions{where}
                ORDER BY date DESC, id DESC LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        return [self._transaction_from_row(row) for row in rows], int(total)

    def get_transaction(self, transaction_id: int) -> CashflowTransaction | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cashflow_transactions WHERE id = ?",
                (transaction_id,),
            ).fetchone()
        return self._transaction_from_row(row) if row else None

    def update_transaction(
        self, transaction_id: int, patch: CashflowTransactionPatch
    ) -> CashflowTransaction | None:
        existing = self.get_transaction(transaction_id)
        if existing is None:
            return None
        values = patch.model_dump(exclude_unset=True)
        if "direction" in values:
            direction = values["direction"]
            if direction == "income":
                values.setdefault("category", "其他收入")
                values["bucket"] = None
                values["investment_action"] = None
            elif direction == "expense":
                values.setdefault("category", "其他支出")
                values["bucket"] = None
                values["investment_action"] = None
            elif direction == "transfer":
                values.setdefault("category", "转账")
                values["bucket"] = None
                values["investment_action"] = None
            elif direction == "ignore":
                values.setdefault("category", "不计收支")
                values["bucket"] = None
                values["investment_action"] = None
            elif direction == "investment":
                values.setdefault("category", "投资")
                values.setdefault("bucket", "other")
                values.setdefault("investment_action", "buy")
        touch_classification = any(
            key in values
            for key in ("direction", "category", "bucket", "investment_action")
        )
        if touch_classification:
            values["category_source"] = "manual"
        if not values:
            return existing
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE cashflow_transactions SET {assignments} WHERE id = ?",
                [*values.values(), transaction_id],
            )
        return self.get_transaction(transaction_id)

    def set_classification(
        self,
        transaction_id: int,
        *,
        direction: str,
        category: str,
        bucket: str | None,
        investment_action: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE cashflow_transactions SET
                    direction = ?, category = ?, bucket = ?,
                    investment_action = ?, category_source = 'rule'
                WHERE id = ? AND category_source != 'manual'
                """,
                (direction, category, bucket, investment_action, transaction_id),
            )

    def list_rules(self) -> list[CashflowRule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM cashflow_rules ORDER BY priority DESC, id ASC"
            ).fetchall()
        return [
            CashflowRule(
                id=row["id"],
                priority=row["priority"],
                pattern=row["pattern"],
                match_field=row["match_field"],
                direction=row["direction"],
                category=row["category"],
                bucket=row["bucket"],
                investment_action=row["investment_action"],
                enabled=bool(row["enabled"]),
                note=row["note"],
            )
            for row in rows
        ]

    def add_rule(self, rule: CashflowRuleInput) -> CashflowRule:
        with self._connect() as connection:
            self._insert_rule(connection, rule)
            rule_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return next(item for item in self.list_rules() if item.id == rule_id)

    def update_rule(self, rule_id: int, rule: CashflowRuleInput) -> CashflowRule | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE cashflow_rules SET
                    priority = ?, pattern = ?, match_field = ?, direction = ?,
                    category = ?, bucket = ?, investment_action = ?,
                    enabled = ?, note = ?
                WHERE id = ?
                """,
                (
                    rule.priority,
                    rule.pattern,
                    rule.match_field,
                    rule.direction,
                    rule.category,
                    rule.bucket,
                    rule.investment_action,
                    1 if rule.enabled else 0,
                    rule.note,
                    rule_id,
                ),
            )
            changed = cursor.rowcount > 0
        if not changed:
            return None
        return next((item for item in self.list_rules() if item.id == rule_id), None)

    def delete_rule(self, rule_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM cashflow_rules WHERE id = ?", (rule_id,)
            )
            changed = cursor.rowcount > 0
        return changed

    @staticmethod
    def _balance_from_row(row: sqlite3.Row) -> CashflowBalance:
        return CashflowBalance(
            id=row["id"],
            date=date.fromisoformat(row["date"]),
            bucket=row["bucket"],
            balance=row["balance"],
            note=row["note"],
            source=row["source"],
            updated_at=row["updated_at"],
        )

    def upsert_balance(
        self, balance: CashflowBalanceInput, *, source: str = "manual"
    ) -> CashflowBalance:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cashflow_balances (date, bucket, balance, note, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, bucket) DO UPDATE SET
                    balance = excluded.balance,
                    note = excluded.note,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    balance.date.isoformat(),
                    balance.bucket,
                    balance.balance,
                    balance.note,
                    source,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM cashflow_balances WHERE date = ? AND bucket = ?",
                (balance.date.isoformat(), balance.bucket),
            ).fetchone()
        return self._balance_from_row(row)

    def list_balances(
        self, *, from_date: date | None = None, to_date: date | None = None
    ) -> list[CashflowBalance]:
        clauses: list[str] = []
        values: list[Any] = []
        if from_date is not None:
            clauses.append("date >= ?")
            values.append(from_date.isoformat())
        if to_date is not None:
            clauses.append("date <= ?")
            values.append(to_date.isoformat())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM cashflow_balances{where} ORDER BY date, bucket",
                values,
            ).fetchall()
        return [self._balance_from_row(row) for row in rows]

    def delete_balance(self, balance_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM cashflow_balances WHERE id = ?", (balance_id,)
            )
            changed = cursor.rowcount > 0
        return changed

    def delete_import(self, import_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM cashflow_transactions WHERE import_id = ?",
                (import_id,),
            )
            deleted = cursor.rowcount
            connection.execute(
                "DELETE FROM cashflow_imports WHERE import_id = ?", (import_id,)
            )
        return deleted
