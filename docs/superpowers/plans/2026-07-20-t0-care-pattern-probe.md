# T0 Care-Pattern Probe — RBA 유효 분류 가설 선검증 Implementation Plan (v2)

> **구현 방식 (CAOF):** Standard 트랙 — 실행자(Claude Code desktop app)가 이 계획을 task 단위로 직접 구현한다. Steps use checkbox (`- [ ]`) syntax for tracking.
> **v2 변경 (2026-07-20):** 그릇 셀(bowl-cell) 기반 랭킹 **폐기** — owner 확인 결과 그릇 위치가 급여 때마다 바뀜 + detector는 gecko만 검출(그릇 검출 없음). 위치 무관 **패턴 점수**(체류 집중도 × 반복성)로 교체. 이로써 중간 STOP(그릇 셀 지정) 삭제.
> **🛑 STOP은 단 1곳 — Task 3 (owner blind 판정).** Task 1~2는 논스톱 자동 진행한다.
> **시험지 승인: 2026-07-20 사용자 대화 승인 완료 ("ㄱ") — 합격 기준 동결. 재승인 불필요.**

**Goal:** 이미 쌓인 `clip_python_evidence_runs`의 `spatial_dwell`(체류 집중도) × `periodicity_summary`(반복성 autocorr)로 "몸 고정 + 반복 동작" 상위 클립이 실제 섭식/음수(케어행동)인지 **blind 육안 precision**을 측정해, Python evidence가 케어행동 분류 신호로 유효한지 GT 엔진 투자(수 주) *이전에* 며칠·비용 0으로 판정한다.

**Architecture:** production DB **read-only SELECT** → 패턴 점수 랭킹 → 상위 60 + 무작위 대조 20을 R2에서 로컬 다운로드 → 익명화(blind) 시트로 owner 육안 판정 → 결정론적 채점 → REPORT (decision: adopt/hold/reject). LLM/VLM 호출 0회.

**Tech Stack:** Python 3.12 + uv, supabase-py(`backend.supabase_client.get_supabase_client`), boto3 R2(`backend.r2_uploader.get_r2_client/get_r2_bucket`), pytest.

---

## 배경 (zero-context 실행자용)

- **문제:** production VLM 케어행동 라벨이 육안감사 10/11 오탐(91%). 원인은 "그릇 근처 이동 → 먹는다고 근거 지어냄"(confabulation)이고, 프롬프트·모델·입력·ROI crop 4레버 전부 천장 실증됨. 유일한 정공법 = 비-VLM 시간축 evidence + production 분포 사람 GT.
- **이 실험의 위치:** 수정판 로드맵 `T0 → T1 → T2 → T3 → T5`의 **T0 (가설 선검증)**. 교차 검수(Codex gpt-5.5)에서 "핵심 가설(evidence=케어 신호) 검증이 가장 비싼 투자(GT 엔진) 뒤에 있다"는 순서 결함이 지적돼 신설. **T0이 reject면 T3/T5 가설을 GT 투자 전에 접거나 수정한다.**
- **왜 위치 무관 패턴인가 (v2):** 그릇 위치가 급여마다 바뀌므로 고정 ROI/셀 지정은 무효(owner 실측 답변). v4.0 drinking 재정의("물이 안 보여도 **몸 고정 + 머리 반복 핥기**면 drinking")의 시계열 버전이 정확히 `체류 집중 × 주기성`이다. 위치 없이도 케어행동의 운동 패턴 자체를 겨냥한다.
- **데이터 실물 (2026-07-20 실측):**
  - `clip_python_evidence_runs` 1,789건 (level0/level1 `ok/ok` 1,489 + `ok/no_bbox` 300), 카메라 3대, 2026-07-17~.
  - `spatial_dwell` = `{"grid_size": 4, "cells": [[...4x4 비율...]], "observed_sec": float, "unobserved_sec": float, "n_observations": int}` — `cells[row][col]`, row=y(위→아래)·col=x(왼→오), 값=observed_sec 대비 체류 비율(합≈1.0). 출처: `gecko-vision-gate` `temporal_evidence.py::_spatial_dwell`.
  - `periodicity_summary` = `{"n_points": int, "peak_autocorr": float, "dominant_lag_sec": float, "dominant_lag_points": int}`.
  - `clip_prelabels.detected_objects`는 **gecko 단일 클래스** (그릇 검출 없음 — DB 실측 85,499건 전부 gecko).
- **알려진 함정 (사전 인지):** 과거 drinking-motion PoC에서 micro-motion 최상위 = **자기 얼굴 핥기**(가짜 양성). 판정 어휘에 `self_grooming`을 분리해 이 오탐 모드를 이번에 정량화한다.

## 하드 계약 (전 task 공통)

1. **production DB는 SELECT만.** `.insert/.update/.delete/.upsert/.rpc` 금지 (스크립트에 해당 토큰 자체를 넣지 않는다).
2. **blind 유지.** 판정 시트·클립 파일명에 clip_id 원본/점수/top·random 그룹/VLM 라벨을 노출하지 않는다. 매핑 키는 `key/` 하위 격리, 실행자는 Task 3에서 key를 열지 않는다.
3. **시험지 동결.** 합격 기준은 2026-07-20 사용자 승인으로 동결 — 사후 변경 금지 (`.claude/rules/research-testing.md`).
4. **영상은 전부 `storage/` 하위에만** (`storage/t0-probe/`, gitignored).
5. **LLM/VLM 호출 0회.** 클립을 Claude/Codex/VLM에 넣지 않는다 — 사람 판정이 실험의 측정 자체다 (VLM으로 대신하면 "VLM 오탐을 VLM으로 검증"하는 순환 = 실험 무효).

## File Structure

```
experiments/t0-care-pattern-probe/
├── TEST-SHEET.md            # Task 1 (사전등록, 승인 동결 기록)
├── blind_sheet.csv          # Task 2 (owner 판정용, 익명)
├── key/assignment_key.json  # Task 2 (review_id→clip 매핑+그룹, owner 판정 전 비공개)
├── results.json             # Task 4 (채점 결과)
└── REPORT.md                # Task 4 (decision)
scripts/
├── t0_pattern_rank.py       # Task 2: 패턴 점수 랭킹→샘플링→다운로드→blind 시트
└── t0_score_probe.py        # Task 4: 채점 + results.json
tests/
└── test_t0_pattern_probe.py # Task 2·4 순수 함수 유닛 테스트
storage/t0-probe/clips/      # (gitignored) 판정 대상 80클립
```

---

### Task 1: 실험 디렉토리 + TEST-SHEET 사전등록

**Context:**
- Depends on: 없음
- Inputs: 이 계획서의 배경 섹션
- Outputs: `experiments/t0-care-pattern-probe/TEST-SHEET.md`
- Must know: 합격 기준은 이미 사용자 승인 완료(2026-07-20 대화) — **여기서 멈추지 말고 그대로 기록 후 Task 2 진행.**
- Acceptance: TEST-SHEET.md가 아래 전문으로 존재 + commit

- [ ] **Step 1: 디렉토리 생성 + TEST-SHEET 작성**

`experiments/t0-care-pattern-probe/TEST-SHEET.md`에 아래 전문을 그대로 쓴다:

```markdown
# TEST-SHEET — T0 Care-Pattern Probe (사전등록, 변경 금지)

**작성:** 2026-07-20 · **승인:** 2026-07-20 사용자 대화 승인("ㄱ") — 동결 · **상태:** 사전등록 완료

## 1. 가설
- **H0 (귀무):** 패턴 점수(체류 집중도 × 반복성) 상위 클립군의 케어행동(eating+drinking) 비율은 무작위 클립군과 다르지 않다.
- **H1 (대립):** 패턴 점수 상위 클립군은 무작위 대비 케어행동이 유의하게 농축된다.

## 2. Sample list
- **Eligible pool:** `clip_python_evidence_runs` 중 `level0_status='ok' AND level1_status='ok'`
  AND `spatial_dwell.observed_sec >= 5` AND `spatial_dwell.n_observations >= 3` (sparse 관찰 dwell은 노이즈)
  AND `periodicity_summary.peak_autocorr` 존재 AND `periodicity_summary.n_points >= 30` (짧은 시계열 autocorr 불안정).
  clip당 최신 run 1건.
- **패턴 점수:** `score = max_cell_fraction × max(peak_autocorr, 0)` — max_cell_fraction = spatial_dwell.cells 16셀 중 최대값(체류 집중도), peak_autocorr = 반복성.
- **Top군 60:** score 내림차순 상위 60. **Random 대조군 20:** top 제외 eligible에서 seed=20260720 무작위 20.
- 재현: `scripts/t0_pattern_rank.py` + `key/assignment_key.json`.

## 3. 모델/입력표현/프롬프트
- 해당 없음 (비-VLM·비-LLM). 판정자 = 사람(owner) blind 육안.

## 4. 측정 지표
- 그룹별 care precision = (eating+drinking) / (판정 가능 수, unsure 제외)
- 보조: self_grooming(알려진 가짜 양성 모드)·stationary_no_care(hard negative)·moving·absent 분포, 카메라별 분포

## 5. 합격 기준 (동결 — 사후 변경 금지)
- **adopt**: top60 케어 ≥ 6건 **AND** top군 케어율 > random군 케어율
- **reject**: top60 케어 ≤ 2건
- **hold**: 3~5건
- ⚠️ 채점은 80건 판정 **전부 완료 후 1회만** 실행 (중간 채점으로 기준 조정 금지)

## 6. 예상 비용/토큰
- LLM 0. R2 GET ~80건(~2.5GB), 사람 판정 ~80클립 × 15초 ≈ 20~30분.

## 7. Decision 룰
- adopt → T2(GT 엔진: 라벨링 pilot + fresh camera-night) 착수. T3 룰 검증은 hard negative(stationary_no_care·self_grooming) 포함 사전등록.
- reject → 체류×주기성 단독 신호 폐기. 다음 후보: feature 재조합(dominant_lag 대역 필터 등) / 캡처·사육환경 조정 / head detector 확보 후 재설계.
- hold → 표본 확대 또는 feature 재조합 후 새 TEST-SHEET.

## 8. 알려진 한계 (해석 시 주의)
- **그릇 위치가 급여마다 바뀜(owner 실측)** → 위치 기반 ROI 룰은 이 가정에서 이미 무효. 이 실험은 위치 무관 운동 패턴만 검증. (제품 함의: 증거 카드 spec의 "owner 고정 ROI 지정"도 재검토 필요)
- 과거 PoC에서 micro-motion 최상위 = 자기 얼굴 핥기 가짜 양성 → self_grooming 분리 집계로 정량화.
- 4×4 dwell 그리드는 coarse. eligible pool은 모션트리거 캡처 3일치 부분집합 → base rate는 참고치.
- 판정자 1인(owner), inter-rater 없음 — unsure 적극 사용으로 보완.
- reject여도 "evidence 전체" 기각이 아니라 "이 2-feature 조합" 기각.
```

- [ ] **Step 2: Commit**

```bash
git add experiments/t0-care-pattern-probe/TEST-SHEET.md
git commit -m "docs: T0 care-pattern probe 시험지 사전등록 (사용자 승인 동결)"
```

---

### Task 2: 패턴 점수 랭킹 → 샘플링 → 다운로드 → blind 시트

**Context:**
- Depends on: Task 1
- Inputs: `clip_python_evidence_runs`(SELECT), `motion_clips`(SELECT), `cameras`(SELECT), R2
- Outputs: `storage/t0-probe/clips/t0-###.mp4` 80개, `experiments/t0-care-pattern-probe/blind_sheet.csv`, `experiments/t0-care-pattern-probe/key/assignment_key.json`
- Must know: **blind 계약**(하드 계약 §2). eligible 필터·score 식·seed는 TEST-SHEET §2와 동일해야 함(불일치=실험 무효). supabase-py는 기본 1000행 제한 → range 페이지네이션 필수.
- Acceptance: `uv run pytest tests/test_t0_pattern_probe.py -v` 전체 PASS + 클립 80개 + blind_sheet.csv 80행 + key 파일 + blind 무결성 grep 0

- [ ] **Step 1: Write the failing tests**

`tests/test_t0_pattern_probe.py` 생성:

```python
"""T0 care-pattern probe 순수 함수 테스트 (DB/R2/네트워크 불필요)."""


def _dwell(max_frac=0.7, observed=30.0, n_obs=8):
    cells = [[0.0] * 4 for _ in range(4)]
    cells[0][0] = max_frac
    cells[1][1] = round(1.0 - max_frac, 4)
    return {"grid_size": 4, "cells": cells,
            "observed_sec": observed, "n_observations": n_obs}


def test_pattern_score():
    from scripts.t0_pattern_rank import pattern_score

    # 체류 집중 0.7 × 반복성 0.5 = 0.35
    assert pattern_score(_dwell(0.7), {"peak_autocorr": 0.5}) == 0.35
    # 음수 autocorr 는 0 으로 clamp
    assert pattern_score(_dwell(0.7), {"peak_autocorr": -0.2}) == 0.0


def test_is_eligible():
    from scripts.t0_pattern_rank import is_eligible

    ok_p = {"peak_autocorr": 0.4, "n_points": 100}
    base = {"level0_status": "ok", "level1_status": "ok",
            "spatial_dwell": _dwell(), "periodicity_summary": ok_p}
    assert is_eligible(base)
    assert not is_eligible({**base, "level1_status": "no_bbox"})       # dwell 무효
    assert not is_eligible({**base, "spatial_dwell": _dwell(observed=3.0)})   # 관찰시간 미달
    assert not is_eligible({**base, "spatial_dwell": _dwell(n_obs=2)})        # 관찰횟수 미달
    assert not is_eligible({**base, "periodicity_summary": None})             # 반복성 없음
    assert not is_eligible({**base, "periodicity_summary": {**ok_p, "n_points": 10}})  # 시계열 짧음
    assert not is_eligible({**base, "periodicity_summary": {"n_points": 100,
                                                            "peak_autocorr": None}})


def test_sample_split_deterministic():
    from scripts.t0_pattern_rank import sample_split

    ranked = [{"clip_id": f"c{i}", "score": 100.0 - i} for i in range(100)]
    top1, rand1 = sample_split(ranked, top_n=60, random_n=20, seed=20260720)
    top2, rand2 = sample_split(ranked, top_n=60, random_n=20, seed=20260720)
    assert top1 == top2 and rand1 == rand2          # 결정론
    assert len(top1) == 60 and len(rand1) == 20
    assert {c["clip_id"] for c in top1} == {f"c{i}" for i in range(60)}  # score 내림차순 상위
    assert not ({c["clip_id"] for c in rand1} & {c["clip_id"] for c in top1})  # 배타
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_t0_pattern_probe.py -v`
Expected: 3개 전부 FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`scripts/t0_pattern_rank.py` 생성:

```python
"""T0: 패턴 점수(체류 집중 × 반복성) 랭킹 → top60+random20 → R2 다운로드 → blind 시트.

하드 계약: production DB SELECT 만 · blind(시트/파일명에 clip_id/점수/그룹 미노출) ·
seed=20260720 고정 (TEST-SHEET §2 와 동일해야 함 — 불일치=실험 무효).
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

SEED = 20260720
TOP_N = 60
RANDOM_N = 20
MIN_OBSERVED_SEC = 5.0
MIN_OBSERVATIONS = 3
MIN_PERIODICITY_POINTS = 30

EXP_DIR = _REPO_ROOT / "experiments" / "t0-care-pattern-probe"
CLIP_DIR = _REPO_ROOT / "storage" / "t0-probe" / "clips"
VERDICTS = "eating|drinking|self_grooming|stationary_no_care|moving|absent|unsure"


def pattern_score(dwell: dict, periodicity: dict) -> float:
    """체류 집중도(최대 셀 비율) × 반복성(autocorr, 음수는 0 clamp)."""
    max_cell = max(max(row) for row in dwell["cells"])
    ac = periodicity.get("peak_autocorr") or 0.0
    return round(max_cell * max(ac, 0.0), 4)


def is_eligible(run: dict) -> bool:
    """TEST-SHEET §2 eligible 필터."""
    d = run.get("spatial_dwell")
    p = run.get("periodicity_summary")
    return bool(
        run.get("level0_status") == "ok"
        and run.get("level1_status") == "ok"
        and d
        and d.get("observed_sec", 0) >= MIN_OBSERVED_SEC
        and d.get("n_observations", 0) >= MIN_OBSERVATIONS
        and p
        and p.get("peak_autocorr") is not None
        and p.get("n_points", 0) >= MIN_PERIODICITY_POINTS
    )


def sample_split(ranked: list, top_n: int, random_n: int, seed: int):
    """score 내림차순 상위 top_n + 나머지에서 무작위 random_n (결정론)."""
    ordered = sorted(ranked, key=lambda x: (-x["score"], x["clip_id"]))
    top = ordered[:top_n]
    rest = ordered[top_n:]
    rng = random.Random(seed)
    rand = rng.sample(rest, min(random_n, len(rest)))
    return top, rand


def _fetch_all(client, table: str, columns: str, page: int = 1000) -> list:
    """supabase-py 기본 1000행 제한 → range 페이지네이션."""
    rows, offset = [], 0
    while True:
        batch = (client.table(table).select(columns)
                 .range(offset, offset + page - 1).execute().data)
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def main() -> int:
    from backend.r2_uploader import get_r2_bucket, get_r2_client
    from backend.supabase_client import get_supabase_client

    client = get_supabase_client()
    cams = {c["id"]: c["name"] for c in
            client.table("cameras").select("id,name").execute().data}
    runs = _fetch_all(
        client, "clip_python_evidence_runs",
        "clip_id,level0_status,level1_status,spatial_dwell,periodicity_summary,created_at")
    clips = {m["id"]: m for m in _fetch_all(
        client, "motion_clips", "id,camera_id,r2_key,started_at,duration_sec")}

    # clip 당 최신 run 1건 (재처리 대비)
    latest: dict[str, dict] = {}
    for r in runs:
        prev = latest.get(r["clip_id"])
        if prev is None or r["created_at"] > prev["created_at"]:
            latest[r["clip_id"]] = r

    ranked = []
    for clip_id, run in latest.items():
        if not is_eligible(run):
            continue
        clip = clips.get(clip_id)
        if clip is None:
            continue
        ranked.append({
            "clip_id": clip_id,
            "camera": cams.get(clip["camera_id"], "?"),
            "r2_key": clip["r2_key"],
            "started_at": clip["started_at"],
            "score": pattern_score(run["spatial_dwell"], run["periodicity_summary"]),
        })

    if len(ranked) < 200:
        # 필터가 과하게 좁거나 데이터 전제가 틀림 — 진행하면 표본이 무의미
        raise SystemExit(f"eligible={len(ranked)} < 200: 중단, 사용자 보고 필요")

    top, rand = sample_split(ranked, TOP_N, RANDOM_N, SEED)
    print(f"eligible={len(ranked)} top={len(top)} random={len(rand)}")

    # blind 셔플: top/random 섞고 review_id 재부여 (시드 고정, 그룹 미노출)
    combined = [dict(x, group="top") for x in top] + \
               [dict(x, group="random") for x in rand]
    random.Random(SEED + 1).shuffle(combined)

    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    (EXP_DIR / "key").mkdir(parents=True, exist_ok=True)
    r2, bucket = get_r2_client(), get_r2_bucket()

    key_rows, sheet_rows = [], []
    for i, item in enumerate(combined, 1):
        rid = f"t0-{i:03d}"
        local = CLIP_DIR / f"{rid}.mp4"
        if not local.exists():  # 재실행 안전 (다운로드만 재개)
            r2.download_file(bucket, item["r2_key"], str(local))
        key_rows.append({"review_id": rid, **item})
        sheet_rows.append({"review_id": rid,
                           "video": f"storage/t0-probe/clips/{rid}.mp4",
                           "verdict": "", "note": ""})
        print(f"[{i}/{len(combined)}] {rid}")

    (EXP_DIR / "key" / "assignment_key.json").write_text(
        json.dumps({"seed": SEED, "items": key_rows}, ensure_ascii=False, indent=2))
    with (EXP_DIR / "blind_sheet.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "video", "verdict", "note"])
        w.writeheader()
        w.writerows(sheet_rows)
        f.write(f"# verdict 허용값: {VERDICTS}\n")
    print(f"sheet={EXP_DIR / 'blind_sheet.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_t0_pattern_probe.py -v`
Expected: 3개 전부 PASS

- [ ] **Step 5: 실행 — 랭킹·다운로드·시트 생성**

Run: `cd /Users/baek/petcam-lab && uv run python scripts/t0_pattern_rank.py`
Expected: `eligible=~1000+ top=60 random=20` → 클립 80개 다운로드 → `sheet=...blind_sheet.csv`. (`eligible < 200` SystemExit 시 진행 중단하고 사용자 보고 — 코드가 아니라 데이터 전제 문제)

- [ ] **Step 6: blind 무결성 자체검증**

Run: `grep -cE "top|random|score|clip_id" experiments/t0-care-pattern-probe/blind_sheet.csv`
Expected: `0` (시트에 그룹/점수/원본 id 누출 없음). 누출 시 시트 재생성.

- [ ] **Step 7: Commit**

```bash
git add scripts/t0_pattern_rank.py tests/test_t0_pattern_probe.py \
  experiments/t0-care-pattern-probe/blind_sheet.csv \
  experiments/t0-care-pattern-probe/key/assignment_key.json
git commit -m "feat: T0 care-pattern 랭킹 + blind 판정 시트 (top60+random20, seed 고정)"
```

---

### Task 3: 🛑 owner blind 육안 판정 (유일한 STOP)

**Context:**
- Depends on: Task 2
- Inputs: `blind_sheet.csv` + `storage/t0-probe/clips/*.mp4` 80개
- Outputs: verdict 컬럼이 채워진 `blind_sheet.csv`
- Must know: **실행자는 이 task에서 아무것도 판정하지 않는다.** 클립을 VLM/Claude에 넣지 않는다(하드 계약 §5). `key/` 를 열지 않는다.
- Acceptance: blind_sheet.csv 80행 verdict 전부 채워짐 (허용값 7종)

- [ ] **Step 1: 사용자에게 판정 안내 후 대기**

안내문:
> `experiments/t0-care-pattern-probe/blind_sheet.csv`를 열고 각 클립(`storage/t0-probe/clips/t0-###.mp4`)을 보고 verdict를 채워줘.
> - **eating**: 입이 먹이/페이스트에 실제 접촉·섭식 동작
> - **drinking**: 물·표면(잎/벽 응결수 포함)을 반복해서 핥음
> - **self_grooming**: 자기 몸·눈·입 주변 핥기 (물/먹이 아님) ← 알려진 가짜 양성 모드
> - **stationary_no_care**: 한자리에 머물지만 섭식/음수/그루밍 없음 ← hard negative
> - **moving**: 이동/활동 위주
> - **absent**: 게코 안 보임
> - **unsure**: 확신 없음 (적극 사용 — 억지 판정 금지)
> 80개 × ~15초, 20~30분 예상.

- [ ] **Step 2: 판정 완료 확인**

Run: `cd /Users/baek/petcam-lab && awk -F, 'NR>1 && !/^#/ && $3=="" {n++} END {print n+0}' experiments/t0-care-pattern-probe/blind_sheet.csv`
Expected: `0` (미기입 없음)

---

### Task 4: 채점 + REPORT + INDEX 등록

**Context:**
- Depends on: Task 3
- Inputs: 채워진 `blind_sheet.csv` + `key/assignment_key.json` + TEST-SHEET §5 기준
- Outputs: `results.json`, `REPORT.md`, `experiments/INDEX.md` 한 줄
- Must know: 채점은 **1회만** 실행. decision은 §5 숫자 기계 적용 — 재량 금지.
- Acceptance: `uv run pytest tests/test_t0_pattern_probe.py -v` 전체 PASS + results.json + REPORT.md(decision 명시) + INDEX 갱신

- [ ] **Step 1: Write the failing test**

`tests/test_t0_pattern_probe.py`에 추가:

```python
def test_score_groups():
    from scripts.t0_score_probe import score_groups

    sheet = {"t0-001": "eating", "t0-002": "stationary_no_care",
             "t0-003": "drinking", "t0-004": "unsure", "t0-005": "self_grooming",
             "t0-006": "moving"}
    key = [{"review_id": "t0-001", "group": "top"},
           {"review_id": "t0-002", "group": "top"},
           {"review_id": "t0-003", "group": "top"},
           {"review_id": "t0-004", "group": "top"},      # unsure → 판정가능 제외
           {"review_id": "t0-005", "group": "top"},
           {"review_id": "t0-006", "group": "random"}]
    r = score_groups(sheet, key)
    assert r["top"]["care_count"] == 2                    # eating+drinking
    assert r["top"]["judged"] == 4                        # unsure 제외
    assert r["top"]["care_rate"] == 0.5
    assert r["top"]["verdicts"]["self_grooming"] == 1     # 가짜 양성 모드 분포 보존
    assert r["random"]["care_count"] == 0


def test_decide():
    from scripts.t0_score_probe import decide

    assert decide({"care_count": 6, "care_rate": 0.12}, {"care_rate": 0.05}) == "adopt"
    assert decide({"care_count": 6, "care_rate": 0.05}, {"care_rate": 0.10}) == "hold"
    assert decide({"care_count": 2, "care_rate": 0.04}, {"care_rate": 0.0}) == "reject"
    assert decide({"care_count": 4, "care_rate": 0.08}, {"care_rate": 0.0}) == "hold"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_t0_pattern_probe.py::test_score_groups -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Write implementation**

`scripts/t0_score_probe.py` 생성:

```python
"""T0 채점: blind_sheet verdict × assignment key 그룹 → care precision + decision.

TEST-SHEET §5 를 기계 적용한다 (재량 금지·1회 실행).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = _REPO_ROOT / "experiments" / "t0-care-pattern-probe"

CARE = {"eating", "drinking"}
VALID = {"eating", "drinking", "self_grooming", "stationary_no_care",
         "moving", "absent", "unsure"}


def score_groups(sheet: dict, key: list) -> dict:
    """그룹별 care_count / judged(unsure 제외) / care_rate / verdict 분포."""
    out: dict[str, dict] = {}
    for item in key:
        g = item["group"]
        v = sheet.get(item["review_id"], "")
        grp = out.setdefault(g, {"care_count": 0, "judged": 0,
                                 "verdicts": Counter(), "n": 0})
        grp["n"] += 1
        grp["verdicts"][v] += 1
        if v and v != "unsure":
            grp["judged"] += 1
            if v in CARE:
                grp["care_count"] += 1
    for grp in out.values():
        grp["care_rate"] = round(grp["care_count"] / grp["judged"], 4) if grp["judged"] else 0.0
        grp["verdicts"] = dict(grp["verdicts"])
    return out


def decide(top: dict, rand: dict) -> str:
    """TEST-SHEET §5: adopt = top 케어 ≥6 AND top care_rate > random care_rate.
    reject = top 케어 ≤2. hold = 그 외."""
    if top["care_count"] >= 6 and top["care_rate"] > rand["care_rate"]:
        return "adopt"
    if top["care_count"] <= 2:
        return "reject"
    return "hold"


def main() -> int:
    sheet: dict[str, str] = {}
    with (EXP_DIR / "blind_sheet.csv").open() as f:
        for row in csv.DictReader(r for r in f if not r.startswith("#")):
            v = row["verdict"].strip()
            if v not in VALID:
                raise SystemExit(f"허용 외 verdict: {row['review_id']}={v!r}")
            sheet[row["review_id"]] = v
    key = json.loads((EXP_DIR / "key" / "assignment_key.json").read_text())["items"]

    groups = score_groups(sheet, key)
    decision = decide(groups["top"], groups["random"])
    results = {"groups": groups, "decision": decision,
               "care_classes": sorted(CARE), "n_total": len(key)}
    (EXP_DIR / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/baek/petcam-lab && uv run pytest tests/test_t0_pattern_probe.py -v`
Expected: 5개 전부 PASS

- [ ] **Step 5: 채점 실행 (1회만)**

Run: `cd /Users/baek/petcam-lab && uv run python scripts/t0_score_probe.py`
Expected: `results.json` 생성 + decision 출력 (`adopt`/`hold`/`reject`)

- [ ] **Step 6: REPORT.md 작성**

`experiments/t0-care-pattern-probe/REPORT.md` — 템플릿 `specs/_report-template.md`을 따르되 최소 포함:
1. 결과 표 (top/random 그룹별 care_count·judged·care_rate·verdict 분포, 카메라별 분포)
2. 시험지 대비 — 사후 변경 없음 (있었으면 사유)
3. 가설 판정 (H0 기각 여부)
4. **decision label** = results.json의 decision 그대로 + TEST-SHEET §7의 다음 액션
5. 한계 + self_grooming(가짜 양성)·stationary_no_care(hard negative) 건수 — T3 설계 입력값
6. 다음 액션 (decision 룰 §7 기계 적용)

- [ ] **Step 7: INDEX 등록 + 커밋**

`experiments/INDEX.md`의 "진행 중 트랙" 표에 한 줄 추가:

```markdown
| 2026-07-XX | **T0 care-pattern probe** (체류×주기성=케어 신호 선검증, blind 80건, 비-VLM) | `(decision)` | top60 care N건/rate X% vs random20 Y% — (한 줄 해석) | [t0-care-pattern-probe/REPORT.md](t0-care-pattern-probe/REPORT.md) |
```

```bash
git add scripts/t0_score_probe.py tests/test_t0_pattern_probe.py \
  experiments/t0-care-pattern-probe/ experiments/INDEX.md
git commit -m "docs: T0 care-pattern probe 채점+보고서 (decision: <adopt|hold|reject>)"
```

- [ ] **Step 8: `.claude/donts-audit.md`에 한 줄 추가** (Standard 이상 작업 완료 규칙)

---

## 후속 로드맵 (T0 이후 — 이 계획서 범위 밖, 각각 별도 승인·계획서 필요)

| 트랙 | 내용 | 게이트 |
|---|---|---|
| **T1** 오탐 소스 제거 | temperature 0 고정 + 주야간 모드전환 필터 + VLM 단독 케어라벨 "후보" 강등. ⚠️ temperature·강등은 **petcam-nightly-reporter 레포** 작업(cross-repo handoff manifest 필수). 기대치: confabulation은 안 고쳐짐 — 노이즈 제거+노출 차단만 | T0과 독립, 병렬 가능 |
| **T2** GT 엔진 | 라벨링 pilot 1명 가동(배포 완료, 지정만 남음) + fresh camera-night passive 녹화. 목표: positive 클래스별 ≥20 **+ hard negative ≥200**. 기간은 T0의 발생률 실측 후 재산정 | T0 decision 무관하게 pilot은 시작 가능 |
| **T3** evidence 룰 검증 | 쌓인 raw feature를 GT에 대조 — hard negative 포함 사전등록, 무작위 표본 보강(selection bias 방지) | T0 adopt + T2 GT 확보 |
| **T4** 처리량 벤치마크 | S1R2 CROI (≥160 clips/h) — 유효성 경로 아님, 안전창 남을 때만 | 우선순위 강등 |
| **T5** 증거 카드 UX | 수렴 증거만 노출, 라벨 앵커링 방지 설계. ⚠️ "owner 고정 ROI 지정" 기능은 그릇 이동 사실로 재검토 | T3 precision 게이트 통과 후 |

## Self-Review 체크 결과

- **Spec coverage:** T0 4단계(시험지→랭킹/blind→판정→채점/보고) 전부 task 존재. v2 변경 반영 확인 — 그릇 셀 의존 제거 ✅ / self_grooming 가짜 양성 분리 ✅ / hard negative 어휘 ✅ / random 대조군 ✅ / precision-first ✅ / eligible<200 fail-loud ✅.
- **Placeholder scan:** TBD/TODO 없음. Task 4 Step 7의 `2026-07-XX`·`(decision)`은 실행 시 실측값 기입 (의도된 것).
- **Type consistency:** `pattern_score(dwell, periodicity)`·`is_eligible(run)`·`sample_split(ranked, top_n, random_n, seed)`(정렬 키 `score`)·`score_groups(sheet, key)`·`decide(top, rand)` — 테스트와 구현 시그니처·키 일치. `assignment_key.json`의 `items[].group` ∈ {top, random}을 Task 2 생성·Task 4 소비 동일 키로 사용. verdict 어휘 7종이 Task 2 시트 주석·Task 3 안내·Task 4 VALID에 동일.
