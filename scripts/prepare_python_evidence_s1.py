"""Python Evidence S1 throughput-benchmark — 사전등록(preparation) 스크립트.

## 무엇을 하나
production DB 를 **read-only(SELECT only)** 로 읽어 두 산출물을 **결정론적으로** 만든다:
  1. `sample_manifest.json` — 32-clip covered-subset workload (+ 16-clip 축소 subset).
  2. `influx_snapshot.json` — 최근 7일 유입량 (projected 4-camera p95).

이 산출물은 벤치마크 실행 전에 **동결**되며, TEST-SHEET 가 두 파일의 해시를 박아둔다.

## 왜 순수 함수 + 주입인가
선택/집계 로직(`eligible_from_rows`, `select_workload`, `compute_influx`)은 Supabase 없이
dict fixture 로 테스트한다(TS 의 dependency injection 과 같은 개념 — DB 클라이언트를 주입).
`main()` 만 실제 클라이언트를 lazy import 한다.

## 하드 계약 (plan Global Constraints / Frozen workload)
  - DB 는 SELECT 만. mutation/RPC 금지 → 이 파일 정적 소스에 write 메서드가 없어야 한다.
  - camera allowlist = covered subset(policy_ready>=80%) 5b3ea7aa, f6599924. 90119209 일반화 금지.
  - tracked manifest 는 clip UUID·duration·bbox stratum 만 저장. **r2_key 는 저장/출력 금지**
    (실행 시 Mac mini 에서 read-only 재조회).
  - accuracy GT 는 보지 않는다(처리량 표본).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc

# covered subset (S0.1 재감사 policy_ready>=80%) — short = camera UUID 앞 8 hex
CAMERA_ALLOWLIST: tuple[str, ...] = ("5b3ea7aa", "f6599924")
SEED: str = "20260717"
POLICY_VERSION: str = "activity-v1"
MIN_FRAMES: int = 6

# Frozen workload strata: (camera_short, bbox_stratum, target_count)
# f6599924 absent 는 가용 clip 이 없어 target 0 (제약을 manifest 에 기록).
STRATA_TARGETS: tuple[tuple[str, str, int], ...] = (
    ("5b3ea7aa", "present", 8),
    ("5b3ea7aa", "absent", 8),
    ("f6599924", "present", 16),
    ("f6599924", "absent", 0),
)

INFLUX_WINDOW_DAYS: int = 7


class PrepContractError(RuntimeError):
    """사전등록 계약 위반(부족 stratum·중복·잘못된 입력). 침묵 실패 금지."""


# --------------------------------------------------------------------------
# datetime / numeric helpers (audit 스크립트와 동일 규약, 여기서는 자체 예외로)
# --------------------------------------------------------------------------

def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:  # 침묵 실패 금지
            raise PrepContractError(f"invalid timestamp: {value!r}") from exc
    else:
        raise PrepContractError(f"unsupported timestamp type: {type(value)!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def percentile(values, q: float) -> float:
    """linear-interpolation percentile (numpy 'linear' 과 동일). 빈 입력은 계약 위반."""
    if not values:
        raise PrepContractError("percentile: empty values")
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    rank = (q / 100.0) * (len(xs) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    frac = rank - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


# --------------------------------------------------------------------------
# 모델 (frozen = 사전등록 무결성)
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EligibleClip:
    clip_id: str
    camera_id: str
    camera_short: str
    duration_sec: float
    bbox_stratum: str  # "present" | "absent"
    frames_sampled: int
    # r2_key 는 의도적으로 보관하지 않는다(artifact leak 방지).


@dataclass(frozen=True, slots=True)
class SelectedClip:
    clip_id: str
    camera_short: str
    duration_sec: float
    bbox_stratum: str
    quartile: int
    in_reduced: bool


@dataclass(frozen=True, slots=True)
class Workload:
    selected: tuple
    strata: tuple
    seed: str

    @property
    def reduced_clip_ids(self) -> tuple:
        return tuple(sorted(c.clip_id for c in self.selected if c.in_reduced))


# --------------------------------------------------------------------------
# eligibility (join + filter) — read 모델
# --------------------------------------------------------------------------

def eligible_from_rows(motion_clips, prelabels, assessments, *,
                       policy_version: str = POLICY_VERSION,
                       camera_allowlist: tuple = CAMERA_ALLOWLIST,
                       min_frames: int = MIN_FRAMES) -> list:
    """production row(dict) → EligibleClip 목록.

    조건: allowlist 카메라 ∧ 현재 activity-v1 assessment 존재 ∧ 그 assessment 가 가리키는
    prelabel 의 frames_sampled>=min_frames ∧ duration>0 ∧ r2_key 존재.
    bbox_stratum 은 그 prelabel 의 gecko_bbox 유무로 정한다.
    """
    prelabel_by_id = {p["id"]: p for p in prelabels}
    assess_by_clip = {}
    for a in assessments:
        if a.get("policy_version") != policy_version:
            continue
        # (clip_id, policy_version) 는 unique — 현재 assessment 하나.
        assess_by_clip[a["clip_id"]] = a

    out: list[EligibleClip] = []
    for m in motion_clips:
        cid = m["id"]
        cam = m.get("camera_id") or ""
        short = cam[:8]
        if short not in camera_allowlist:
            continue
        dur = m.get("duration_sec")
        if not _finite(dur) or float(dur) <= 0:
            continue
        if not m.get("r2_key"):
            continue
        a = assess_by_clip.get(cid)
        if a is None:
            continue
        p = prelabel_by_id.get(a.get("prelabel_id"))
        if p is None:
            continue
        frames = p.get("frames_sampled")
        if not isinstance(frames, int) or frames < min_frames:
            continue
        bbox = p.get("gecko_bbox")
        stratum = "present" if bbox else "absent"
        out.append(EligibleClip(
            clip_id=cid, camera_id=cam, camera_short=short,
            duration_sec=float(dur), bbox_stratum=stratum, frames_sampled=frames))
    return out


# --------------------------------------------------------------------------
# deterministic stratified selection
# --------------------------------------------------------------------------

def _stable_key(clip_id: str, seed: str) -> str:
    """seed 고정 해시 — hash randomization 무관, 머신 간 재현 가능."""
    return hashlib.sha256(f"{seed}:{clip_id}".encode("utf-8")).hexdigest()


def _split_counts(total: int, k: int) -> list:
    base, rem = divmod(total, k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def _quartile_buckets(ordered: list) -> list:
    """duration 순 정렬된 목록을 rank 기반 4분위(연속 청크)로 나눈다."""
    sizes = _split_counts(len(ordered), 4)
    buckets, idx = [], 0
    for s in sizes:
        buckets.append(ordered[idx:idx + s])
        idx += s
    return buckets


def _select_stratum(pool: list, target: int, seed: str) -> list:
    """(EligibleClip, quartile, in_reduced) 목록을 결정론적으로 반환. 부족하면 []."""
    if len(pool) < target:
        return []
    ordered = sorted(pool, key=lambda e: (e.duration_sec, _stable_key(e.clip_id, seed)))
    buckets = _quartile_buckets(ordered)
    per_bucket = _split_counts(target, 4)
    picks = []
    for qi in range(4):
        bucket = buckets[qi]
        need = per_bucket[qi]
        if len(bucket) < need:
            return []
        by_hash = sorted(bucket, key=lambda e: _stable_key(e.clip_id, seed))
        chosen = by_hash[:need]
        reduced_ids = {c.clip_id for c in chosen[: need // 2]}  # 축소 subset = 해시 앞쪽 절반
        for e in chosen:
            picks.append((e, qi + 1, e.clip_id in reduced_ids))
    return picks


def select_workload(eligible, *, seed: str = SEED, targets: tuple = STRATA_TARGETS) -> Workload:
    seen = set()
    for e in eligible:
        if e.clip_id in seen:
            raise PrepContractError(f"duplicate clip_id in eligible input: {e.clip_id!r}")
        seen.add(e.clip_id)

    groups = {}
    for e in eligible:
        groups.setdefault((e.camera_short, e.bbox_stratum), []).append(e)

    selected: list[SelectedClip] = []
    strata_summary = []
    for cam, stratum, target in targets:
        pool = groups.get((cam, stratum), [])
        summary = {"camera_short": cam, "bbox_stratum": stratum,
                   "target": target, "available": len(pool), "selected": 0}
        strata_summary.append(summary)
        if target == 0:
            continue
        picks = _select_stratum(pool, target, seed)
        if len(picks) != target:
            raise PrepContractError(
                f"insufficient stratum {cam}/{stratum}: need {target}, "
                f"available {len(pool)} (fail-closed, sample rule 변경 금지)")
        summary["selected"] = len(picks)
        for e, quartile, in_reduced in picks:
            selected.append(SelectedClip(
                clip_id=e.clip_id, camera_short=e.camera_short, duration_sec=e.duration_sec,
                bbox_stratum=e.bbox_stratum, quartile=quartile, in_reduced=in_reduced))

    selected.sort(key=lambda c: (c.camera_short, c.bbox_stratum, c.quartile, c.clip_id))
    return Workload(selected=tuple(selected), strata=tuple(strata_summary), seed=seed)


# --------------------------------------------------------------------------
# manifest (stable, self-hashing JSON)
# --------------------------------------------------------------------------

def _canonical_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def workload_to_manifest(workload: Workload, *, as_of: datetime) -> dict:
    clips = sorted(
        ({"clip_id": c.clip_id, "camera_short": c.camera_short,
          "duration_sec": c.duration_sec, "bbox_stratum": c.bbox_stratum,
          "quartile": c.quartile, "in_reduced": c.in_reduced} for c in workload.selected),
        key=lambda d: (d["camera_short"], d["bbox_stratum"], d["quartile"], d["clip_id"]))
    strata = sorted((dict(s) for s in workload.strata),
                    key=lambda s: (s["camera_short"], s["bbox_stratum"]))
    payload = {
        "schema": "python-evidence-s1-sample-manifest-v1",
        "seed": workload.seed,
        "generated_as_of_utc": _iso(as_of),
        "camera_allowlist": list(CAMERA_ALLOWLIST),
        "policy_version": POLICY_VERSION,
        "min_frames": MIN_FRAMES,
        "total_selected": len(clips),
        "reduced_count": len(workload.reduced_clip_ids),
        "reduced_clip_ids": list(workload.reduced_clip_ids),
        "strata": strata,
        "clips": clips,
        "notes": [
            "throughput sample only; not for accuracy/label evaluation.",
            "r2 object keys are re-queried read-only at runtime and never stored here.",
            "f6599924 has no bbox-absent eligible clip (available recorded in strata).",
        ],
    }
    payload["content_sha256"] = _canonical_hash(payload)
    return payload


# --------------------------------------------------------------------------
# influx snapshot (유입량, projected 4-camera p95)
# --------------------------------------------------------------------------

def compute_influx(clip_rows, *, as_of: datetime, window_days: int = INFLUX_WINDOW_DAYS) -> dict:
    """최근 window_days 유입량. 시간버킷은 active-hour(>=1 clip) 기준으로 peak 를 보수적으로 잰다."""
    if not clip_rows:
        raise PrepContractError("influx: empty clip rows")
    window_start = as_of - timedelta(days=window_days)

    per_hour_total: dict[str, int] = {}
    per_cam_hours: dict[str, dict[str, int]] = {}
    cameras: set[str] = set()
    in_window = 0
    for r in clip_rows:
        dt = _parse_dt(r["started_at"])
        if dt < window_start or dt >= as_of:
            continue
        in_window += 1
        cam = r.get("camera_id") or ""
        cameras.add(cam)
        hour_key = dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        per_hour_total[hour_key] = per_hour_total.get(hour_key, 0) + 1
        per_cam_hours.setdefault(cam, {})[hour_key] = per_cam_hours.setdefault(cam, {}).get(hour_key, 0) + 1

    if in_window == 0:
        raise PrepContractError("influx: no clips within window")

    hourly_totals = list(per_hour_total.values())  # active hours only
    cam_count = len(cameras)
    p95 = percentile(hourly_totals, 95)

    per_camera = []
    for cam in sorted(cameras):
        hours = per_cam_hours.get(cam, {})
        counts = list(hours.values())
        per_camera.append({
            "camera_short": cam[:8],
            "clips_in_window": sum(counts),
            "active_hours": len(counts),
            "clips_per_active_hour_p95": percentile(counts, 95) if counts else 0.0,
        })

    return {
        "schema": "python-evidence-s1-influx-v1",
        "as_of_utc": _iso(as_of),
        "window_start_utc": _iso(window_start),
        "window_days": window_days,
        "clips_in_window": in_window,
        "observed_camera_count": cam_count,
        "active_hours": len(hourly_totals),
        "total_window_hours": window_days * 24,
        "observed_total_p50": percentile(hourly_totals, 50),
        "observed_total_p95": p95,
        "observed_total_max": max(hourly_totals),
        "projected_4_camera_p95": p95 * 4 / cam_count,
        "projected_note": (
            "linear per-camera projection: observed_total_p95 * 4 / observed_camera_count. "
            "percentiles over active hours (>=1 clip) to measure realized peak inflow, not idle-diluted rate."
        ),
        "per_camera": per_camera,
    }


# --------------------------------------------------------------------------
# I/O loaders (SELECT only) — main 에서만 실제 client 사용
# --------------------------------------------------------------------------

def _select_all(query_factory, order_column: str = "id", page_size: int = 1000) -> list:
    """안정 정렬 + range pagination. mutation 메서드 호출 없음(SELECT only)."""
    rows, seen, offset = [], set(), 0
    while True:
        query = query_factory().order(order_column).range(offset, offset + page_size - 1)
        resp = query.execute()
        data = getattr(resp, "data", None) or []
        for r in data:
            rid = r.get(order_column)
            if rid in seen:
                raise PrepContractError(f"duplicate page id {order_column}={rid!r}")
            seen.add(rid)
        rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
    return rows


def _select_in_batches(client, table, column, ids, columns, batch=200) -> list:
    out = []
    unique = sorted({i for i in ids if i is not None})
    for i in range(0, len(unique), batch):
        chunk = unique[i:i + batch]
        resp = client.table(table).select(columns).in_(column, chunk).order(column).execute()
        out.extend(getattr(resp, "data", None) or [])
    return out


def _resolve_camera_ids(client, allowlist: tuple) -> dict:
    cams = _select_all(lambda: client.table("cameras").select("id,name"), order_column="id")
    mapping = {}
    for c in cams:
        short = str(c["id"])[:8]
        if short in allowlist:
            mapping[short] = str(c["id"])
    missing = [s for s in allowlist if s not in mapping]
    if missing:
        raise PrepContractError(f"camera allowlist not found in DB: {missing}")
    return mapping


def load_eligible(client, *, as_of: datetime, lookback_days: int,
                  policy_version: str = POLICY_VERSION) -> list:
    cam_ids = list(_resolve_camera_ids(client, CAMERA_ALLOWLIST).values())
    start_iso = _iso(as_of - timedelta(days=lookback_days))
    motion = _select_all(
        lambda: client.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key")
        .in_("camera_id", cam_ids).gte("started_at", start_iso).lt("started_at", _iso(as_of)),
        order_column="id")
    clip_ids = [m["id"] for m in motion]
    assessments = _select_in_batches(
        client, "clip_activity_assessments", "clip_id", clip_ids,
        "id,clip_id,prelabel_id,policy_version,decision")
    prelabel_ids = [a["prelabel_id"] for a in assessments if a.get("prelabel_id")]
    prelabels = _select_in_batches(
        client, "clip_prelabels", "id", prelabel_ids, "id,clip_id,frames_sampled,gecko_bbox")
    return eligible_from_rows(motion, prelabels, assessments, policy_version=policy_version)


def load_influx_rows(client, *, as_of: datetime, window_days: int = INFLUX_WINDOW_DAYS) -> list:
    start_iso = _iso(as_of - timedelta(days=window_days))
    return _select_all(
        lambda: client.table("motion_clips").select("id,camera_id,started_at")
        .gte("started_at", start_iso).lt("started_at", _iso(as_of)),
        order_column="id")


def _lab_head() -> str:
    try:
        import subprocess
        repo = Path(__file__).resolve().parent.parent
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
        return out.stdout.strip()[:12] if out.returncode == 0 else ""
    except Exception:
        return ""


def _write_json(path: Path, payload: dict) -> str:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prepare Python Evidence S1 throughput sample (read-only).")
    p.add_argument("--as-of", default=None, help="ISO-8601 as-of (default: now UTC).")
    p.add_argument("--lookback-days", type=int, default=60,
                   help="eligible pool lookback (pre-registered, do not tune after seeing counts).")
    p.add_argument("--out-dir", default="experiments/python-evidence-s1-throughput")
    p.add_argument("--seed", default=SEED)
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    as_of = _parse_dt(args.as_of) if args.as_of else datetime.now(UTC)

    from backend.supabase_client import get_supabase_client
    client = get_supabase_client()

    eligible = load_eligible(client, as_of=as_of, lookback_days=args.lookback_days)
    workload = select_workload(eligible, seed=args.seed)
    manifest = workload_to_manifest(workload, as_of=as_of)
    manifest["lab_head"] = _lab_head()
    manifest["lookback_days"] = args.lookback_days

    influx_rows = load_influx_rows(client, as_of=as_of)
    influx = compute_influx(influx_rows, as_of=as_of)
    influx["lab_head"] = manifest["lab_head"]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_hash = _write_json(out_dir / "sample_manifest.json", manifest)
    influx_hash = _write_json(out_dir / "influx_snapshot.json", influx)

    # stdout: short IDs + aggregate counts only (no r2_key / no full clip UUID).
    print(f"[prep] as_of={_iso(as_of)} lab_head={manifest['lab_head']}", file=sys.stderr)
    for s in manifest["strata"]:
        print(f"[prep] stratum {s['camera_short']}/{s['bbox_stratum']} "
              f"target={s['target']} available={s['available']} selected={s['selected']}", file=sys.stderr)
    print(f"[prep] total_selected={manifest['total_selected']} reduced={manifest['reduced_count']}",
          file=sys.stderr)
    print(f"[prep] influx cameras={influx['observed_camera_count']} "
          f"total_p95={influx['observed_total_p95']} projected_4cam_p95={influx['projected_4_camera_p95']}",
          file=sys.stderr)
    print(f"[prep] sample_manifest.json sha256={manifest_hash}", file=sys.stderr)
    print(f"[prep] influx_snapshot.json sha256={influx_hash}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
