from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from backend.research_runtime.contracts import JobState
from backend.research_runtime.events import EventWriteError, EventWriter
from backend.research_runtime.job_spec import JobSpec
from backend.research_runtime.paths import RuntimePaths

SCHEMA_VERSION = 1


def _iso(value: datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class JobRow:
    job_id: str
    state: JobState
    lease_epoch: int
    attempt: int
    cancel_requested_at: str | None
    spec_sha256: str


@dataclass(frozen=True, slots=True)
class Claim:
    job_id: str
    lease_epoch: int
    attempt: int


@dataclass(frozen=True, slots=True)
class RunningJob:
    job_id: str
    boot_id: str | None
    pid: int | None
    lease_epoch: int
    attempt: int


@dataclass(frozen=True, slots=True)
class ExecutionJob:
    job_id: str
    handler: str
    handler_args: dict[str, int]
    expected_host: str
    repo_head: str
    deadline: datetime
    max_wall_seconds: int
    lease_epoch: int
    attempt: int
    cancel_requested_at: str | None


class Ledger:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        event_writer: EventWriter,
    ) -> None:
        self._db = connection
        self._events = event_writer

    @classmethod
    def open(
        cls,
        paths: RuntimePaths,
        *,
        event_writer: EventWriter | None = None,
    ) -> Ledger:
        existed = paths.ledger.exists()
        connection = sqlite3.connect(paths.ledger, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    spec_sha256 TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    handler TEXT NOT NULL,
                    manifest_blob_sha TEXT NOT NULL,
                    manifest_commit_sha TEXT NOT NULL,
                    repo_head TEXT NOT NULL,
                    expected_host TEXT NOT NULL,
                    state TEXT NOT NULL,
                    boot_id TEXT,
                    pid INTEGER,
                    lease_epoch INTEGER NOT NULL DEFAULT 0,
                    lease_expires_monotonic REAL,
                    heartbeat_at_utc TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    yield_count INTEGER NOT NULL DEFAULT 0,
                    last_yield_reason TEXT,
                    first_queued_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    deadline_utc TEXT NOT NULL,
                    max_wall_seconds INTEGER NOT NULL,
                    max_provider_calls INTEGER NOT NULL DEFAULT 0,
                    max_cost_krw INTEGER NOT NULL DEFAULT 0,
                    provider_calls INTEGER NOT NULL DEFAULT 0,
                    cost_krw INTEGER NOT NULL DEFAULT 0,
                    cancel_requested_at TEXT,
                    exit_code INTEGER,
                    error_code TEXT,
                    error_detail_redacted TEXT,
                    result_dir TEXT,
                    result_bytes INTEGER,
                    ledger_schema_version INTEGER NOT NULL,
                    CHECK (state IN (
                        'queued', 'running', 'deferred', 'blocked',
                        'succeeded', 'failed', 'cancelled'
                    ))
                );
                CREATE INDEX IF NOT EXISTS jobs_claim_idx
                    ON jobs(state, first_queued_at, job_id);
                """
            )
            row = connection.execute(
                "SELECT value FROM runtime_meta WHERE key='ledger_schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO runtime_meta(key, value) VALUES(?, ?)",
                    ("ledger_schema_version", str(SCHEMA_VERSION)),
                )
            elif int(row["value"]) != SCHEMA_VERSION:
                raise RuntimeError("ledger_schema_version_mismatch")
            os.chmod(paths.ledger, 0o600)
            for suffix in ("-wal", "-shm"):
                sidecar = paths.ledger.with_name(paths.ledger.name + suffix)
                if sidecar.exists():
                    os.chmod(sidecar, 0o600)
        except Exception:
            connection.close()
            if not existed and paths.ledger.exists():
                paths.ledger.unlink(missing_ok=True)
            raise
        return cls(
            connection,
            event_writer=event_writer or EventWriter(paths.events),
        )

    def close(self) -> None:
        self._db.close()

    def _append_or_block(self, job_id: str, event: dict[str, object]) -> None:
        try:
            self._events.append(event)
        except EventWriteError:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    """
                    UPDATE jobs
                    SET state='blocked', error_code='event_append_failed'
                    WHERE job_id=?
                    """,
                    (job_id,),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
            raise

    def enqueue(self, spec: JobSpec, *, now: datetime) -> bool:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT spec_sha256 FROM jobs WHERE job_id=?",
                (spec.job_id,),
            ).fetchone()
            if row is not None:
                self._db.execute("COMMIT")
                if row["spec_sha256"] == spec.spec_sha256:
                    return False
                raise ValueError("job_spec_conflict")
            self._db.execute(
                """
                INSERT INTO jobs(
                    job_id, spec_sha256, spec_json, task_id, handler,
                    manifest_blob_sha, manifest_commit_sha, repo_head,
                    expected_host, state, first_queued_at, deadline_utc,
                    max_wall_seconds, max_provider_calls, max_cost_krw,
                    ledger_schema_version
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.job_id,
                    spec.spec_sha256,
                    spec.canonical_bytes.decode(),
                    spec.task_id,
                    spec.handler,
                    spec.manifest_blob_sha,
                    spec.manifest_commit_sha,
                    spec.repo_head,
                    spec.expected_host,
                    _iso(now),
                    _iso(spec.deadline),
                    spec.max_wall_seconds,
                    spec.max_provider_calls,
                    spec.max_cost_krw,
                    SCHEMA_VERSION,
                ),
            )
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        self._append_or_block(
            spec.job_id,
            {"job_id": spec.job_id, "state": JobState.QUEUED.value},
        )
        return True

    def claim(
        self,
        *,
        boot_id: str,
        pid: int,
        now_mono: float,
        now: datetime,
        lease_seconds: int,
    ) -> Claim | None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                """
                SELECT job_id FROM jobs
                WHERE state IN ('queued', 'deferred')
                  AND cancel_requested_at IS NULL
                ORDER BY first_queued_at, job_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                self._db.execute("COMMIT")
                return None
            cursor = self._db.execute(
                """
                UPDATE jobs
                SET state='running',
                    boot_id=?,
                    pid=?,
                    lease_epoch=lease_epoch+1,
                    lease_expires_monotonic=?,
                    heartbeat_at_utc=?,
                    attempt=attempt+1,
                    started_at=COALESCE(started_at, ?)
                WHERE job_id=? AND state IN ('queued', 'deferred')
                """,
                (
                    boot_id,
                    pid,
                    now_mono + lease_seconds,
                    _iso(now),
                    _iso(now),
                    row["job_id"],
                ),
            )
            if cursor.rowcount != 1:
                self._db.execute("ROLLBACK")
                return None
            claimed = self._db.execute(
                "SELECT job_id, lease_epoch, attempt FROM jobs WHERE job_id=?",
                (row["job_id"],),
            ).fetchone()
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        claim = Claim(
            job_id=claimed["job_id"],
            lease_epoch=claimed["lease_epoch"],
            attempt=claimed["attempt"],
        )
        self._append_or_block(
            claim.job_id,
            {
                "attempt": claim.attempt,
                "job_id": claim.job_id,
                "lease_epoch": claim.lease_epoch,
                "state": JobState.RUNNING.value,
            },
        )
        return claim

    def reclaim(
        self,
        job_id: str,
        *,
        expected_epoch: int,
        boot_id: str,
        pid: int,
    ) -> bool:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._db.execute(
                """
                UPDATE jobs
                SET boot_id=?, pid=?, lease_epoch=lease_epoch+1, attempt=attempt+1
                WHERE job_id=? AND state='running' AND lease_epoch=?
                """,
                (boot_id, pid, job_id, expected_epoch),
            )
            self._db.execute("COMMIT")
            changed = cursor.rowcount == 1
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        if changed:
            self._append_or_block(
                job_id,
                {
                    "event": "reclaimed",
                    "job_id": job_id,
                    "previous_lease_epoch": expected_epoch,
                },
            )
        return changed

    def heartbeat(
        self,
        job_id: str,
        *,
        expected_epoch: int,
        now_mono: float,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        cursor = self._db.execute(
            """
            UPDATE jobs
            SET heartbeat_at_utc=?, lease_expires_monotonic=?
            WHERE job_id=? AND state='running' AND lease_epoch=?
            """,
            (_iso(now), now_mono + lease_seconds, job_id, expected_epoch),
        )
        return cursor.rowcount == 1

    def transition(
        self,
        job_id: str,
        *,
        expected_epoch: int,
        target: JobState,
        now: datetime,
        exit_code: int | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        result_dir: str | None = None,
    ) -> bool:
        detail = error_detail[:512] if error_detail else None
        self._db.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._db.execute(
                """
                UPDATE jobs
                SET state=?, finished_at=?, exit_code=?, error_code=?,
                    error_detail_redacted=?, result_dir=?
                WHERE job_id=? AND state='running' AND lease_epoch=?
                """,
                (
                    target.value,
                    _iso(now),
                    exit_code,
                    error_code,
                    detail,
                    result_dir,
                    job_id,
                    expected_epoch,
                ),
            )
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        if cursor.rowcount != 1:
            return False
        self._append_or_block(
            job_id,
            {"job_id": job_id, "lease_epoch": expected_epoch, "state": target.value},
        )
        return True

    def request_cancel(self, job_id: str, *, now: datetime) -> bool:
        cursor = self._db.execute(
            """
            UPDATE jobs SET cancel_requested_at=COALESCE(cancel_requested_at, ?)
            WHERE job_id=? AND state IN ('queued','running','deferred')
            """,
            (_iso(now), job_id),
        )
        if cursor.rowcount:
            self._append_or_block(
                job_id,
                {"event": "cancel_requested", "job_id": job_id},
            )
        return cursor.rowcount == 1

    def get(self, job_id: str) -> JobRow | None:
        row = self._db.execute(
            """
            SELECT job_id, state, lease_epoch, attempt, cancel_requested_at,
                   spec_sha256
            FROM jobs WHERE job_id=?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return JobRow(
            job_id=row["job_id"],
            state=JobState(row["state"]),
            lease_epoch=row["lease_epoch"],
            attempt=row["attempt"],
            cancel_requested_at=row["cancel_requested_at"],
            spec_sha256=row["spec_sha256"],
        )

    def list_jobs(self) -> tuple[JobRow, ...]:
        rows = self._db.execute(
            """
            SELECT job_id, state, lease_epoch, attempt, cancel_requested_at,
                   spec_sha256
            FROM jobs ORDER BY first_queued_at, job_id
            """
        ).fetchall()
        return tuple(
            JobRow(
                job_id=row["job_id"],
                state=JobState(row["state"]),
                lease_epoch=row["lease_epoch"],
                attempt=row["attempt"],
                cancel_requested_at=row["cancel_requested_at"],
                spec_sha256=row["spec_sha256"],
            )
            for row in rows
        )

    def running_jobs(self) -> tuple[RunningJob, ...]:
        rows = self._db.execute(
            """
            SELECT job_id, boot_id, pid, lease_epoch, attempt
            FROM jobs WHERE state='running'
            ORDER BY first_queued_at, job_id
            """
        ).fetchall()
        return tuple(
            RunningJob(
                job_id=row["job_id"],
                boot_id=row["boot_id"],
                pid=row["pid"],
                lease_epoch=row["lease_epoch"],
                attempt=row["attempt"],
            )
            for row in rows
        )

    def execution_job(self, job_id: str) -> ExecutionJob | None:
        row = self._db.execute(
            """
            SELECT job_id, handler, spec_json, expected_host, repo_head,
                   deadline_utc, max_wall_seconds, lease_epoch, attempt,
                   cancel_requested_at
            FROM jobs WHERE job_id=? AND state='running'
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(row["spec_json"])
        return ExecutionJob(
            job_id=row["job_id"],
            handler=row["handler"],
            handler_args=dict(raw["handler_args"]),
            expected_host=row["expected_host"],
            repo_head=row["repo_head"],
            deadline=datetime.fromisoformat(row["deadline_utc"]),
            max_wall_seconds=row["max_wall_seconds"],
            lease_epoch=row["lease_epoch"],
            attempt=row["attempt"],
            cancel_requested_at=row["cancel_requested_at"],
        )

    def defer_next(self, *, now: datetime, reason: str) -> bool:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                """
                SELECT job_id, first_queued_at, yield_count
                FROM jobs
                WHERE state IN ('queued','deferred')
                ORDER BY first_queued_at, job_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                self._db.execute("COMMIT")
                return False
            first = datetime.fromisoformat(row["first_queued_at"])
            next_count = row["yield_count"] + 1
            blocked = next_count >= 12 or (now - first).total_seconds() >= 21600
            state = JobState.BLOCKED.value if blocked else JobState.DEFERRED.value
            self._db.execute(
                """
                UPDATE jobs
                SET state=?, yield_count=?, last_yield_reason=?,
                    finished_at=CASE WHEN ?='blocked' THEN ? ELSE finished_at END
                WHERE job_id=? AND state IN ('queued','deferred')
                """,
                (state, next_count, reason, state, _iso(now), row["job_id"]),
            )
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        self._append_or_block(
            row["job_id"],
            {
                "job_id": row["job_id"],
                "reason": reason,
                "state": state,
                "yield_count": next_count,
            },
        )
        return True

    def raw_spec(self, job_id: str) -> dict[str, object] | None:
        row = self._db.execute(
            "SELECT spec_json FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        return json.loads(row["spec_json"]) if row is not None else None
