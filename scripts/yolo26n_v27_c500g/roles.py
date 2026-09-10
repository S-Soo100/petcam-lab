"""Task 3 — metadata-only camera-night role freeze와 v2.6 sealed holdout reservation.

입력은 inventory(레코드 = 30분 번들)와 v2.6 freeze 매니페스트뿐이고 파일을 열지 않는다.
owner 승인(2026-09-10, decision-gate 2차):
- holdout = freeze cutoff 이후 첫 3 complete camera-night(정렬 = 첫 슬롯 UTC, 카메라 digest).
- 같은 날짜의 나머지 camera-night 는 `v26_holdout_date_guard`.
- 나머지는 v2.7 dev. 불완비 camera-night 는 `v27_train` 전용. validation 은 세 카메라가 모두 완비된 날짜 블록에서만.
- 실제 `yolo26n-v26-detector-freeze-v1` 파일엔 cutoff 필드가 없으므로 명시 cutoff 를 받아 근거와 함께 기록한다.

왜 완비 판정을 여기서 다시 하나: inventory 는 완비 camera-night 의 *개수*만 내고 어느 밤인지 주지 않는다.
같은 규칙(20:00~07:30 KST 30분 그리드 24슬롯)을 메타데이터만으로 재계산해 두 계산이 어긋나면 감사에서 드러나게 둔다.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

ROLE_FREEZE_SCHEMA = "yolo26n-v27-c500g-role-freeze-v1"
READY = "V27_ROLE_FREEZE_READY"
HOLDOUT_SHORTAGE = "V26_HOLDOUT_SHORTAGE"
VAL_SHORTAGE = "V27_VAL_SHORTAGE"

INVENTORY_SCHEMA = "yolo26n-v27-c500g-source-inventory-v1"
INVENTORY_READY = "V27_SOURCE_INVENTORY_READY"
TEACHER_FREEZE_SCHEMA = "yolo26n-v26-teacher-freeze-v1"
DETECTOR_FREEZE_SCHEMA = "yolo26n-v26-detector-freeze-v1"

ROLE_HOLDOUT = "v26_holdout"
ROLE_GUARD = "v26_holdout_date_guard"
ROLE_TRAIN = "v27_train"
ROLE_VAL = "v27_val"

HOLDOUT_CAMERA_NIGHTS = 3
MIN_DEV_DATE_BLOCKS = 3
VAL_FRACTION = 0.2
SLOTS_PER_NIGHT = 24
KST = ZoneInfo("Asia/Seoul")
ZERO_WRITES = {"db_write_count": 0, "r2_write_count": 0, "service_write_count": 0, "git_write_count": 0}


class PixelAccessDenied(PermissionError):
    """role 이 허용되지 않은 source 의 pixel 접근 (holdout·guard 등)."""


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be canonical UTC ending in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _night_date(start: datetime) -> str:
    """20:00~07:59 KST 를 한 밤으로: 시작 시각(KST) 에서 12시간을 빼 날짜를 잡는다."""
    return (start.astimezone(KST) - timedelta(hours=12)).date().isoformat()


def _canonical_slots(night_date: str) -> tuple[str, ...]:
    base = datetime.fromisoformat(night_date).replace(tzinfo=KST) + timedelta(hours=20)
    return tuple(
        (base + timedelta(minutes=30 * i)).astimezone(UTC).isoformat().replace("+00:00", "Z")
        for i in range(SLOTS_PER_NIGHT)
    )


def _resolve_cutoff(v26_freeze: Mapping[str, object], freeze_cutoff_utc: str | None,
                    freeze_manifest_sha256: str | None, freeze_manifest_mtime_utc: str | None) -> tuple[str, dict]:
    schema = v26_freeze.get("schema")
    if schema == TEACHER_FREEZE_SCHEMA:
        manifest_cutoff = v26_freeze.get("freeze_cutoff_utc")
        if not isinstance(manifest_cutoff, str):
            raise ValueError("teacher freeze manifest lacks freeze_cutoff_utc (cutoff)")
        if freeze_cutoff_utc is not None and freeze_cutoff_utc != manifest_cutoff:
            raise ValueError("explicit cutoff differs from manifest freeze_cutoff_utc")
        _parse_utc(manifest_cutoff, "freeze_cutoff_utc")
        return manifest_cutoff, {"origin": "manifest", "freeze_schema": schema}
    if schema == DETECTOR_FREEZE_SCHEMA:
        if freeze_cutoff_utc is None:
            raise ValueError("detector freeze manifest has no cutoff; explicit freeze_cutoff_utc is required")
        _parse_utc(freeze_cutoff_utc, "freeze_cutoff_utc")
        return freeze_cutoff_utc, {
            "origin": "explicit",
            "freeze_schema": schema,
            "checkpoint_sha256": v26_freeze.get("checkpoint_sha256"),
            "freeze_manifest_sha256": freeze_manifest_sha256,
            "freeze_manifest_mtime_utc": freeze_manifest_mtime_utc,
        }
    raise ValueError(f"unsupported v2.6 freeze schema: {schema!r}")


def freeze_roles(
    inventory: Mapping[str, object],
    v26_freeze: Mapping[str, object],
    *,
    seed: str,
    freeze_cutoff_utc: str | None = None,
    freeze_manifest_sha256: str | None = None,
    freeze_manifest_mtime_utc: str | None = None,
) -> dict[str, object]:
    if inventory.get("schema") != INVENTORY_SCHEMA or inventory.get("status") != INVENTORY_READY:
        raise ValueError("inventory must be a READY source inventory before role freeze")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be a non-empty string")
    cutoff_text, cutoff_source = _resolve_cutoff(v26_freeze, freeze_cutoff_utc, freeze_manifest_sha256, freeze_manifest_mtime_utc)
    cutoff = _parse_utc(cutoff_text, "freeze_cutoff_utc")

    # camera-night 별 집계 (메타데이터만)
    groups: dict[str, dict] = {}
    for record in inventory.get("records", []):
        start = _parse_utc(record["scheduled_start_utc"], "scheduled_start_utc")
        night = _night_date(start)
        key = str(record["camera_night"])
        group = groups.setdefault(key, {
            "camera_night": key, "camera": str(record["anonymous_camera_digest"]), "night_date": night,
            "starts": set(), "first_start": start, "records": [],
        })
        if group["night_date"] != night:
            raise ValueError("camera_night groups records from different nights")
        group["starts"].add(record["scheduled_start_utc"])
        group["first_start"] = min(group["first_start"], start)
        group["records"].append(record)
    for group in groups.values():
        # inventory v1.1: 레코드 complete_slot(늦은 시작·짧은 길이면 false)이 하나라도 false 면 불완비. 필드 없으면 v1.0 호환으로 true.
        slots_complete = all(record.get("complete_slot", True) is True for record in group["records"])
        group["complete"] = slots_complete and group["starts"] == set(_canonical_slots(group["night_date"]))
        group["after_freeze"] = group["first_start"] > cutoff

    # 1) holdout: cutoff 이후 complete 를 (첫 슬롯 UTC, 카메라) 순으로 3개
    eligible = sorted(
        (g for g in groups.values() if g["complete"] and g["after_freeze"]),
        key=lambda g: (g["first_start"], g["camera"]),
    )
    holdout = eligible[:HOLDOUT_CAMERA_NIGHTS]
    holdout_keys = {g["camera_night"] for g in holdout}
    holdout_dates = {g["night_date"] for g in holdout}
    status = READY if len(holdout) == HOLDOUT_CAMERA_NIGHTS else HOLDOUT_SHORTAGE

    # 2) date guard: holdout 날짜의 나머지 camera-night
    role_of: dict[str, str] = {}
    for g in groups.values():
        if g["camera_night"] in holdout_keys:
            role_of[g["camera_night"]] = ROLE_HOLDOUT
        elif g["night_date"] in holdout_dates:
            role_of[g["camera_night"]] = ROLE_GUARD

    # 3) dev: 날짜 블록 → validation 은 세 카메라 모두 complete 인 날짜에서만, seed 로 결정론 선택
    dev = [g for g in groups.values() if g["camera_night"] not in role_of]
    by_date: dict[str, list[dict]] = defaultdict(list)
    for g in dev:
        by_date[g["night_date"]].append(g)
    blocks = sorted(d for d, gs in by_date.items() if any(g["complete"] for g in gs))
    fully_complete = sorted(d for d, gs in by_date.items() if gs and all(g["complete"] for g in gs))
    val_dates: list[str] = []
    if len(blocks) < MIN_DEV_DATE_BLOCKS or not fully_complete:
        if status == READY:
            status = VAL_SHORTAGE
    else:
        k = max(1, round(len(fully_complete) * VAL_FRACTION))
        ranked = sorted(fully_complete, key=lambda d: hashlib.sha256(f"{seed}|{d}".encode()).hexdigest())
        val_dates = sorted(ranked[:k])
    for g in dev:
        role_of[g["camera_night"]] = ROLE_VAL if g["night_date"] in val_dates else ROLE_TRAIN

    rows = []
    for g in groups.values():
        for record in g["records"]:
            rows.append({
                "source_ref": record["source_ref"],
                "source_sha256": record["source_sha256"],
                "anonymous_camera_digest": g["camera"],
                "camera_night": g["camera_night"],
                "night_date": g["night_date"],
                "scheduled_start_utc": record["scheduled_start_utc"],
                "role": role_of[g["camera_night"]],
                "complete": g["complete"],
                "starts_after_v26_freeze": g["after_freeze"],
            })
    rows.sort(key=lambda r: (r["night_date"], r["anonymous_camera_digest"], r["scheduled_start_utc"]))

    counts: dict[str, int] = defaultdict(int)
    for g in groups.values():
        counts[role_of[g["camera_night"]]] += 1
    return {
        "schema": ROLE_FREEZE_SCHEMA,
        "status": status,
        "test_sheet_sha256": inventory.get("test_sheet_sha256"),
        "seed": seed,
        "freeze_cutoff_utc": cutoff_text,
        "freeze_cutoff_source": cutoff_source,
        "camera_night_counts": {role: counts.get(role, 0) for role in (ROLE_HOLDOUT, ROLE_GUARD, ROLE_TRAIN, ROLE_VAL)},
        "date_blocks": {
            "holdout": sorted(holdout_dates),
            "train": sorted(d for d in by_date if d not in val_dates),
            "val": val_dates,
        },
        "rows": rows,
        **ZERO_WRITES,
    }


def assert_pixel_access_allowed(role_manifest: Mapping[str, object], source_ref: str, allowed_roles: Sequence[str]) -> None:
    for row in role_manifest.get("rows", []):
        if row.get("source_ref") == source_ref:
            if row.get("role") in set(allowed_roles):
                return
            raise PixelAccessDenied(f"source role {row.get('role')!r} is not in allowed roles")
    raise PixelAccessDenied("source_ref is not in the role freeze manifest")
