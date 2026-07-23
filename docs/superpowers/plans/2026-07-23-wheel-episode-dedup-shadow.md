# P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow — 구현 계획

> **구현 방식 (CAOF):** Critical 트랙. 이 계획을 task 단위 TDD 로 구현한다(메인 직접 구현). Steps use checkbox (`- [ ]`).
> **시험지(동결):** [`experiments/wheel-episode-dedup-shadow/TEST-SHEET.md`](../../../experiments/wheel-episode-dedup-shadow/TEST-SHEET.md)
> **설계 정본:** [`docs/superpowers/specs/2026-07-23-wheel-episode-dedup-design.md`](../specs/2026-07-23-wheel-episode-dedup-design.md)

**Goal:** P4 Cam(dev)(별칭 "P4 Cam 1") 반복 쳇바퀴 clip 을 read-only 로 중복 묶음 후보로 접고 대표 ≤3 을 뽑는 shadow artifact 를 만든다. production write·VLM·라벨링 웹 변경 0.

**Architecture:** 순수 결정론 모듈(signatures/grouping/representatives/cohort)을 TDD 로 만들고, 오케스트레이터(`run_wheel_shadow.py`)가 production DB SELECT + R2 GET + ffmpeg 프레임 추출로 시그니처를 채워 grouping → artifact 를 쓴다. 시간은 외곽 경계(≤10분)로만, 실제 묶음은 wheel ROI temporal motion + perceptual similarity 로 결정한다(precision-first).

**Tech Stack:** Python 3.12 · OpenCV(cv2) · numpy · boto3(R2, read-only) · supabase-py(SELECT-only) · ffmpeg · pytest.

---

## 안전 계약 (모든 task 공통 — 위반 시 즉시 중단)

- DB: `client.table(...).select(...)` **오직 SELECT**. `.insert/.update/.delete/.rpc(write)` 금지.
- R2: `head_object`/`get_object` **오직 read**. `put_object`/`delete_object`/lifecycle 금지. signed URL 생성 안 함(있으면 로그·commit 금지).
- media: 모든 mp4/frame 은 `tempfile.TemporaryDirectory` 안에서만. 종료 시 0건.
- git: JSON/CSV/MD/`.gitignore` 만 commit. `*.png/*.jpg/*.mp4` 는 gitignore(ROI-PREVIEW 포함).
- VLM: Anthropic/Groq/local 호출 0.
- 기존 파일 수정 0 (전부 신규 파일). 라벨링 웹/backend/migration 불변.

---

## File Structure (전부 신규)

| 파일 | 책임 |
|---|---|
| `scripts/wheel_shadow/__init__.py` | 패키지 마커 |
| `scripts/wheel_shadow/signatures.py` | ROI crop · IR/day mode · ROI motion 시계열/요약 · dHash · hamming · `ClipSignature` |
| `scripts/wheel_shadow/grouping.py` | 시간-run 분할 · wheel-active 게이트 · anchor precision-first 클러스터 · `Group`/`GroupingParams` |
| `scripts/wheel_shadow/representatives.py` | 대표 ≤3 선택 (evidence/motion/novelty) |
| `scripts/wheel_shadow/cohort.py` | canonical SHA-256 · frozen cohort 조립(순수 부분) |
| `scripts/run_wheel_shadow.py` | 오케스트레이터: DB SELECT · R2 GET · ffmpeg · 시그니처 · grouping · artifact · temp 정리 · mutation fingerprint |
| `tests/test_wheel_shadow.py` | signatures/grouping/representatives/cohort 단위 테스트 (fake numpy frame + synthetic 시그니처, 네트워크 0) |
| `experiments/wheel-episode-dedup-shadow/.gitignore` | `*.png *.jpg *.jpeg *.mp4 _tmp/` (raw media 미추적) |

산출물(오케스트레이터가 생성): `frozen-cohort.json` · `wheel-roi-profile-v1.json` · `shadow-groups.json` · `BLIND-REVIEW.csv` · `EVIDENCE-AUDIT.json` · `REPORT.md` (+ gitignored `ROI-PREVIEW.png`).

---

## Task 0: scaffolding

**Context:**
- Depends on: 없음
- Inputs: 없음
- Outputs: 패키지 디렉토리 + experiment media gitignore
- Must know: experiment 디렉토리에 raw frame(ROI-PREVIEW.png)이 생기지만 **commit 금지**. 로컬 .gitignore 로 차단.
- Acceptance: `git status` 에서 media 패턴이 무시된다.

**Files:**
- Create: `scripts/wheel_shadow/__init__.py` (빈 파일)
- Create: `experiments/wheel-episode-dedup-shadow/.gitignore`

- [ ] **Step 1: 패키지 마커 생성**

`scripts/wheel_shadow/__init__.py`:
```python
"""P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow (순수 결정론 모듈)."""
```

- [ ] **Step 2: experiment media gitignore**

`experiments/wheel-episode-dedup-shadow/.gitignore`:
```
# raw media·frame·preview 는 커밋 금지 (테스트 계약: raw media tracked = 0)
*.png
*.jpg
*.jpeg
*.mp4
_tmp/
```

- [ ] **Step 3: 확인** — Run: `cd /Users/baek/petcam-lab/.worktrees/wheel-episode-dedup-shadow && printf 'x' > experiments/wheel-episode-dedup-shadow/ROI-PREVIEW.png && git status --porcelain experiments/wheel-episode-dedup-shadow/ROI-PREVIEW.png && rm experiments/wheel-episode-dedup-shadow/ROI-PREVIEW.png`
  Expected: 빈 출력(무시됨).

- [ ] **Step 4: Commit** — S0 에서 계획/시험지와 함께 commit.

---

## Task 1: signatures.py (결정론 프레임 시그니처)

**Context:**
- Depends on: Task 0
- Inputs: BGR numpy 프레임 리스트, `RoiBox`(normalized)
- Outputs: `RoiBox`, `crop_roi`, `ir_mode`, `roi_motion_series`, `motion_summary`, `dhash`, `hamming`, `ClipSignature`
- Must know: 모든 함수 결정론. 부동소수 요약은 `round(...,6)` 로 양자화(결정론 SHA 안정). dHash 는 이산(bit) → 프레임 동일하면 hash 동일.
- Acceptance: `uv run pytest tests/test_wheel_shadow.py -k signature -q` GREEN.

**Files:**
- Create: `scripts/wheel_shadow/signatures.py`
- Test: `tests/test_wheel_shadow.py`

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_wheel_shadow.py`)
```python
import numpy as np
from scripts.wheel_shadow import signatures as sig


def _solid(h, w, bgr):
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[:, :] = bgr
    return f


def test_signature_crop_roi_normalized():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[10:60, 40:140] = 255  # y 10..60, x 40..140
    roi = sig.RoiBox(x=0.2, y=0.1, w=0.5, h=0.5)  # x40..140, y10..60
    crop = sig.crop_roi(frame, roi)
    assert crop.shape == (50, 100, 3)
    assert crop.mean() == 255.0


def test_signature_ir_vs_day_mode():
    gray = [_solid(20, 20, (128, 128, 128)) for _ in range(3)]  # 무채색
    color = [_solid(20, 20, (10, 200, 30)) for _ in range(3)]   # 채도 높음
    assert sig.ir_mode(gray) == "ir"
    assert sig.ir_mode(color) == "day"


def test_signature_motion_series_and_summary():
    a = _solid(10, 10, (0, 0, 0))
    b = _solid(10, 10, (255, 255, 255))
    series = sig.roi_motion_series([a, b, a])  # 큰 변화 2회
    assert len(series) == 2
    assert series[0] > 0.9
    mean, peak, per = sig.motion_summary(series)
    assert peak >= mean > 0.0


def test_signature_dhash_identical_and_hamming():
    grad = np.tile(np.arange(9, dtype=np.uint8) * 28, (8, 1))
    h1 = sig.dhash(grad)
    h2 = sig.dhash(grad.copy())
    assert h1 == h2
    assert sig.hamming(h1, h2) == 0
    assert sig.hamming(0b1010, 0b0011) == 2
```

- [ ] **Step 2: 실패 확인** — Run: `cd /Users/baek/petcam-lab/.worktrees/wheel-episode-dedup-shadow && PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k signature -q`
  Expected: FAIL (module/함수 없음).

- [ ] **Step 3: 최소 구현** (`scripts/wheel_shadow/signatures.py`)
```python
"""결정론 프레임 시그니처 — VLM 없이 OpenCV/numpy 로만 계산."""
from __future__ import annotations

import dataclasses

import cv2
import numpy as np


@dataclasses.dataclass(frozen=True, slots=True)
class RoiBox:
    """normalized [0,1] 좌표. 해상도 독립 → 프로파일 재사용 가능."""
    x: float
    y: float
    w: float
    h: float

    def pixel_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        px = max(0, min(width - 1, int(round(self.x * width))))
        py = max(0, min(height - 1, int(round(self.y * height))))
        pw = max(1, int(round(self.w * width)))
        ph = max(1, int(round(self.h * height)))
        return px, py, min(pw, width - px), min(ph, height - py)


def crop_roi(frame: np.ndarray, roi: RoiBox) -> np.ndarray:
    h, w = frame.shape[:2]
    px, py, pw, ph = roi.pixel_box(w, h)
    return frame[py:py + ph, px:px + pw]


def ir_mode(frames: list[np.ndarray], sat_threshold: float = 20.0) -> str:
    """IR 야간 프레임은 거의 무채색 → HSV saturation 평균으로 판정."""
    sats = []
    for f in frames:
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        sats.append(float(hsv[:, :, 1].mean()))
    return "ir" if (sum(sats) / len(sats)) < sat_threshold else "day"


def roi_motion_series(roi_frames: list[np.ndarray]) -> tuple[float, ...]:
    """연속 ROI grayscale absdiff 평균 (0~1 정규화)."""
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in roi_frames]
    series: list[float] = []
    for a, b in zip(grays, grays[1:]):
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
        d = np.abs(a.astype(np.int16) - b.astype(np.int16)).mean() / 255.0
        series.append(round(float(d), 6))
    return tuple(series)


def motion_summary(series: tuple[float, ...]) -> tuple[float, float, float]:
    """(mean, peak, periodicity). periodicity = 최대 lag autocorr (0~1)."""
    if not series:
        return (0.0, 0.0, 0.0)
    arr = np.asarray(series, dtype=np.float64)
    mean = round(float(arr.mean()), 6)
    peak = round(float(arr.max()), 6)
    return (mean, peak, _peak_autocorr(arr))


def _peak_autocorr(arr: np.ndarray) -> float:
    if len(arr) < 4:
        return 0.0
    a = arr - arr.mean()
    denom = float((a * a).sum())
    if denom == 0.0:
        return 0.0
    best = 0.0
    for lag in range(1, len(a) // 2 + 1):
        c = float((a[:-lag] * a[lag:]).sum()) / denom
        best = max(best, c)
    return round(best, 6)


def dhash(gray_roi: np.ndarray, hash_size: int = 8) -> int:
    """difference hash — resize 후 인접 픽셀 대소 비교로 64bit."""
    small = cv2.resize(gray_roi, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(bool(v))
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclasses.dataclass(frozen=True, slots=True)
class ClipSignature:
    clip_id: str
    started_at: str
    duration_sec: float
    mode: str                 # 'ir' | 'day'
    roi_motion_mean: float
    roi_motion_peak: float
    roi_periodicity: float
    perceptual_hash: int
    evidence_quality: str     # 'ok' | 'degraded' | 'missing'
    evidence_score: float     # 대표 랭킹용 (높을수록 좋음)
    novelty: bool
    frames_used: int
```

- [ ] **Step 4: 통과 확인** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k signature -q`
  Expected: PASS.

---

## Task 2: grouping.py (precision-first 결정론 묶음)

**Context:**
- Depends on: Task 1 (`ClipSignature`, `hamming`), Task 3 는 `select_representatives` 를 제공하지만 grouping 은 함수 주입으로 결합(순환 import 회피).
- Inputs: `list[ClipSignature]`, `GroupingParams`, representative selector 콜러블
- Outputs: `GroupingParams`, `Group`, `group_clips(sigs, params, select_reps) -> (groups, ungrouped)`
- Must know: **overlap 0** = 한 clip 은 최대 1 그룹. 시간 ≤10분은 외곽 경계일 뿐, 실제 묶음은 wheel-active + 같은 mode + hamming≤thr + motion 근접. 애매하면 ungrouped. 정렬 `(started_at, clip_id)` 로 결정론.
- Acceptance: `uv run pytest tests/test_wheel_shadow.py -k grouping -q` GREEN.

**Files:**
- Create: `scripts/wheel_shadow/grouping.py`
- Test: `tests/test_wheel_shadow.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**
```python
from scripts.wheel_shadow import grouping as grp
from scripts.wheel_shadow.representatives import select_representatives
from scripts.wheel_shadow.signatures import ClipSignature


def _sig(cid, ts, mode="ir", mean=0.20, peak=0.30, ph=0, quality="ok", score=1.0, novelty=False):
    return ClipSignature(cid, ts, 30.0, mode, mean, peak, 0.7, ph, quality, score, novelty, 10)


def test_grouping_time_gap_splits_episodes():
    # 같은 시각대 유사 2개 + 20분 뒤 유사 2개 → 서로 다른 그룹
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b1111),
        _sig("b", "2026-07-19T03:01:00+00:00", ph=0b1111),
        _sig("c", "2026-07-19T03:21:00+00:00", ph=0b1111),
        _sig("d", "2026-07-19T03:22:00+00:00", ph=0b1111),
    ]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=4, motion_tolerance=0.1)
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert len(groups) == 2
    assert set(groups[0].member_clip_ids) == {"a", "b"}
    assert set(groups[1].member_clip_ids) == {"c", "d"}


def test_grouping_dissimilar_stays_ungrouped_no_overlap():
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b0000),
        _sig("b", "2026-07-19T03:01:00+00:00", ph=0b1111_1111),   # hamming 8 > thr → 안 묶임
        _sig("c", "2026-07-19T03:02:00+00:00", ph=0b0000),
    ]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=3, motion_tolerance=0.1)
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    members = [cid for g in groups for cid in g.member_clip_ids]
    assert len(members) == len(set(members))     # overlap 0
    assert set(groups[0].member_clip_ids) == {"a", "c"}
    assert "b" in ungrouped


def test_grouping_low_motion_or_missing_evidence_ungrouped():
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", mean=0.02),                 # 저모션
        _sig("b", "2026-07-19T03:01:00+00:00", quality="missing"),        # evidence 없음
        _sig("c", "2026-07-19T03:02:00+00:00", mean=0.02),
    ]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=4, motion_tolerance=0.1)
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert groups == []
    assert set(ungrouped) == {"a", "b", "c"}


def test_grouping_deterministic():
    import random
    base = [_sig(f"c{i}", f"2026-07-19T03:{i:02d}:00+00:00", ph=0b1010) for i in range(6)]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=4, motion_tolerance=0.1)
    shuffled = base[:]
    random.Random(7).shuffle(shuffled)
    g1, u1 = grp.group_clips(base, params, select_representatives)
    g2, u2 = grp.group_clips(shuffled, params, select_representatives)
    assert [g.member_clip_ids for g in g1] == [g.member_clip_ids for g in g2]
    assert u1 == u2
```

- [ ] **Step 2: 실패 확인** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k grouping -q`
  Expected: FAIL.

- [ ] **Step 3: 최소 구현** (`scripts/wheel_shadow/grouping.py`)
```python
"""precision-first 결정론 묶음 — 시간은 외곽 경계, 실제 묶음은 ROI motion + perceptual."""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from datetime import datetime

from .signatures import ClipSignature, hamming


@dataclasses.dataclass(frozen=True, slots=True)
class GroupingParams:
    max_gap_sec: float = 600.0        # 10분 외곽 경계 (단독 판정 신호 아님)
    wheel_motion_floor: float = 0.08  # ROI mean motion 하한 (wheel-active 게이트)
    hamming_threshold: int = 8        # dHash 근접 임계 (0~64)
    motion_tolerance: float = 0.08    # anchor 대비 ROI mean motion 허용차


@dataclasses.dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    mode: str
    member_clip_ids: tuple[str, ...]
    representative_clip_ids: tuple[str, ...]
    started_at_first: str
    started_at_last: str


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def _wheel_active(s: ClipSignature, p: GroupingParams) -> bool:
    return (
        s.evidence_quality == "ok"
        and not s.novelty
        and s.roi_motion_mean >= p.wheel_motion_floor
    )


def _similar(s: ClipSignature, anchor: ClipSignature, p: GroupingParams) -> bool:
    return (
        s.mode == anchor.mode
        and hamming(s.perceptual_hash, anchor.perceptual_hash) <= p.hamming_threshold
        and abs(s.roi_motion_mean - anchor.roi_motion_mean) <= p.motion_tolerance
    )


def group_clips(
    sigs: Sequence[ClipSignature],
    params: GroupingParams,
    select_reps: Callable[[list[ClipSignature]], tuple[str, ...]],
) -> tuple[list[Group], list[str]]:
    ordered = sorted(sigs, key=lambda s: (s.started_at, s.clip_id))
    runs: list[list[ClipSignature]] = []
    cur: list[ClipSignature] = []
    for s in ordered:
        if cur and _epoch(s.started_at) - _epoch(cur[-1].started_at) > params.max_gap_sec:
            runs.append(cur)
            cur = []
        cur.append(s)
    if cur:
        runs.append(cur)

    groups: list[Group] = []
    ungrouped: list[str] = []
    gi = 0
    for run in runs:
        groupable = [s for s in run if _wheel_active(s, params)]
        ungrouped.extend(s.clip_id for s in run if not _wheel_active(s, params))
        remaining = list(groupable)
        while remaining:
            # anchor = 최대 ROI motion peak, tie → 이른 시각 → clip_id
            anchor = sorted(
                remaining, key=lambda s: (-s.roi_motion_peak, s.started_at, s.clip_id)
            )[0]
            members = [s for s in remaining if _similar(s, anchor, params)]
            if len(members) >= 2:
                gi += 1
                members_sorted = sorted(members, key=lambda s: (s.started_at, s.clip_id))
                reps = select_reps(members)
                groups.append(
                    Group(
                        group_id=f"wheel_ep_{gi:03d}",
                        mode=anchor.mode,
                        member_clip_ids=tuple(m.clip_id for m in members_sorted),
                        representative_clip_ids=reps,
                        started_at_first=members_sorted[0].started_at,
                        started_at_last=members_sorted[-1].started_at,
                    )
                )
                remaining = [s for s in remaining if s not in members]
            else:
                ungrouped.append(anchor.clip_id)
                remaining = [s for s in remaining if s is not anchor]
    return groups, sorted(set(ungrouped))
```

- [ ] **Step 4: 통과 확인** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k grouping -q`
  Expected: PASS.

---

## Task 3: representatives.py (대표 ≤3)

**Context:**
- Depends on: Task 1 (`ClipSignature`, `hamming`)
- Inputs: 한 그룹의 `list[ClipSignature]`
- Outputs: `select_representatives(members, max_reps=3, novelty_min_hamming=6) -> tuple[str,...]` (우선순위 순: evidence→motion→novelty)
- Must know: r1=evidence_score 최고, r2=motion peak 최고(≠r1), r3={r1,r2}와 최소 hamming 이 `novelty_min_hamming` 이상일 때만. tie-break clip_id. 없으면 2개.
- Acceptance: `uv run pytest tests/test_wheel_shadow.py -k represent -q` GREEN.

**Files:**
- Create: `scripts/wheel_shadow/representatives.py`
- Test: `tests/test_wheel_shadow.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**
```python
from scripts.wheel_shadow.representatives import select_representatives as sr
from scripts.wheel_shadow.signatures import ClipSignature


def _m(cid, score, peak, ph):
    return ClipSignature(cid, "2026-07-19T03:00:00+00:00", 30.0, "ir", 0.2, peak, 0.7, ph, "ok", score, False, 10)


def test_representative_three_distinct_axes():
    members = [
        _m("best_ev", score=9.0, peak=0.2, ph=0b0000_0000),
        _m("big_mot", score=1.0, peak=0.9, ph=0b0000_0001),
        _m("novel", score=1.0, peak=0.3, ph=0b1111_1111_1111),  # 시각적으로 매우 다름
        _m("dup", score=1.0, peak=0.25, ph=0b0000_0000),
    ]
    reps = sr(members, max_reps=3, novelty_min_hamming=4)
    assert reps[0] == "best_ev"
    assert reps[1] == "big_mot"
    assert reps[2] == "novel"
    assert len(reps) == 3


def test_representative_caps_at_two_when_no_novelty():
    members = [
        _m("best_ev", score=9.0, peak=0.2, ph=0b0000),
        _m("big_mot", score=1.0, peak=0.9, ph=0b0001),
        _m("similar", score=1.0, peak=0.3, ph=0b0000),
    ]
    reps = sr(members, max_reps=3, novelty_min_hamming=6)
    assert len(reps) == 2
    assert set(reps) == {"best_ev", "big_mot"}
```

- [ ] **Step 2: 실패 확인** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k represent -q`
  Expected: FAIL.

- [ ] **Step 3: 최소 구현** (`scripts/wheel_shadow/representatives.py`)
```python
"""대표 ≤3 선택 — evidence 품질 · ROI motion · novelty 세 축."""
from __future__ import annotations

from .signatures import ClipSignature, hamming


def select_representatives(
    members: list[ClipSignature],
    max_reps: int = 3,
    novelty_min_hamming: int = 6,
) -> tuple[str, ...]:
    if not members:
        return ()
    r1 = sorted(members, key=lambda s: (-s.evidence_score, -s.roi_motion_peak, s.clip_id))[0]
    reps = [r1]
    rest = [s for s in members if s.clip_id != r1.clip_id]
    if rest and max_reps >= 2:
        r2 = sorted(rest, key=lambda s: (-s.roi_motion_peak, s.clip_id))[0]
        reps.append(r2)
        rest2 = [s for s in rest if s.clip_id != r2.clip_id]
        if rest2 and max_reps >= 3:
            def min_dist(s: ClipSignature) -> int:
                return min(hamming(s.perceptual_hash, r.perceptual_hash) for r in reps)
            r3 = sorted(rest2, key=lambda s: (-min_dist(s), s.clip_id))[0]
            if min_dist(r3) >= novelty_min_hamming:
                reps.append(r3)
    return tuple(r.clip_id for r in reps)
```

- [ ] **Step 4: 통과 확인** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k represent -q`
  Expected: PASS.

---

## Task 4: cohort.py (canonical SHA + frozen cohort 조립)

**Context:**
- Depends on: 없음(순수)
- Inputs: dict payload / DB row 리스트(dict)
- Outputs: `cohort_sha256(payload) -> str`, `build_frozen_cohort(...) -> dict`
- Must know: SHA 는 `json.dumps(sort_keys=True, separators=(",",":"))` canonical 직렬화. 같은 입력 → 같은 SHA. clip_ids 는 항상 정렬.
- Acceptance: `uv run pytest tests/test_wheel_shadow.py -k cohort -q` GREEN.

**Files:**
- Create: `scripts/wheel_shadow/cohort.py`
- Test: `tests/test_wheel_shadow.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**
```python
from scripts.wheel_shadow import cohort as co


def test_cohort_sha_is_order_independent_for_ids():
    a = co.build_frozen_cohort(
        camera_name="P4 Cam (dev)", camera_id="cam-uuid",
        started_at_range=["2026-07-19T00:00:00+00:00", "2026-07-22T00:00:00+00:00"],
        clips=[{"clip_id": "b", "run_id": "r2"}, {"clip_id": "a", "run_id": "r1"}],
        known_wheel_gt_clip_ids=["z", "y"],
        gt_snapshot_watermark="2026-07-23T00:00:00+00:00",
    )
    b = co.build_frozen_cohort(
        camera_name="P4 Cam (dev)", camera_id="cam-uuid",
        started_at_range=["2026-07-19T00:00:00+00:00", "2026-07-22T00:00:00+00:00"],
        clips=[{"clip_id": "a", "run_id": "r1"}, {"clip_id": "b", "run_id": "r2"}],
        known_wheel_gt_clip_ids=["y", "z"],
        gt_snapshot_watermark="2026-07-23T00:00:00+00:00",
    )
    assert a["cohort_sha256"] == b["cohort_sha256"]
    assert a["clip_ids"] == ["a", "b"]


def test_cohort_sha_changes_with_content():
    a = co.build_frozen_cohort("cam", "id", ["s", "e"], [{"clip_id": "a", "run_id": "r"}], [], "w")
    b = co.build_frozen_cohort("cam", "id", ["s", "e"], [{"clip_id": "a", "run_id": "r2"}], [], "w")
    assert a["cohort_sha256"] != b["cohort_sha256"]
```

- [ ] **Step 2: 실패 확인** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -k cohort -q`
  Expected: FAIL.

- [ ] **Step 3: 최소 구현** (`scripts/wheel_shadow/cohort.py`)
```python
"""frozen cohort 조립 + canonical SHA-256 (동시 라벨링 안전 계약의 재현 앵커)."""
from __future__ import annotations

import hashlib
import json


def cohort_sha256(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_frozen_cohort(
    camera_name: str,
    camera_id: str,
    started_at_range: list[str],
    clips: list[dict],
    known_wheel_gt_clip_ids: list[str],
    gt_snapshot_watermark: str | None,
) -> dict:
    clip_map = {c["clip_id"]: c for c in clips}
    clip_ids = sorted(clip_map)
    identity = {cid: clip_map[cid] for cid in clip_ids}
    core = {
        "camera_name": camera_name,
        "camera_id": camera_id,
        "started_at_range": started_at_range,
        "clip_ids": clip_ids,
        "python_evidence_run_identity": identity,
        "known_wheel_gt_clip_ids": sorted(known_wheel_gt_clip_ids),
        "gt_snapshot_watermark": gt_snapshot_watermark,
    }
    return {**core, "cohort_sha256": cohort_sha256(core)}
```

- [ ] **Step 4: 통과 확인 + 전체 단위 테스트** — Run: `PYTHONPATH=. uv run pytest tests/test_wheel_shadow.py -q`
  Expected: 전부 PASS.

---

## Task 5: run_wheel_shadow.py (오케스트레이터 — SELECT-only 통합)

**Context:**
- Depends on: Task 1~4
- Inputs: production DB(SELECT), R2(read), `wheel-roi-profile-v1.json`(Task 6 산출)
- Outputs: `frozen-cohort.json`, `shadow-groups.json`, `BLIND-REVIEW.csv`, `EVIDENCE-AUDIT.json`, mutation fingerprint, `--replay` 결정론
- Must know:
  - DB: `backend.supabase_client.get_supabase_client()`. **오직 `.select()`**. camera 는 exact name `"P4 Cam (dev)"` 로 조회(정확히 1건 아니면 중단).
  - R2: `backend.r2_uploader.get_r2_client()`+`get_r2_bucket()`. `head_object`(존재)→`get_object`(temp 다운로드). **write 계열 호출 금지.**
  - 프레임: ffmpeg 적응형(간격3.5/clamp6~20/구간중앙/no-upscale). `tempfile.TemporaryDirectory` 안에서만, 처리 후 삭제.
  - evidence_score: Python Evidence `decoded_frame_count`·`level0_status`·`level1_status`·frames_used 로 산출. run 없으면 quality='missing'.
  - novelty: 프레임 decode 실패 / R2 미존재 / ROI 전부 저분산 → True → ungrouped.
  - mutation fingerprint: 실행 전/후 SELECT count 지문(모션 clip 수·behavior_logs·motion_clip_labeling_sessions·clip_python_evidence_runs·triage) 동일해야 함.
  - `--replay`: 저장된 시그니처(EVIDENCE-AUDIT.json)에서 grouping/artifact 만 재생성 → 결정론 SHA 검증(순수 함수라 100%).
  - BLIND-REVIEW.csv 컬럼: `group_id, is_representative, clip_id, captured_at, labeling_url, owner_verdict`(빈 칸). **score/근거 노출 금지.**
- Acceptance: `--replay` 2회 output SHA 동일 · fingerprint 불변 · temp 0 · overlap 0. (Task 7 에서 실행)

**Files:**
- Create: `scripts/run_wheel_shadow.py`

- [ ] **Step 1: 오케스트레이터 골격 작성** — 아래 구조로 구현.
```python
"""P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow 오케스트레이터.

SELECT-only + R2 read-only. production write·VLM·라벨링웹 변경 0.
사용:
  PYTHONPATH=. uv run python scripts/run_wheel_shadow.py --limit 0
  PYTHONPATH=. uv run python scripts/run_wheel_shadow.py --replay   # 결정론 재생성
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2

from backend.r2_uploader import get_r2_bucket, get_r2_client
from backend.supabase_client import get_supabase_client
from scripts.wheel_shadow import cohort as co
from scripts.wheel_shadow import grouping as grp
from scripts.wheel_shadow import signatures as sig
from scripts.wheel_shadow.representatives import select_representatives

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "wheel-episode-dedup-shadow"
CAMERA_NAME = "P4 Cam (dev)"          # exact name 조회 (UUID 하드코딩 금지)
RANGE = ("2026-07-19T00:00:00+00:00", "2026-07-22T00:00:00+00:00")
LABELING_URL = "https://label.tera-ai.uk/labeling/motion/{clip_id}"
FRAME_INTERVAL, FRAME_MIN, FRAME_MAX = 3.5, 6, 20
```
핵심 함수(구현 시 채움):
- `resolve_camera(sb) -> tuple[str,str]`: `sb.table("cameras").select("id,name").eq("name", CAMERA_NAME).execute()`; len!=1 → SystemExit("HOLD: camera not unique").
- `select_fresh_clips(sb, cam_id) -> list[row]`: `motion_clips` SELECT (camera_id, RANGE, r2_key not null, order started_at,id).
- `select_known_wheel_gt(sb, cam_id) -> list[clip_id]`: `motion_clip_labeling_sessions` current_gt/initial_gt enrichment_object='wheel' → clip_id 교집합 camera=cam_id.
- `latest_evidence(sb, clip_ids) -> dict[clip_id, run]`: `clip_python_evidence_runs` schema/algo 최신.
- `mutation_fingerprint(sb, cam_id) -> dict`: 각 테이블 SELECT count(motion_clips·behavior_logs·motion_clip_labeling_sessions·clip_python_evidence_runs·motion_clip_labeling_triage).
- `download_clip(r2, bucket, r2_key, dst) -> bool`: `r2.head_object` 존재 확인 → `r2.download_file`(temp). 실패 False.
- `extract_frames(mp4, out) -> list[Path]`: `_extract_frames_clip.extract_adaptive` 재사용(적응형 @1080).
- `signature_for_clip(frames, roi, evidence) -> ClipSignature`: 프레임 로드→ROI crop→ir_mode/roi_motion_series/motion_summary/dhash→evidence_score/quality/novelty 채움.
- `write_artifacts(cohort, sigs, groups, ungrouped, profile)`: frozen-cohort.json / shadow-groups.json / BLIND-REVIEW.csv / EVIDENCE-AUDIT.json.
- `groups_sha(groups, ungrouped) -> str`: canonical SHA over group 구조(결정론 게이트).

- [ ] **Step 2: temp 정리 계약** — 다운로드/프레임을 `tempfile.TemporaryDirectory()` 컨텍스트 안에서만 생성, clip 처리 후 즉시 삭제. 종료 시 `EXP/_tmp` 및 temp dir 잔존 media 0 assert.

- [ ] **Step 3: mutation fingerprint 가드** — 시작 시 fingerprint 저장, 종료 시 재측정 후 `assert before == after`, 불일치면 `SHADOW_REJECTED_SAFETY` 로 중단.

- [ ] **Step 4: `--replay` 결정론** — EVIDENCE-AUDIT.json(시그니처)에서 `ClipSignature` 복원 → grouping/artifact 재생성 → `groups_sha` 출력. 2회 호출 SHA 동일.

- [ ] **Step 5: smoke(네트워크 없이 순수 경로)** — `--replay` 는 저장된 시그니처만 쓰므로 DB/R2 없이 재현 가능. Task 7 에서 실제 run 후 replay 로 결정론 확인.

---

## Task 6: wheel ROI profile v1 도출 (데이터 준비)

**Context:**
- Depends on: Task 1, 5 (R2/frame 유틸)
- Inputs: known wheel GT 24 clip 의 대표 프레임
- Outputs: `wheel-roi-profile-v1.json` (normalized ROI + provenance), `ROI-PREVIEW.png`(gitignored)
- Must know: ROI 는 known wheel 프레임에서 **육안 + 모션에너지**로 국소화. normalized 좌표. **fresh grouping 전에 동결.** owner 확인 전 provisional(production 계약 아님). similarity threshold 도 known wheel 에서 calibration 해 profile 에 박고 fresh 튜닝 금지.
- Acceptance: ROI-PREVIEW.png 에서 wheel 영역이 ROI 박스로 덮이는지 육안 확인. profile JSON 은 normalized 좌표 + provenance(derived_from, method, frame_size, status='provisional_shadow') 포함.

**Files:**
- Create: `scripts/derive_wheel_roi.py` (1회성 데이터 준비 스크립트)
- Output: `experiments/wheel-episode-dedup-shadow/wheel-roi-profile-v1.json`, `ROI-PREVIEW.png`(gitignored)

- [ ] **Step 1:** known wheel GT clip 몇 개를 R2 에서 temp 로 받아 프레임 추출.
- [ ] **Step 2:** 프레임 위 모션에너지(연속 absdiff 누적) 히트맵 + 육안으로 wheel 위치 파악 → normalized ROI 확정.
- [ ] **Step 3:** ROI 박스를 대표 프레임에 그려 `ROI-PREVIEW.png` 저장 → Read 로 육안 검증.
- [ ] **Step 4:** `wheel-roi-profile-v1.json` 작성(normalized ROI, frame_size, thresholds(calibration), provenance). temp media 삭제.

---

## Task 7: 실행 · 검증 · REPORT

**Context:**
- Depends on: Task 1~6
- Inputs: frozen cohort(fresh 779 + known 24), wheel-roi-profile-v1
- Outputs: 모든 산출물 + `REPORT.md` + 최종 판정 라벨
- Must know: 검증 게이트 = 결정론(replay 2회 SHA)·overlap 0·temp 0·mutation 불변·R2 write 0·VLM 0·secret/media tracked 0·worker 영향 0. 데이터 게이트 = night≥3·membership≥100·ROI 신뢰. 미달 시 HOLD, 위반 시 REJECT. 수치 조작 금지.
- Acceptance: REPORT.md 에 판정 라벨 1개(READY/BLOCKED/REJECTED) + 게이트 표 + owner-pending 항목.

- [ ] **Step 1:** `uv run pytest tests/test_wheel_shadow.py -q` 전부 GREEN.
- [ ] **Step 2:** 실제 shadow run → 산출물 생성.
- [ ] **Step 3:** 검증 — `--replay` 2회 SHA 동일 · overlap 0 · temp 0 · fingerprint 불변 · `git diff --check` · tracked media/secret 0.
- [ ] **Step 4:** `uv run pytest -q` 전체(회귀 없음, 694+ 유지).
- [ ] **Step 5:** REPORT.md 작성(결과표·시험지 대비·decision·한계·다음 액션) + INDEX.md 등록.
- [ ] **Step 6:** 최종 handoff report + Stop Point. main merge·DB/UI·배포 금지.

---

## Self-Review

- **Spec coverage:** 설계 §6.1 그룹 조건(camera/ROI profile/시간경계/ROI motion+지문/저품질 ungrouped) → Task 2. §6.2 대표 선택 → Task 3. §8 hard gate → Task 7 + TEST-SHEET §5. 동시 라벨링 안전 → Task 4 frozen cohort + Task 5 fingerprint. ROI profile → Task 6.
- **Placeholder scan:** Task 5/6/7 은 오케스트레이션/데이터준비/검증이라 step 서술 + 함수 계약으로 명시(순수 로직 코드는 Task 1~4 에 완결). 네트워크 I/O 는 단위테스트 대상 아님(donts/python #13).
- **Type consistency:** `ClipSignature`(evidence_score 포함) · `Group`(representative_clip_ids) · `GroupingParams`(max_gap_sec/wheel_motion_floor/hamming_threshold/motion_tolerance) · `group_clips(sigs, params, select_reps)` · `select_representatives(members, max_reps, novelty_min_hamming)` — Task 간 시그니처 일치 확인.
