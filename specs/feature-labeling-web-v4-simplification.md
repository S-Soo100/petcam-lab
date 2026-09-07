# 라벨링 웹 v4 단순화 — 교차검증 폐기, 단독 확정, 카메라 배정 + 전체 열람

> 두 명 blind → 합의 → 불일치 owner 검수 구조를 전부 버린다. Owner는 모든 영상, 회원은 A페이지(배정 카메라)와 B페이지(모든 카메라)를 보고, 라벨링 안 된 영상은 누구든 라벨링한다. 한 사람이 확정하면 끝.

**상태:** 🚧 Phase 1·2 `IMPLEMENTED_VERIFIED_NOT_DEPLOYED` (2026-09-07, 브랜치 `feat/highlight-rule-v0`) — Preview canary·production 은 Task 9 owner 승인 대기
**작성:** 2026-09-07
**연관:** [`feature-highlight-auto-initial-designation.md`](feature-highlight-auto-initial-designation.md) (첫 라벨 항목 = 하이라이트 O/X), [`docs/FEATURES.md`](../docs/FEATURES.md) §11.8 (버리는 구조의 현재 기록)
**결정 게이트:** [`docs/decision-gate.md`](../docs/decision-gate.md) 2026-09-07 3차
**구현 계획:** [`docs/superpowers/plans/2026-09-07-labeling-web-v4.md`](../docs/superpowers/plans/2026-09-07-labeling-web-v4.md) (A 계획 뒤에 실행)

## 0. owner 지시 (2026-09-07, 원문 요지)

> 싹 다 버리고. owner는 모든 영상을 볼 수 있고, 다른 회원은 A페이지(가칭)에서 지정된 카메라의 영상을, B페이지에서 모든 카메라의 영상을 볼 수 있고, 라벨링되지 않은 영상은 누구든지 라벨링할 수 있는 권한이 있어. 사람 교차검증은 그만, 각자 검증한 결과를 100% 신뢰.

## 1. 목적

- **운영:** 라벨링을 "배정된 두 명이 같은 걸 두 번 보고 합의"에서 "누구든 안 된 걸 하나 집어서 확정"으로 바꾼다. 대기·불일치·검수함이 사라진다.
- **제품:** 첫 라벨 항목은 하이라이트 O/X(GME 1차 판정 확인). 행동 class는 같은 화면에 나중에 얹는다.
- **학습:** 큰 구조를 걷어낼 때 **데이터는 보존하고 경로만 닫는** 방법. 권한 모델을 페이지·카메라·라벨 상태 세 축으로 단순하게 세우는 연습.

## 2. 스코프

### In

1. **역할 2개** — `owner` / `member`(승인된 라벨러). 기존 승인 흐름(`labelers`, `labeler_applications`)은 유지.
2. **카메라 배정** — member ↔ camera 다대다(`labeler_camera_assignments`, owner가 관리). 한 카메라에 여러 명, 한 명에 여러 카메라 가능.
3. **A페이지(가칭 `내 카메라`)** — 로그인한 member에게 배정된 카메라의 영상. 날짜 최신순. 필터: `라벨 안 됨 / 됨`, `하이라이트 O / X / 대기`.
4. **B페이지(가칭 `전체`)** — 모든 카메라의 영상. 같은 필터 + 카메라 필터. member도 열람·라벨링 가능.
5. **Owner 페이지** — B페이지와 같되 관리 기능(카메라 배정, 규칙 버전 활성화, 집계, 정정) 추가.
6. **라벨링 권한 규칙** — 라벨 안 된 영상은 A/B 어디서든 누구나 확정 가능. **확정된 영상은 잠금**(다른 사람 수정 불가). owner만 정정 append.
7. **라벨 항목 v4.0** — 하이라이트 O/X 확정만. 행동 class·구간·대상은 이 스펙 밖(다음 항목으로 같은 상세 화면에 추가 예정, 폼 자리만 남김).
8. **퇴역** — `/labeling/blind/**`(큐·상세·canary·불일치 검수·그룹 배정), consensus/comparator, 30분 lease, slot materializer. 코드·라우트·API 제거, **DB 테이블·row는 보존**(append-only 원장, 삭제 안 함). 관련 RPC는 EXECUTE 회수만.

### Out

- **행동 class·구간·쳇바퀴 폼** — 기존 GT 폼(`_labeling-forms.tsx`)은 코드 유지, v4 상세엔 아직 안 붙임. 어떻게 얹을지 다음 논의.
- **튜토리얼·YOLO bbox·GME 점검(negative audit)·연구 화면·보관함·뉴스레터** — 건드리지 않음. 이번 퇴역 대상은 **이중 blind 교차검증 트랙만**.
- **옛 GT 마이그레이션** — 옛 consensus `final_gt`·owner v3 세션은 그대로 둔다. v4 하이라이트 verdict로 변환하지 않는다(기준이 다름).
- **앱·terra-server** — 없음.
- **자동 삭제·격리** — 없음.

> **퇴역 범위가 흔들리면 이 섹션 수정 + 사유 기록.** "싹 다"의 경계를 §4.3에 표로 못 박았으니 그 표가 정본.

## 3. 완료 조건

### Phase 0 — 확인

- [x] owner가 §4.3 퇴역 표와 §4.4에 답함 — 배정=편의 필터 확정, 잠금 정책·페이지 이름은 제안값으로 승인(2026-09-07)
- [x] 결정 게이트 3차 판정 확정 (2026-09-07 append)
- [x] `docs/FEATURES.md` §11.8·`docs/DATABASE.md` 해당 절에 `RETIRED 2026-09-xx` 표시(내용 삭제 않고 역사 보존)

### Phase 1 — DB (forward-only, 하이라이트 스펙 Phase 1과 같은 migration 가능)

- [x] `labeler_camera_assignments`(member, camera, assigned_at, ended_at) — RLS ON, client policy 0, service_role만
- [x] 목록 RPC: `fn_list_labeling_v4_clips(viewer, scope: mine|all, camera[], label_state, highlight_state, cursor, limit)` — keyset, viewer의 배정과 role로 scope 검증, 응답은 allowlist(썸네일·시작시각·카메라명·길이·하이라이트 현재값·라벨 상태·라벨러 표시명)
- [x] 확정 RPC: `fn_submit_highlight_verdict(viewer, clip, verdict, change_reason)` — 이미 verdict 있으면 `PT409`(잠금), 배정 무관(누구나), append-only
- [x] owner 정정: 별도 RPC 대신 `fn_submit_highlight_verdict(kind='correction')` append(owner 만, `superseded_by` 컬럼 없이 최신 row 가 현재값) — 구현 시 단순화
- [x] blind 트랙 RPC 11개 `REVOKE EXECUTE FROM service_role` (테이블 불변)
- [x] 정적 계약 테스트 + 로컬 disposable PostgreSQL probe `PROBE_RESIDUE=0`

### Phase 2 — Web

- [x] 라우트: `/labeling/mine`(A) · `/labeling/all`(B) · `/labeling/owner`(기존 owner 셸 재사용) · 상세 `/labeling/v4/[clipId]`
- [x] 상세: 영상 + GME 오버레이(기존 `_gme-overlay`) + `1차 판정: O — 근거` + `O 확정 / X 확정` + 사유 칩 + 다음 영상
- [x] 잠금 상태 표시: `OO님이 확정 (O)` — 다른 회원은 읽기만
- [x] `/labeling/blind/**` 라우트·API·컴포넌트 제거, 홈 전환 메뉴 갱신, 관련 테스트 삭제 또는 퇴역 마킹
- [x] Web 전체 테스트·TypeScript·`next build` 통과
- [ ] Preview canary(owner + member 1명 실계정 read-only smoke) → production `DEPLOYED_VERIFIED`

### Phase 3 — 운영 첫 주

- [ ] 회원별 카메라 배정 실제 입력
- [ ] 1주 뒤: 라벨된 영상 수·회원별·카메라별·A/B 경로별 집계
- [ ] 행동 class 폼을 v4 상세에 얹는 다음 스펙 착수 판단

## 4. 설계 메모

### 4.1 권한 모델 (세 축)

| 축 | 값 | 규칙 |
|---|---|---|
| 역할 | owner / member | owner = 전체 + 관리. member = 열람 전체, 라벨링 전체 |
| 페이지 | A(내 카메라) / B(전체) | A는 **편의 필터**일 뿐 권한 경계가 아니다. B에서도 같은 권한 |
| 라벨 상태 | 없음 / 확정됨 | 없음 → 누구나 확정. 확정됨 → 잠금, owner만 정정 append |

즉 "지정된 카메라"는 **무엇을 먼저 보게 할지**를 정하고, **누가 라벨링할 수 있나**는 정하지 않는다. owner 지시 "라벨링되지 않은 영상은 누구든지"를 그대로 옮긴 것. 배정을 권한으로 쓰고 싶으면 §4.4 Q1.

### 4.2 동시 확정 충돌

두 사람이 같은 안 된 영상을 동시에 열 수 있다. lease(30분 잠금)는 버린다 — 복잡하고 blind 전용이었다. 대신 **먼저 저장한 사람이 이긴다**: verdict INSERT에 `unique(clip_id) WHERE superseded_by IS NULL` 부분 유니크 → 두 번째 저장은 `PT409` → 화면에 "방금 OO님이 확정했어, 다음 영상으로". 영상 60초짜리라 충돌 비용이 작다.

### 4.3 퇴역 표 ("싹 다"의 경계)

| 대상 | 처리 |
|---|---|
| `/labeling/blind/**` 화면·API·컴포넌트(`_blind-review-*`, `_owner-conflict-comparison`) | **제거** |
| comparator v1/v2(`motionBlindReview*.ts`) | 제거. formal Blind30 TEST-SHEET의 "v1 불변" 요구는 실험 종료로 소멸 — REPORT/INDEX에 `closed by owner 2026-09-07` 기록 |
| slot / submission / consensus / events / group / cohort / progress 테이블 (9개) | **보존**, INSERT 경로만 사라짐. 문서에 RETIRED |
| blind RPC 11개 | `REVOKE EXECUTE` (DROP 안 함) |
| `fn_ensure_motion_review_slots` materializer 호출(워커/cron) | 중단 |
| GME 큐 순위 RPC(`fn_list_motion_blind_queue` v2) | 제거. v4 목록은 최신순 기본, 하이라이트 필터로 대체 |
| owner v3 직접 라벨링(`/labeling/motion`, `motion_clip_labeling_*`) | **유지**(행동 class 폼의 현재 집). v4에 행동 폼 얹은 뒤 별도 판단 |
| 튜토리얼·YOLO·GME 점검·보관함·연구·뉴스 | 유지 |
| 옛 GT 데이터 | 보존, 변환 없음 |

### 4.4 미해결 항목 (owner)

1. ~~**배정 = 권한?**~~ **✅ 2026-09-07 owner 확정:** 배정은 먼저 보여주는 편의 필터. B페이지에서 남의 카메라 영상도 라벨링 가능. §4.1 그대로.
2. **잠금 정책** — 확정 뒤 본인은 고칠 수 있나? 제안: 본인도 못 고침(단순), owner만 정정 append.
3. **페이지 이름** — `내 카메라` / `전체`? 다른 이름?
4. **owner v3 직접 라벨링 화면** — 지금은 유지로 뒀다. 하이라이트만 쓰는 동안 숨길지.
5. **formal Blind30 실험 종료 기록** — REPORT에 `closed` 남기는 것으로 충분한지.

## 5. 유저 체험 시뮬레이션

### member — A페이지

`[화면]` 로그인 → `내 카메라` 탭. 배정된 카메라 2대의 어젯밤 영상 목록. 카드마다 `하이라이트 O/X` 배지, `라벨 안 됨` 표시. 기본 필터 = `라벨 안 됨`
→ `[조작]` 첫 카드 탭
→ `[반응]` 영상 재생 + GME 박스 + `1차 판정: O — 움직임 12.4초` + `O 확정 / X 확정`
→ `[조작]` `O 확정` → 다음 안 된 영상 자동
→ `[감정]` 내 카메라는 내가 챙긴다는 감각. 밀린 개수가 보여서 얼마나 남았는지 안다.

### member — B페이지

`[화면]` `전체` 탭. 모든 카메라, 카메라 필터 칩. 다른 회원이 확정한 카드엔 `OO님 확정 (X)`가 보이고 열면 읽기 전용
→ `[조작]` `라벨 안 됨` 필터 → 남의 카메라 영상도 확정 가능
→ `[감정]` 남는 시간에 전체 진도를 밀어줄 수 있다.

### owner

`[화면]` `전체` + 관리 메뉴(카메라 배정 / 규칙 버전 / 집계)
→ `[조작]` 회원 ↔ 카메라 체크박스로 배정. 규칙 v1 활성화 버튼
→ `[반응]` 집계: 이번 주 확정 412 · 회원별 · 카메라별 · 유지율
→ `[감정]` 대기·불일치·검수함이 없어서 "지금 뭐가 밀렸나"만 보면 된다.

## 6. 학습 노트

- **경로만 닫고 데이터는 둔다:** 큰 기능을 접을 때 테이블 DROP 대신 INSERT 경로 제거 + RPC EXECUTE 회수. 되돌리기 비용 0, 역사 보존.
- **배정 vs 권한 분리:** "먼저 보여줄 것"과 "할 수 있는 것"을 한 테이블에 섞으면 나중에 둘 중 하나만 바꾸기 어렵다.
- **낙관적 충돌 처리:** 잠금(lease) 대신 부분 유니크 + 409. 충돌 비용이 작을 때 훨씬 단순하다. TS로 치면 mutex 대신 `insert … on conflict` 한 줄.

## 7. 참고

- 버리는 구조의 현재 기록: `docs/FEATURES.md` §11.8, `docs/DATABASE.md` "motion_labeling_review_*" 절, `docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md`
- 재사용할 것: `_gme-overlay.tsx`, `_role-shell.tsx`, `_review-video.tsx`, 역할별 읽기 RPC 패턴(`2026-07-24_role_based_labeling_reads.sql`)
- activation event 패턴: `2026-08-10-yolo-demo-team-contribution-design.md`
