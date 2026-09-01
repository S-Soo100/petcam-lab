"""RAP C500G manager의 secret-free SQLite 설정·상태 원장."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.rap_c500g_types import CAMERA_KEYS


TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_plan_values(
    *,
    start_local: str,
    end_local: str,
    selected_cameras: Sequence[str],
    volume_name: str,
    max_capture_retries: int,
) -> tuple[str, ...]:
    if not TIME_PATTERN.fullmatch(start_local) or not TIME_PATTERN.fullmatch(end_local):
        raise ValueError("schedule time must use HH:MM")
    cameras = tuple(selected_cameras)
    if not cameras or len(set(cameras)) != len(cameras):
        raise ValueError("selected cameras must be non-empty and unique")
    if any(camera not in CAMERA_KEYS for camera in cameras):
        raise ValueError("selected cameras contain an unknown camera")
    if not volume_name or Path(volume_name).name != volume_name or volume_name in {".", ".."}:
        raise ValueError("volume name must be a safe basename")
    if not isinstance(max_capture_retries, int) or not 0 <= max_capture_retries <= 5:
        raise ValueError("max capture retries must be between 0 and 5")
    return cameras


@dataclass(frozen=True, slots=True)
class ManagerPlan:
    revision: int
    start_local: str
    end_local: str
    selected_cameras: tuple[str, ...]
    volume_name: str
    max_capture_retries: int
    saved_at: str
    applied_at: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_cameras"] = list(self.selected_cameras)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ManagerPlan":
        return cls(
            revision=int(payload["revision"]),
            start_local=str(payload["start_local"]),
            end_local=str(payload["end_local"]),
            selected_cameras=tuple(str(item) for item in payload["selected_cameras"]),
            volume_name=str(payload["volume_name"]),
            max_capture_retries=int(payload["max_capture_retries"]),
            saved_at=str(payload["saved_at"]),
            applied_at=(str(payload["applied_at"]) if payload.get("applied_at") else None),
        )


@dataclass(frozen=True, slots=True)
class CameraRuntimeState:
    camera_key: str
    ip: str
    probe_state: str
    capture_state: str
    retry_count: int
    file_bytes: int
    file_growing: bool
    last_frame_at: str | None
    error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CameraRuntimeState":
        return cls(
            camera_key=str(payload["camera_key"]),
            ip=str(payload["ip"]),
            probe_state=str(payload["probe_state"]),
            capture_state=str(payload["capture_state"]),
            retry_count=int(payload["retry_count"]),
            file_bytes=int(payload["file_bytes"]),
            file_growing=bool(payload["file_growing"]),
            last_frame_at=(
                str(payload["last_frame_at"]) if payload.get("last_frame_at") else None
            ),
            error_code=(str(payload["error_code"]) if payload.get("error_code") else None),
        )


@dataclass(frozen=True, slots=True)
class ManagerSnapshot:
    manager_state: str
    updated_at: str
    current_slot: str | None
    next_slot: str | None
    volume: Mapping[str, Any]
    cameras: Mapping[str, CameraRuntimeState]
    recent_completed: tuple[Mapping[str, Any], ...]
    incidents: tuple[Mapping[str, Any], ...]
    sync: Mapping[str, Any]
    schema_version: str = "rap-c500g-manager-status/v1"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manager_state": self.manager_state,
            "updated_at": self.updated_at,
            "current_slot": self.current_slot,
            "next_slot": self.next_slot,
            "volume": dict(self.volume),
            "cameras": {
                key: camera.to_dict() for key, camera in sorted(self.cameras.items())
            },
            "recent_completed": [dict(item) for item in self.recent_completed],
            "incidents": [dict(item) for item in self.incidents],
            "sync": dict(self.sync),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ManagerSnapshot":
        cameras = {
            str(key): CameraRuntimeState.from_dict(value)
            for key, value in dict(payload.get("cameras", {})).items()
        }
        return cls(
            schema_version=str(
                payload.get("schema_version", "rap-c500g-manager-status/v1")
            ),
            manager_state=str(payload["manager_state"]),
            updated_at=str(payload["updated_at"]),
            current_slot=(str(payload["current_slot"]) if payload.get("current_slot") else None),
            next_slot=(str(payload["next_slot"]) if payload.get("next_slot") else None),
            volume=dict(payload.get("volume", {})),
            cameras=cameras,
            recent_completed=tuple(
                dict(item) for item in payload.get("recent_completed", [])
            ),
            incidents=tuple(dict(item) for item in payload.get("incidents", [])),
            sync=dict(payload.get("sync", {})),
        )


class ManagerStore:
    """작은 single-process manager용 SQLite store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS manager_plan (
                    slot TEXT PRIMARY KEY CHECK (slot IN ('active', 'pending')),
                    revision INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manager_snapshot (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manager_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manager_capture_claim (
                    slot_start TEXT NOT NULL,
                    camera_key TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    payload TEXT,
                    PRIMARY KEY (slot_start, camera_key)
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(manager_capture_claim)"
                ).fetchall()
            }
            if "status" not in columns:
                connection.execute(
                    "ALTER TABLE manager_capture_claim "
                    "ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
                )
            if "payload" not in columns:
                connection.execute(
                    "ALTER TABLE manager_capture_claim ADD COLUMN payload TEXT"
                )
            existing = connection.execute(
                "SELECT 1 FROM manager_plan WHERE slot = 'active'"
            ).fetchone()
            if existing is None:
                now = _utc_now()
                default = ManagerPlan(
                    revision=0,
                    start_local="20:00",
                    end_local="08:00",
                    selected_cameras=("cam01", "cam02", "cam03"),
                    volume_name="RAP-C500G",
                    max_capture_retries=3,
                    saved_at=now,
                    applied_at=now,
                )
                connection.execute(
                    "INSERT INTO manager_plan(slot, revision, payload) VALUES('active', ?, ?)",
                    (default.revision, json.dumps(default.to_dict(), sort_keys=True)),
                )

    def _load_plan_slot(self, slot: str) -> ManagerPlan | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM manager_plan WHERE slot = ?", (slot,)
            ).fetchone()
        if row is None:
            return None
        return ManagerPlan.from_dict(json.loads(row[0]))

    def load_plan(self) -> ManagerPlan:
        plan = self._load_plan_slot("active")
        if plan is None:
            raise RuntimeError("active manager plan is missing")
        return plan

    def load_pending_plan(self) -> ManagerPlan | None:
        return self._load_plan_slot("pending")

    def save_pending_plan(
        self,
        *,
        start_local: str,
        end_local: str,
        selected_cameras: Sequence[str],
        volume_name: str,
        max_capture_retries: int,
    ) -> ManagerPlan:
        cameras = _validate_plan_values(
            start_local=start_local,
            end_local=end_local,
            selected_cameras=selected_cameras,
            volume_name=volume_name,
            max_capture_retries=max_capture_retries,
        )
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM manager_plan"
            ).fetchone()
            revision = int(row[0]) + 1
            pending = ManagerPlan(
                revision=revision,
                start_local=start_local,
                end_local=end_local,
                selected_cameras=cameras,
                volume_name=volume_name,
                max_capture_retries=max_capture_retries,
                saved_at=_utc_now(),
                applied_at=None,
            )
            connection.execute(
                "INSERT OR REPLACE INTO manager_plan(slot, revision, payload) VALUES('pending', ?, ?)",
                (revision, json.dumps(pending.to_dict(), sort_keys=True)),
            )
        return pending

    def apply_pending_plan(self) -> ManagerPlan:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM manager_plan WHERE slot = 'pending'"
            ).fetchone()
            if row is None:
                connection.rollback()
                return self.load_plan()
            pending = ManagerPlan.from_dict(json.loads(row[0]))
            applied = ManagerPlan(
                revision=pending.revision,
                start_local=pending.start_local,
                end_local=pending.end_local,
                selected_cameras=pending.selected_cameras,
                volume_name=pending.volume_name,
                max_capture_retries=pending.max_capture_retries,
                saved_at=pending.saved_at,
                applied_at=_utc_now(),
            )
            connection.execute(
                "INSERT OR REPLACE INTO manager_plan(slot, revision, payload) VALUES('active', ?, ?)",
                (applied.revision, json.dumps(applied.to_dict(), sort_keys=True)),
            )
            connection.execute("DELETE FROM manager_plan WHERE slot = 'pending'")
            connection.commit()
        return applied

    def write_snapshot(self, snapshot: ManagerSnapshot) -> None:
        payload = json.dumps(snapshot.to_public_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO manager_snapshot(id, payload) VALUES(1, ?)",
                (payload,),
            )

    def read_snapshot(self) -> ManagerSnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM manager_snapshot WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return ManagerSnapshot.from_dict(json.loads(row[0]))

    def append_event(self, kind: str, payload: Mapping[str, Any]) -> None:
        if not kind or len(kind) > 80:
            raise ValueError("event kind is invalid")
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO manager_event(kind, payload, created_at) VALUES(?, ?, ?)",
                (kind, json.dumps(dict(payload), sort_keys=True), _utc_now()),
            )

    def claim_capture(self, slot_start: str, camera_key: str) -> bool:
        if camera_key not in CAMERA_KEYS or not slot_start:
            raise ValueError("capture claim is invalid")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO manager_capture_claim(
                    slot_start, camera_key, claimed_at, status
                ) VALUES(?, ?, ?, 'running')
                """,
                (slot_start, camera_key, _utc_now()),
            )
            return cursor.rowcount == 1

    def mark_capture_claim(
        self,
        slot_start: str,
        camera_key: str,
        status: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if status not in {"running", "finalizing", "completed", "terminal"}:
            raise ValueError("capture claim status is invalid")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE manager_capture_claim "
                "SET status = ?, payload = COALESCE(?, payload) "
                "WHERE slot_start = ? AND camera_key = ?",
                (
                    status,
                    json.dumps(dict(payload), sort_keys=True) if payload else None,
                    slot_start,
                    camera_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("capture claim is missing")

    def release_capture_claim(self, slot_start: str, camera_key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM manager_capture_claim "
                "WHERE slot_start = ? AND camera_key = ?",
                (slot_start, camera_key),
            )

    def release_unfinished_claims(self) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM manager_capture_claim "
                "WHERE status = 'running'"
            )
            return int(cursor.rowcount)

    def read_capture_claims(
        self, *, statuses: set[str] | None = None
    ) -> set[tuple[str, str]]:
        with self._lock, self._connect() as connection:
            if statuses is None:
                rows = connection.execute(
                    "SELECT slot_start, camera_key FROM manager_capture_claim"
                ).fetchall()
            else:
                allowed = {"running", "finalizing", "completed", "terminal"}
                if not statuses or not statuses <= allowed:
                    raise ValueError("capture claim statuses are invalid")
                placeholders = ",".join("?" for _ in statuses)
                rows = connection.execute(
                    "SELECT slot_start, camera_key FROM manager_capture_claim "
                    f"WHERE status IN ({placeholders})",
                    tuple(sorted(statuses)),
                ).fetchall()
        return {(str(slot), str(camera)) for slot, camera in rows}

    def read_finalizing_claims(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT slot_start, camera_key, payload "
                "FROM manager_capture_claim WHERE status = 'finalizing'"
            ).fetchall()
        records: list[dict[str, Any]] = []
        for slot, camera, payload in rows:
            if not payload:
                continue
            records.append(
                {
                    "slot_start": str(slot),
                    "camera_key": str(camera),
                    "payload": json.loads(payload),
                }
            )
        return records

    def read_completed_claims(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT slot_start, camera_key, payload "
                "FROM manager_capture_claim WHERE status = 'completed'"
            ).fetchall()
        return [
            {
                "slot_start": str(slot),
                "camera_key": str(camera),
                "payload": json.loads(payload) if payload else {},
            }
            for slot, camera, payload in rows
        ]

    def read_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("event limit must be between 1 and 100")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT kind, payload, created_at FROM manager_event ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"kind": kind, "payload": json.loads(payload), "created_at": created_at}
            for kind, payload, created_at in rows
        ]
