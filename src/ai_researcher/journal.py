"""Immutable SQLite journal for scientific handoffs and execution bindings."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .records import ID_FIELDS, canonical_json, validate_record


class JournalConflictError(RuntimeError):
    """An immutable scientific identity was reused with different content."""


class ResearchJournal:
    """Append-only scientific records with explicit provenance links."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_digest TEXT PRIMARY KEY,
                    schema_name TEXT NOT NULL,
                    primary_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(schema_name, primary_id)
                );
                CREATE TABLE IF NOT EXISTS record_links (
                    parent_digest TEXT NOT NULL REFERENCES records(record_digest),
                    child_digest TEXT NOT NULL REFERENCES records(record_digest),
                    relation TEXT NOT NULL,
                    PRIMARY KEY(parent_digest, child_digest, relation)
                );
                CREATE TABLE IF NOT EXISTS experiment_bindings (
                    experiment_id TEXT PRIMARY KEY,
                    experiment_digest TEXT NOT NULL,
                    approval_digest TEXT NOT NULL REFERENCES records(record_digest),
                    task_card_path TEXT NOT NULL,
                    lane_id TEXT,
                    run_id TEXT,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def append(
        self,
        record: Mapping[str, Any],
        *,
        source: str,
        links: Iterable[tuple[str, str]] = (),
    ) -> dict[str, Any]:
        normalized = validate_record(record)
        digest = normalized["record_digest"]
        schema = normalized["schema"]
        identifier = str(normalized[ID_FIELDS[schema]])
        payload = canonical_json(normalized).decode("utf-8")
        if not source.strip():
            raise ValueError("source must be non-empty")
        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT record_digest FROM records WHERE schema_name=? AND primary_id=?",
                (schema, identifier),
            ).fetchone()
            if existing is not None and existing[0] != digest:
                raise JournalConflictError(
                    f"{schema} identity {identifier!r} already has different content"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO records
                    (record_digest, schema_name, primary_id, payload_json, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (digest, schema, identifier, payload, source, _utc_now()),
            )
            for parent_digest, relation in links:
                connection.execute(
                    "INSERT OR IGNORE INTO record_links VALUES (?, ?, ?)",
                    (parent_digest, digest, relation),
                )
        return normalized

    def get(self, digest: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM records WHERE record_digest=?", (digest,)
            ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def find(self, schema: str, primary_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM records WHERE schema_name=? AND primary_id=?",
                (schema, primary_id),
            ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def bind_experiment(
        self,
        *,
        experiment_id: str,
        experiment_digest: str,
        approval_digest: str,
        task_card_path: str | Path,
        status: str = "STAGED",
        lane_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.initialize()
        values = (
            experiment_digest,
            approval_digest,
            str(Path(task_card_path).resolve()),
            lane_id,
            run_id,
            status,
            _utc_now(),
            experiment_id,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT experiment_digest, approval_digest FROM experiment_bindings WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            if existing is not None and tuple(existing) != (experiment_digest, approval_digest):
                raise JournalConflictError("experiment binding conflicts with its immutable approval")
            connection.execute(
                """
                INSERT INTO experiment_bindings
                    (experiment_id, experiment_digest, approval_digest, task_card_path,
                     lane_id, run_id, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    lane_id=excluded.lane_id,
                    run_id=excluded.run_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (experiment_id, *values[:-1]),
            )

    def experiment_status(self, experiment_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT experiment_id, experiment_digest, approval_digest,
                       task_card_path, lane_id, run_id, status, updated_at
                FROM experiment_bindings WHERE experiment_id=?
                """,
                (experiment_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
