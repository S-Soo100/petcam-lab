"""v2.7 C500G 준비 CLI (Task 10 부분) — `inventory` · `freeze-roles` · `roi-profile` · `pilot-select` · `pilot-extract`.

실행 예 (레포 루트, uv 환경):
  uv run python -m scripts.yolo26n_v27_c500g.cli inventory \
      --attempt storage/yolo26n-v27-c500g/attempts/2026-09-10-a1 \
      --local-root storage/rap-c500g-mirror \
      --night-start 2026-08-27 --night-end 2026-09-09 \
      --test-sheet-sha256 <TEST-SHEET sha256>
  uv run python -m scripts.yolo26n_v27_c500g.cli freeze-roles \
      --attempt storage/yolo26n-v27-c500g/attempts/2026-09-10-a1 \
      --freeze-manifest /path/detector-freeze.private.json \
      --freeze-cutoff-utc 2026-08-31T13:51:52Z --seed v27-role-freeze-v1 \
      --test-sheet-sha256 <TEST-SHEET sha256>

  uv run python -m scripts.yolo26n_v27_c500g.cli roi-profile --attempt <attempt> --tool-json roi-v1.json \
      --calibration-source recordings/camXX/night=…/<slot> … --test-sheet-sha256 <sha>
  uv run python -m scripts.yolo26n_v27_c500g.cli pilot-select --attempt <attempt> --seed v27-pilot-v1 --test-sheet-sha256 <sha>
  uv run python -m scripts.yolo26n_v27_c500g.cli pilot-extract --attempt <attempt> --source-root storage/rap-c500g-mirror \
      --which warmup|pilot --test-sheet-sha256 <sha>

콘솔에는 aggregate 요약만 찍는다. 원천·R2·DB 는 read-only, 파생물은 attempt 아래 0700/0600 새 파일로만.
카메라 키(cam01…)는 private artifact 에만 들어가며 콘솔·요약엔 digest 만 남는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from scripts.yolo26n_v27_c500g.contracts import WRITE_COUNT_FIELDS, FrameRequest, RoiProfile
from scripts.yolo26n_v27_c500g.inventory import _camera_digest as camera_digest
from scripts.yolo26n_v27_c500g.inventory import build_expected_slots, collect_inventory, inventory_public_summary
from scripts.yolo26n_v27_c500g.private_io import sha256_file, write_private_json_new
from scripts.yolo26n_v27_c500g.roi import ROI_NAMES, ROI_PROFILE_SCHEMA, profile_digest, validate_roi_profile
from scripts.yolo26n_v27_c500g.roles import freeze_roles
from scripts.yolo26n_v27_c500g.sampling import (
    extract_review_items,
    select_double_review,
    select_pilot_requests,
    summarize_selection,
)

DEFAULT_CAMERA_KEYS = ("cam01", "cam02", "cam03")
ROI_TOOL_SCHEMA = "c500g-roi-tool-v1"
DISH_TAGS_SCHEMA = "yolo26n-v27-c500g-dish-tags-v1"
PILOT_REQUESTS_SCHEMA = "yolo26n-v27-c500g-pilot-requests-v1"
DOUBLE_REVIEW_SCHEMA = "yolo26n-v27-c500g-double-review-v1"
_ZERO_WRITES = {field: 0 for field in WRITE_COUNT_FIELDS}


def run_inventory(*, local_root: Path, r2_reader, db_reader, attempt: Path, camera_keys: Sequence[str],
                  nights: Sequence[str], test_sheet_sha256: str) -> dict[str, object]:
    ledger = build_expected_slots(camera_keys, nights, test_sheet_sha256=test_sheet_sha256)
    inventory_dir = Path(attempt) / "inventory"
    write_private_json_new(inventory_dir / "expected-slots.private.json", ledger)
    inventory = collect_inventory(Path(local_root), r2_reader, db_reader, test_sheet_sha256=test_sheet_sha256, expected_slots=ledger)
    private_path = inventory_dir / "source-inventory.private.json"
    write_private_json_new(private_path, inventory)
    summary = inventory_public_summary(inventory)
    return {"inventory": inventory, "summary": summary, "private_path": private_path}


def run_freeze_roles(*, attempt: Path, freeze_manifest: Path, freeze_cutoff_utc: str | None, seed: str,
                     test_sheet_sha256: str) -> dict[str, object]:
    inventory = json.loads((Path(attempt) / "inventory" / "source-inventory.private.json").read_text(encoding="utf-8"))
    if inventory.get("test_sheet_sha256") != test_sheet_sha256:
        raise ValueError("inventory TEST-SHEET pin differs from the requested TEST-SHEET sha256")
    freeze_path = Path(freeze_manifest)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    mtime = datetime.fromtimestamp(freeze_path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
    result = freeze_roles(
        inventory, freeze, seed=seed, freeze_cutoff_utc=freeze_cutoff_utc,
        freeze_manifest_sha256=sha256_file(freeze_path), freeze_manifest_mtime_utc=mtime,
    )
    private_path = Path(attempt) / "roles" / "role-freeze.private.json"
    write_private_json_new(private_path, result)
    summary = {k: result[k] for k in ("schema", "status", "test_sheet_sha256", "seed", "freeze_cutoff_utc",
                                      "freeze_cutoff_source", "camera_night_counts", "date_blocks")}
    return {"status": result["status"], "summary": summary, "private_path": private_path}


def _read_private(path: Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _check_pin(doc: Mapping[str, object], test_sheet_sha256: str, what: str) -> None:
    if doc.get("test_sheet_sha256") != test_sheet_sha256:
        raise ValueError(f"{what} TEST-SHEET pin differs from the requested TEST-SHEET sha256")


def run_roi_profile(*, attempt: Path, tool_json: Path, label_map: Mapping[str, str], calibration_sources: Sequence[str],
                    test_sheet_sha256: str) -> dict[str, object]:
    """ROI 보정 도구(artifact db `roi/v1`) JSON → 검증된 roi-profile-v1. 검증이 다 통과해야 파일을 쓴다."""
    roles = _read_private(Path(attempt) / "roles" / "role-freeze.private.json")
    _check_pin(roles, test_sheet_sha256, "role manifest")
    tool = json.loads(Path(tool_json).read_text(encoding="utf-8"))
    if tool.get("schema") != ROI_TOOL_SCHEMA:
        raise ValueError(f"roi tool JSON schema must be {ROI_TOOL_SCHEMA}")
    tool_cameras = tool.get("cameras")
    if not isinstance(tool_cameras, Mapping):
        raise ValueError("roi tool JSON has no cameras")
    cameras: dict[str, dict[str, dict[str, float]]] = {}
    for label, camera_key in label_map.items():
        entry = tool_cameras.get(label)
        if not isinstance(entry, Mapping):
            raise ValueError(f"roi tool JSON has no camera label {label}")
        rects = entry.get("rects")
        if not isinstance(rects, Mapping) or set(rects) != set(ROI_NAMES):
            raise ValueError(f"camera label {label} must have exactly 3 rects named {ROI_NAMES}")
        if entry.get("day_verified") is not True:
            raise ValueError(f"camera label {label}: day_verified must be true (check the evening frame)")
        if entry.get("ir_verified") is not True:
            raise ValueError(f"camera label {label}: ir_verified must be true (check the IR frame)")
        cameras[camera_digest(camera_key)] = {
            name: {axis: float(rects[name][axis]) for axis in ("x1", "y1", "x2", "y2")} for name in ROI_NAMES
        }
    body: dict[str, object] = {
        "schema": ROI_PROFILE_SCHEMA, "status": "V27_ROI_PROFILE_READY", "test_sheet_sha256": test_sheet_sha256,
        "frame_width": int(tool["frame_width"]), "frame_height": int(tool["frame_height"]), "padding_px": int(tool["padding_px"]),
        "calibration_provenance": "v27_train", "day_verified": True, "ir_verified": True, "cameras": cameras, **_ZERO_WRITES,
    }
    body["profile_sha256"] = profile_digest(body)
    profile = validate_roi_profile(body, roles, calibration_sources=calibration_sources)
    roi_dir = Path(attempt) / "roi"
    private_path = roi_dir / "roi-profile.private.json"
    write_private_json_new(private_path, body)
    write_private_json_new(roi_dir / "roi-tool-input.private.json", {
        "tool": tool, "label_map": dict(label_map), "calibration_sources": list(calibration_sources),
    })
    summary = {
        "status": body["status"], "profile_sha256": body["profile_sha256"], "camera_count": len(cameras),
        "padding_px": body["padding_px"], "frame": [body["frame_width"], body["frame_height"]],
        "calibration_source_count": len(list(calibration_sources)),
    }
    return {"profile": profile, "summary": summary, "private_path": private_path}


def load_dish_tags(path: Path) -> dict[str, dict[str, object]]:
    """dish-tags-v1 원장 → {source_ref: {roi_name: food_in_dish(bool|None)}}."""
    doc = _read_private(Path(path))
    if doc.get("schema") != DISH_TAGS_SCHEMA:
        raise ValueError(f"dish tags ledger schema must be {DISH_TAGS_SCHEMA} (dish-tags-v1)")
    tags: dict[str, dict[str, object]] = {}
    for entry in doc.get("entries", []):  # type: ignore[union-attr]
        tags.setdefault(str(entry["source_ref"]), {})[str(entry["roi_name"])] = entry.get("food_in_dish")
    return tags


def run_pilot_select(*, attempt: Path, seed: str, target: int = 600, warmup: int = 27, test_sheet_sha256: str,
                     dish_tags_path: Path | None = None) -> dict[str, object]:
    """train-only 파일럿 + 워밍업(파일럿과 소스 disjoint) 요청 목록 → attempt/pilot/pilot-requests.private.json."""
    root = Path(attempt)
    inventory = _read_private(root / "inventory" / "source-inventory.private.json")
    roles = _read_private(root / "roles" / "role-freeze.private.json")
    profile_doc = _read_private(root / "roi" / "roi-profile.private.json")
    for doc, what in ((inventory, "inventory"), (roles, "role manifest"), (profile_doc, "ROI profile")):
        _check_pin(doc, test_sheet_sha256, what)
    profile = RoiProfile.from_json(profile_doc)
    dish_path = Path(dish_tags_path) if dish_tags_path else root / "dish" / "dish-tags-v1.private.json"
    dish_tags = load_dish_tags(dish_path) if dish_path.exists() else None
    pilot = select_pilot_requests(inventory, roles, profile, target=target, seed=seed, dish_tags=dish_tags)
    warm = (
        select_pilot_requests(inventory, roles, profile, target=warmup, seed=f"{seed}|warmup", dish_tags=None,
                              exclude_sources={r.source_ref for r in pilot})
        if warmup else []
    )
    summary = {"pilot": summarize_selection(pilot, dish_tags=dish_tags), "warmup": summarize_selection(warm, dish_tags=dish_tags)}
    doc = {
        "schema": PILOT_REQUESTS_SCHEMA, "status": "PILOT_REQUESTS_READY", "test_sheet_sha256": test_sheet_sha256,
        "seed": seed, "target": int(target), "warmup": int(warmup), "roi_profile_sha256": profile.profile_sha256,
        "dish_tags_used": dish_tags is not None, "requests": [r.to_json() for r in pilot],
        "warmup_requests": [r.to_json() for r in warm], "summary": summary, **_ZERO_WRITES,
    }
    private_path = root / "pilot" / "pilot-requests.private.json"
    write_private_json_new(private_path, doc)
    return {"status": doc["status"], "summary": summary, "private_path": private_path}


def run_pilot_extract(*, attempt: Path, source_root: Path, which: str, test_sheet_sha256: str, double_review_count: int = 60,
                      capture_factory=None, jpeg_quality: int = 95) -> dict[str, object]:
    """요청 목록의 프레임을 미러 영상에서 decode → 익명 ZIP·lineage → (pilot 만) double-review 목록."""
    if which not in ("pilot", "warmup"):
        raise ValueError("which must be 'pilot' or 'warmup'")
    root = Path(attempt)
    doc = _read_private(root / "pilot" / "pilot-requests.private.json")
    profile_doc = _read_private(root / "roi" / "roi-profile.private.json")
    _check_pin(doc, test_sheet_sha256, "pilot requests")
    _check_pin(profile_doc, test_sheet_sha256, "ROI profile")
    profile = RoiProfile.from_json(profile_doc)
    if doc.get("roi_profile_sha256") != profile.profile_sha256:
        raise ValueError("pilot requests were selected against a different ROI profile")
    key = "requests" if which == "pilot" else "warmup_requests"
    requests = [FrameRequest.from_json(r) for r in doc[key]]  # type: ignore[index]
    out_dir = root / "pilot" / which
    result = extract_review_items(
        requests, Path(source_root), profile, out_dir, seed=str(doc["seed"]), sequence_prefix="P" if which == "pilot" else "W",
        capture_factory=capture_factory, jpeg_quality=jpeg_quality,
    )
    if which == "pilot":
        chosen = select_double_review(result["queue"]["items"], count=double_review_count)  # type: ignore[index]
        write_private_json_new(out_dir / "double-review.private.json", {
            "schema": DOUBLE_REVIEW_SCHEMA, "status": "DOUBLE_REVIEW_READY", "test_sheet_sha256": test_sheet_sha256,
            "count": len(chosen), "anonymous_sequences": chosen, **_ZERO_WRITES,
        })
        result["double_review"] = chosen
    return result


def _parse_label_map(raw: str) -> dict[str, str]:
    pairs = [item.strip() for item in raw.split(",") if item.strip()]
    mapping: dict[str, str] = {}
    for pair in pairs:
        label, _, camera_key = pair.partition("=")
        if not label or not camera_key:
            raise ValueError("--label-map expects A=cam01,B=cam02,C=cam03")
        mapping[label.strip()] = camera_key.strip()
    return mapping


def _nights_between(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError("--night-end must not precede --night-start")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def env_file_path() -> Path:
    """자격증명 .env 위치: `PETCAM_ENV_FILE` 이 있으면 그 파일, 없으면 레포 루트 .env (worktree 엔 .env 가 없어서 필요)."""
    override = os.environ.get("PETCAM_ENV_FILE")
    return Path(override) if override else Path(__file__).resolve().parents[2] / ".env"


def _real_readers(bucket: str):
    """실제 R2(boto3)·DB(supabase) read-only 어댑터. 자격증명은 .env 에서만 읽고 출력하지 않는다."""
    from dotenv import load_dotenv

    load_dotenv(env_file_path())
    import boto3
    from supabase import create_client

    from scripts.yolo26n_v27_c500g.readers import ProductionDbReader, ReadOnlyR2

    client = boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT"], aws_access_key_id=os.environ["R2_C500G_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_C500G_SECRET_ACCESS_KEY"], region_name="auto",
    )
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    return ReadOnlyR2(client, bucket=bucket), ProductionDbReader(sb.table("rap_c500g_recordings"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yolo26n_v27_c500g", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="read-only 3계층 inventory → attempt/inventory/*.private.json")
    inv.add_argument("--attempt", required=True)
    inv.add_argument("--local-root", required=True, help="미러 루트 (그 아래 recordings/…)")
    inv.add_argument("--night-start", required=True)
    inv.add_argument("--night-end", required=True)
    inv.add_argument("--test-sheet-sha256", required=True)
    inv.add_argument("--camera-keys", default=os.environ.get("RAP_C500G_CAMERA_KEYS", ",".join(DEFAULT_CAMERA_KEYS)))
    inv.add_argument("--bucket", default=os.environ.get("R2_C500G_BUCKET", "c500g"))

    fr = sub.add_parser("freeze-roles", help="metadata-only 역할 동결 → attempt/roles/role-freeze.private.json")
    fr.add_argument("--attempt", required=True)
    fr.add_argument("--freeze-manifest", required=True)
    fr.add_argument("--freeze-cutoff-utc", default=None)
    fr.add_argument("--seed", required=True)
    fr.add_argument("--test-sheet-sha256", required=True)

    rp = sub.add_parser("roi-profile", help="ROI 보정 도구 JSON → attempt/roi/roi-profile.private.json (검증 통과 시에만)")
    rp.add_argument("--attempt", required=True)
    rp.add_argument("--tool-json", required=True, help="artifact db roi/v1 문서를 저장한 JSON")
    rp.add_argument("--label-map", default="A=cam01,B=cam02,C=cam03")
    rp.add_argument("--calibration-source", action="append", default=[], help="보정에 연 프레임의 source_ref (반복 가능)")
    rp.add_argument("--test-sheet-sha256", required=True)

    ps = sub.add_parser("pilot-select", help="train-only 파일럿·워밍업 요청 선택 → attempt/pilot/pilot-requests.private.json")
    ps.add_argument("--attempt", required=True)
    ps.add_argument("--seed", required=True)
    ps.add_argument("--target", type=int, default=600)
    ps.add_argument("--warmup", type=int, default=27)
    ps.add_argument("--dish-tags", default=None, help="dish-tags-v1 원장 (기본: attempt/dish/dish-tags-v1.private.json 있으면 사용)")
    ps.add_argument("--test-sheet-sha256", required=True)

    pe = sub.add_parser("pilot-extract", help="요청 프레임 decode → attempt/pilot/<which>/review-queue.zip + lineage")
    pe.add_argument("--attempt", required=True)
    pe.add_argument("--source-root", required=True, help="미러 루트 (그 아래 recordings/…)")
    pe.add_argument("--which", choices=("pilot", "warmup"), required=True)
    pe.add_argument("--double-review-count", type=int, default=60)
    pe.add_argument("--jpeg-quality", type=int, default=95)
    pe.add_argument("--test-sheet-sha256", required=True)

    args = parser.parse_args(argv)
    if args.command == "inventory":
        r2_reader, db_reader = _real_readers(args.bucket)
        out = run_inventory(
            local_root=Path(args.local_root), r2_reader=r2_reader, db_reader=db_reader, attempt=Path(args.attempt),
            camera_keys=[k.strip() for k in args.camera_keys.split(",") if k.strip()],
            nights=_nights_between(args.night_start, args.night_end), test_sheet_sha256=args.test_sheet_sha256,
        )
        print(json.dumps({"status": out["inventory"]["status"], **out["summary"]}, ensure_ascii=False, sort_keys=True))
        return 0 if out["inventory"]["status"] == "V27_SOURCE_INVENTORY_READY" else 1
    if args.command == "freeze-roles":
        out = run_freeze_roles(
            attempt=Path(args.attempt), freeze_manifest=Path(args.freeze_manifest), freeze_cutoff_utc=args.freeze_cutoff_utc,
            seed=args.seed, test_sheet_sha256=args.test_sheet_sha256,
        )
        print(json.dumps(out["summary"], ensure_ascii=False, sort_keys=True))
        return 0 if out["status"] == "V27_ROLE_FREEZE_READY" else 1
    if args.command == "roi-profile":
        out = run_roi_profile(
            attempt=Path(args.attempt), tool_json=Path(args.tool_json), label_map=_parse_label_map(args.label_map),
            calibration_sources=list(args.calibration_source), test_sheet_sha256=args.test_sheet_sha256,
        )
        print(json.dumps(out["summary"], ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "pilot-select":
        out = run_pilot_select(
            attempt=Path(args.attempt), seed=args.seed, target=args.target, warmup=args.warmup,
            test_sheet_sha256=args.test_sheet_sha256, dish_tags_path=Path(args.dish_tags) if args.dish_tags else None,
        )
        print(json.dumps({"status": out["status"], **out["summary"]}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "pilot-extract":
        out = run_pilot_extract(
            attempt=Path(args.attempt), source_root=Path(args.source_root), which=args.which,
            test_sheet_sha256=args.test_sheet_sha256, double_review_count=args.double_review_count, jpeg_quality=args.jpeg_quality,
        )
        print(json.dumps(out["report"], ensure_ascii=False, sort_keys=True))
        return 0 if out["report"]["status"] == "REVIEW_QUEUE_READY" else 1
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
