# 라벨링 웹 v4 단순화 — 교차검증 폐기, 단독 확정, 카메라 배정 + 전체 열람

> 두 명 blind → 합의 → 불일치 owner 검수 구조를 전부 버린다. Owner는 모든 영상, 회원은 A페이지(배정 카메라)와 B페이지(모든 카메라)를 보고, 라벨링 안 된 영상은 누구든 라벨링한다. 한 사람이 확정하면 끝.

**상태:** ✅ Phase 1·2 `DEPLOYED_VERIFIED` (2026-09-07, PR #13 머지·production migration·label.tera-ai.uk 배포). Phase 3(운영 첫 주·카메라 배정 입력)은 진행 중
**작성:** 2026-09-07
**연관:** [`feature-highlight-auto-initial-designation.md`](feature-highlight-auto-initial-designation.md) (첫 라벨 항목 = 하이라이트 O/X), [`docs/FEATURES.md`](../docs/FEATURES.md) §11.8 (버리는 구조의 현재 기록)
**결정 게이트:** [`docs/decision-gate.md`](../docs/decision-gate.md) 2026-09-07 3차
**구현 계획:** [`docs/superpowers/plans/2026-09-07-labeling-web-v4.md`](../docs/superpowers/plans/2026-09-07-labeling-web-v4.md) (A 계획 뒤에 실행)

> **운영·개선 런북(진입점):** [`docs/highlight-rule-operations.md`](../docs/highlight-rule-operations.md) — 데이터 흐름·params 계약·주간 조정 루프·코드 지도·트리거 추가 절차·검증/배포·함정. 이 스펙은 '왜'만 담는다.

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
- **대화형 튜토리얼** — 원래 Out 이었으나 **2026-09-07 owner 추가 결정으로 퇴역**(docs/decision-gate.md 4차). 화면·API·접근 게이트·팀 관리 진행률 제거, 테이블·row 보존, RPC EXECUTE 회수(`migrations/2026-09-08_labeling_tutorial_retirement.sql`).
- **YOLO bbox·GME 점검(negative audit)·연구 화면·보관함·뉴스레터** — 건드리지 않음.
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
- [x] production 배포 `DEPLOYED_VERIFIED` (2026-09-07 — 공개 화면 200·비인증 v4 API 401·퇴역 경로 404 smoke; 실계정 member smoke 는 운영 첫 주에)

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
| 대화형 튜토리얼(/labeling/tutorial, /api/labeling-tutorial, 접근 게이트, 팀 관리 진행률) | **제거** (2026-09-07 owner 추가 결정). 테이블 보존, RPC EXECUTE 회수 |
| YOLO·GME 점검·보관함·연구·뉴스 | 유지 |
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

### member — 폰에서 (2026-09-08 추가)

`[화면]` 폰으로 `/labeling/v4/<id>` 열면 영상 아래를 스크롤하지 않아도 화면 하단에 `O 확정 / X 확정` 큰 버튼 두 개(56px)가 고정. 바 위에 `1차 X · 짧은 움직임 3.0초 · 최장 연속 3.0초` 한 줄. 이 페이지에서만 하단 6탭 메뉴는 숨김(복귀는 상단 `목록`·뒤로가기)
→ `[조작]` 엄지로 한 번 탭
→ `[반응]` 1차와 같으면 즉시 저장 → 다음 영상. 규칙 X 를 O 로 올리는 것도 즉시 저장(사유 없음 — 놓친 건 `x_to_o` 집계로 충분, 2026-09-08 owner). 규칙 O 를 X 로 내릴 때만 같은 바가 위로 늘어나 이유 칩 5개(오검출·게코 안 보임·카메라 흔들림·움직임 짧음·기타, 칩 툴팁·선택 시 아래 한 줄 설명 — 2026-09-08 owner 피드백) + `저장하고 다음`, 강조는 고른 쪽으로 이동. **1차가 `게코 미관측` X 면** O/X 대신 `게코 안 보여 · X 확정` / `게코 보여 · 하이라이트 O` / `게코 보여 · 하이라이트 아님 X` 세 버튼(모두 즉시 저장; 셋째는 X 로만 남고 '게코는 보였다' 사유는 enum 에 없어 미기록 — 팔로업). 저장 중엔 누른 버튼만 색 유지한 채 스피너+`저장 중…`, 나머지 잠금, 바 아래 `저장하고 다음 영상으로 넘어가는 중…`. 다음 영상은 영상 자리 스켈레톤 + 같은 자리 바에 `다음 영상 불러오는 중…`(바 깜빡임 없음)
→ `[감정]` 영상 보고 바로 누르는 리듬. 확정된 영상은 바에 `OO님이 확정`과 `다음 안 된 영상`.

구현: `HighlightDecisionPanel` 액션 블록이 `fixed bottom-0 … lg:static`(safe-area 포함), 본문 `pb-80 lg:pb-6`. `RoleShell.isFocusRoute('/labeling/v4/')` 가 모바일 탭 숨김. 로컬 dev + 375×812 실측(확정 요청 0건).

### member — 움직임 구간만 보기 (2026-09-08 UX ①)

`[화면]` 영상 타임라인 아래 초록 마커(GME `moving` 구간, 0.5초 이내 끊김은 병합) + 한 줄 내비 `움직임 3구간 · 12.4초 · 지금 1/3 · ⏭ 다음 움직임 2/3 · 1× 1.5× 2× · ☑ 움직임부터 시작`
→ `[조작]` 영상이 열리면 첫 움직임 0.5초 전으로 자동 점프(1초 미만이면 안 함, 영상당 1회, 칩으로 끔). `다음 움직임` 탭 → 다음 구간 시작 0.5초 전, 마지막 뒤면 `처음 움직임으로`. 속도·자동 점프 설정은 브라우저에 기억(`labeling.v4.speed`/`autoSkip`)
→ `[반응]` `첫 움직임 53.7초로 건너뜀 — 처음부터 보려면 타임라인을 왼쪽으로` 안내 한 줄. 구간이 없으면 GME 상태별로 `GME 분석 대기 — 현재 계약으로 아직 안 돌았어` / `GME: 게코 미관측` / `GME: 게코는 보이지만 움직임 없음(정지)` (2026-09-08 실측: 8/27 이전 14,231건은 활성 계약 run 없음, 활성 run 의 62% 가 움직임 0·36% 가 미관측)
→ `[감정]` 60초를 다 안 봐도 된다. 규칙이 잡은 구간이 눈에 보이니 O/X·"움직임 짧음" 판단이 빨라진다.

구현: `lib/movingIntervals.ts`(순수: 병합·점프 대상·다음 index) · `ReviewVideo` `markers/markersDurationSec/playbackRate` 옵션 prop(다른 페이지 영향 0) · `MotionNavRow`. 로컬 375 실측: 자동 점프 53.2초·마커 1개·속도 유지.

### member — 다음 영상이 바로 뜬다 (2026-09-08 UX ②)

`[화면]` 확정 → 다음 영상이 로딩 화면 없이 즉시 재생
→ `[원리]` 상세가 열리면 같은 카메라의 다음 안 된 영상 id 를 묻고 그 메타·서명 URL·GME overlay 를 미리 받아 둔다(`lib/labelingV4Prefetch.ts`, clip 당 1개·최근 4개·서명 URL 만료 30초 전 무효). 영상 바이트는 숨은 `<video preload=auto>` 로 예열. 이동 시 캐시로 먼저 그리고 메타만 다시 받아 덮어쓴다(그 사이 남이 확정했을 수 있음). "다음"은 이동 시점에 서버에 다시 묻고 id 가 같을 때만 캐시를 쓴다.
→ `[함정]` 캐시는 읽어도 지우지 않고 최신 메타를 받은 뒤 지운다 — React StrictMode(dev)가 mount 효과를 두 번 돌려 첫 실행이 캐시를 소비해 버리는 문제를 실측으로 잡았다. 로컬 실측: 이동 0.4초 뒤 로딩 화면 없음, 서명 URL·overlay 재요청 0.

### member — 이어서 라벨링 + 오늘 N개·남은 M개 (2026-09-08 UX ③)

`[화면]` 내 카메라/전체 목록 맨 위 카드: `오늘 내가 12개 · 남은 310개` + `▶ 이어서 라벨링`. 상세 바 요약 줄 오른쪽에 `오늘 12 · 남은 2481`
→ `[조작]` 이어서 라벨링 → 현재 scope·카메라 필터의 첫 '라벨 안 된' 영상으로 바로(목록 안 거침). 남은 게 없으면 `남은 영상이 없어…` 안내
→ `[원리]` 서버 집계 `fn_get_labeling_v4_progress(viewer)`(오늘 내가/전체·미라벨 전체/배정 카메라, 배정 없으면 mine NULL)는 전체 clip 을 훑으므로 **목록 방문 때만** 부르고 sessionStorage 에 둔다. 상세는 확정할 때마다 로컬로 +1/−1(배정 카메라 영상이면 mine 도 −1), 10분 지나면 표시 안 함. 실패하면 `진행 수를 못 가져왔어`
→ `[감정]` "얼마나 남았나"가 보이고, 목록 스크롤 없이 바로 시작한다.

구현: migration `2026-09-09_labeling_v4_progress.sql` + probe §9 · `GET /api/labeling-v4/progress`(승인 사용자) · `lib/labelingV4Progress.ts`(정규화·가감·문구·stale) · `ProgressRow`.

### member — PC 단축키 (2026-09-08 UX ④)

`[화면]` 데스크톱(lg)에서 영상 아래 회색 한 줄 `단축키: O / X 확정 · 1~5 사유 · Enter 저장 · Space 재생 · N 다음 움직임 · F 의미있는 행동`, 사유 칩 앞에 번호
→ `[조작]` 마우스 없이 O/X(한글 자판 ㅐ/ㅌ 도) → 사유 번호 → Enter. 미관측 화면에선 O=게코 보여·하이라이트 O, X=게코 안 보여. 입력창 포커스·조합키(⌘/Ctrl/Alt)면 무시, 확정된 영상은 O/X 무시
→ `[원리]` `lib/labelingHotkeys.ts` 순수 매핑(테스트) + 패널이 `keyboardRef` 핸들(pickVerdict/chooseReason/save)을 채우고 상세가 window keydown 을 받는다. Space 는 preventDefault 로 스크롤 방지. 로컬 실측: Space 재생 토글·N 점프·O 저장 중 진입.

### member — 동시 작업 겹침 완화 · 검출기 누락 사유 · 카드 썸네일 (2026-09-08 UX ⑤⑥⑦)

`[⑤]` 상세를 열면 "보는 중" 힌트(`motion_clip_view_claims`, clip 당 1행, 120초)를 남기고, `다음 안 된 영상`·`이어서 라벨링`은 후보 6개 중 남이 120초 안에 연 clip 을 건너뛴다(전부 겹치면 첫 후보). 잠금이 아니라 힌트 — 확정은 여전히 먼저 저장한 사람이 이긴다(409). migration `2026-09-09_labeling_v4_view_claims.sql`, probe §10, `GET /api/labeling-v4/continue`, `POST clips/[id]/view-claim`.
`[⑥]` 미관측 화면의 `게코 보여 · 하이라이트 아님 X` 가 사유 `gecko_visible_not_highlight`(검출기 누락 신호)를 남긴다. X→X 라 유지율엔 안 섞이고 owner 통계 사유 열에만 보인다. migration `2026-09-09_highlight_reason_gecko_visible.sql`(CHECK·submit 검증·stats 키), highlight probe 3a. 칩으로는 안 보임.
`[⑦]` 목록 카드 왼쪽 112×64 썸네일(`motion_clips.thumbnail_key` → 10분 서명 URL, 30장 병렬 presign, 없으면 빈 칸). 26,724/26,741 영상에 키 있음(2026-09-08 실측). 실패해도 목록은 그대로.

### member — "의미있는 행동" 체크 (2026-09-08 추가, owner 지시)

`[화면]` 상세 액션 바 O/X 윗줄에 `✨ 의미있는 행동 보여 (물·허물·밥 등, 종류는 안 골라도 돼)` 버튼(PC·폰 같은 자리)
→ `[조작]` VLM/GT 라벨 대상 행동이 보이면 한 번 탭. 종류는 고르지 않는다. O/X 확정과 무관하게 언제든(확정 전후·남이 확정한 영상도) 가능
→ `[반응]` 스피너 `저장 중…` → `✨ 의미있는 행동 체크됨 · OO — 눌러서 해제`. 해제는 체크한 사람·owner 만(남의 체크 해제 시 403 안내). 목록 카드에 ✨ 배지, 필터 칩 `✨ 의미있는 행동`(`?behavior_flag=yes`)으로 체크된 영상만 모아 본다
→ `[감정]` "이건 뭔가 하는 중이다"를 종류 고민 없이 흘려보내지 않고 붙잡아 둔다. 나중에 이 목록만 보며 기존 행동 GT 라벨링을 붙인다.
→ `[조작]` 체크된 영상엔 카드 아래·상세 버튼 옆에 `행동 라벨링 열기 →`(`/labeling/motion/<id>`, 기존 motion v3 GT 화면). **2026-09-08 owner 결정으로 승인 라벨러에게도 개방** — 라우트 `shared`, API `requireLabelingAccess`, `fn_lock_motion_clip_gt` 가 라벨러도 unreviewed/label clip 을 잠그게 변경(hold/skip 은 모두 PT424, 이벤트 `labeler_started_labeling`). 라벨러의 `← 목록`은 v4 체크 목록으로 돌아간다. owner 전용으로 남는 것: 큐 분류(hold/skip/reset)·GT 보정·다음 미분류 이동·`/labeling/motion` 큐 루트. migration `2026-09-09_motion_gt_labeler_open.sql`, probe `scripts/run_motion_gt_labeler_open_probe.py`.

구현: `motion_clip_behavior_flags`(clip 당 1행, RPC 전용) · `fn_get/set_motion_clip_behavior_flag` · 13-인자 `fn_list_labeling_v4_clips`(`p_behavior_flag`, `behavior_flagged*` 컬럼; 12-인자는 위임 wrapper) · `POST /api/labeling-v4/clips/[id]/behavior-flag` · `BehaviorFlagButton`. migration `2026-09-09_labeling_v4_behavior_flags.sql`, probe `scripts/run_labeling_v4_probe.py` §8.

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
