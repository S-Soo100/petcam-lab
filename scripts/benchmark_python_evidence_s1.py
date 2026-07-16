"""Python Evidence S1 throughput benchmark — 메트릭 코어 + fail-closed 안전 가드.

## 무엇을 하나
동결된 32-clip manifest 를 A6/B12/CROI/DALL 조건 × cache mode(cold/warm) × device(mps/cpu)
로 paired 측정해 clip end-to-end p50/p95·capacity(clips/hour)·자원·안전 게이트를 낸다.
Mac mini 에서 nightly-reporter uv 환경으로 실행하며 **R2 read + 로컬 연산만**(DB write 0, VLM 0).

## 설계 원칙
- 무거운 의존(RF-DETR/OpenCV/boto3)은 top-level import 안 함 → 런타임 주입(injection).
  MacBook 단위 테스트는 fake 주입으로 순수하게 돈다.
- 안전 preflight(host·SHA·lock·25분창)는 **R2 GET·detector load·temp 생성 전에** 통과해야 한다.
- `time.perf_counter` + `resource.getrusage` + 로컬 디렉토리 byte 합산만. `psutil` 안 씀.
- 결과는 append-safe JSONL — 완료된 (clip,condition,device,cache_mode,repeat) 는 재실행 안 함.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.prepare_python_evidence_s1 import percentile

# ---- 동결 상수 (TEST-SHEET) ------------------------------------------------
EXPECTED_HOST = "baeg-endeuui-Macmini.local"
RUNTIME_BUDGET_S = 20 * 60          # 20분 hard budget
MIN_SAFE_WINDOW_MIN = 25.0          # 다음 예약 job 까지 최소 안전창
RSS_LIMIT_BYTES = 4 * 1024 ** 3     # peak RSS <= 4 GiB
DISK_LIMIT_BYTES = 2 * 1024 ** 3    # peak local temp disk <= 2 GiB
# H3: production activity-v1 gate_threshold 와 동일 (결과를 본 뒤 바꾸지 않는다)
DEFAULT_GATE_THRESHOLD = 0.10

CONDITIONS = ("A6", "B12", "CROI", "DALL")
DEVICES = ("mps", "cpu")
CACHE_MODES = ("cold_independent", "warm_same_run")

FORBIDDEN_ADAPTER_KEYS = frozenset({
    "vlm", "claude", "llm", "anthropic", "db_write", "supabase_write",
    "selector", "insert", "update", "delete", "upsert", "rpc",
})
ALLOWED_ADAPTER_KEYS = frozenset({
    "downloader", "resolve_r2_key", "detector_factory", "sample_frames",
    "extract_six", "extract_adaptive", "probe_duration", "motion_metrics",
    "assess_clip", "checkpoint_sha256", "policy", "clock", "monotonic",
})


class SafetyAbort(RuntimeError):
    """fail-closed 안전 위반 — R2/detector/temp 어떤 부작용도 내기 전에 멈춘다."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class DeadlineExceeded(RuntimeError):
    """20분 hard budget 초과."""


class BenchContractError(RuntimeError):
    """측정/집계 계약 위반(nonfinite·음수·빈 표본)."""


# --------------------------------------------------------------------------
# H1 — device 계약 래퍼 (lazy-load 이후 실제 device 검증)
# --------------------------------------------------------------------------

class DeviceContractDetector:
    """GeckoDetector 를 감싸 첫 detect() 에서 실제 model device 를 검증한다.

    - 요청 device 와 다르면 SafetyAbort("device_mismatch") — 잘못된 device 로 결과 기록 금지.
    - model.device 속성 없으면 SafetyAbort("device_check_failed") — fail-closed.
    - 검증은 첫 호출 1회만 수행(lazy-load 완료 후 확인).
    """

    def __init__(self, inner, requested: str):
        self._inner = inner
        self._requested = requested.split(":")[0].lower()  # "mps:0" → "mps"
        self._verified = False

    def detect(self, frame):
        if not self._verified:
            self._check_device()
            self._verified = True
        return self._inner.detect(frame)

    def _check_device(self):
        # 1차: RF-DETR 실제 경로 — inner._model.model.device (GeckoDetector._model = RFDETR 인스턴스)
        device_val = None
        _rfdetr = getattr(self._inner, "_model", None)
        if _rfdetr is not None:
            _torch_model = getattr(_rfdetr, "model", None)
            if _torch_model is not None:
                device_val = getattr(_torch_model, "device", None)
        # 2차 폴백: inner.device 직접 속성 (테스트 더블, 다른 래퍼)
        if device_val is None:
            device_val = getattr(self._inner, "device", None)
        if device_val is None:
            raise SafetyAbort(
                "device_check_failed",
                f"cannot find device (tried ._model.model.device and .device; "
                f"requested={self._requested!r})")
        actual_norm = str(device_val).split(":")[0].lower()
        if actual_norm != self._requested:
            raise SafetyAbort(
                "device_mismatch",
                f"model.device={device_val!r} != requested={self._requested!r}")

    def __getattr__(self, name):
        return getattr(self._inner, name)


# --------------------------------------------------------------------------
# 측정 레코드 (frozen = 결과 무결성)
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BenchRecord:
    clip_id: str
    camera_short: str
    condition: str
    device: str
    cache_mode: str
    repeat: int
    is_warmup: bool
    e2e_s: float
    download_s: float
    decode_s: float
    detector_s: float
    roi_flow_s: float = 0.0
    bytes_downloaded: int = 0
    downloads: int = 0
    peak_rss_bytes: int = 0
    temp_peak_bytes: int = 0
    roi_status: str = "ok"
    risk_control_only: bool = False
    frames_out: int = 0
    error_code: object = None  # str | None

    @property
    def key(self) -> tuple:
        return (self.clip_id, self.condition, self.device, self.cache_mode, self.repeat)

    def to_json(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# 순수 메트릭
# --------------------------------------------------------------------------

def _finite_pos(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0


def throughput_capacity(p95_e2e_s: float) -> float:
    """지속 처리 능력 clips/hour = 3600 / clip_e2e_p95."""
    if not _finite_pos(p95_e2e_s):
        raise BenchContractError(f"invalid p95 seconds: {p95_e2e_s!r}")
    return 3600.0 / float(p95_e2e_s)


def projected_four_camera_p95(observed_total_p95: float, observed_camera_count: int) -> float:
    if observed_camera_count <= 0:
        raise BenchContractError("observed_camera_count must be > 0")
    return observed_total_p95 * 4.0 / observed_camera_count


def aggregate(records) -> dict:
    """warmup 제외, (condition,device,cache_mode) 별 p50/p95·capacity·자원 집계."""
    # error 레코드(error_code!=None)는 timing 표본이 아니므로 percentile 에서 제외한다.
    measured = [r for r in records if not r.is_warmup and r.error_code is None]
    if not measured:
        raise BenchContractError("no measured (non-warmup) records to aggregate")
    for r in measured:
        v = r.e2e_s
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0:
            raise BenchContractError(f"nonfinite/negative e2e_s in {r.key}: {v!r}")

    groups: dict[tuple, list] = {}
    for r in measured:
        groups.setdefault((r.condition, r.device, r.cache_mode), []).append(r)

    out = {}
    for key, rs in groups.items():
        e2e = [r.e2e_s for r in rs]
        p95 = percentile(e2e, 95)
        out[key] = {
            "count": len(rs),
            "e2e_p50": percentile(e2e, 50),
            "e2e_p95": p95,
            "e2e_max": max(e2e),
            "capacity_per_hour": throughput_capacity(p95),
            "download_p95": percentile([r.download_s for r in rs], 95),
            "decode_p95": percentile([r.decode_s for r in rs], 95),
            "detector_p95": percentile([r.detector_s for r in rs], 95),
            "roi_flow_p95": percentile([r.roi_flow_s for r in rs], 95),
            "peak_rss_bytes": max(r.peak_rss_bytes for r in rs),
            "temp_peak_bytes": max(r.temp_peak_bytes for r in rs),
            "duplicate_downloads": sum(r.downloads for r in rs),
            "errors": [r.error_code for r in rs if r.error_code],
            "risk_control_only": all(r.risk_control_only for r in rs),
        }
    return out


# --------------------------------------------------------------------------
# fail-closed 안전 preflight
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PreflightInputs:
    hostname: str
    expected_host: str
    repo_head: str
    pinned_sha: str
    repo_dirty: bool
    activity_lock_busy: bool
    vlm_lock_busy: bool
    minutes_until_next_job: float
    min_safe_window_min: float = MIN_SAFE_WINDOW_MIN


def run_preflight(inp: PreflightInputs) -> None:
    """부작용 내기 전에 호출. 위반 시 SafetyAbort(code)."""
    if inp.hostname != inp.expected_host:
        raise SafetyAbort("wrong_host", f"{inp.hostname!r} != expected {inp.expected_host!r}")
    if inp.repo_head != inp.pinned_sha:
        raise SafetyAbort("head_mismatch", f"HEAD {inp.repo_head[:12]} != pinned {inp.pinned_sha[:12]}")
    if inp.repo_dirty:
        raise SafetyAbort("repo_dirty", "working tree has uncommitted changes")
    if inp.activity_lock_busy:
        raise SafetyAbort("activity_lock_busy", "activity worker lock held")
    if inp.vlm_lock_busy:
        raise SafetyAbort("vlm_lock_busy", "vlm worker lock held")
    if inp.minutes_until_next_job < inp.min_safe_window_min:
        raise SafetyAbort(
            "insufficient_window",
            f"{inp.minutes_until_next_job:.1f}min < {inp.min_safe_window_min:.1f}min")


# --------------------------------------------------------------------------
# 20분 hard deadline
# --------------------------------------------------------------------------

class Deadline:
    def __init__(self, budget_s: float = RUNTIME_BUDGET_S, clock=None):
        import time
        self._clock = clock or time.monotonic
        self._budget = float(budget_s)
        self._start = self._clock()

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining(self) -> float:
        return self._budget - self.elapsed()

    def exceeded(self) -> bool:
        return self.elapsed() >= self._budget

    def check(self) -> None:
        if self.exceeded():
            raise DeadlineExceeded(f"runtime budget {self._budget:.0f}s exceeded (elapsed {self.elapsed():.0f}s)")


# --------------------------------------------------------------------------
# temp 격리 (성공·예외·중단 모두 cleanup)
# --------------------------------------------------------------------------

@contextmanager
def scoped_tempdir(root=None):
    path = Path(tempfile.mkdtemp(prefix="pe_s1_", dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def dir_size_bytes(path) -> int:
    total = 0
    for p in Path(path).rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


# --------------------------------------------------------------------------
# 주입 어댑터 검증 (VLM/write 주입 금지)
# --------------------------------------------------------------------------

def validate_adapter_config(config: dict) -> None:
    for key in config:
        if key in FORBIDDEN_ADAPTER_KEYS or key not in ALLOWED_ADAPTER_KEYS:
            raise SafetyAbort("forbidden_adapter", f"adapter {key!r} not allowed in benchmark")


# --------------------------------------------------------------------------
# append-safe JSONL 결과 (resume)
# --------------------------------------------------------------------------

def append_record(path, record: BenchRecord) -> None:
    """한 measured 레코드를 JSONL 로 append + fsync (crash 이후 resume 안전)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.to_json(), separators=(",", ":"), ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def load_completed_keys(path) -> set:
    """이미 기록된 (clip,condition,device,cache_mode,repeat) 집합. corrupt 라인은 건너뛴다."""
    path = Path(path)
    keys: set = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                keys.add((d["clip_id"], d["condition"], d["device"], d["cache_mode"], d["repeat"]))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue  # crash 중 truncated 라인 tolerate
    return keys


# ==========================================================================
# 조건 어댑터 (A6 / B12 / CROI / DALL) + device
#   실제 nightly/gate 함수는 런타임에 주입한다. 여기 어댑터는 timing·계약만 담당.
# ==========================================================================

@dataclass(frozen=True, slots=True)
class AdapterResult:
    condition: str
    decode_s: float
    detector_s: float
    roi_flow_s: float
    frames_out: int
    roi_status: str
    risk_control_only: bool
    temp_peak_bytes: int = 0
    detections_total: int = 0
    roi_series_len: int = 0


def resolve_device(requested: str, *, torch_module) -> str:
    """요청 device 를 확정. MPS 요청인데 미가용이면 **CPU 로 눙치지 않고 중단**."""
    if requested == "cpu":
        return "cpu"
    if requested == "mps":
        try:
            ok = bool(torch_module.backends.mps.is_available())
        except AttributeError:
            ok = False
        if not ok:
            raise SafetyAbort("mps_unavailable", "MPS unavailable; refuse to report CPU as MPS")
        return "mps"
    raise BenchContractError(f"unknown device {requested!r}")


def robust_union_bbox(detections_per_frame, *, gecko_class: str = "gecko", conf_floor: float = 0.0):
    """B12 detector 출력에서만 gecko bbox 의 union 을 낸다. 없으면 None(→ no_bbox)."""
    boxes = []
    for dets in detections_per_frame:
        for d in dets:
            if getattr(d, "class_name", None) == gecko_class and getattr(d, "confidence", 0.0) >= conf_floor:
                boxes.append(d.xywh)
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def run_A6(video_path, *, extract_six, clock, temp_root=None) -> AdapterResult:
    """현행 6-frame 입력 경로(nightly vlm_frames.extract_six). Claude 호출 없음."""
    with scoped_tempdir(temp_root) as d:
        t0 = clock()
        paths = extract_six(video_path, d)
        t1 = clock()
        temp_peak = dir_size_bytes(d)
    return AdapterResult(
        condition="A6", decode_s=t1 - t0, detector_s=0.0, roi_flow_s=0.0,
        frames_out=len(paths), roi_status="n/a", risk_control_only=False, temp_peak_bytes=temp_peak)


def run_B12(video_path, *, sample_frames, detector, clock, num_frames: int = 12) -> AdapterResult:
    """sparse Gate 12-frame + detector. sampling/decode 와 detector 를 분리 측정."""
    t0 = clock()
    frames = sample_frames(video_path, num_frames)
    t1 = clock()
    t2 = clock()
    total = 0
    for _, fr in frames:
        total += len(detector.detect(fr))
    t3 = clock()
    return AdapterResult(
        condition="B12", decode_s=t1 - t0, detector_s=t3 - t2, roi_flow_s=0.0,
        frames_out=len(frames), roi_status="n/a", risk_control_only=False, detections_total=total)


def run_CROI(video_path, *, sample_frames, detector, dense_roi_flow, clock,
             num_frames: int = 12, gecko_class: str = "gecko", conf_floor: float = 0.0) -> AdapterResult:
    """B12 + bbox 내부 dense OpenCV flow. raw·의미 중립 series 만; 분류/threshold/head 없음."""
    t0 = clock()
    frames = sample_frames(video_path, num_frames)
    t1 = clock()
    t2 = clock()
    per_frame = [detector.detect(fr) for _, fr in frames]
    t3 = clock()
    bbox = robust_union_bbox(per_frame, gecko_class=gecko_class, conf_floor=conf_floor)
    if bbox is None:
        # no_bbox: dense ROI 비용 0. full frame 을 ROI 로 바꾸지 않는다.
        return AdapterResult(
            condition="CROI", decode_s=t1 - t0, detector_s=t3 - t2, roi_flow_s=0.0,
            frames_out=len(frames), roi_status="no_bbox", risk_control_only=False, roi_series_len=0)
    t4 = clock()
    series = dense_roi_flow(video_path, bbox)
    t5 = clock()
    return AdapterResult(
        condition="CROI", decode_s=t1 - t0, detector_s=t3 - t2, roi_flow_s=t5 - t4,
        frames_out=len(frames), roi_status="ok", risk_control_only=False, roi_series_len=len(series))


def run_DALL(video_path, *, decode_seq, detector, deadline, clock, in_reduced: bool) -> AdapterResult:
    """위험 대조군: 모든 frame 에 detector. 한 프레임씩 decode→infer→release (전량 보유 금지)."""
    if not in_reduced:
        raise BenchContractError("DALL is reduced-manifest-only (risk control)")
    decode_s = 0.0
    detector_s = 0.0
    frames_out = 0
    it = iter(decode_seq(video_path))
    while True:
        ta = clock()
        try:
            frame = next(it)
        except StopIteration:
            break
        tb = clock()
        deadline.check()          # 매 프레임 hard deadline
        detector.detect(frame)
        tc = clock()
        decode_s += tb - ta
        detector_s += tc - tb
        frames_out += 1
        frame = None              # 즉시 release — 전체 프레임을 붙잡지 않는다
    return AdapterResult(
        condition="DALL", decode_s=decode_s, detector_s=detector_s, roi_flow_s=0.0,
        frames_out=frames_out, roi_status="n/a", risk_control_only=True)


# ==========================================================================
# 다운로드 재사용 + end-to-end 러너 (Task 4)
# ==========================================================================

CROSS_PROCESS_CACHE_STATUS = "not_run_design_required"


class TransientDownloadError(RuntimeError):
    """bounded read 에러 — 유한 재시도만. 소진 시 systemic 으로 승격."""


class SystemicFailure(RuntimeError):
    """detector/R2 계통 실패 — run 을 중단한다(단일 clip 실패와 구분)."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: object
    download_s: float
    bytes: int
    downloads: int
    # r2_key 는 담지 않는다(redaction).


@dataclass(frozen=True, slots=True)
class ClipSpec:
    clip_id: str
    camera_short: str
    bbox_stratum: str
    duration_sec: float
    quartile: int
    in_reduced: bool


def clips_from_manifest(manifest: dict) -> list:
    return [ClipSpec(c["clip_id"], c["camera_short"], c["bbox_stratum"],
                     c["duration_sec"], c["quartile"], c["in_reduced"]) for c in manifest["clips"]]


class DownloadManager:
    """cold_independent = 매번 다운로드, warm_same_run = clip 당 1회 후 재사용(프로세스 내).

    cross_process_cache 는 설계 전이므로 실행 자체를 거부한다.
    """

    def __init__(self, downloader, mode: str, clock, *, max_retries: int = 3):
        self.downloader = downloader
        self.mode = mode
        self.clock = clock
        self.max_retries = max_retries
        self._cache: dict = {}
        self.total_downloads = 0
        self.cross_process_cache_enabled = False  # 계약상 절대 True 안 됨

    def get(self, clip_id: str, r2_key: str, dest_dir) -> DownloadResult:
        if self.mode == "cross_process_cache":
            raise BenchContractError(f"cross_process_cache {CROSS_PROCESS_CACHE_STATUS}")
        if self.mode == "warm_same_run" and clip_id in self._cache:
            path, size = self._cache[clip_id]
            return DownloadResult(path=path, download_s=0.0, bytes=0, downloads=0)  # reuse
        dest = Path(dest_dir) / f"{clip_id}.mp4"
        t0 = self.clock()
        size = self._download_with_retry(r2_key, dest)
        t1 = self.clock()
        self.total_downloads += 1
        if self.mode == "warm_same_run":
            self._cache[clip_id] = (dest, size)
        return DownloadResult(path=dest, download_s=t1 - t0, bytes=size, downloads=1)

    def _download_with_retry(self, r2_key: str, dest) -> int:
        last = None
        for _ in range(self.max_retries):
            try:
                self.downloader(r2_key, dest)  # nightly download_clip(r2_key, dest)
                return Path(dest).stat().st_size if Path(dest).exists() else 0
            except TransientDownloadError as e:  # bounded read 만 재시도
                last = e
                continue
        raise last  # 무한 재시도 없음


def rotate_conditions(conditions, repeat_index: int) -> list:
    """반복마다 조건 순서를 회전해 condition-order bias 를 줄인다."""
    conditions = list(conditions)
    if not conditions:
        return conditions
    i = repeat_index % len(conditions)
    return conditions[i:] + conditions[:i]


def plan_passes(cache_modes, warmup: int, repeats: int) -> list:
    """(cache_mode, repeat_index, is_warmup) 목록. cross_process 는 포함하지 않는다."""
    passes = []
    for cm in cache_modes:
        for w in range(warmup):
            passes.append((cm, w, True))
        for r in range(1, repeats + 1):
            passes.append((cm, r, False))
    return passes


def should_run(clip: ClipSpec, condition: str, device: str) -> bool:
    """DALL·CPU 는 reduced 16 에서만. MPS 전체 workload."""
    if condition == "DALL" and not clip.in_reduced:
        return False
    if device == "cpu" and not clip.in_reduced:
        return False
    return True


def count_media_files(root) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    exts = {".mp4", ".jpg", ".jpeg", ".png", ".mov", ".mkv", ".avi"}
    return sum(1 for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def scan_media(roots) -> dict:
    """최종 acceptance: 여러 temp root 의 media 파일 수. 0 이어야 한다."""
    return {str(r): count_media_files(r) for r in roots}


def _sanitize_error(exc: BaseException) -> str:
    return type(exc).__name__  # 메시지(경로·key) 누출 방지, 타입명만


def _build_record(clip, cond, *, device, cache_mode, repeat, is_warmup, dl, res, rusage_fn,
                  error_code, dest_dir_peak: int = 0):
    """dest_dir_peak = 다운로드 직후 dest_dir 전체 크기(원본 MP4 포함). H2 정직성 계약."""
    if res is not None:
        e2e = dl.download_s + res.decode_s + res.detector_s + res.roi_flow_s
        return BenchRecord(
            clip_id=clip.clip_id, camera_short=clip.camera_short, condition=cond, device=device,
            cache_mode=cache_mode, repeat=repeat, is_warmup=is_warmup, e2e_s=e2e,
            download_s=dl.download_s, decode_s=res.decode_s, detector_s=res.detector_s,
            roi_flow_s=res.roi_flow_s, bytes_downloaded=dl.bytes, downloads=dl.downloads,
            peak_rss_bytes=rusage_fn(),
            temp_peak_bytes=dest_dir_peak + res.temp_peak_bytes,  # MP4 + 어댑터 산출물
            roi_status=res.roi_status, risk_control_only=res.risk_control_only,
            frames_out=res.frames_out, error_code=None)
    return BenchRecord(
        clip_id=clip.clip_id, camera_short=clip.camera_short, condition=cond, device=device,
        cache_mode=cache_mode, repeat=repeat, is_warmup=is_warmup, e2e_s=0.0,
        download_s=(dl.download_s if dl else 0.0), decode_s=0.0, detector_s=0.0, roi_flow_s=0.0,
        bytes_downloaded=(dl.bytes if dl else 0), downloads=(dl.downloads if dl else 0),
        peak_rss_bytes=rusage_fn(),
        temp_peak_bytes=dest_dir_peak,  # 다운로드 완료됐다면 MP4 크기 반영 (0 숨김 금지)
        roi_status="error",
        risk_control_only=(cond == "DALL"), frames_out=0, error_code=error_code)


def _run_one(clip, cond, *, dest_dir, cache_mode, manager, adapters, resolve_r2_key, device,
             repeat, is_warmup, rusage_fn, consecutive, max_consecutive_failures):
    dl = None
    res = None
    error_code = None
    dest_dir_peak = 0  # H2: 다운로드 직후 dest_dir 전체 크기 (원본 MP4 포함)
    try:
        r2_key = resolve_r2_key(clip.clip_id)          # 런타임 read-only 재조회
        dl = manager.get(clip.clip_id, r2_key, dest_dir)
        dest_dir_peak = dir_size_bytes(dest_dir)       # 원본 MP4 측정 — 어댑터 실행 전
        res = adapters[cond](dl.path)
        consecutive = 0
    except (DeadlineExceeded, SystemicFailure):
        raise
    except TransientDownloadError as e:                # 재시도 소진 = 계통 실패
        raise SystemicFailure(f"download exhausted for {cond}") from e
    except Exception as e:                             # 단일 clip 실패 → sanitize + 계속
        error_code = _sanitize_error(e)
        consecutive += 1
        if consecutive >= max_consecutive_failures:
            raise SystemicFailure(f"{consecutive} consecutive clip failures") from e
    rec = _build_record(clip, cond, device=device, cache_mode=cache_mode, repeat=repeat,
                        is_warmup=is_warmup, dl=dl, res=res, rusage_fn=rusage_fn,
                        error_code=error_code, dest_dir_peak=dest_dir_peak)
    return rec, consecutive


def run_pass(clips, conditions, *, cache_mode, manager, adapters, resolve_r2_key, deadline,
             device, temp_root, repeat, is_warmup, rusage_fn, max_consecutive_failures=5,
             result_log=None, completed=None) -> list:
    """한 (cache_mode, repeat) 패스. cold=조건별 temp 격리, warm=clip 별 temp 격리(재사용).

    - 매 (clip,condition) 전에 hard deadline 확인.
    - 단일 clip 실패는 sanitized error 로 계속, systemic/deadline 은 중단.
    - result_log 있으면 append(resume 안전), completed 키는 건너뜀.
    """
    records = []
    consecutive = 0
    completed = completed or set()

    def _emit(rec):
        records.append(rec)
        if result_log is not None:
            append_record(result_log, rec)

    if cache_mode == "warm_same_run":
        for clip in clips:
            with scoped_tempdir(temp_root) as clip_dir:  # clip-scope: 다운로드 재사용 유효
                for cond in conditions:
                    if not should_run(clip, cond, device):
                        continue
                    deadline.check()
                    key = (clip.clip_id, cond, device, cache_mode, repeat)
                    if key in completed:
                        continue
                    rec, consecutive = _run_one(
                        clip, cond, dest_dir=clip_dir, cache_mode=cache_mode, manager=manager,
                        adapters=adapters, resolve_r2_key=resolve_r2_key, device=device,
                        repeat=repeat, is_warmup=is_warmup, rusage_fn=rusage_fn,
                        consecutive=consecutive, max_consecutive_failures=max_consecutive_failures)
                    _emit(rec)
    else:  # cold_independent
        for clip in clips:
            for cond in conditions:
                if not should_run(clip, cond, device):
                    continue
                deadline.check()
                key = (clip.clip_id, cond, device, cache_mode, repeat)
                if key in completed:
                    continue
                with scoped_tempdir(temp_root) as cond_dir:  # condition-scope: 독립
                    rec, consecutive = _run_one(
                        clip, cond, dest_dir=cond_dir, cache_mode=cache_mode, manager=manager,
                        adapters=adapters, resolve_r2_key=resolve_r2_key, device=device,
                        repeat=repeat, is_warmup=is_warmup, rusage_fn=rusage_fn,
                        consecutive=consecutive, max_consecutive_failures=max_consecutive_failures)
                _emit(rec)
    return records


def run_benchmark(clips, *, conditions, cache_modes, adapters, manager_factory, resolve_r2_key,
                  device, temp_root, deadline, rusage_fn, result_log=None, warmup=1, repeats=3,
                  completed=None, temp_check=True) -> list:
    """모든 (cache_mode, repeat) 패스를 조건 순서 회전과 함께 실행. warm cache 는 패스 단위."""
    completed = completed or set()
    all_recs = []
    for cache_mode, repeat, is_warmup in plan_passes(cache_modes, warmup, repeats):
        conds = rotate_conditions(conditions, repeat)
        manager = manager_factory(cache_mode)  # 패스마다 새 매니저 = warm cache 는 패스 안에서만
        recs = run_pass(
            clips, conds, cache_mode=cache_mode, manager=manager, adapters=adapters,
            resolve_r2_key=resolve_r2_key, deadline=deadline, device=device, temp_root=temp_root,
            repeat=repeat, is_warmup=is_warmup, rusage_fn=rusage_fn, result_log=result_log,
            completed=completed)
        all_recs.extend(recs)
        if temp_check:
            leaked = count_media_files(temp_root)
            if leaked:
                raise BenchContractError(f"temp media leak after {cache_mode}/{repeat}: {leaked} files")
    return all_recs


def evaluate_s1_gates(aggregate_cells, projected_4cam_p95, *, rss_limit=RSS_LIMIT_BYTES,
                      disk_limit=DISK_LIMIT_BYTES, gate_cache_mode="cold_independent") -> dict:
    """aggregate 로부터 판정 가능한 게이트(throughput·RSS·disk). service/temp0/deadline 은 별도.

    게이트 정본 = CROI·mps·cold_independent (TEST-SHEET §5, 중복 다운로드 포함 실태).
    """
    croi_key = ("CROI", "mps", gate_cache_mode)
    if croi_key not in aggregate_cells:
        raise BenchContractError(f"missing gate cell {croi_key} (fail-closed)")
    capacity = aggregate_cells[croi_key]["capacity_per_hour"]
    required = projected_4cam_p95 * 2.0
    peak_rss = max((c.get("peak_rss_bytes", 0) for c in aggregate_cells.values()), default=0)
    peak_disk = max((c.get("temp_peak_bytes", 0) for c in aggregate_cells.values()), default=0)
    throughput_pass = capacity >= required
    rss_pass = peak_rss <= rss_limit
    disk_pass = peak_disk <= disk_limit
    return {
        "gate_cache_mode": gate_cache_mode,
        "croi_mps_capacity": capacity,
        "required_capacity": required,
        "throughput_ratio": (capacity / projected_4cam_p95) if projected_4cam_p95 > 0 else float("inf"),
        "throughput_pass": bool(throughput_pass),
        "peak_rss_bytes": peak_rss, "rss_limit_bytes": rss_limit, "rss_pass": bool(rss_pass),
        "peak_temp_bytes": peak_disk, "disk_limit_bytes": disk_limit, "disk_pass": bool(disk_pass),
        "all_pass": bool(throughput_pass and rss_pass and disk_pass),
    }


# ==========================================================================
# 런타임 wiring + main (Mac mini 전용 — 유닛테스트 없음, compile + Mac mini 검증)
#   무거운 의존(reporter.*, gecko_vision_gate.*, torch, cv2, boto3)은 여기서만 lazy import.
# ==========================================================================

def _normalize_host(h: str) -> str:
    return (h or "").strip().lower().removesuffix(".local")


def _repo_git_state(repo_dir):
    import subprocess
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir,
                          capture_output=True, text=True).stdout.strip()
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir,
                               capture_output=True, text=True).stdout.strip()
    return head, bool(porcelain)


def _rusage_peak_rss():
    import resource
    # macOS: ru_maxrss 는 bytes (Linux 는 KB). Mac mini = macOS → bytes.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _make_dense_roi_flow(stride: int = 1):
    """bbox 내부 raw grayscale absdiff magnitude 시계열(의미 중립). 분류/threshold 없음."""
    def dense_roi_flow(video_path, bbox):
        import cv2
        import numpy as np
        x, y, w, h = (int(v) for v in bbox)
        cap = cv2.VideoCapture(str(video_path))
        series = []
        prev = None
        idx = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if stride > 1 and (idx % stride):
                    idx += 1
                    continue
                idx += 1
                fh, fw = frame.shape[:2]
                x0, y0 = max(0, min(x, fw - 1)), max(0, min(y, fh - 1))
                x1, y1 = max(x0 + 1, min(x + w, fw)), max(y0 + 1, min(y + h, fh))
                roi = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
                if prev is not None and prev.shape == roi.shape:
                    series.append(float(np.mean(cv2.absdiff(prev, roi))))
                prev = roi
        finally:
            cap.release()
        return series
    return dense_roi_flow


def _make_decode_seq():
    """DALL: 한 프레임씩 yield (전량 보유 금지)."""
    def decode_seq(video_path):
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame
        finally:
            cap.release()
    return decode_seq


def _make_detector(device: str, checkpoint: str, model_size: str,
                   threshold: float = DEFAULT_GATE_THRESHOLD):
    """RF-DETR 기반 GeckoDetector 생성 — H1/H3 계약 준수.

    H1: GeckoDetector 생성자에는 지원하는 인자만 전달 (device 제외 — 계약 없음).
        benchmark-local 서브클래스가 _ensure_loaded 에서 RFDETR.from_checkpoint(...,
        device=requested_device) 로 명시 로드. Gate production 코드는 건드리지 않는다.
        lazy-load 이후 실제 _model.model.device 를 DeviceContractDetector 가 검증.
    H3: threshold=DEFAULT_GATE_THRESHOLD(0.10) 로 production 정합.
    """
    import importlib
    import torch
    from gecko_vision_gate.detector import GeckoDetector

    resolve_device(device, torch_module=torch)  # MPS 미가용이면 fail-closed

    _ckpt = checkpoint or None
    _device = device  # closure 캡처

    class _BenchmarkGeckoDetector(GeckoDetector):
        """Benchmark-local 서브클래스: _ensure_loaded 에서 RF-DETR를 명시 device 로 로드.

        Gate production GeckoDetector 코드를 수정하지 않는다.
        checkpoint 없을 때는 부모 _ensure_loaded 폴백(COCO pretrained, device 미지정).
        """

        def _ensure_loaded(self):
            if self._model is not None:
                return
            rfdetr = importlib.import_module("rfdetr")
            if self.checkpoint:
                # 명시 device 로드 — 부모는 device 인자 없이 로드하므로 여기서만 지정
                self._model = rfdetr.RFDETR.from_checkpoint(
                    str(self.checkpoint), device=_device)
                try:
                    self._model.optimize_for_inference()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._names = {
                        i: str(n)
                        for i, n in enumerate(self._model.class_names or [])
                    }
                except Exception:  # noqa: BLE001
                    self._names = {}
            else:
                # checkpoint 없음 → 부모 _ensure_loaded (COCO pretrained, device 미지정)
                super()._ensure_loaded()

    det = _BenchmarkGeckoDetector(
        model_size=model_size,
        checkpoint=_ckpt,
        threshold=threshold,
    )
    # lazy-load 이후 실제 _model.model.device 불일치는 DeviceContractDetector 가 처리
    return DeviceContractDetector(det, requested=device)


def _make_r2_downloader():
    def downloader(r2_key, dest):
        from reporter.r2 import download_clip
        try:
            return download_clip(r2_key, dest)
        except Exception as e:  # bounded read/connection 만 transient 로 승격
            name = type(e).__name__
            if name in ("ReadTimeoutError", "ConnectTimeoutError", "EndpointConnectionError",
                        "ConnectionError", "IncompleteReadError", "TimeoutError", "ProtocolError"):
                raise TransientDownloadError(name) from e
            raise
    return downloader


def _make_resolve_r2_key(client):
    def resolve(clip_id):
        resp = client.table("motion_clips").select("r2_key").eq("id", clip_id).limit(1).execute()
        data = getattr(resp, "data", None) or []
        if not data or not data[0].get("r2_key"):
            raise BenchContractError(f"no r2_key for clip {clip_id[:8]}")
        return data[0]["r2_key"]
    return resolve


def build_adapters(device: str, *, checkpoint: str, model_size: str, deadline,
                   threshold: float = DEFAULT_GATE_THRESHOLD) -> dict:
    import time
    from reporter.vlm_frames import extract_six as _extract_six
    from gecko_vision_gate.frame_sampling import sample_frames as _sample_frames

    detector = _make_detector(device, checkpoint, model_size, threshold=threshold)
    dense = _make_dense_roi_flow()
    decode_seq = _make_decode_seq()
    clock = time.perf_counter

    return {
        "A6": lambda p: run_A6(p, extract_six=_extract_six, clock=clock),
        "B12": lambda p: run_B12(p, sample_frames=_sample_frames, detector=detector, clock=clock),
        "CROI": lambda p: run_CROI(p, sample_frames=_sample_frames, detector=detector,
                                   dense_roi_flow=dense, clock=clock),
        "DALL": lambda p: run_DALL(p, decode_seq=decode_seq, detector=detector,
                                   deadline=deadline, clock=clock, in_reduced=True),
    }


def write_summary(records, *, projected_4cam_p95, out_path, meta) -> dict:
    agg = aggregate(records)
    cells = {f"{c}|{d}|{cm}": v for (c, d, cm), v in agg.items()}
    try:
        gates = evaluate_s1_gates(agg, projected_4cam_p95)
    except BenchContractError as e:
        gates = {"incomplete": True, "reason": str(e)}
    summary = {
        "schema": "python-evidence-s1-summary-v1",
        "meta": meta,
        "projected_4_camera_p95": projected_4cam_p95,
        "cross_process_cache": CROSS_PROCESS_CACHE_STATUS,
        "cells": cells,
        "gates": gates,
        "error_records": [r.to_json() for r in records if r.error_code],
    }
    Path(out_path).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _build_parser():
    import argparse
    p = argparse.ArgumentParser(description="Python Evidence S1 throughput benchmark (Mac mini, read-only).")
    p.add_argument("--manifest", required=True, help="frozen sample_manifest.json")
    p.add_argument("--influx", required=True, help="frozen influx_snapshot.json")
    p.add_argument("--pinned-sha", required=True, help="feature branch SHA (fail-closed vs HEAD)")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--device", choices=["mps", "cpu"], default="mps")
    p.add_argument("--checkpoint", default="", help="gate fine-tune .pth (필수: gecko bbox 생성)")
    p.add_argument("--model-size", default="nano")
    p.add_argument("--window-minutes", type=float, default=0.0, help="다음 예약 job 까지 분(probed)")
    p.add_argument("--activity-lock-free", action="store_true")
    p.add_argument("--vlm-lock-free", action="store_true")
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--budget-s", type=float, default=RUNTIME_BUDGET_S)
    p.add_argument("--expected-host", default=EXPECTED_HOST)
    p.add_argument("--dry-run", action="store_true", help="preflight+deps 만, 벤치마크 load 미실행")
    p.add_argument("--verify-deps", action="store_true", help="import·checkpoint sha·device 확인 후 종료")
    p.add_argument("--resume", action="store_true", help="raw_results.jsonl 완료 키 건너뜀")
    p.add_argument("--threshold", type=float, default=DEFAULT_GATE_THRESHOLD,
                   help=f"GeckoDetector confidence threshold (default={DEFAULT_GATE_THRESHOLD}; "
                        "결과를 본 뒤 바꾸지 않는다 — H3 provenance)")
    return p


def main(argv=None) -> int:
    import socket
    import sys
    args = _build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = Path(__file__).resolve().parent.parent

    if args.verify_deps:
        return _verify_deps(args)

    # ---- fail-closed preflight (부작용 전) ----
    head, dirty = _repo_git_state(repo_dir)
    inp = PreflightInputs(
        hostname=_normalize_host(socket.gethostname()),
        expected_host=_normalize_host(args.expected_host),
        repo_head=head, pinned_sha=args.pinned_sha, repo_dirty=dirty,
        activity_lock_busy=not args.activity_lock_free,
        vlm_lock_busy=not args.vlm_lock_free,
        minutes_until_next_job=args.window_minutes)
    try:
        run_preflight(inp)
    except SafetyAbort as e:
        # 부작용(R2/detector/temp) 전에 fail-closed. 2 = preflight HOLD/REJECT.
        print(f"[bench] preflight abort code={e.code} :: {e}", file=sys.stderr)
        return 2
    print(f"[bench] preflight OK host={inp.hostname} head={head[:12]} "
          f"window={args.window_minutes}min device={args.device}", file=sys.stderr)

    if args.dry_run:
        print("[bench] dry-run: preflight passed, benchmark load skipped.", file=sys.stderr)
        return 0

    # ---- device·adapters·data ----
    deadline = Deadline(budget_s=args.budget_s)
    adapters = build_adapters(args.device, checkpoint=args.checkpoint,
                              model_size=args.model_size, deadline=deadline,
                              threshold=args.threshold)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    influx = json.loads(Path(args.influx).read_text(encoding="utf-8"))
    projected = influx["projected_4_camera_p95"]
    all_clips = clips_from_manifest(manifest)
    clips = all_clips if args.device == "mps" else [c for c in all_clips if c.in_reduced]

    from backend.supabase_client import get_supabase_client
    client = get_supabase_client()
    resolve_r2_key = _make_resolve_r2_key(client)
    downloader = _make_r2_downloader()

    def manager_factory(cache_mode):
        import time
        return DownloadManager(downloader, cache_mode, time.perf_counter)

    result_log = out_dir / "raw_results.jsonl"
    completed = load_completed_keys(result_log) if args.resume else set()

    leaked = -1
    try:
        with scoped_tempdir() as temp_root:  # 예외·중단·정상 모두 cleanup
            run_benchmark(
                clips, conditions=CONDITIONS, cache_modes=CACHE_MODES, adapters=adapters,
                manager_factory=manager_factory, resolve_r2_key=resolve_r2_key, device=args.device,
                temp_root=str(temp_root), deadline=deadline, rusage_fn=_rusage_peak_rss,
                result_log=str(result_log), warmup=args.warmup, repeats=args.repeats, completed=completed)
            leaked = count_media_files(temp_root)
    except DeadlineExceeded as e:
        # 20분 hard budget 초과 → cleanup(위 context 종료) 후 부분 summary + HOLD.
        print(f"[bench] HOLD_RUNTIME_BUDGET :: {e}", file=sys.stderr)
        partial = _reload_records(result_log)
        write_summary(partial, projected_4cam_p95=projected, out_path=out_dir / "summary.json",
                      meta={"host": inp.hostname, "device": args.device, "pinned_sha": args.pinned_sha,
                            "deadline_exceeded": True, "verdict_hint": "S1_HOLD_RUNTIME_BUDGET",
                            "record_count": len(partial), "gate_threshold": args.threshold})
        return 3

    all_records = _reload_records(result_log)
    meta = {
        "host": inp.hostname, "device": args.device, "pinned_sha": args.pinned_sha,
        "manifest_sha256": _file_sha(args.manifest), "influx_sha256": _file_sha(args.influx),
        "clips": len(clips), "record_count": len(all_records), "temp_leak_after": leaked,
        "budget_s": args.budget_s, "warmup": args.warmup, "repeats": args.repeats,
        "gate_threshold": args.threshold,  # H3 provenance — 결과를 본 뒤 바꾸지 않는다
    }
    summary = write_summary(all_records, projected_4cam_p95=projected,
                            out_path=out_dir / "summary.json", meta=meta)
    gates = summary.get("gates", {})
    print(f"[bench] records={len(all_records)} temp_leak={leaked} "
          f"croi_capacity={gates.get('croi_mps_capacity')} ratio={gates.get('throughput_ratio')} "
          f"all_pass={gates.get('all_pass')}", file=sys.stderr)
    return 0


def _file_sha(path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reload_records(result_log) -> list:
    """raw JSONL 을 BenchRecord 로 복원(resume/최종 집계용)."""
    records = []
    p = Path(result_log)
    if not p.exists():
        return records
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.append(BenchRecord(**d))
    return records


def _verify_deps(args) -> int:
    import sys
    problems = []
    try:
        import torch
        mps = bool(torch.backends.mps.is_available())
    except Exception as e:  # noqa: BLE001
        problems.append(f"torch import: {type(e).__name__}")
        mps = False
    for mod in ("reporter.vlm_frames", "reporter.r2", "gecko_vision_gate.frame_sampling",
                "gecko_vision_gate.detector"):
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001
            problems.append(f"import {mod}: {type(e).__name__}")
    ckpt_sha = ""
    if args.checkpoint:
        try:
            from gecko_vision_gate.provenance import checkpoint_sha256
            ckpt_sha = checkpoint_sha256(args.checkpoint)
        except Exception as e:  # noqa: BLE001
            problems.append(f"checkpoint sha: {type(e).__name__}")
    print(f"[verify] mps_available={mps} checkpoint_sha256={ckpt_sha[:16]} "
          f"device_request={args.device}", file=sys.stderr)
    if args.device == "mps" and not mps:
        problems.append("mps requested but unavailable")
    for p in problems:
        print(f"[verify][FAIL] {p}", file=sys.stderr)
    return 0 if not problems else 3


if __name__ == "__main__":
    raise SystemExit(main())
