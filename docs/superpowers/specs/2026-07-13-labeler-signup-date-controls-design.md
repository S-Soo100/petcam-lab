# 라벨러 회원가입·승인·간편 날짜 선택 설계

> 상태: 구현·preview 검증 완료 · production 승격 전 (2026-07-13) — DB migration 은 이미 적용·검증됨.
> Python 334·web tests 60·TypeScript·Vercel remote `next build` 통과. preview `dpl_D45VbxNBBFBzsXYoLL7DeD939PDX` READY.
> 배포는 §12 순서(DB→preview→실계정 E2E→prod)로 진행한다. preview는 Deployment Protection 대상이다.
> ⚠️ prod env 에 `DEV_USER_ID` 필요(owner 판정). ⚠️ 큐 제외는 §4.8 그대로(세션 기준만) 채택 →
> 세션 없는 기존 owner 라벨 233건이 '미검수'로 큐에 재노출(사용자 결정, 재라벨 유도).
> 작성일: 2026-07-13
> 구현 담당: Claude
> SQL: [`migrations/2026-07-13_labeler_applications.sql`](../../../migrations/2026-07-13_labeler_applications.sql)

## 1. 목표

현재 `label.tera-ai.uk`는 관리자가 Supabase에서 Auth 사용자와 `labelers` row를
직접 만들어야 한다. 팀원이 웹에서 가입을 신청하고 owner가 같은 웹에서 승인할 수
있게 바꾼다.

업무 배정 테이블은 만들지 않는다. 팀장이 담당 날짜를 구두로 전달하고, 팀원은 큐에서
해당 KST 날짜를 빠르게 선택한다.

완료 조건은 다음과 같다.

- 이름·이메일·비밀번호로 가입할 수 있다.
- 이메일 인증은 요구하지 않는다.
- 가입 직후에는 영상 데이터에 접근할 수 없다.
- owner가 `팀원 관리`에서 승인·거절·권한 해제를 할 수 있다.
- 승인된 사용자만 라벨링 큐와 영상 API를 사용할 수 있다.
- 날짜 필터를 프리셋과 이전·다음 날 버튼으로 쉽게 조작할 수 있다.
- 날짜 상태가 URL에 남아 새로고침과 링크 공유가 가능하다.
- GT를 잠근 뒤 VLM 검수를 끝내지 않은 영상은 큐에서 사라지지 않는다.

## 2. 범위

### In scope

- 공개 회원가입 화면
- 기존 Auth 사용자의 라벨러 참여 신청
- 승인 대기·거절 상태 화면
- owner 전용 팀원 관리 화면
- 가입 신청 상태 저장
- `labelers` 기반 승인·해제
- 라벨링 웹 API 전체의 승인 상태 게이트
- KST 날짜 프리셋·하루 이동 UI
- `gt_locked` 미완료 영상의 큐 복귀·이어하기
- 권한·날짜 경계 테스트

### Out of scope

- 이메일 인증
- 이메일 초대
- CAPTCHA
- 비밀번호 찾기 신규 구현
- owner 외 복수 관리자 역할
- 담당자·작업 배치 테이블
- 자동 물량 균등 배분
- class/VLM 판정 기준 업무 배분
- Auth 사용자 삭제
- 검수 결과나 기존 이력 삭제

## 3. 사용자 경험

### 3.1 신규 팀원

1. `[화면]` 로그인 화면에서 `회원가입` 링크를 본다.
2. `[조작]` 이름·이메일·비밀번호·비밀번호 확인을 입력한다.
3. `[반응]` Supabase Auth 가입과 라벨러 신청이 완료되고 승인 대기 화면으로 이동한다.
4. `[화면]` 본인 이름·이메일과 `관리자 승인 대기 중` 안내만 보인다.
5. `[감정]` 가입 성공과 영상 접근 권한이 다르다는 점을 명확히 이해한다.

Auth 가입은 성공했지만 신청 API가 실패하면 로그인 상태를 유지하고
`/labeling/apply`에서 이름을 다시 제출할 수 있게 한다.

### 3.2 기존 Auth 사용자

1. 기존 이메일·비밀번호로 로그인한다.
2. 가입 신청이 없으면 `/labeling/apply`로 이동한다.
3. 이름을 입력해 라벨러 참여를 신청한다.
4. 승인 대기 화면으로 이동한다.

동일 이메일로 Auth 계정을 중복 생성하지 않는다.

### 3.3 owner

1. 상단 `팀원 관리` 메뉴로 이동한다.
2. 승인 대기, 활동 중, 거절됨 목록을 본다.
3. 대기 사용자를 승인하거나 거절한다.
4. 활동 중 사용자의 권한을 해제할 수 있다.
5. 거절된 사용자를 다시 승인할 수 있다.

Auth 계정과 과거 GT·VLM 검수 이력은 삭제하지 않는다.

### 3.4 날짜를 전달받은 팀원

1. 팀장에게 `7월 8일 영상을 검수해줘`라고 구두로 전달받는다.
2. 큐에서 날짜 입력을 한 번 눌러 `2026-07-08`을 선택한다.
3. 화면에서 `현재 범위: 2026년 7월 8일 하루`를 확인한다.
4. 다음 날짜로 넘어갈 때 `다음 날 →`을 누른다.

날짜는 class나 VLM 판정과 무관한 배분 축이다. Blind GT를 보호하기 위해 업무를
VLM class별로 나누거나 큐에서 VLM 판정을 노출하지 않는다.

## 4. 화면 설계

### 4.1 `/labeling/login`

- 기존 이메일·비밀번호 로그인 유지
- 하단에 `계정이 없나? 회원가입` 링크 추가
- 로그인 성공 후 `/`로 보내지 않고 access API 결과에 따라 직접 이동
  - `owner`, `labeler` → `/labeling`
  - `pending`, `rejected` → `/labeling/pending`
  - `unregistered` → `/labeling/apply`

### 4.2 `/labeling/signup`

필수 입력:

- 이름: trim 후 1~80자
- 이메일: 브라우저 email validation + Supabase Auth validation
- 비밀번호: Supabase 프로젝트의 현행 password policy
- 비밀번호 확인: 비밀번호와 일치

가입 요청:

1. `supabase.auth.signUp({ email, password, options: { data: { display_name }}})`
2. 세션이 생기면 `POST /api/labeler-applications`
3. 성공하면 `/labeling/pending`

프로덕션 Supabase Auth의 email confirmation은 비활성 상태를 전제로 한다. 설정이
바뀌어 세션이 반환되지 않으면 성공으로 가장하지 말고 `로그인 세션을 만들지 못했어`를
표시한다.

### 4.3 `/labeling/apply`

- 로그인했지만 신청 row가 없는 사용자만 사용
- Auth 이메일은 읽기 전용 표시
- 이름만 입력
- 신청 성공 후 `/labeling/pending`

### 4.4 `/labeling/pending`

- `pending`: 승인 대기 안내, 이름·이메일, `상태 새로고침`, 로그아웃
- `rejected`: 승인되지 않았다는 안내, 관리자 문의 안내, 로그아웃
- 새로고침 결과 `owner/labeler`가 되면 `/labeling`으로 이동

### 4.5 `/labeling/team`

owner에게만 내비게이션을 노출한다. 서버도 owner를 다시 검증한다.

구역:

- 승인 대기: 이름, 이메일, 신청 시각, `승인`, `거절`
- 활동 중: 이름, 이메일, 승인 시각, `권한 해제`
- 거절됨: 이름, 이메일, 처리 시각, `다시 승인`

각 작업 중 버튼을 비활성화하고 성공 후 목록을 다시 불러온다. owner 본인에 대한
권한 해제 작업은 UI와 API 모두 거부한다.

### 4.6 라벨링 큐 날짜 컨트롤

기존 날짜 입력 위에 다음 버튼을 제공한다.

```text
[오늘] [어제] [최근 3일] [최근 7일]
[← 이전 날] [2026-07-08] [다음 날 →] [전체 기간]
현재 범위: 2026년 7월 8일 하루
```

규칙:

- `오늘`: 오늘 KST 00:00:00~23:59:59
- `어제`: 어제 KST 00:00:00~23:59:59
- `최근 3일`: 오늘 포함 3개 KST calendar day
- `최근 7일`: 오늘 포함 7개 KST calendar day
- 날짜 입력: 선택한 KST 하루
- 이전·다음 날: 단일 날짜 범위일 때만 활성화
- 전체 기간: `date_from`, `date_to` 제거
- URL에는 `+09:00`이 포함된 ISO 범위를 유지
- 모바일에서는 두 줄 wrap을 허용하고 horizontal scroll을 만들지 않음

### 4.7 라벨링 레이아웃 게이트

레이아웃이 세션 유무만 확인하고 내비게이션을 먼저 그리면 pending 사용자가 메뉴를
잠깐 볼 수 있다. access 확인이 끝날 때까지 빈 화면이나 중립 loading 상태를 표시한다.

- 공개: `/labeling/login`, `/labeling/signup`
- 로그인 필요, 승인 불필요: `/labeling/apply`, `/labeling/pending`
- owner/labeler 필요: `/labeling`, `/labeling/me`, 단건 상세, 라우터 리뷰
- owner 필요: `/labeling/team`

내비게이션도 access 상태에 따라 렌더링한다. pending/rejected에는 큐·내 라벨·라우터
리뷰 링크를 표시하지 않는다.

### 4.8 GT 잠금 후 이어하기

현재 큐는 본인의 `behavior_labels`가 생기면 영상을 제외한다. GT 잠금 시 호환
`behavior_labels`가 먼저 저장되므로 사용자가 VLM 검수 전에 이탈하면 해당 영상이 큐에서
사라진다.

큐 제외 기준을 본인의 `clip_labeling_sessions.stage = completed`로 바꾼다.

- session 없음: 일반 `미검수` 카드
- `gt_locked`: `VLM 검수 이어하기` badge를 표시하고 큐에 유지
- `completed`: 큐에서 제외

큐 응답에는 stage만 포함하고 `prediction_snapshot`이나 VLM action은 포함하지 않는다.
따라서 Blind GT인 다른 영상의 답은 노출되지 않는다.

## 5. 권한 모델

인증과 라벨링 권한을 분리한다.

| 상태 | 로그인 | 대기 화면 | 큐·영상 | 팀원 관리 |
|---|---:|---:|---:|---:|
| 미로그인 | ❌ | ❌ | ❌ | ❌ |
| unregistered | ✅ | 신청 화면 | ❌ | ❌ |
| pending | ✅ | ✅ | ❌ | ❌ |
| rejected | ✅ | 거절 안내 | ❌ | ❌ |
| labeler | ✅ | 자동 이탈 | ✅ | ❌ |
| owner | ✅ | 자동 이탈 | ✅ | ✅ |

권한 SOT:

- owner: `auth.user.id === DEV_USER_ID`
- labeler: `public.labelers`에 `user_id` 존재
- 신청 상태: `public.labeler_applications.status`

`labeler_applications.status = approved`만으로 영상 접근을 허용하지 않는다. 승인 RPC가
원자적으로 `labelers`와 신청 상태를 함께 갱신하고, 런타임 접근 판정은 `labelers`를
확인한다.

## 6. 데이터 모델

`public.labeler_applications`를 추가한다.

| 컬럼 | 타입 | 규칙 |
|---|---|---|
| `user_id` | UUID PK | `auth.users(id)` FK, 계정 삭제 시 CASCADE |
| `email` | TEXT | Auth에서 읽은 이메일 snapshot |
| `display_name` | TEXT | trim 1~80자 |
| `status` | TEXT | `pending/approved/rejected` |
| `requested_at` | TIMESTAMPTZ | 최초 신청 시각 |
| `reviewed_at` | TIMESTAMPTZ NULL | 마지막 승인·거절 시각 |
| `reviewed_by` | UUID NULL | 처리한 owner |
| `updated_at` | TIMESTAMPTZ | 마지막 변경 시각 |

`(status, requested_at DESC)` B-tree index를 둔다. 팀원 관리 화면의 상태별 최신순
조회에 사용한다.

기존 `labelers` row는 migration에서 `approved` 신청으로 backfill한다. 이름은 Auth
`raw_user_meta_data.display_name`, 이메일 앞부분, `기존 라벨러` 순서로 fallback한다.

RLS를 enable하고 `anon`, `authenticated`, `PUBLIC` 권한을 회수한다. 브라우저는 직접
접근하지 않으며 service role API만 읽고 쓴다.

## 7. 서버 인터페이스

### `GET /api/labeling-access`

인증 사용자 누구나 호출 가능하다.

```ts
type LabelingAccess = {
  status: 'owner' | 'labeler' | 'pending' | 'rejected' | 'unregistered';
  display_name: string | null;
  email: string;
};
```

판정 순서는 `owner → labelers → application → unregistered`다. 이 순서로 stale한 신청
상태가 실제 권한을 덮어쓰지 못하게 한다.

### `POST /api/labeler-applications`

```ts
type ApplyBody = { display_name: string };
```

- JWT user ID와 Auth user email을 서버에서 취득
- 이름 trim·길이 검증
- 본인 `user_id` 한 건만 UPSERT
- `approved` 사용자의 재신청은 거부
- `pending` 재호출은 동일 row 반환
- `rejected` 사용자는 직접 재신청하지 않고 owner가 다시 승인

### `GET /api/labeling-team`

owner 전용이다. 신청을 상태·신청일 순으로 반환한다.

### `POST /api/labeling-team/[userId]/decision`

```ts
type DecisionBody = {
  decision: 'approve' | 'reject' | 'deactivate';
};
```

- owner 검증 후 DB RPC 호출
- 대상이 owner 자신이면 400
- 존재하지 않는 신청이면 404
- 승인·거절 반복 호출은 같은 최종 상태를 만드는 idempotent 동작
- `deactivate`는 DB에서 `labelers`를 제거하고 신청 상태를 `rejected`로 기록

## 8. 공통 서버 헬퍼

- `verifyBearer(req)`: 기존 JWT 검증 유지
- `requireOwner(req)`: JWT 검증 후 `DEV_USER_ID` 비교
- `getLabelingAccess(userId)`: owner/labeler/application 상태 판정
- `requireLabelingAccess(req)`: owner 또는 실제 `labelers` 멤버만 허용

`/api/poc/summary`를 owner 판정 API로 재사용하지 않는다. PoC 통계 endpoint와 관리자
권한 책임을 분리한다.

`requireLabelingAccess`를 큐, 단건, 썸네일, 재생 URL, 다운로드 URL, 라벨 조회·저장,
GT 잠금, VLM 검수에 적용한다. pending 사용자가 자기 소유 clip을 통해 우회하지 못해야
한다.

## 9. 오류 처리

- 이미 존재하는 이메일: `이미 계정이 있다면 로그인해줘` 안내
- Auth 성공·신청 실패: `/labeling/apply`에서 재시도
- 세션 없음: 로그인으로 이동
- 승인 대기: 403 JSON 대신 승인 대기 UI로 이동
- owner env 누락: 관리 API 503, 일반 사용자에게 내부 UUID 미노출
- DB 오류: 사용자에게 일반 메시지, 서버 로그에도 token/password 미기록
- 승인 RPC 중 오류: 트랜잭션 rollback으로 두 테이블 원상 유지
- 권한 해제: 다음 access/API 요청부터 즉시 차단, 기존 검수 이력 유지
- GT 잠금 후 이탈: 같은 날짜 큐에 `VLM 검수 이어하기`로 남음

## 10. 테스트·검증

### 자동 테스트

- access matrix: 미로그인, unregistered, pending, rejected, labeler, owner
- owner 전용 API의 401/403/200
- 이름 공백·0자·81자 거부
- 신청 idempotency
- 승인 시 `applications=approved`와 `labelers row 존재`
- 거절·권한 해제 시 `applications=rejected`와 `labelers row 없음`
- 재승인 정합성
- owner 자기 권한 해제 거부
- KST 오늘·어제·최근 3일·최근 7일 경계
- 12월 31일↔1월 1일 하루 이동
- URL serialize/parse round trip
- `gt_locked`는 큐에 남고 `completed`만 제외
- blind queue 응답에 prediction snapshot과 VLM action이 없음

### 수동 production E2E

1. 신규 테스트 이메일로 가입한다.
2. 승인 전 큐·직접 clip URL·다운로드 API가 모두 차단되는지 확인한다.
3. owner 팀원 관리에 신청이 보이는지 확인한다.
4. 승인 후 큐와 영상에 접근되는지 확인한다.
5. 1일 날짜 선택과 이전·다음 날 이동을 확인한다.
6. 권한 해제 후 열린 상세 페이지의 다음 API 요청이 차단되는지 확인한다.
7. 기존 라벨러가 migration 이후 그대로 접근하는지 확인한다.
8. 390px viewport에서 가입·대기·팀원 관리·날짜 컨트롤의 가로 넘침이 없는지 확인한다.

## 11. 구현 파일 경계

신규 후보:

- `migrations/2026-07-13_labeler_applications.sql`
- `web/src/lib/labelingAccess.ts`
- `web/src/lib/labelingDateRange.ts`
- `web/src/app/api/labeling-access/route.ts`
- `web/src/app/api/labeler-applications/route.ts`
- `web/src/app/api/labeling-team/route.ts`
- `web/src/app/api/labeling-team/[userId]/decision/route.ts`
- `web/src/app/labeling/signup/page.tsx`
- `web/src/app/labeling/apply/page.tsx`
- `web/src/app/labeling/pending/page.tsx`
- `web/src/app/labeling/team/page.tsx`

수정 후보:

- `web/src/lib/clipPerms.ts`
- `web/src/lib/labelingApi.ts`
- `web/src/app/labeling/layout.tsx`
- `web/src/app/labeling/login/page.tsx`
- `web/src/app/labeling/_filter-bar.tsx`
- `web/src/app/labeling/page.tsx`
- `web/src/app/api/labeling-v2/queue/route.ts`
- 라벨링 관련 Next.js API routes
- `docs/DATABASE.md`
- `docs/FEATURES.md`
- `specs/next-session.md`

## 12. 배포 순서

1. SQL migration을 Supabase에 적용한다.
2. 기존 `labelers` backfill 결과와 RLS를 확인한다.
3. 웹 코드를 preview 배포한다.
4. preview에서 신규 계정 전체 E2E를 수행한다.
5. production 배포한다.
6. production E2E 후 SOT를 갱신한다.

웹을 먼저 배포하면 신규 테이블/API가 없어 가입이 실패하므로 SQL을 먼저 적용한다.
