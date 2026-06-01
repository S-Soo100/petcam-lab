# RBA evidence-based feeding/drinking inference

> `밥 먹음` / `물 마심`을 60초 영상 top-1로 단정하지 않고, ROI 체류 + 전후 상태 변화 + 표면 핥기 증거를 조합해서 `방문`, `후보`, `추론`, `확정` 단계로 기록하는 RBA 증거 기반 섭식/음수 판단 레이어.

**상태:** 🚧 진행 중 (2026-06-02 — 구현 계획서 작성, 착수 전)  
**작성:** 2026-06-02  
**넘김 대상:** 구현 담당 Claude  
**연관 SOT:** [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [`docs/VLM-CLASSIFIER.md`](../docs/VLM-CLASSIFIER.md), [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md)

---

## 1. 목적

현재 Track A는 `60초 motion clip → Gemini 2.5 Flash v3.5 → top-1 action` 구조다. feeding-merged 기준 85.5% floor는 확보했지만, `eating_paste`와 `drinking`은 같은 자세/같은 그릇/낮은 fps 조건에서 픽셀만으로 구분하기 어렵다.

이번 스펙의 목적은 VLM에게 "직접 먹었나/마셨나"를 무리하게 맞히게 하는 게 아니라, **행동 판단에 필요한 증거를 구조화해서 모으는 것**이다.

핵심 전환:

```text
기존: "이 클립의 행동 라벨 하나를 골라라"
변경: "어떤 대상 근처에 얼마나 있었고, 전후 상태가 어떻게 변했고, 표면 핥기 증거가 있었는지 기록하라"
```

제품적으로도 더 정직하다. 사용자에게 "밥 먹음"이라고 단정하기보다, "밥그릇 근처 18초 체류 + 이후 먹이 표면 감소 후보"처럼 근거를 보여준다.

---

## 2. 사용자 체험 시뮬레이션

구현 전에 사용자가 실제로 경험하는 흐름을 먼저 고정한다.

### 2.1 아침 요약

`[화면]` 사용자는 아침에 앱/라벨링 웹에서 밤사이 요약을 본다.  
`[조작]` "섭식/수분 후보" 섹션을 펼친다.  
`[반응]` "02:14 밥그릇 근처 21초 체류, 먹이 표면 변화 후보" / "03:52 벽면 핥기 후보 6초" 같은 증거 카드가 보인다.  
`[감정]` 사용자는 AI가 억지로 단정하지 않고 근거를 말한다고 느낀다.

### 2.2 상세 검수

`[화면]` 증거 카드에는 짧은 event clip, ROI 박스, before/after crop이 같이 보인다.  
`[조작]` 사용자가 "맞음", "아님", "모름" 중 하나를 누른다.  
`[반응]` 답변은 `behavior_labels` 또는 HITL 계열 데이터로 저장되고, 같은 환경의 다음 판단 근거로 누적된다.  
`[감정]` 검수 부담은 60초 전체 재시청이 아니라 5~15초 구간 확인으로 줄어든다.

### 2.3 ROI 설정

`[화면]` owner/admin은 카메라 화면 위에 밥그릇, 물그릇, 잎/벽면 같은 관심 영역을 지정한다.  
`[조작]` 다각형 또는 사각형으로 영역을 찍고 `food_bowl`, `water_bowl`, `surface_leaf`, `surface_wall` 같은 타입을 고른다.  
`[반응]` 이후 RBA는 해당 ROI 기준으로 체류 시간과 전후 crop을 계산한다.  
`[감정]` 사용자는 "우리 사육장 배치"가 반영된다고 느낀다.

---

## 3. 스코프

### In (이번 스펙에서 한다)

- 섭식/음수 판단을 `direct action label`이 아니라 `evidence event`로 재정의한다.
- 카메라별 ROI 메타데이터를 추가한다.
  - `food_bowl`
  - `water_bowl`
  - `surface_leaf`
  - `surface_wall`
  - `surface_branch`
  - `surface_object`
  - `hide`
  - `other`
- Track B / SegmentVLM 쪽에 evidence analyzer를 추가한다.
  - 5~15초 event segment
  - ROI crop/contact sheet
  - before/after crop 비교
  - surface licking 후보 분석
- `behavior_logs` top-1 결과는 유지하고, 별도 evidence table에 다중 이벤트를 저장한다.
- owner/HITL 검수용 API와 최소 UI를 계획한다.
- 미스팅 컨텍스트를 표면 음수 판단의 1급 신호로 추가한다 (타이머 스케줄 ∪ 영상 감지 ∪ 선택적 원탭 수동 로그). 상세 §4.4 / §5.5.
- 수분 신호는 개별 `confirmed` 가 아니라 밤/주 단위 집계 요약으로 출력한다.
- 평가는 30~50개 대표 클립 + 정상 운영 1~2박 passive 녹화로 만든다 (상세 §7 Phase 7).

### Out (이번 스펙에서 안 한다)

- Track A v3.5 prompt 교체. v3.5 85.5% floor는 유지한다.
- fps 증가를 기본 해결책으로 채택. 필요하면 direct-confirmed 샘플 검증용 후속 카드로만 둔다.
- `behavior_logs.action` raw 9-class를 즉시 바꾸기.
- "밥 먹음" / "물 마심" 단정 알림을 바로 production 앱에 켜기.
- 음식 무게 센서, 자동 급수기 센서 같은 하드웨어 연동.
- fine-tune 또는 사용자별 모델 학습 자동화.
- Flutter 앱 본 구현. 여기서는 백엔드/라벨링 웹/실험 artifact 기준으로 먼저 검증한다.

> 스코프 변경은 합의 후에만. 작업 중 In/Out 경계가 흔들리면 이 섹션 수정 + 사유 기록.

---

## 4. 핵심 설계 원칙

### 4.1 단정 대신 증거 레벨

| 레벨 | 내부 값 | 필요한 증거 | 사용자 문구 |
|---|---|---|---|
| 방문 | `visit` | ROI 근처 N초 이상 체류 | "밥그릇 근처에 있었어" |
| 후보 | `candidate` | 방문 + 머리 방향/반복 접근/표면 접촉 중 하나 | "섭식 후보야" |
| 강한 추론 | `inferred` | 후보 + before/after 상태 변화 또는 명확한 반복 핥기 | "먹었을 가능성이 높아" |
| 직접 확인 | `confirmed` | 혀/입 접촉, 포식, 삼킴 등 직접 장면 | "먹는 장면이 보여" |
| 검수 필요 | `needs_review` | 신호 충돌, 가림, 낮은 신뢰도 | "확인이 필요해" |

`confirmed`는 아껴 써야 한다. fps가 낮거나 혀 접촉이 안 보이면 `inferred`나 `candidate`로 남긴다.

### 4.2 action과 evidence 분리

기존 raw action:

```text
eating_paste / drinking / moving / unknown / eating_prey / defecating / shedding / basking / unseen
```

새 evidence event:

```text
food_bowl_visit
food_intake_candidate
food_intake_inferred
food_intake_confirmed
water_bowl_visit
dish_drinking_candidate
dish_drinking_inferred
dish_drinking_confirmed
surface_licking_candidate
surface_drinking_candidate
surface_drinking_inferred
surface_drinking_confirmed
```

`behavior_logs.action`은 기존 top-1 baseline으로 남기고, evidence event가 사용자 설명과 HITL 라우팅을 담당한다.

### 4.3 VLM 질문을 바꾼다

VLM에게 바로 묻지 않는다:

```text
Did the gecko eat or drink?
```

대신 이렇게 묻는다:

```text
- Is the gecko near the food bowl ROI?
- When does the head/mouth enter the ROI?
- Is the food surface visibly changed between before/after crops?
- Is there repeated mouth/tongue contact with wall/leaf/object surface?
- Is the evidence direct, inferred, candidate, or insufficient?
```

이게 hallucination을 줄인다. 모델의 역할은 최종 판사가 아니라 증거 추출기다.

### 4.4 표면 음수와 미스팅 컨텍스트 (fuzzy 신호 다루기)

표면(벽/잎/조화/사물) 음수는 본질적으로 시각으로 확정 불가다. "사람도 헷갈리는" 케이스이므로 (memory `feedback_vlm_visual_information_limit`), 이 레이어의 목표는 확정이 아니라 **합당한 evidence 레벨 + 집계 신호**다.

**원칙 1 — 물그릇이 신뢰 앵커, 표면은 candidate 보너스.**
`water_bowl` 음수는 ROI 체류 + 반복 접촉이라 robust 한 주 수분 신호다. 벽/잎 표면 음수는 그 위에 얹는 fuzzy 보너스이며 기본적으로 `candidate` 를 넘지 않는다. 제일 어려운 5%(표면 음수 확정)에 매달려 80%(물그릇 + 집계)를 놓치지 않는다.

**원칙 2 — 미스팅 컨텍스트는 1급 disambiguator (단, 시간 창은 약하게).**
게코는 분무 직후 벽/잎에 맺힌 물을 핥아 마신다. 그래서 "표면 핥기"의 의미는 핥는 프레임 픽셀이 아니라 **언제 핥았느냐(미스팅과의 관계)**에서 나온다.

```text
미스팅 컨텍스트 = 타이머 스케줄  ∪  영상 감지 미스팅 이벤트  ∪  (선택) 원탭 수동 로그
```

- 자동분무 → 스케줄로 시각을 공짜로 안다.
- 수동분무 → 영상 감지(분무/안개/손 진입은 "벽이 젖었나"보다 큰 신호) 또는 원탭 로그로 흡수.
- 둘 다 놓친 수동분무 → 그냥 `candidate` 에 머문다. **이건 실패가 아니라 설계다.** 모르면 단정하지 않는다.

단, 마르는 시간은 표면·습도마다 들쭉날쭉하다 (벽은 분 단위, 조화 잎에 고인 물은 시간 단위). 그래서 "분무 후 N분 내" 같은 칼같은 시간 창을 강한 신호로 쓰지 않는다.

**원칙 3 — 시간 창 대신 더 robust 한 두 신호.**
1. **핥는 행동의 모양** — 한 자리에 박혀 반복적으로 핥음(sustained lapping) ≈ 음수 / 돌아다니며 짧게 혀 날름(darting flick) ≈ 탐색·그루밍. 물이 보이냐와 거의 무관하게 구분된다. (§6.4 "반복 접촉 ≥ 3초" 가 이 신호다)
2. **집계** — 개별 음수를 확정하지 않고 밤/주 단위로 수분 후보를 합산한다. 제품 가치는 "03:42 에 마셨나"가 아니라 "이 개체 수분 행동이 평소만큼 있나"다.

**출력 형태 (위 원칙이 다 흡수되는 형태):**

```text
오늘밤 수분 행동
- 물그릇 방문 2회 (확실)
- 미스팅 후 표면 핥기 3회 (후보)
- 최근 7일 평균과 비슷
```

다중 소스, 개별 불확실성(후보), 들쭉날쭉 타이밍이 모두 이 집계 형태에 녹는다.

---

## 5. 데이터 모델 계획

### 5.1 `camera_rois`

카메라별 관심 영역. DB CHECK는 최소화하고 앱 레벨 검증을 따른다.

```sql
CREATE TABLE camera_rois (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  roi_type TEXT NOT NULL,
  label TEXT,
  polygon JSONB NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_camera_rois_camera_active
  ON camera_rois (camera_id, active);
```

`polygon`은 normalized 좌표를 기본으로 둔다.

```json
{
  "shape": "polygon",
  "points": [[0.12, 0.44], [0.28, 0.44], [0.28, 0.62], [0.12, 0.62]]
}
```

MVP에서는 사각형만 UI로 그려도 된다. 저장 포맷은 polygon으로 열어둔다.

### 5.2 `rba_evidence_events`

한 클립 안에 여러 증거 이벤트를 저장한다.

```sql
CREATE TABLE rba_evidence_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id UUID NOT NULL REFERENCES camera_clips(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  camera_id UUID REFERENCES cameras(id) ON DELETE SET NULL,
  roi_id UUID REFERENCES camera_rois(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  action_hint TEXT,
  evidence_level TEXT NOT NULL,
  start_sec NUMERIC,
  end_sec NUMERIC,
  duration_sec NUMERIC,
  confidence NUMERIC,
  source TEXT NOT NULL,
  analyzer_version TEXT,
  dedupe_key TEXT NOT NULL,
  artifact_key TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  needs_human_review BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (clip_id, source, dedupe_key)
);

CREATE INDEX idx_rba_evidence_events_clip_id
  ON rba_evidence_events (clip_id);

CREATE INDEX idx_rba_evidence_events_user_created
  ON rba_evidence_events (user_id, created_at DESC);

CREATE INDEX idx_rba_evidence_events_type
  ON rba_evidence_events (event_type);
```

`source` 후보:

```text
track_b_gemini
track_b_codex
track_b_claude
cv_roi
fusion
human_review
```

`dedupe_key`는 같은 analyzer 재실행 중복을 막는 키다. 예: `food_bowl_visit:roi-uuid:12.0-30.5`. 숫자 초는 0.5초 또는 1초 bucket으로 반올림해서 흔들림을 줄인다.

`artifact_key`는 R2 또는 로컬 artifact prefix를 가리킨다.

```text
rba/evidence/{clip_id}/{source}/{dedupe_key}/
```

`evidence` 예시:

```json
{
  "roi_type": "food_bowl",
  "dwell_sec": 18.4,
  "head_near_roi": true,
  "mouth_contact_visible": false,
  "before_crop_key": "rba/crops/clip/before.jpg",
  "after_crop_key": "rba/crops/clip/after.jpg",
  "food_level_change": "possible_decrease",
  "food_level_confidence": 0.62,
  "surface_target": null,
  "notes": ["gecko occludes bowl for part of the segment"]
}
```

### 5.3 `rba_evidence_reviews`

event 단위 사람 검수 결과. 한 event에 여러 사람이 답할 수 있게 별도 테이블로 둔다.

```sql
CREATE TABLE rba_evidence_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES rba_evidence_events(id) ON DELETE CASCADE,
  clip_id UUID NOT NULL REFERENCES camera_clips(id) ON DELETE CASCADE,
  reviewed_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  review_status TEXT NOT NULL,
  corrected_action TEXT,
  corrected_lick_target TEXT,
  note TEXT,
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_id, reviewed_by)
);

CREATE INDEX idx_rba_evidence_reviews_clip_id
  ON rba_evidence_reviews (clip_id);
```

`review_status` 후보:

```text
confirmed
rejected
unknown
```

confirmed/rejected/unknown은 event 증거에 대한 답이다. 최종 GT 라벨이 필요하면 별도로 `behavior_labels`에 upsert한다.

### 5.4 `behavior_labels`와의 관계

기존 `behavior_labels`에는 이미 `lick_target`이 있다. 이 필드는 유지한다.

- 사람이 최종 라벨을 `drinking`으로 고르면 `lick_target=wall|object|dish`를 저장할 수 있다.
- evidence event는 "AI가 본 증거"다.
- behavior label은 "사람 또는 최종 합의 라벨"이다.

RLS/권한은 기존 패턴과 맞춘다. 초기에는 service_role 백엔드 API가 owner/labeler 권한을 검사하고, 테이블은 RLS enable + 최소 policy 또는 policy 0건으로 시작한다.

### 5.5 미스팅 컨텍스트

표면 음수 판단(§4.4)에 쓸 미스팅 신호. 세 소스를 합집합으로 본다. 초기에는 테이블 신설을 최소화하고 가볍게 시작한다.

1. **스케줄 (camera 메타)** — `cameras` 또는 별도 `camera_misting_schedule` 에 자동분무 시각/주기를 둔다. 가장 싸고 정확.

```json
{ "mode": "auto", "times": ["22:00", "02:00", "06:00"], "tz": "Asia/Seoul" }
```

2. **감지 이벤트 (rba_evidence_events 재사용)** — 미스팅을 별도 테이블이 아니라 `event_type='misting_detected'` evidence event 로 저장한다. `source='cv_roi'` 또는 analyzer. 수동/자동 모두 흡수.

3. **수동 원탭 로그 (선택)** — owner 가 "방금 분무" 누르면 timestamp 기록. 초기엔 `rba_evidence_events(event_type='misting_manual', source='human_review')` 로 갈음 (새 테이블 불필요).

표면 음수 evidence 의 `evidence` JSONB 에 미스팅 연결을 남긴다.

```json
{
  "roi_type": "surface_leaf",
  "lick_shape": "sustained_lapping",
  "contact_sec": 7.2,
  "misting_context": { "source": "schedule", "minutes_since": 14, "matched": true }
}
```

`misting_context.matched=false` 면 `surface_drinking_candidate` 까지만 올린다.

---

## 6. 판단 룰 초안

초기값은 평가셋으로 조정한다. 아래 숫자는 첫 구현 기본값이다.

### 6.1 밥그릇 방문

```text
food_bowl_visit =
  gecko head/body near padded food_bowl ROI for >= 5 sec
```

`>= 10 sec`이면 strong visit로 본다. 단, 몸 전체가 지나가기만 한 경우는 `moving_near_roi`로 낮춘다.

### 6.2 밥 먹음 추론

```text
food_intake_inferred =
  food_bowl_visit
  AND (
    mouth_contact_visible
    OR repeated_head_dip_to_bowl
    OR food_level_change in {possible_decrease, clear_decrease}
  )
```

`food_level_change=clear_decrease`이면 confidence를 올린다. 그릇이 가려져 before/after가 불확실하면 `candidate`로 남긴다.

### 6.3 물그릇 음수

```text
dish_drinking_inferred =
  water_bowl_visit
  AND repeated_mouth_contact
  AND no_food_visible_in_roi
```

물그릇은 표면 변화가 작아서 before/after보다 반복 접촉과 ROI 타입을 더 신뢰한다.

### 6.4 벽/잎/사물 표면 음수

```text
surface_drinking_candidate =
  repeated mouth/tongue contact with surface ROI
  OR repeated head press/lick-like motion against wall/leaf/object
```

```text
surface_drinking_inferred =
  surface_drinking_candidate
  AND sustained_lapping_shape            # 한 자리 반복 lapping (darting flick 아님)
  AND (
    misting_context.matched             # 스케줄 ∪ 감지 ∪ 원탭 중 하나로 최근 미스팅 확인 (§5.5)
    OR repeated contacts last >= 3 sec
  )
```

마르는 시간이 표면마다 달라 "분무 후 N분" 칼같은 창은 쓰지 않는다 (§4.4). 미스팅 매칭이 없거나 행동이 darting flick 이면 `surface_drinking_candidate` 까지만 올린다. "벽면을 핥음"과 "물을 마심"은 다르다. 개별 확정보다 **밤 단위 집계**가 본질이다.

---

## 7. 구현 단계

### Phase 0 — 문서/타입 고정

- [ ] 이 스펙을 구현 담당 Claude가 읽고 In/Out 경계를 확인한다.
- [ ] `docs/VLM-CLASSIFIER.md`에 "direct top-1 한계 → evidence-based inference" 후속 전략을 한 단락 추가한다.
- [ ] `experiment-event-segment-vlm.md`에 Track B evidence event 연결을 추가한다.

### Phase 1 — DB + 타입

- [ ] migration 추가: `migrations/2026-06-02_rba_evidence_events.sql`
- [ ] `camera_rois`, `rba_evidence_events`, `rba_evidence_reviews` 테이블 생성.
- [ ] Python 타입 추가: `backend/rba/evidence.py`
  - `RoiType`
  - `EvidenceLevel`
  - `EvidenceEventType`
  - `RbaEvidenceEvent`
- [ ] TypeScript 타입 추가: `web/src/types.ts` 또는 `web/src/lib/rbaEvidence.ts`
  - Python enum-ish와 동치 주석.
- [ ] DB CHECK는 과하게 걸지 않는다. 기존 라벨 정책처럼 앱 레벨 검증을 우선한다.

### Phase 2 — ROI 관리 최소 API

- [ ] `backend/routers/rba.py` 추가.
- [ ] `GET /cameras/{camera_id}/rois`
- [ ] `POST /cameras/{camera_id}/rois`
- [ ] `PATCH /rois/{roi_id}`
- [ ] `DELETE /rois/{roi_id}` 또는 `active=false`
- [ ] 권한은 camera owner만. labeler는 읽기만 허용할지 별도 결정.
- [ ] `backend/main.py`에 router include.

MVP UI가 늦으면, 첫 카메라는 SQL seed나 JSON import 스크립트로 ROI를 넣어도 된다.

### Phase 3 — offline analyzer PoC

- [ ] `scripts/rba_evidence_poc.py` 작성.
- [ ] 입력:
  - clip id 또는 local mp4 path
  - ROI JSON 또는 DB `camera_rois`
  - optional previous/next clip for before/after
- [ ] 출력:
  - `experiments/rba-evidence/{clip_id}/events.json`
  - ROI crop/contact sheet
  - before/after crop
- [ ] 처음 10개는 DB write 없이 artifact만 만든다.

분석 순서:

```text
clip mp4
→ ROI 로드
→ 1fps 또는 2fps frame sample
→ ROI crop/contact sheet 생성
→ SegmentVLM analyzer 호출
→ evidence events JSON 생성
→ 사람이 artifact 보고 outcome 기록
```

### Phase 4 — analyzer backend

- [ ] `backend/rba/analyzer.py` 또는 `scripts/` 쪽에 먼저 구현한다.
- [ ] Gemini direct-video analyzer는 event mp4 + ROI metadata를 입력으로 받는다.
- [ ] Codex/Claude frame analyzer는 contact sheet + crop pair를 입력으로 받는다.
- [ ] analyzer prompt는 "final action"보다 "evidence extraction"을 우선한다.
- [ ] 응답 JSON schema:

```json
{
  "events": [
    {
      "event_type": "food_bowl_visit",
      "evidence_level": "visit",
      "start_sec": 12.0,
      "end_sec": 30.5,
      "duration_sec": 18.5,
      "confidence": 0.78,
      "needs_human_review": true,
      "evidence": {
        "roi_type": "food_bowl",
        "mouth_contact_visible": false,
        "food_level_change": "unknown",
        "reason": "Gecko remains near bowl but mouth is occluded."
      }
    }
  ]
}
```

### Phase 5 — DB write + API read

- [ ] artifact 검증 후 `rba_evidence_events` insert를 켠다.
- [ ] 같은 clip/source 재실행 시 `dedupe_key`로 중복 저장을 막는다.
- [ ] `GET /clips/{clip_id}/rba-evidence`
- [ ] `GET /clips/rba-summary?from=&to=`
- [ ] `POST /clips/{clip_id}/rba-evidence/{event_id}/review`
  - `confirmed`
  - `rejected`
  - `unknown`
  - optional corrected action/lick_target
- [ ] review 저장은 `rba_evidence_reviews`에 하고, 최종 GT 확정이 필요할 때만 `behavior_labels`에 upsert한다.

### Phase 6 — 라벨링 웹 검수 UI

- [ ] clip detail 화면에 RBA Evidence 패널 추가.
- [ ] event card:
  - event type badge
  - evidence level badge
  - 5~15초 clip link
  - ROI crop before/after
  - "맞음 / 아님 / 모름" 버튼
- [ ] 사용자-facing 문구는 단정하지 않는다.
  - good: "밥그릇 방문"
  - good: "섭식 가능성 높음"
  - bad: "밥 먹음" (confirmed 아니면 금지)

### Phase 7 — 평가 리포트

**검증 대상 주의:** "물 마셨다"를 per-event 로 라벨링하지 않는다 (시각으로 불가능). 대신 **GT 달 수 있는 입력**(미스팅 시각 / 입·혀 접촉 y/n + 지속초 + 핥기 모양 / 어느 ROI)으로부터 **파이프라인이 합당한 evidence 레벨을 뱉는지** + **밤 단위 집계 요약이 말이 되는지**를 본다.

데이터 수집:
- [ ] **Gate 0 (먼저)** — 미스팅이 카메라에 보이는지 1~3개 clip 으로 확인. 안 보이면 감지 노선 접고 스케줄+원탭+candidate 폴백으로 결정.
- [ ] 정상 운영 **1~2박 passive 녹화** (실 미스팅 레짐) — 물그릇 방문 + 여러 표면 핥기 + 미스팅 이벤트가 자연 발생. 카메라 고정 + 물그릇·핥는 표면 한 프레임 + 야간 IR.
- [ ] 30~50개 representative/mismatch clip 선정 (기존 Track A 비교용).

- [ ] 기존 Track A와 비교:
  - clip-level top-1 accuracy
  - P0 recall
  - feeding false positive
  - drinking/surface drinking candidate precision
  - human review rate
- [ ] **집계 검증** — 밤 단위 수분 요약(물그릇 확실 + 표면 후보 집계)이 owner 가 보기에 합당한가.
- [ ] `experiments/rba-evidence/report.md` 작성.
- [ ] 기준 충족 시 production selective fallback 후보로 승격.

---

## 8. 파일 작업 가이드

구현 담당 Claude는 아래 파일을 먼저 읽어라.

1. [`AGENTS.md`](../AGENTS.md)
2. [`docs/VLM-CLASSIFIER.md`](../docs/VLM-CLASSIFIER.md)
3. [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md)
4. [`specs/feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md)
5. [`specs/feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md)
6. [`specs/experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md)
7. [`backend/routers/labels.py`](../backend/routers/labels.py)
8. [`backend/vlm/prompts.py`](../backend/vlm/prompts.py)
9. [`web/src/types.ts`](../web/src/types.ts)

예상 신규 파일:

```text
migrations/2026-06-02_rba_evidence_events.sql
backend/rba/__init__.py
backend/rba/evidence.py
backend/rba/roi.py
backend/rba/analyzer.py
backend/routers/rba.py
scripts/rba_evidence_poc.py
scripts/eval_rba_evidence.py
web/src/lib/rbaEvidence.ts
```

예상 수정 파일:

```text
backend/main.py
web/src/types.ts
web/src/app/labeling/[clipId]/page.tsx
docs/VLM-CLASSIFIER.md
docs/AI-VIDEO-ANALYSIS-STRATEGY.md
specs/experiment-event-segment-vlm.md
specs/README.md
```

---

## 9. 테스트 계획

### Backend

- [ ] ROI 타입/Pydantic 검증 단위 테스트.
- [ ] owner만 ROI 쓰기 가능.
- [ ] labeler/owner 권한 경계 회귀.
- [ ] `GET /clips/{clip_id}/rba-evidence`가 clip owner에게만 보이는지 확인.
- [ ] migration SQL 문법 검증.

### Analyzer

- [ ] local mp4 1건에서 ROI crop 생성 성공.
- [ ] before/after crop key 생성.
- [ ] analyzer JSON schema parse 실패 시 안전하게 `needs_human_review=true`.
- [ ] 동일 input 재실행 시 `dedupe_key` 중복 방어 확인.

### Web

- [ ] ROI/evidence 타입 렌더링.
- [ ] confirmed 아닌 event는 단정 문구를 쓰지 않음.
- [ ] before/after crop이 없으면 graceful empty state.
- [ ] 버튼 클릭 후 review 상태 반영.

### Eval

- [ ] 30~50개 report에서 아래 지표 출력:
  - Track A baseline accuracy
  - evidence-assisted inferred accuracy
  - P0 recall
  - feeding false positive
  - surface drinking candidate precision
  - review burden

---

## 10. 성공 기준

다음 중 하나 이상 만족하면 Track B selective fallback으로 계속 투자할 가치가 있다.

| 기준 | 채택 신호 |
|---|---|
| P0 recall | Track A 대비 +10%p 이상 |
| feeding false positive | 기존 `moving → eating_paste` 오답 감소 |
| drinking coverage | dish drinking과 surface drinking 후보가 분리되어 검수 가능 |
| HITL 효율 | 사용자가 60초 전체가 아니라 5~15초 evidence segment만 보면 됨 |
| 설명 가능성 | 사용자에게 "왜 그렇게 판단했는지" crop/ROI/시간으로 설명 가능 |
| 비용 | Track B 실행률 10~15% 이하 유지 가능 |

전체 top-1 정확도 +3%p도 좋지만, 이 스펙의 본질은 top-1 하나가 아니다. **짧은 섭식/음수 신호를 놓치지 않고, 단정 대신 근거를 남기는 것**이 핵심이다.

---

## 11. 리스크

- 카메라 위치가 바뀌면 ROI가 틀어진다. ROI drift 감지 또는 owner 재설정 UX가 필요할 수 있다.
- 그릇이 게코 몸에 가려지면 before/after 비교가 무효가 된다.
- 먹이 표면 변화는 조명/압축/그림자에 취약하다.
- 물그릇은 양 변화가 거의 안 보인다. 반복 접촉/ROI 타입 중심으로 봐야 한다.
- 벽면/잎 표면 핥기는 "수분 섭취"와 "탐색/그루밍" 구분이 어렵다. `surface_drinking_candidate`부터 시작한다.
- analyzer가 evidence JSON을 그럴듯하게 꾸며낼 수 있다. crop/contact sheet artifact와 사람이 확인 가능한 근거를 반드시 남긴다.

---

## 12. 구현 담당 Claude에게 주는 지시

이 작업은 "Gemini prompt를 더 세게 고쳐서 eating/drinking을 맞히는 일"이 아니다.

먼저 해야 할 일:

1. 이 스펙과 연관 문서 6개를 읽어.
2. `behavior_logs`와 `behavior_labels` 기존 역할을 확인해.
3. DB migration + 타입 + offline PoC부터 작게 시작해.
4. production worker나 v3.5 prompt는 건드리지 마.
5. 10개 artifact로 사람이 납득 가능한지 먼저 보여줘.

금지:

- v3.5 prompt를 임의 수정하지 마.
- `feeding` UI merge를 되돌리지 마.
- `eating_paste` / `drinking`을 바로 폐기하지 마.
- `confirmed`를 쉽게 쓰지 마.
- "fps 늘리면 해결" 방향으로 선회하지 마. fps 증가는 후속 실험 카드다.

권장 첫 PR/작업 단위:

```text
1. migration + 타입 + router skeleton
2. ROI seed/import script
3. offline rba_evidence_poc.py artifact 생성
4. 10개 샘플 수동 평가 리포트
```

---

## 13. 참고

- [`docs/VLM-CLASSIFIER.md`](../docs/VLM-CLASSIFIER.md) — v3.5 baseline, 85.5% floor, 시각 한계 결론
- [`feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md) — drinking + eating_paste UI 통합
- [`feature-vlm-feeding-postfilter.md`](feature-vlm-feeding-postfilter.md) — dish binary router 폐기 근거
- [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md) — 모호 케이스 사용자 검수
- [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) — Track B / SegmentVLM 기본 전략
