# 2026-07-29 뉴스 댓글·관리자 migration 완료 보고서

## 판정

`NEWS_COMMENTS_ADMIN_MIGRATION_APPLIED_VERIFIED`

프로덕션 Supabase `slxjvzzfisxqwnghvrit`에 뉴스 댓글·관리자·이미지 Storage 경계를
적용했고, 로컬 PG15·production rollback probe·실제 anon REST 호출로 검증했다.
R1은 적용 전에 기존 측정창을 정상 supersede했고, 이 보고서를 main에 반영한 뒤 fresh
24시간 창을 0초부터 다시 시작한다.

## 범위와 정본

- 원본 요청:
  `/Users/baek/terra-ai-promotion-website/docs/requests/2026-07-29-petcam-lab-news-comments-admin-migration.md`
- 요청 commit:
  `34a51e615a63a431a81ea684db896a349e969eae`
- 대상 레포:
  `/Users/baek/petcam-lab`
- 격리 worktree:
  `/Users/baek/petcam-lab/.worktrees/news-comments-admin-migration-20260729`
- branch:
  `codex/news-comments-admin-migration-20260729`
- production 반영 HEAD:
  `bae72af7b668f1d00fb3744e3164722a5729115e`
- 정본 migration:
  `migrations/2026-07-29_news_comments_admin.sql`
- migration SHA-256:
  `3fe89db99d24016000b9cb67f3ad489c1212646018b42f439681e1e49473ddeb`

요청서가 가리킨 promotion plan과 petcam handoff 파일은 실제로 존재하지 않았다. 추측
구현 대신 요청 commit 자체를 승인된 design으로 사용하고, petcam-lab에 추적 가능한
design/plan을 먼저 커밋했다.

## 구현 계약

- `news_admins`: 뉴스 전용 멤버십. 라벨러·Owner 역할과 연결하지 않는다.
- `news_comments`: 익명 닉네임/본문, 관리자 숨김·삭제, 본인 수정·삭제 없음.
- anon/authenticated 테이블 INSERT·UPDATE·DELETE grant 0.
- 익명 댓글은 `fn_submit_news_comment`만 사용한다.
- 관리자 쓰기는 전부 뉴스 멤버십을 재확인하는 RPC만 사용한다.
- SECURITY DEFINER 7종 모두 `search_path=''`.
- 댓글 지문은 IP·User-Agent 원문을 저장하지 않고 소문자 SHA-256만 저장한다.
- `news-comment-v1`은 비밀 salt가 아니라 용도 분리용 domain separator다.
- 동일 지문의 동시 제출은 advisory transaction lock으로 직렬화한다.
- `news-media`는 public bucket이며 쓰기는 뉴스 관리자만 가능하다.
- 기존 영상·라벨·GT·blind·RBA 테이블을 migration에서 참조하거나 변경하지 않는다.

## TDD와 로컬 DB 검증

RED:

- 정적 계약: migration 파일 부재로 8 errors.
- 런타임 계약: runner 부재로 2 failures.
- 첫 PG15 실행은 `pg_catalog.nullif` 때문에 fail-closed, residue 0.

원인은 `NULLIF`·`COALESCE`가 `pg_catalog` 함수가 아닌 PostgreSQL 특수 구문인데
함수처럼 수식된 것이었다. 정적 회귀 테스트를 추가하고 migration/fixture를 최소 수정했다.

GREEN:

```text
NEWS_COMMENTS_RUNTIME_OK
NEWS_ADMIN_RLS_OK
NEWS_COMMENT_RATE_LIMIT_OK
NEWS_STORAGE_POLICY_OK
PROBE_RESIDUE=0
```

- focused: 10 passed
- 전체: 857 passed, 3 skipped
- `git diff --check`: clean
- 동시 제출: 첫 transaction commit 전 둘째 요청이 대기한 뒤 SQLSTATE 53400으로 거부
- 임시 DB·probe가 만든 role 잔여: 0

## Production 적용

- organization: `terra-ai-dev`
- project: `Terra AI`
- project id: `slxjvzzfisxqwnghvrit`
- branch/environment: `main` / Production
- migration version: `20260729205215`
- migration name: `news_comments_admin_rpc`
- migration history rows: 1

적용 전:

- 기존 `news_articles`: 9행
- 기존 `news_articles` MD5: `55835e57432a782c40d731f050fce892`
- 기존 공개 policy: 1
- `news_admins`·`news_comments`·함수 7종·`news-media`·migration 이력: 전부 없음

적용은 tracked SQL 전체와 SHA/commit provenance를 같은 transaction의 migration history에
기록한 뒤 commit했다. SQL Editor에서는 이전 사고 재발을 막기 위해 쿼리마다 기존 탭을
닫고 새 빈 탭을 생성했으며, 실행 전 전체 선택·복사 값이 정본 SQL과 byte-equivalent인지
확인했다.

적용 후:

- `news_articles`: 9행, MD5 동일
- `news_articles` policy: 2(기존 공개 + 신규 관리자 읽기)
- `news_admins`: RLS enabled, client policy 0, rows 0
- `news_comments`: RLS enabled, policy 2, rows 0
- helper/RPC: 7종, 전부 SECURITY DEFINER + 빈 search path
- anon/authenticated 댓글 table INSERT: false/false
- anon 댓글 제출 RPC EXECUTE: true
- anon 관리자 RPC EXECUTE: false
- `news-media`: public bucket 1, policy 4
- Storage UPDATE policy: `USING`과 `WITH CHECK` 모두 존재
- 최초 뉴스 관리자 등록: **false** — 기존 라벨링 계정을 임의 재사용하지 않았다.

## 필수 검증 8건

1. anon 직접 댓글 table 쓰기: SQL 권한 거부, 실제 REST `401`.
2. anon 댓글 RPC: uuid 반환.
3. 같은 지문 1분 내 두 번째 RPC: SQLSTATE `53400`.
4. draft 글 댓글: SQLSTATE `P0002`.
5. 관리자 숨김 후 anon SELECT: 0행.
6. 비관리자 authenticated 관리자 RPC: SQLSTATE `42501`.
7. anon `motion_clips` 접근: permission denied, 기존 라벨링 경계 불변.
8. 실제 HTTP 서로 다른 User-Agent 2건: 둘 다 HTTP 200, fingerprint 2건/2종,
   `^[0-9a-f]{64}$` 2/2.

추가 Storage 검증:

- 비관리자 INSERT: RLS 거부.
- 뉴스 관리자 INSERT·UPDATE: 허용.
- DELETE policy predicate: catalog 확인.
- `storage.objects` 직접 DELETE는 Supabase가 Storage API 사용을 강제해 SQL에서
  `Direct deletion from storage tables is not allowed`로 차단했다. 이는 정책 실패가
  아니라 Storage 내부 보호 계약이며 probe transaction은 커밋되지 않았다.

최종 residue:

```text
news_articles probe rows = 0
news_comments probe rows = 0
storage probe rows = 0
news_admins rows = 0
```

## Security Advisor

- Errors: 0
- Warnings: 21
- Info: 34

직전 뉴스 아티클 적용 후 warning은 11이었다. 신규 10건은 다음 승인된 구조에 대한
일반 경고다.

- `news-media` public bucket listing 1건
- anon이 호출하는 검증된 SECURITY DEFINER helper/댓글 제출 RPC 2건
- authenticated가 호출하되 함수 내부에서 `news_admins`를 다시 검증하는 RPC/helper 7건

함수는 모두 빈 search path, 최소 EXECUTE grant, 내부 멤버십/발행 상태/길이/rate-limit
검증을 갖는다. 경고를 없애려고 테이블 쓰기를 열거나 service key를 브라우저에 두는 것이
더 위험하므로 승인된 RPC 경계를 유지한다.

## R1 연속성

기존 v13 창은 적용 직전 실패가 아닌
`SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`로 정상 종료했다.

- 종료 KST: `2026-07-29T20:49:29.425056+09:00`
- 경과: 8,187초
- runs/exit: 643/0
- provider calls/cost: 0/0
- residue/drift: 0/0
- service action: none, loaded 유지
- completion automation: 삭제, R1 automation 0
- control SHA:
  `9c6e555a465cc163f44ef47ec95ce78e84c204e1`

이 보고서가 main에 반영된 뒤 Mac mini는 production DB를 직접 읽지 않고 이 commit을
외부 변경 attestation으로 사용해 fresh runtime gates·immutable baseline·marker를 만들고
새 24시간 창을 0초부터 시작한다.

## 금지 경계

- 기존 영상·라벨·GT·blind consensus·behavior·activity 변경 0
- R2/media write·delete 0
- provider/model/Claude/VLM/local LLM 호출·비용 0
- Gemini CLI 실행·복구 0
- 라벨러/Owner 계정의 뉴스 관리자 승격 0
- primary dirty checkout reset/rebase/checkout 0
- force push 0

## 후속

Promotion 웹은 별도 뉴스 전용 Auth 사용자를 만든 뒤 그 UUID만 `news_admins`에 등록한다.
R1 fresh 24시간 창 시작 증거는 이 보고서에 additive로 붙이고 최종 판정을
`NEWS_COMMENTS_ADMIN_MIGRATION_APPLIED_VERIFIED_R1_RESTARTED`로 승격한다.
