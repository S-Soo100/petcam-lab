# 구현계획 — 테스트 카메라 활동시간 필터 v0

> 작성일 2026-07-14 · 상태 **Phase 0~3 완료. Phase 3 preflight = 두 스위치 reject → Phase 5 활성화 보류** · scope cross-repo HIGH
>
> **결과 요약 (2026-07-14):** 파이프라인(Gate evidence + four-state policy + nightly activity_worker + DB migration/view)
> 완성·테스트·운영 migration 적용 완료. 그러나 카메라 A 사람 preflight 에서 **exclude_absent 10/10 false
> exclusion(RF-DETR 게코 미검출 FN, precision 0%)** + **exclude_static 1건 false exclusion** →
> 두 스위치 모두 활성화 금지. 앱 활동시간 raw 유지(변화 0). detector recall(Gate v3 재학습)이 선결.
> 상세: [`experiments/activity-preflight-0714/REPORT.md`](../../../experiments/activity-preflight-0714/REPORT.md).
> 지시문: `docs/handoff-prompts/claude-test-camera-activity-filter-v0.md`
> 목표: Claude/VLM 없이 Mac mini에서 테스트 카메라 motion clip을 Gate로 자동 분석 → 명확한 비활동 클립 길이를 앱 활동시간에서 안전하게 제외 + evidence를 Gate 발전 데이터로 축적.

---

## 0. Phase 0 확인 사실과 이전 가정 불일치

### 확정 사실 (read-only 검증)
- **DB는 통합 Supabase 프로젝트 1개.** `motion_clips`(10,457행)·`cameras`(3행)·기존 연구 테이블이 전부 같은 프로젝트에 존재. → 여기서 `motion_clips(id)` FK를 직접 걸 수 있다.
- **머신 = Mac mini M4 (`Mac17,2`, 10코어, macOS 26.2).** 현재 실행 머신이 곧 운영 Mac mini.
- **Gate 실측 처리시간 (이 Mac mini):** 모델 로드+첫 추론 **6.55s**, 재사용 추론 **0.53s/clip**(12프레임). 게코 검출 정상(conf 0.85 visible / absent 구분).
  - 처리량: 오늘 유입 ~350clip ≈ **10분**, 전체 backlog 10,457 ≈ **4시간**. **단일 worker로 충분, MPS 병렬 불필요.**
- **Gate 체크포인트 로컬 존재:** `runs/gecko_v2/checkpoint_best_ema.pth`(120MB)·`checkpoint_best_regular.pth`. `.venv` 정상, rfdetr/torch 설치됨.
- **카메라 데이터 분포:** A(9,650clip·오늘 324)·B(755·오늘 0)·C(60·오늘 29). 오늘(KST) 총 ~353clip.

### 이전 가정과의 불일치 (지시문 §57~71 대비)
| 가정 | 실제 |
|---|---|
| "`motion_clips`는 terra 별도 프로젝트일 수 있음" | **같은 통합 프로젝트.** FK 직접 가능 (설계 단순화) |
| "Gate 0.25가 잠정 recall 동작점" | gate 자체 test는 @0.25 clip recall 97.8%지만, **petcam backlog 300 평가(Claude proxy GT, regular ckpt)는 recall 90.9%/specificity 40%** — gate-v3.md가 "artifact/GT 재감사 전 자동 skip 금지" 상태로 명시. → **0.25를 정식값으로 단정 안 함. Phase 3 사람 GT로 확정.** |
| "clip_prelabels/clip_activity_assessments 없거나 접근 불가" | **둘 다 DB에 없음(신규 생성 대상).** clip_prelabels는 SOT(petcam-ai-pipeline §11)에 계획만, DDL은 gate `schema.py` dataclass로만 존재. clip_activity_assessments는 이 지시문이 유일 언급 = 완전 신규 |
| — | **기존 연구 테이블(clip_router_features·router_review_items·behavior_logs)은 전부 `camera_clips(id)` FK.** 이번 작업은 지시문 명시·Flutter 정합·운영 SOT 근거로 **`motion_clips(id)` FK를 쓰는 첫 케이스.** |

### 충돌/불명확 → 사용자 확인 필요 (§11 참조)
설계상 지시문과 정면 충돌은 없음. 단 3개 재량 결정(policy 모듈 위치·dependency 방식·read contract)은 추천안을 제시하고 승인받는다.

---

## 1. 아키텍처 결정 (근거 포함)

### D1. 새 DB 테이블 3개, 전부 `motion_clips(id)` FK
`clip_prelabels`(Gate evidence) · `clip_activity_assessments`(제품 판정) · `camera_activity_filter_settings`(카메라별 스위치).
- **FK 대상 = `motion_clips(id)`** (camera_clips 아님). 근거: ① 지시문 §157 명시 ② Flutter가 `motion_clips` 직접 조회 → 활동시간 정합 ③ motion_clips가 운영 SOT(최신 10k행).
- evidence(무엇을 봤나)와 decision(제품 판정)을 **테이블로 분리** — 지시문 §97 책임 분리.

### D2. read contract = `security_invoker` VIEW (RPC 아님) — **추천, 승인 요청**
- Flutter 기존 패턴은 `.from('motion_clips')` + RLS 직접 조회. **집계 아닌 clip 단위 행**을 받아 앱에서 합산(byHour 포함).
- `security_invoker=on` view면 조회자의 RLS(motion_clips owner)가 그대로 적용 → owner 격리 자동, 기존 RLS 패턴과 정합. RPC(SECURITY DEFINER)는 owner 체크를 수동 구현해야 해 더 복잡·위험.
- 대안(RPC)은 "집계를 DB에서" 필요할 때 유리하나 v0는 clip 단위 계약이라 view가 최소 변경.

### D3. activity policy 모듈 = **Gate 레포 별도 모듈** `gecko_vision_gate.activity_policy` — **추천, 승인 요청**
- evidence 생성(`prelabel`)과 policy decision을 **파일·DB로 분리**(지시문 §97·§119)하되, 같은 데이터 계약(`PrelabelResult`/`DetectedObject`)을 공유하므로 같은 레포 별도 모듈이 import 경계가 깔끔.
- 이점: nightly가 **Gate 하나만** dependency로 가짐(petcam-lab 런타임 의존 불필요). policy는 versioned dataclass로 주입 → 코드 상수 하드코딩 금지 충족.
- 대안(petcam-lab에 policy): "연구소=정책 SOT" 원칙엔 부합하나 petcam-lab은 런타임 패키지가 아니고 nightly에 새 의존을 강제. → **Gate 레포 별도 모듈 채택**, Gate 책임 경계는 "evidence 생성 순수함수 vs decision 순수함수"를 파일 분리로 유지.

### D4. nightly→gate dependency = **uv 로컬 path(editable)** — **추천, 승인 요청**
- `[tool.uv.sources]`에 상대경로 `../myPythonProjects/gecko-vision-gate` editable. 절대경로 하드코딩 아님(지시문 §135).
- git dependency(`S-Soo100/gecko-vision-gate` 존재)는 체크포인트(runs/ gitignore) 미포함 + 네트워크 의존이라 24h 상시가동 Mac mini에 부적합.
- 약점: 두 레포의 상대 위치 고정 필요 → `.env`의 `GATE_REPO_PATH`로도 override 가능하게 하고 설치 문서에 명시.

### D5. 미처리 clip 선택 = `clip_prelabels` LEFT JOIN (motion_clips 불변)
- `motion_clips`에 상태 컬럼 추가 **금지**(지시문 §438). 미처리 = "allowlist 카메라 AND `NOT EXISTS(clip_prelabels WHERE clip_id=mc.id AND model_version=현재)`".
- clip_router_features의 `(processing_status, started_at)` 인덱스 패턴 참조하되, 우리는 별도 상태 테이블 없이 evidence 존재 여부로 판별.

### D6. shadow/fail-open 계층
- **evidence·assessment 저장**은 allowlist 카메라면 항상(연구 데이터 축적). **앱 제외(effective=0)**는 `settings.enabled AND reason_enabled`일 때만.
- settings row 없음 = view LEFT JOIN NULL → `effective_activity_sec = raw` (fail-open). `unknown`/`pending`/`active`도 raw.

### D7. worker 분리
- `reporter.activity_worker` 신규 entrypoint + 별도 launchd job(`com.petcam.activity-worker`). 기존 `reporter.worker`(Claude 상황판) **무수정**. 새 worker는 **Claude/VLM 0회**.

---

## 2. DB 설계 (DDL 초안 — Phase 2에서 확정)

> 마이그레이션: `migrations/2026-07-14_activity_filter_v0.sql` (날짜프리픽스 forward-only) → `apply_migration` MCP. 원본 파일 수정 없음. rollback SQL 하단 주석.

### 2.1 `clip_prelabels` (Gate evidence, service write / owner read)
```sql
create table public.clip_prelabels (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.motion_clips(id) on delete cascade,
  -- provenance (지시문 §164)
  model_name text not null,               -- 'rf-detr-nano'
  model_version text not null,            -- 'gecko_v2 (checkpoint_best_ema)'
  checkpoint_sha256 text not null,        -- 실행환경 실측
  threshold real not null,                -- evidence 추출 threshold (recall 우선 낮은값)
  sampler_version text not null,
  schema_version text not null,
  frames_sampled int not null,
  -- evidence (손실 없이)
  gecko_visible boolean not null,
  visibility_confidence real not null,
  best_frame_ts real,
  gecko_bbox jsonb,                       -- [x,y,w,h]
  detected_objects jsonb not null,        -- [{type,confidence,bbox,frame_ts},...] 전체
  motion_metrics jsonb,                   -- static/activity 계산 근거 (bbox trajectory·ROI flow 등)
  producer_host text,
  producer_run_id text,
  created_at timestamptz not null default now(),
  unique (clip_id, model_version, schema_version)   -- 멱등 (같은 clip+gate버전)
);
create index idx_clip_prelabels_clip on public.clip_prelabels (clip_id);
```

### 2.2 `clip_activity_assessments` (제품 판정, service write / owner read)
```sql
create table public.clip_activity_assessments (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.motion_clips(id) on delete cascade,
  prelabel_id uuid not null references public.clip_prelabels(id) on delete cascade,
  decision text not null check (decision in ('active','exclude_absent','exclude_static','unknown')),
  reason_code text not null,              -- no_gecko / static_confirmed / sparse_detection / decode_fail ...
  measurements jsonb,                     -- 원시 측정값(판정 근거)
  policy_version text not null,
  producer_host text,
  producer_run_id text,
  created_at timestamptz not null default now(),
  unique (clip_id, policy_version)        -- 멱등. 새 policy_version = 새 row(이력 보존)
);
create index idx_clip_activity_assess_clip on public.clip_activity_assessments (clip_id);
```

### 2.3 `camera_activity_filter_settings` (카메라별 독립 스위치)
```sql
create table public.camera_activity_filter_settings (
  camera_id uuid primary key references public.cameras(id) on delete cascade,
  enabled boolean not null default false,
  exclude_absent_enabled boolean not null default false,   -- 독립 스위치
  exclude_static_enabled boolean not null default false,   -- 독립 스위치
  active_policy_version text,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id),               -- 감사
  note text
);
-- 카메라 UUID는 마이그레이션에 하드코딩 금지. Phase 5에서 사용자가 INSERT.
```

### 2.4 RLS (behavior_logs 패턴 이식)
```sql
-- 3개 테이블 공통: RLS on, service_role write, authenticated owner read
alter table public.clip_prelabels enable row level security;
create policy "owner reads own clip prelabels" on public.clip_prelabels
  for select to authenticated
  using (exists (select 1 from public.motion_clips mc
                 where mc.id = clip_prelabels.clip_id and mc.owner_id = auth.uid()));
revoke all on public.clip_prelabels from anon, authenticated;
grant select on public.clip_prelabels to authenticated;   -- RLS로 owner 필터
grant all on public.clip_prelabels to service_role;
-- clip_activity_assessments 동일. settings는 cameras owner_id 기준 read.
```

### 2.5 read contract VIEW
```sql
create view public.v_clip_effective_activity with (security_invoker = on) as
select
  mc.id as clip_id, mc.camera_id, mc.owner_id, mc.started_at,
  mc.duration_sec as raw_duration_sec,
  coalesce(caa.decision, 'pending') as activity_decision,
  case
    when s.camera_id is null or not s.enabled then mc.duration_sec
    when caa.decision = 'exclude_absent' and s.exclude_absent_enabled then 0
    when caa.decision = 'exclude_static' and s.exclude_static_enabled then 0
    else mc.duration_sec
  end as effective_activity_sec,
  (caa.clip_id is null) as analysis_pending,
  s.active_policy_version as policy_version
from public.motion_clips mc
left join public.camera_activity_filter_settings s on s.camera_id = mc.camera_id
left join public.clip_activity_assessments caa
  on caa.clip_id = mc.id and caa.policy_version = s.active_policy_version;
```
- `security_invoker=on` → motion_clips owner RLS 상속. 활동시간 전체·시간대별 그래프가 같은 `effective_activity_sec` 사용.
- **롤백:** `update camera_activity_filter_settings set enabled=false` → 즉시 raw 복귀(앱 재배포 불필요). 완전 제거는 `drop view; drop table ...`.

---

## 3. Gate 확장 (`gecko-vision-gate`) — 하위호환

| 파일 | 변경 | 내용 |
|---|---|---|
| `src/gecko_vision_gate/schema.py` | 수정(하위호환) | `PrelabelResult`에 provenance 필드 추가(기본값 有): `checkpoint_sha256`·`threshold`·`sampler_version`·`schema_version`·`motion_metrics`. `to_dict` 기존 순서 유지 + 신규 뒤에 append. 기존 테스트 회귀 없게. |
| `src/gecko_vision_gate/provenance.py` | **신규** | `checkpoint_sha256(path) -> str` (hashlib, lru_cache). `SAMPLER_VERSION`/`SCHEMA_VERSION` 상수. |
| `src/gecko_vision_gate/motion_evidence.py` | **신규** | 순수 OpenCV. `compute_motion_metrics(frames, result) -> dict`: bbox center/size/IoU 변화·연속프레임 ROI grayscale/optical flow·global background 보정·visibility ratio. **판정 안 함, 수치만.** |
| `src/gecko_vision_gate/activity_policy.py` | **신규(별도 모듈)** | `@dataclass(frozen=True) ActivityPolicy(version, gate_threshold, absent_min_frames, static_motion_max, edge_margin, ...)` + 순수함수 `decide(result, motion_metrics, policy) -> ActivityAssessment(decision, reason_code, measurements)`. four-state 로직. |
| `src/gecko_vision_gate/prelabel.py` | 수정(하위호환) | frames를 함께 반환하는 경로 추가(motion_evidence가 프레임 필요). 기존 `prelabel_clip` 시그니처 유지, 신규 `prelabel_clip_with_frames` 또는 옵션 인자. |
| `tests/` | **신규** | 아래 §6 Gate 테스트. |

### four-state decision 로직 (지시문 §202~231)
- **unknown(fail-open 기본):** decode 실패·sample 부족·모델 오류·sparse detection(1~2프레임만)·bbox 심하게 edge crop·local/global motion 구분 불가·임계값 경계·짧은 혀/머리 움직임 배제 위험.
- **exclude_absent:** 정상 decode + 충분 frame sampling + gecko detection **0건**일 때만.
- **exclude_static:** gecko 안정적 visible(충분 visibility ratio) + activity evidence 없음 + 위 unknown 조건 아님.
- **active:** activity evidence 하나라도 신뢰 관찰(미세 움직임 무시 금지).
- 모든 임계값은 `ActivityPolicy` 하나에서 주입. 수치는 Phase 3 dry-run+사람 GT로 확정(추측 확정 금지).

---

## 4. Nightly activity_worker (`petcam-nightly-reporter`)

| 파일 | 변경 | 내용 |
|---|---|---|
| `reporter/activity_worker.py` | **신규 entrypoint** | `run()`: flock → settings allowlist → 미처리 clip 선택 → detector 1회 로드 → batch(오류 격리) → evidence+assessment 멱등 upsert → 관측 로그 1줄. **Claude 0회.** |
| `reporter/gate_runner.py` | **신규** | `GeckoDetector` 1회 로드 캐시 + `prelabel_clip_with_frames`→`compute_motion_metrics`→`decide` 파이프라인 래퍼. |
| `reporter/activity_indexer.py` | **신규** | 미처리 motion_clips 선택(allowlist 카메라 + `NOT EXISTS clip_prelabels`). 시간창 or backlog 모드. |
| `reporter/activity_store.py` | **신규** | `clip_prelabels`/`clip_activity_assessments` service_role upsert(on conflict do nothing). |
| `reporter/activity_settings.py` | **신규** | `camera_activity_filter_settings` 조회 → enabled 카메라 목록. 비면 0건 종료. |
| `reporter/config.py` | 수정(추가만) | `GATE_CHECKPOINT_PATH`·`GATE_REPO_PATH`·`ACTIVITY_POLICY_VERSION`·`ACTIVITY_MODEL_VERSION` env 읽기. 기존 상수 무수정. |
| `pyproject.toml` | 수정 | `[tool.uv.sources]` gecko-vision-gate editable path (D4). |
| `.env.example` | 수정 | 위 env **이름만** 추가. 카메라 UUID·비밀값 금지. |
| `install-launchd-activity.sh` | **신규** | 별도 job `com.petcam.activity-worker`, 로그 `/tmp/activity-worker.log`. 기존 `install-launchd.sh` 무수정. |

- **재사용:** `config`(creds)·`r2.download_clip`·`indexer.list_clips_for_window`(참조)·flock 신규 추가·`TemporaryDirectory`(기존 패턴)·오류 격리(기존 패턴).
- **성능:** detector process lifetime 재사용, 단일 worker, `VideoCapture.release()` 전 경로 보장, temp `try/finally`.

---

## 5. Flutter 연결 (`tera-ai-flutter`) — 최소 변경

| 파일 | 변경 |
|---|---|
| `lib/features/my_cage/data/motion_clip_repository.dart` | `motionSeconds`(:130-149)·`motionSecondsByHour`(:153-174) **본문만**: `.from('motion_clips')`→`.from('v_clip_effective_activity')`, `duration_sec`→`effective_activity_sec`. 시그니처·provider·위젯 불변. `bucketMotionSecondsByHour`(cage_activity.dart) record 키 `durationSec` 유지 → 무수정. |
| `assets/l10n/ko.json` | 활동시간 문구 → `활동시간(추정)` (`home_activity_total_label` 등 대상). |
| `test/features/my_cage/` | 순수 함수(bucket) 테스트는 유지. view 계약 검증은 §6 DB SQL probe로 보완(repository는 mock 없음). |

- `unknown`/pending/disabled 카메라 → view가 이미 raw 반환 → 앱은 그대로 포함. active만 포함, absent/static만 0.
- 전체 합 = hourly 합: 둘 다 같은 view의 `effective_activity_sec` 사용 → 자동 일치.

---

## 6. 테스트 계획

- **Gate:** schema 직렬화·하위호환 / per-frame evidence / provenance(sha256·threshold·version) / four-state decision table / local vs global motion 구분 / invalid video·sparse fail-open / policy version·threshold 주입. (합성 프레임 fixture 8케이스: absent·visible+static·visible+이동·머리혀 미세·IR밝기만·전체흔들림·sparse·decode실패)
- **Worker:** allowlist 없는 camera 미적용 / disabled 미적용 / 미처리 clip만 선택 / 재실행 멱등 / model 1회 로드 batch 재사용 / 한 clip 실패가 batch 안 죽임 / temp cleanup / DB·R2 오류→unknown or retry / 두 독립 스위치.
- **DB(SQL probe):** FK/cascade / unique·index / service write / authenticated owner read / **타 owner read 거부** / 설정 없음=disabled(raw) / active policy version만 반영 / disabled 시 raw 복귀. rollback transaction probe.
- **Flutter:** active 포함 / absent·static 제외 / unknown·pending 포함 / disabled 포함 / 전체=hourly 일치 / 다중카메라 NightlyReport 회귀.

---

## 7. cross-repo 파일 목록 (신규 N / 수정 M)

```
gecko-vision-gate/     [N] provenance.py, motion_evidence.py, activity_policy.py, tests/test_activity_policy.py, tests/test_motion_evidence.py
                       [M] schema.py, prelabel.py
petcam-nightly-reporter/ [N] reporter/activity_worker.py, gate_runner.py, activity_indexer.py,
                             activity_store.py, activity_settings.py, install-launchd-activity.sh,
                             tests/test_activity_worker.py, tests/test_activity_indexer.py, tests/test_activity_store.py
                       [M] reporter/config.py, pyproject.toml, .env.example
petcam-lab/            [N] migrations/2026-07-14_activity_filter_v0.sql
                       [M] specs/*, docs SOT (활동 완료 시)
tera-ai-flutter/       [M] lib/features/my_cage/data/motion_clip_repository.dart, assets/l10n/ko.json
tera-ai-product-master/ [M] docs/specs/petcam-ai-pipeline.md §11 (clip_activity_assessments 편입)
```

---

## 8. 배포·롤백 순서 (Phase별 승인 게이트)

1. **Phase 1** Gate 확장 TDD → 테스트 green → **사용자 승인 후** gate 레포 commit.
2. **Phase 2** migration SQL 작성 + rollback probe → **운영 apply_migration 전 사용자 승인** → worker TDD(shadow, 앱 제외 0건).
3. **Phase 3** 사람 preflight(absent/static/active 각 10, 총 30, blind manifest) → detector/decision 비교 → **권장 스위치 보고 + 활성화 승인**. 명확 active가 exclude 1건이라도 → 그 스위치 활성화 금지.
4. **Phase 4** Flutter 연결 TDD → analyze/test/build.
5. **Phase 5** 승인된 test camera만 `enabled=true` → 통과한 reason만 켜기 → **오늘 데이터만** backfill → raw vs filtered 대조 → 24h 50clip 표본검수 → false exclusion 1건이라도 → 즉시 해당 reason off. **앱 배포·launchd enable 각각 승인.**

**롤백 요약:** ① 스위치 `enabled=false`(즉시 raw, 무배포) ② launchd `bootout` ③ migration down SQL ④ Flutter git revert. 원본 R2·motion_clips 불변 유지 → 항상 안전 복구.

---

## 9. 관측성 (worker 1줄 로그, 비밀값 없음)
조회 clip수 / 성공·실패·skip / active·absent·static·unknown / 평균·최대 처리시간 / backlog / model·policy version. 일단위 비교: raw vs filtered minutes / reason별 제외 / pending·unknown·error 비율 / camera별. R2 signed URL·service key·SQL 오류 상세 노출 금지.

---

## 10. v0 범위 재확인
- **In:** 테스트카메라 allowlist / Gate v2 evidence+provenance / four-state assessment / 별도 24h worker / dry-run+review manifest / migration+RLS+read contract / Flutter 전체·시간대별 연결 / `활동시간(추정)` / 오늘 데이터 backfill / 관측+즉시롤백 / SOT 동기화.
- **Out:** 클립 내부 초단위 활동합산 / 행동분류 / Claude·VLM 재개 / Gate v3 재학습 / 고객 카메라 / Nightly Slack 수치전환 / 7일+ backfill / 라벨링웹 Gate UI / 원본 삭제.

---

## 11. 사용자 확인 필요 (Phase 0 게이트)
1. **D2 read contract = view** (RPC 아님) — 동의?
2. **D3 activity_policy = Gate 레포 별도 모듈** (petcam-lab 아님) — 동의?
3. **D4 dependency = uv 로컬 path editable** — 동의?
4. **테스트 카메라 선택** — Phase 5에서 어느 카메라(A/B/C) 활성화할지. 지금은 미정, 하드코딩 안 함.
5. **전체 구현 착수 승인** — Phase 1(Gate TDD)부터 시작해도 되나?

---

## 12. shadow-only 운영 + policy-version guard (2026-07-14 보정 — 미실행 계획)

fresh safety holdout 결과(REPORT `experiments/activity-preflight-0714/REPORT.md` §8~15):
**exclude_absent = REJECT**(카메라 B, threshold 0.10 도 게코 놓침) · **exclude_static = HOLD**(effective episode ≈2 + 사람 질문 결함) · **두 차감 스위치 disabled**. 활성화 전 shadow-only 로 evidence 를 축적한다.

### 실행 순서 (A~G, 각 단계 사용자 승인 후)
- **A. policy-version 정합성 guard 구현·테스트** — worker `run()` 에 카메라별 검사 추가:
  - `load_enabled_cameras` 가 주는 `CameraFilterSetting.active_policy_version` 을 worker `config.ACTIVITY_POLICY_VERSION` 과 비교.
  - **null 이거나 불일치 → 그 카메라 skip**(evidence/assessment **미저장**), mismatch 를 로그(`camera <id[:8]> policy mismatch settings=<x> worker=<y> — skip`).
  - **테스트 3케이스**: 일치→처리 / 불일치→skip·미저장 / null→skip·미저장.
  - **config 기본값 activity-v0 는 유지**(조용히 v1 로 바꾸지 않음). launchd 에서 `ACTIVITY_POLICY_VERSION=activity-v1` 명시.
- **B. feature branch 커밋/push + 통합 검토** (현재 미push: gate `89237a5`·nightly `e5c9bdf`·lab `cd00472` + 보정 문서 uncommitted).
- **C. shadow-only 가동** — DB `camera_activity_filter_settings`:
  `enabled=true, exclude_absent_enabled=false, exclude_static_enabled=false, active_policy_version='activity-v1'`.
  launchd `com.petcam.activity-worker` + env `ACTIVITY_POLICY_VERSION=activity-v1`. 가동 후 `v_clip_effective_activity` 에서
  `effective_activity_sec == raw_duration_sec`·exclusions=0 확인.
- **D. 며칠 evidence/assessment 축적** (앱 활동시간 불변).
- **E. 축적 데이터에 30분 episode dedup → 독립 static ≥20 선정** (REPORT §13 selector).
- **F. 사람 blind 검수** — 질문 2단 분리(먼저 include/exclude/unclear, 별도 진단으로 presence·activity).
- **G. FE=0 일 때만 카메라 A 의 exclude_static 제한 활성화 검토.**

### 불변 제약
- exclude_absent 계속 **REJECT**, exclude_static **HOLD**. Flutter 연결·실제 시간 차감·스위치 활성화는 금지.
- push/merge/launchd/DB write 는 각 단계 사용자 승인 후에만. 이번 세션은 **문서·계획만**(코드/DB 무변경).

### utility 다음 스크립트 계획
- decision 별 clip count 뿐 아니라 **`raw_duration_sec`·`excluded_duration_sec` 를 각각 저장** (활동시간 지표는 duration 가중이 정본; 현재 static/absent 분리치는 클립 수 기준 근사).
