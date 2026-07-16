"""Python Evidence Hybrid — S0 coverage audit (production READ-ONLY).

이 스크립트는 production DB 를 **SELECT 만** 읽어서 Gate evidence 가 어디까지 실제로
채워졌는지, 그리고 정규 VLM selector 입력 시점에 얼마나 사용 가능했는지를
재현 가능하게 측정한다. (상위 정본: docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md §12 S0, §17-1)

핵심 설계 규칙(왜 이렇게 나눴나):
- **exact / estimate / not_reconstructable 를 절대 한 수치로 합치지 않는다.**
  - exact: `clip_vlm_jobs` FK(prelabel_id, activity_assessment_id) — 선택 결과에 실제 연결된 evidence.
  - estimate: selector run window 안의 motion clip 중 `prelabel.created_at <= run.created_at` 비율.
  - not_reconstructable: episode reduction·제외 전 eligible pool 의 clip 단위 snapshot 은 저장되지 않음.
- production 은 read-only. `.insert/.update/.delete/.upsert/.rpc` 를 이 파일에 두지 않는다(정적 스캔으로 강제).
- 산출물에 owner UUID / R2 key / raw evidence JSON / clip 전체 UUID 를 넣지 않는다(짧은 8자 prefix 만).

TS/Node 배경 비유: read adapter(=repository), 순수 집계 함수(=pure service), renderer(=presenter),
CLI(=controller) 로 계층을 나눴다. DB 접근은 adapter 에만 있고 나머지는 dict 로 테스트한다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# 스크립트 직접 실행(`uv run python scripts/...`) 시 sys.path[0]=scripts/ 라 `backend` 를 못 찾는다.
# repo root 를 앞에 붙인다. list.insert 계열은 read-only 정적 스캔 금지 토큰이라 슬라이스 대입으로 prepend.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

KST = ZoneInfo("Asia/Seoul")

# clip_prelabels.motion_metrics 의 필수 8키 (설계 §5.3)
MOTION_KEYS = (
    "visible_frame_count",
    "visible_frame_ratio",
    "max_bbox_center_disp",
    "max_bbox_size_change",
    "min_bbox_iou",
    "roi_flow_mag",
    "global_bg_change",
    "bbox_edge_clipped",
)

_PROVENANCE_STR_KEYS = ("model_name", "model_version", "sampler_version", "schema_version")
_CHECKPOINT_RE = re.compile(r"^[0-9a-fA-F]{64}$")

VERDICT_PASS = "S0_PASS"
VERDICT_GAP = "S0_PASS_WITH_COVERAGE_GAP"
VERDICT_HOLD = "S0_HOLD_DATA_CONTRACT"

DEFAULT_START = "2026-07-14T00:00:00+09:00"
DEFAULT_POLICY = "activity-v1"
DEFAULT_REGULAR_SELECTOR = "budget-router-v1"


class AuditContractError(RuntimeError):
    """fail-closed: pagination 중복/누락, FK 단절, count 불일치, 시간 파싱 실패 등."""


# --------------------------------------------------------------------------
# 시간 유틸
# --------------------------------------------------------------------------

def parse_dt(value) -> datetime:
    """ISO-8601 문자열/naive/aware → tz-aware datetime. 'Z' 접미사 처리."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:  # 침묵 실패 금지
            raise AuditContractError(f"invalid timestamp: {value!r}") from exc
    else:
        raise AuditContractError(f"unsupported timestamp type: {type(value)!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def kst_date(dt: datetime) -> date:
    """촬영일 strata = started_at 을 Asia/Seoul 로 변환한 날짜."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).date()


def _is_finite_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


# --------------------------------------------------------------------------
# 정규화된 snapshot + 요약 레코드 (frozen = 감사 무결성)
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AuditSnapshot:
    start: datetime
    as_of: datetime
    policy_version: str = DEFAULT_POLICY
    regular_selector_version: str = DEFAULT_REGULAR_SELECTOR
    cameras: tuple = ()
    motion_clips: tuple = ()
    prelabels: tuple = ()
    assessments: tuple = ()
    selector_runs: tuple = ()
    jobs: tuple = ()
    settings: dict = field(default_factory=dict)
    source_counts: dict = field(default_factory=dict)
    snapshot_id: str = ""
    lab_head: str = ""


@dataclass(frozen=True, slots=True)
class CoverageCounts:
    total_eligible: int
    any_prelabel_count: int
    policy_ready_count: int
    core_complete_count: int


@dataclass(frozen=True, slots=True)
class InventorySummary:
    counts: CoverageCounts
    camera_date_rows: tuple
    identity_rows: tuple
    per_camera: tuple
    core_incomplete_clip_ids: tuple

    @property
    def total_eligible(self) -> int:
        return self.counts.total_eligible

    @property
    def any_prelabel_count(self) -> int:
        return self.counts.any_prelabel_count

    @property
    def policy_ready_count(self) -> int:
        return self.counts.policy_ready_count

    @property
    def core_complete_count(self) -> int:
        return self.counts.core_complete_count


@dataclass(frozen=True, slots=True)
class SelectorCoverageRow:
    run_id: str
    run_short: str
    camera_id: str
    camera_short: str
    selector_version: str
    selector_kind: str
    created_at: datetime
    window_start: datetime
    window_end: datetime
    selected_jobs: int
    selected_with_prelabel: int
    selected_linkage_kind: str
    window_clips: int
    window_clips_with_prelabel_at_run: int
    window_time_kind: str
    eligible_pool_kind: str


@dataclass(frozen=True, slots=True)
class CoverageVerdict:
    label: str
    reasons: tuple
    warnings: tuple
    gap: tuple
    zero_coverage: tuple


# --------------------------------------------------------------------------
# 순수 함수 — evidence 완전성
# --------------------------------------------------------------------------

def core_evidence_issues(prelabel: dict) -> tuple:
    """core_complete 가 아니면 결손 필드명 튜플, 완전하면 빈 튜플.

    absent evidence 에서 정상인 gecko_bbox=null / best_frame_ts=null 은 결손으로 세지 않는다(설계 §5.3).
    """
    issues = []
    for k in _PROVENANCE_STR_KEYS:
        v = prelabel.get(k)
        if not (isinstance(v, str) and v.strip()):
            issues.append(k)
    cp = prelabel.get("checkpoint_sha256")
    if not (isinstance(cp, str) and _CHECKPOINT_RE.match(cp)):
        issues.append("checkpoint_sha256")
    if not _is_finite_number(prelabel.get("threshold")):
        issues.append("threshold")
    fs = prelabel.get("frames_sampled")
    if not (isinstance(fs, int) and not isinstance(fs, bool) and fs > 0):
        issues.append("frames_sampled")
    if not isinstance(prelabel.get("gecko_visible"), bool):
        issues.append("gecko_visible")
    if not _is_finite_number(prelabel.get("visibility_confidence")):
        issues.append("visibility_confidence")

    mm = prelabel.get("motion_metrics")
    if not isinstance(mm, dict):
        issues.append("motion_metrics")
    else:
        for k in MOTION_KEYS:
            if k not in mm:
                issues.append(f"motion_metrics.{k}")
                continue
            v = mm[k]
            if k == "bbox_edge_clipped":
                if not isinstance(v, bool):
                    issues.append(f"motion_metrics.{k}")
            elif k == "visible_frame_count":
                if not (isinstance(v, int) and not isinstance(v, bool)):
                    issues.append(f"motion_metrics.{k}")
            else:
                if not _is_finite_number(v):
                    issues.append(f"motion_metrics.{k}")
    return tuple(issues)


def _identity_tuple(prelabel: dict) -> tuple:
    return (
        prelabel.get("model_version"),
        prelabel.get("schema_version"),
        prelabel.get("checkpoint_sha256"),
        prelabel.get("threshold"),
        prelabel.get("sampler_version"),
        prelabel.get("frames_sampled"),
    )


def _short(value) -> str:
    return str(value)[:8] if value is not None else ""


# --------------------------------------------------------------------------
# 순수 함수 — 재고 / 현재정책 coverage
# --------------------------------------------------------------------------

def build_inventory_rows(snapshot: AuditSnapshot, policy_version: str) -> InventorySummary:
    prelabels_by_id = {p["id"]: p for p in snapshot.prelabels}
    prelabels_by_clip: dict = {}
    for p in snapshot.prelabels:
        prelabels_by_clip.setdefault(p["clip_id"], []).append(p)

    assess_by_clip: dict = {}
    for a in snapshot.assessments:
        if a.get("policy_version") == policy_version:
            assess_by_clip[a["clip_id"]] = a  # 멱등: clip+policy 유일

    cam_by_id = {c["id"]: c for c in snapshot.cameras}

    # eligible = 고유 clip_id (evidence row 를 clip 으로 세지 않는다)
    eligible_ids = []
    seen = set()
    mc_by_id = {}
    for mc in snapshot.motion_clips:
        cid = mc["id"]
        mc_by_id[cid] = mc
        if cid in seen:
            continue
        seen.add(cid)
        eligible_ids.append(cid)

    any_prelabel = policy_ready = core_complete = 0
    core_incomplete = []
    strata: dict = {}
    per_cam: dict = {}
    identity: dict = {}

    for cid in eligible_ids:
        mc = mc_by_id[cid]
        cam = mc["camera_id"]
        kd = kst_date(parse_dt(mc["started_at"]))
        st = strata.setdefault((cam, kd), {"eligible": 0, "any_prelabel": 0, "policy_ready": 0, "core_complete": 0})
        pc = per_cam.setdefault(cam, {"eligible": 0, "any_prelabel": 0, "policy_ready": 0, "core_complete": 0})
        st["eligible"] += 1
        pc["eligible"] += 1

        plist = prelabels_by_clip.get(cid, [])
        if plist:
            any_prelabel += 1
            st["any_prelabel"] += 1
            pc["any_prelabel"] += 1
            for ident in {_identity_tuple(p) for p in plist}:
                identity.setdefault(ident, set()).add(cid)

        a = assess_by_clip.get(cid)
        ready = a is not None and a.get("prelabel_id") in prelabels_by_id
        if ready:
            policy_ready += 1
            st["policy_ready"] += 1
            pc["policy_ready"] += 1
            ref = prelabels_by_id[a["prelabel_id"]]
            if core_evidence_issues(ref) == ():
                core_complete += 1
                st["core_complete"] += 1
                pc["core_complete"] += 1
            else:
                core_incomplete.append(cid)

    camera_date_rows = []
    for (cam, kd) in sorted(strata, key=lambda t: (_short(t[0]), t[1].isoformat())):
        c = strata[(cam, kd)]
        cam_row = cam_by_id.get(cam, {})
        camera_date_rows.append({
            "camera_name": cam_row.get("name", ""),
            "camera_short": _short(cam),
            "kst_date": kd.isoformat(),
            "eligible": c["eligible"],
            "any_prelabel": c["any_prelabel"],
            "policy_ready": c["policy_ready"],
            "core_complete": c["core_complete"],
            "any_prelabel_ratio": _ratio(c["any_prelabel"], c["eligible"]),
            "policy_ready_ratio": _ratio(c["policy_ready"], c["eligible"]),
        })

    identity_rows = []
    for ident in sorted(identity, key=lambda t: tuple(str(x) for x in t)):
        mv, sv, cp, th, samp, fr = ident
        identity_rows.append({
            "model_version": mv,
            "schema_version": sv,
            "checkpoint_sha256": cp,
            "threshold": th,
            "sampler_version": samp,
            "frames_sampled": fr,
            "unique_clips": len(identity[ident]),
        })

    per_camera = []
    for cam in sorted(per_cam, key=_short):
        c = per_cam[cam]
        cam_row = cam_by_id.get(cam, {})
        per_camera.append({
            "camera_id": cam,
            "camera_name": cam_row.get("name", ""),
            "camera_short": _short(cam),
            "eligible": c["eligible"],
            "any_prelabel": c["any_prelabel"],
            "policy_ready": c["policy_ready"],
            "core_complete": c["core_complete"],
        })

    return InventorySummary(
        counts=CoverageCounts(total_eligible=len(eligible_ids), any_prelabel_count=any_prelabel,
                              policy_ready_count=policy_ready, core_complete_count=core_complete),
        camera_date_rows=tuple(camera_date_rows),
        identity_rows=tuple(identity_rows),
        per_camera=tuple(per_camera),
        core_incomplete_clip_ids=tuple(core_incomplete),
    )


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


# --------------------------------------------------------------------------
# 순수 함수 — selector 시점 coverage
# --------------------------------------------------------------------------

def classify_selector(version: str) -> str:
    if version == DEFAULT_REGULAR_SELECTOR:
        return "regular"
    if version and "backfill" in version:
        return "backfill"
    return "other"


def build_selector_rows(snapshot: AuditSnapshot) -> list:
    prelabels_by_id = {p["id"]: p for p in snapshot.prelabels}
    assess_by_id = {a["id"]: a for a in snapshot.assessments}
    prelabels_by_clip: dict = {}
    for p in snapshot.prelabels:
        prelabels_by_clip.setdefault(p["clip_id"], []).append(p)

    jobs_by_run: dict = {}
    for j in snapshot.jobs:
        # FK 계약: non-null 참조는 실제 row 를 가리켜야 한다. broken FK = null success 가 아니라 contract error.
        pid = j.get("prelabel_id")
        if pid is not None and pid not in prelabels_by_id:
            raise AuditContractError(f"job {j.get('id')} references missing prelabel {pid}")
        aid = j.get("activity_assessment_id")
        if aid is not None and aid not in assess_by_id:
            raise AuditContractError(f"job {j.get('id')} references missing assessment {aid}")
        jobs_by_run.setdefault(j.get("selector_run_id"), []).append(j)

    rows = []
    for run in sorted(snapshot.selector_runs, key=lambda r: (parse_dt(r["created_at"]), str(r["id"]))):
        run_id = run["id"]
        run_created = parse_dt(run["created_at"])
        w_start = parse_dt(run["window_start"])
        w_end = parse_dt(run["window_end"])
        cam = run.get("camera_id")

        run_jobs = jobs_by_run.get(run_id, [])
        selected_jobs = len(run_jobs)
        selected_with_prelabel = sum(1 for j in run_jobs if j.get("prelabel_id") in prelabels_by_id)

        # window-time availability (estimate): [window_start, window_end) 반개구간, camera 일치
        window_clip_ids = [
            mc["id"] for mc in snapshot.motion_clips
            if mc.get("camera_id") == cam and w_start <= parse_dt(mc["started_at"]) < w_end
        ]
        with_prelabel_at_run = 0
        for cid in window_clip_ids:
            if any(parse_dt(p["created_at"]) <= run_created for p in prelabels_by_clip.get(cid, [])):
                with_prelabel_at_run += 1

        rows.append(SelectorCoverageRow(
            run_id=str(run_id),
            run_short=_short(run_id),
            camera_id=str(cam),
            camera_short=_short(cam),
            selector_version=run.get("selector_version", ""),
            selector_kind=classify_selector(run.get("selector_version", "")),
            created_at=run_created,
            window_start=w_start,
            window_end=w_end,
            selected_jobs=selected_jobs,
            selected_with_prelabel=selected_with_prelabel,
            selected_linkage_kind="exact",
            window_clips=len(window_clip_ids),
            window_clips_with_prelabel_at_run=with_prelabel_at_run,
            window_time_kind="estimate",
            eligible_pool_kind="not_reconstructable",
        ))
    return rows


def selector_warnings(rows) -> tuple:
    """정규 selector 표본이 없으면 0% coverage 로 오해하지 않게 경고를 낸다."""
    warnings = []
    if not any(r.selector_kind == "regular" for r in rows):
        warnings.append("regular_selector_sample_missing")
    return tuple(warnings)


# --------------------------------------------------------------------------
# 순수 함수 — 판정
# --------------------------------------------------------------------------

def evaluate_verdict(snapshot: AuditSnapshot, inventory: InventorySummary, selector_rows,
                     extra_contract_reasons=()) -> CoverageVerdict:
    reasons = list(extra_contract_reasons)
    warnings = list(selector_warnings(selector_rows))
    gap = []
    zero = []

    # 데이터 계약: policy_ready clip 의 참조 prelabel core completeness < 100%
    if inventory.policy_ready_count > 0 and inventory.core_complete_count < inventory.policy_ready_count:
        reasons.append(
            f"core_completeness_below_100:{inventory.core_complete_count}/{inventory.policy_ready_count}"
        )

    per_cam = {r["camera_id"]: r for r in inventory.per_camera}
    enabled = [c for c in snapshot.cameras if snapshot.settings.get(c["id"], {}).get("enabled")]

    if not enabled:
        gap.append("no_enabled_camera")
    for c in enabled:
        pc = per_cam.get(c["id"])
        if pc is None or pc["eligible"] == 0:
            gap.append(f"no_eligible_clips:{_short(c['id'])}")
            continue
        if pc["any_prelabel"] == 0:
            zero.append(_short(c["id"]))
            gap.append(f"zero_prelabel_coverage:{_short(c['id'])}")
            continue
        ratio = _ratio(pc["policy_ready"], pc["eligible"])
        if ratio < 0.8:
            gap.append(f"policy_ready_below_80:{_short(c['id'])}:{ratio}")

    if not any(r.selector_kind == "regular" for r in selector_rows):
        gap.append("regular_selector_sample_missing")

    if reasons:
        label = VERDICT_HOLD
    elif gap:
        label = VERDICT_GAP
    else:
        label = VERDICT_PASS
    return CoverageVerdict(label=label, reasons=tuple(reasons), warnings=tuple(warnings),
                           gap=tuple(gap), zero_coverage=tuple(zero))


def evaluate_verdict_for(snapshot: AuditSnapshot) -> CoverageVerdict:
    """편의 함수: snapshot 하나로 inventory/selector 계산 후 판정."""
    inv = build_inventory_rows(snapshot, snapshot.policy_version)
    sel = build_selector_rows(snapshot)
    return evaluate_verdict(snapshot, inv, sel)


# --------------------------------------------------------------------------
# read-only Supabase adapter
# --------------------------------------------------------------------------

def select_all(query_factory, order_column: str = "id", page_size: int = 1000) -> list:
    """안정적 정렬 + 명시적 range 로 pagination. mutation 메서드는 호출하지 않는다.

    query_factory 는 매 페이지마다 새 query builder 를 반환해야 한다(builder 는 1회 소비).
    """
    rows = []
    seen = set()
    offset = 0
    while True:
        query = query_factory().order(order_column).range(offset, offset + page_size - 1)
        resp = query.execute()
        data = getattr(resp, "data", None)
        if data is None and isinstance(resp, dict):
            data = resp.get("data")
        data = data or []
        for r in data:
            rid = r.get(order_column)
            if rid in seen:
                raise AuditContractError(f"duplicate page id in {order_column}: {rid!r}")
            seen.add(rid)
        rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
    return rows


def _select_in_batches(client, table, column, ids, columns, batch=200):
    out = []
    unique_ids = sorted({i for i in ids if i is not None})
    for i in range(0, len(unique_ids), batch):
        chunk = unique_ids[i : i + batch]
        query = client.table(table).select(columns).in_(column, chunk)
        resp = query.order(column).execute()
        data = getattr(resp, "data", None) or []
        out.extend(data)
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def load_snapshot(client, start: datetime, as_of: datetime,
                  policy_version: str = DEFAULT_POLICY,
                  regular_selector_version: str = DEFAULT_REGULAR_SELECTOR,
                  lab_head: str = "") -> AuditSnapshot:
    start = parse_dt(start)
    as_of = parse_dt(as_of)
    if as_of <= start:
        raise AuditContractError("--as-of must be after --start")

    start_iso, as_of_iso = _iso(start), _iso(as_of)

    # cameras (작은 테이블, 이름만)
    cameras_raw = select_all(
        lambda: client.table("cameras").select("id,name"), order_column="id")
    cameras = tuple({"id": c["id"], "name": c.get("name", "")} for c in cameras_raw)

    # motion_clips: started_at 범위 + eligible(duration>0, r2_key 존재). r2_key 는 snapshot 에 남기지 않는다.
    mc_raw = select_all(
        lambda: client.table("motion_clips")
        .select("id,camera_id,started_at,duration_sec,r2_key")
        .gte("started_at", start_iso).lt("started_at", as_of_iso),
        order_column="id",
    )
    motion_clips = []
    for m in mc_raw:
        dur = m.get("duration_sec")
        if dur is None or float(dur) <= 0:
            continue
        if not m.get("r2_key"):
            continue
        motion_clips.append({
            "id": m["id"], "camera_id": m.get("camera_id"),
            "started_at": parse_dt(m["started_at"]), "duration_sec": float(dur),
        })
    motion_clips = tuple(motion_clips)
    eligible_ids = [m["id"] for m in motion_clips]

    pre_cols = ("id,clip_id,model_name,model_version,checkpoint_sha256,threshold,"
                "sampler_version,schema_version,frames_sampled,gecko_visible,"
                "visibility_confidence,best_frame_ts,gecko_bbox,motion_metrics,created_at")
    prelabels_raw = _select_in_batches(client, "clip_prelabels", "clip_id", eligible_ids, pre_cols)
    prelabels = tuple({**p, "created_at": parse_dt(p["created_at"])} for p in prelabels_raw)

    assess_cols = "id,clip_id,prelabel_id,decision,policy_version,created_at"
    assess_raw = _select_in_batches(client, "clip_activity_assessments", "clip_id", eligible_ids, assess_cols)
    assessments = tuple({**a, "created_at": parse_dt(a["created_at"])} for a in assess_raw)

    runs_raw = select_all(
        lambda: client.table("clip_vlm_selector_runs")
        .select("id,camera_id,window_start,window_end,selector_version,created_at")
        .gte("created_at", start_iso).lt("created_at", as_of_iso),
        order_column="id",
    )
    selector_runs = tuple({
        "id": r["id"], "camera_id": r.get("camera_id"),
        "window_start": parse_dt(r["window_start"]), "window_end": parse_dt(r["window_end"]),
        "selector_version": r.get("selector_version", ""), "created_at": parse_dt(r["created_at"]),
    } for r in runs_raw)

    run_ids = [r["id"] for r in selector_runs]
    job_cols = "id,selector_run_id,clip_id,camera_id,prelabel_id,activity_assessment_id,created_at"
    jobs_raw = _select_in_batches(client, "clip_vlm_jobs", "selector_run_id", run_ids, job_cols)
    jobs = tuple({**j, "created_at": parse_dt(j["created_at"])} for j in jobs_raw)

    # FK 무결성: job 이 참조하는 prelabel/assessment 가 eligible 로더에 없을 수 있으니 보강 조회 후 검증.
    known_prelabels = {p["id"] for p in prelabels}
    known_assess = {a["id"] for a in assessments}
    extra_pre_ids = [j.get("prelabel_id") for j in jobs
                     if j.get("prelabel_id") and j["prelabel_id"] not in known_prelabels]
    extra_assess_ids = [j.get("activity_assessment_id") for j in jobs
                        if j.get("activity_assessment_id") and j["activity_assessment_id"] not in known_assess]
    if extra_pre_ids:
        extra = _select_in_batches(client, "clip_prelabels", "id", extra_pre_ids, pre_cols)
        prelabels = prelabels + tuple({**p, "created_at": parse_dt(p["created_at"])} for p in extra)
        known_prelabels = {p["id"] for p in prelabels}
    if extra_assess_ids:
        extra = _select_in_batches(client, "clip_activity_assessments", "id", extra_assess_ids, assess_cols)
        assessments = assessments + tuple({**a, "created_at": parse_dt(a["created_at"])} for a in extra)
        known_assess = {a["id"] for a in assessments}
    for j in jobs:
        if j.get("prelabel_id") and j["prelabel_id"] not in known_prelabels:
            raise AuditContractError(f"job {j['id']} references missing prelabel {j['prelabel_id']}")
        if j.get("activity_assessment_id") and j["activity_assessment_id"] not in known_assess:
            raise AuditContractError(f"job {j['id']} references missing assessment {j['activity_assessment_id']}")

    settings_raw = select_all(
        lambda: client.table("camera_activity_filter_settings")
        .select("camera_id,enabled,exclude_absent_enabled,exclude_static_enabled,active_policy_version"),
        order_column="camera_id",
    )
    settings = {}
    for s in settings_raw:
        settings[s["camera_id"]] = {
            "enabled": bool(s.get("enabled")),
            "exclude_absent_enabled": bool(s.get("exclude_absent_enabled")),
            "exclude_static_enabled": bool(s.get("exclude_static_enabled")),
            "active_policy_version": s.get("active_policy_version"),
        }

    source_counts = {
        "cameras": len(cameras),
        "motion_clips_eligible": len(motion_clips),
        "clip_prelabels": len(prelabels),
        "clip_activity_assessments": len(assessments),
        "clip_vlm_selector_runs": len(selector_runs),
        "clip_vlm_jobs": len(jobs),
        "camera_activity_filter_settings": len(settings),
    }

    snap = AuditSnapshot(
        start=start, as_of=as_of, policy_version=policy_version,
        regular_selector_version=regular_selector_version,
        cameras=cameras, motion_clips=motion_clips, prelabels=prelabels,
        assessments=assessments, selector_runs=selector_runs, jobs=jobs,
        settings=settings, source_counts=source_counts, lab_head=lab_head,
    )
    return _finalize(snap)


def _finalize(snap: AuditSnapshot) -> AuditSnapshot:
    if snap.snapshot_id:
        return snap
    payload = json.dumps({
        "start": _iso(snap.start), "as_of": _iso(snap.as_of),
        "policy": snap.policy_version, "regular": snap.regular_selector_version,
        "source_counts": snap.source_counts,
    }, sort_keys=True)
    sid = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return AuditSnapshot(
        start=snap.start, as_of=snap.as_of, policy_version=snap.policy_version,
        regular_selector_version=snap.regular_selector_version, cameras=snap.cameras,
        motion_clips=snap.motion_clips, prelabels=snap.prelabels, assessments=snap.assessments,
        selector_runs=snap.selector_runs, jobs=snap.jobs, settings=snap.settings,
        source_counts=snap.source_counts, snapshot_id=sid, lab_head=snap.lab_head,
    )


# --------------------------------------------------------------------------
# 렌더링 (원자적)
# --------------------------------------------------------------------------

def _clip_id_checksum(snapshot: AuditSnapshot) -> str:
    ids = sorted(str(m["id"]) for m in snapshot.motion_clips)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _write_summary(snapshot, inventory, selector_rows, verdict, out: Path):
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "as_of_utc": _iso(snapshot.as_of),
        "as_of_kst": snapshot.as_of.astimezone(KST).isoformat(),
        "start_utc": _iso(snapshot.start),
        "start_kst": snapshot.start.astimezone(KST).isoformat(),
        "policy_version": snapshot.policy_version,
        "regular_selector_version": snapshot.regular_selector_version,
        "lab_head": snapshot.lab_head,
        "coverage": {
            "total_eligible": inventory.total_eligible,
            "any_prelabel_count": inventory.any_prelabel_count,
            "policy_ready_count": inventory.policy_ready_count,
            "core_complete_count": inventory.core_complete_count,
        },
        "selector_kinds": sorted({r.selector_kind for r in selector_rows}),
        "verdict": verdict.label,
        "verdict_reasons": list(verdict.reasons),
        "warnings": list(verdict.warnings),
        "gap": list(verdict.gap),
        "zero_coverage_cameras": list(verdict.zero_coverage),
        "source_counts": snapshot.source_counts,
        "clip_id_checksum": _clip_id_checksum(snapshot),
        "core_incomplete_clip_shorts": [_short(c) for c in inventory.core_incomplete_clip_ids],
    }
    (out / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, fieldnames, rows):
    # csv 기본 lineterminator 는 '\r\n' 이라 git 이 CR 을 trailing whitespace 로 잡는다 → '\n' 강제.
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fieldnames})


def _write_camera_date_csv(inventory, out: Path):
    fieldnames = ["camera_name", "camera_short", "kst_date", "eligible", "any_prelabel",
                  "policy_ready", "core_complete", "any_prelabel_ratio", "policy_ready_ratio"]
    _write_csv(out / "camera_date_coverage.csv", fieldnames, inventory.camera_date_rows)


def _write_selector_csv(selector_rows, out: Path):
    fieldnames = ["run_short", "camera_short", "selector_version", "selector_kind",
                  "created_at_kst", "window_start_kst", "window_end_kst",
                  "selected_jobs", "selected_with_prelabel", "selected_linkage_kind",
                  "window_clips", "window_clips_with_prelabel_at_run", "window_time_kind",
                  "eligible_pool_kind"]
    rows = [{
        "run_short": r.run_short, "camera_short": r.camera_short,
        "selector_version": r.selector_version, "selector_kind": r.selector_kind,
        "created_at_kst": r.created_at.astimezone(KST).isoformat(),
        "window_start_kst": r.window_start.astimezone(KST).isoformat(),
        "window_end_kst": r.window_end.astimezone(KST).isoformat(),
        "selected_jobs": r.selected_jobs, "selected_with_prelabel": r.selected_with_prelabel,
        "selected_linkage_kind": r.selected_linkage_kind, "window_clips": r.window_clips,
        "window_clips_with_prelabel_at_run": r.window_clips_with_prelabel_at_run,
        "window_time_kind": r.window_time_kind, "eligible_pool_kind": r.eligible_pool_kind,
    } for r in selector_rows]
    _write_csv(out / "selector_time_coverage.csv", fieldnames, rows)


def _write_identity_csv(inventory, out: Path):
    fieldnames = ["model_version", "schema_version", "checkpoint_sha256", "threshold",
                  "sampler_version", "frames_sampled", "unique_clips"]
    _write_csv(out / "identity_distribution.csv", fieldnames, inventory.identity_rows)


def _write_report_md(snapshot, inventory, selector_rows, verdict, out: Path):
    regular = [r for r in selector_rows if r.selector_kind == "regular"]
    backfill = [r for r in selector_rows if r.selector_kind == "backfill"]
    lines = []
    lines.append("# Python Evidence Hybrid — S0 Coverage Audit REPORT")
    lines.append("")
    lines.append(f"- snapshot_id: `{snapshot.snapshot_id}`")
    lines.append(f"- as_of: `{snapshot.as_of.astimezone(KST).isoformat()}` (KST) / `{_iso(snapshot.as_of)}` (UTC)")
    lines.append(f"- start: `{snapshot.start.astimezone(KST).isoformat()}` (KST) / `{_iso(snapshot.start)}` (UTC)")
    lines.append(f"- policy_version: `{snapshot.policy_version}` · regular selector: `{snapshot.regular_selector_version}`")
    if snapshot.lab_head:
        lines.append(f"- petcam-lab HEAD: `{snapshot.lab_head}`")
    lines.append("")
    lines.append(f"## 판정: **{verdict.label}**")
    if verdict.reasons:
        lines.append("")
        lines.append("계약 위반 사유:")
        for r in verdict.reasons:
            lines.append(f"- {r}")
    if verdict.gap:
        lines.append("")
        lines.append("coverage gap:")
        for g in verdict.gap:
            lines.append(f"- {g}")
    if verdict.warnings:
        lines.append("")
        lines.append("경고:")
        for w in verdict.warnings:
            lines.append(f"- {w}")
    lines.append("")
    lines.append("## 재고 / 현재정책 coverage")
    lines.append("")
    lines.append(f"- total_eligible motion clips: **{inventory.total_eligible}**")
    lines.append(f"- any_prelabel clips: **{inventory.any_prelabel_count}**")
    lines.append(f"- policy_ready (`{snapshot.policy_version}` + 유효 prelabel 참조): **{inventory.policy_ready_count}**")
    lines.append(f"- core_complete (policy_ready 중 필수 evidence 완비): **{inventory.core_complete_count}**")
    lines.append("")
    lines.append("### 0% coverage 카메라/날짜 strata")
    zero_rows = [row for row in inventory.camera_date_rows if row["any_prelabel"] == 0]
    if zero_rows:
        for row in zero_rows:
            lines.append(f"- `{row['camera_short']}` {row['kst_date']}: eligible {row['eligible']}, prelabel 0")
    else:
        lines.append("- (없음 또는 eligible 0)")
    lines.append("")
    lines.append("## selector 시점 coverage (정규/backfill 분리)")
    lines.append("")
    lines.append(f"- 정규(`{snapshot.regular_selector_version}`) run: **{len(regular)}**, backfill run: **{len(backfill)}**")
    lines.append("- **exact** = `clip_vlm_jobs` FK(prelabel_id/activity_assessment_id) 로 선택 결과에 실제 연결된 evidence.")
    lines.append("- **estimate** = run window `[window_start, window_end)` 안 motion clip 중 `prelabel.created_at <= run.created_at` 비율(복원 근사치).")
    lines.append("- **not_reconstructable** = episode reduction·제외 전 eligible pool 의 clip 단위 snapshot 은 저장되지 않아 정확 pool 을 복원하지 않는다.")
    if not regular:
        lines.append("- ⚠️ 정규 selector 표본 없음(`regular_selector_sample_missing`) — 0% coverage 가 아니라 표본 부재로 해석한다.")
    lines.append("")
    lines.append("## S1 권고 (범위 한정)")
    lines.append("")
    if verdict.label == VERDICT_PASS:
        lines.append("- S0_PASS: 기존 evidence 로 S1 표본 구성 가능. 단 S1 은 처리량 벤치마크만이며 selector/threshold/자동제외 변경 금지.")
    elif verdict.label == VERDICT_GAP:
        covered = [row["camera_short"] for row in inventory.per_camera
                   if row["eligible"] > 0 and row["policy_ready"] / row["eligible"] >= 0.8]
        lines.append("- S0_PASS_WITH_COVERAGE_GAP: S1 은 아래 covered subset 으로만 진행하고 전체 카메라/기간으로 일반화 금지.")
        lines.append(f"  - covered subset(policy_ready≥80%): {covered if covered else '없음 — 기간 연장 필요'}")
    else:
        lines.append("- S0_HOLD_DATA_CONTRACT: 데이터 계약이 불완전하므로 S1 진행 금지. 위 계약 위반 사유부터 해소한다.")
    lines.append("")
    lines.append("본 감사는 read-only 다. selector/threshold/자동제외/행동라벨/앱 활동시간을 변경하지 않았다.")
    lines.append("")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_all(snapshot, inventory, selector_rows, verdict, staging: Path):
    _write_summary(snapshot, inventory, selector_rows, verdict, staging)
    _write_camera_date_csv(inventory, staging)
    _write_selector_csv(selector_rows, staging)
    _write_identity_csv(inventory, staging)
    _write_report_md(snapshot, inventory, selector_rows, verdict, staging)


def _validate_written(staging: Path):
    required = ("summary.json", "camera_date_coverage.csv", "selector_time_coverage.csv",
               "identity_distribution.csv", "REPORT.md")
    for name in required:
        if not (staging / name).exists():
            raise AuditContractError(f"missing artifact after write: {name}")
    summary = json.loads((staging / "summary.json").read_text(encoding="utf-8"))
    if not summary.get("snapshot_id"):
        raise AuditContractError("summary.json missing snapshot_id")


def render_artifacts(snapshot: AuditSnapshot, output_dir, overwrite: bool = False) -> Path:
    snapshot = _finalize(snapshot)
    inventory = build_inventory_rows(snapshot, snapshot.policy_version)
    selector_rows = build_selector_rows(snapshot)
    verdict = evaluate_verdict(snapshot, inventory, selector_rows)

    output_dir = Path(output_dir)
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not overwrite:
        raise AuditContractError(f"output dir already exists (use --overwrite): {output_dir}")

    staging = Path(tempfile.mkdtemp(dir=parent, prefix=".s0-staging-"))
    try:
        _write_all(snapshot, inventory, selector_rows, verdict, staging)
        _validate_written(staging)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        os.rename(staging, output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output_dir


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Python Evidence Hybrid S0 coverage audit (read-only)")
    p.add_argument("--start", default=DEFAULT_START)
    p.add_argument("--as-of", required=True, help="required ISO-8601 timestamp (snapshot 고정)")
    p.add_argument("--policy-version", default=DEFAULT_POLICY)
    p.add_argument("--regular-selector-version", default=DEFAULT_REGULAR_SELECTOR)
    p.add_argument("--output", default="reports/python-evidence-s0-coverage-20260716")
    p.add_argument("--overwrite", action="store_true", default=False)
    return p


def _lab_head() -> str:
    try:
        import subprocess
        repo = Path(__file__).resolve().parent.parent
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
        return out.stdout.strip()[:12] if out.returncode == 0 else ""
    except Exception:
        return ""


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    start = parse_dt(args.start)
    as_of = parse_dt(args.as_of)

    from backend.supabase_client import get_supabase_client
    client = get_supabase_client()

    snapshot = load_snapshot(
        client, start, as_of, policy_version=args.policy_version,
        regular_selector_version=args.regular_selector_version, lab_head=_lab_head(),
    )
    inventory = build_inventory_rows(snapshot, snapshot.policy_version)
    selector_rows = build_selector_rows(snapshot)
    verdict = evaluate_verdict(snapshot, inventory, selector_rows)

    print(f"[audit] snapshot_id={snapshot.snapshot_id} verdict={verdict.label}", file=sys.stderr)
    print(f"[audit] eligible={inventory.total_eligible} any_prelabel={inventory.any_prelabel_count} "
          f"policy_ready={inventory.policy_ready_count} core_complete={inventory.core_complete_count}",
          file=sys.stderr)

    # 계약/쿼리 FAILURE(FK 단절·pagination 불일치·시간 파싱)는 load_snapshot 에서 예외로 abort → 산출물 0.
    # 반면 computed verdict(S0_HOLD 포함)는 감사의 정상 결과이므로 리포트를 남겨 사람이 검수하게 한다.
    render_artifacts(snapshot, args.output, overwrite=args.overwrite)
    print(f"[audit] wrote {args.output}", file=sys.stderr)

    if verdict.label == VERDICT_HOLD:
        for r in verdict.reasons:
            print(f"[hold] {r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
