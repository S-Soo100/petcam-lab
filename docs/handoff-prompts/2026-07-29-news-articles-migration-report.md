# 2026-07-29 프로모션 뉴스 아티클 migration 완료 보고서

## 판정

`NEWS_ARTICLES_MIGRATION_APPLIED_VERIFIED`

프로덕션 `slxjvzzfisxqwnghvrit`에 독립 `news_articles` 테이블과 공개 읽기 RLS를
적용했고, 실제 REST 요청으로 공개 범위·쓰기 차단·트리거·probe 무잔류를 확인했다.
이 보고서의 후속 절에서 R1 새 24시간 검증 창 재시작 증거를 별도로 닫는다.

## 요청과 범위

- 원본 요청:
  `/Users/baek/terra-ai-promotion-website/docs/requests/2026-07-29-petcam-lab-news-articles-migration.md`
- 원본 요청 commit: `fc021aa`
- 구현 레포: `/Users/baek/petcam-lab`
- 격리 worktree:
  `/Users/baek/petcam-lab/.worktrees/news-articles-migration-20260729`
- branch: `codex/news-articles-migration-20260729`
- 시작 production 기준 HEAD: `e2486ec29b1bb7da5443bce7eca70d61c32b3ddf`
- 설계 commit: `e057490315e0bbfb5250b492a3318fe6aadda441`
- 구현 commit: `c387c5cc292034d64e6a29d65b0581e1e488017c`

## 구현 계약

- 기존 영상·라벨링·RBA 테이블과 FK가 없는 독립 `public.news_articles`
- 공개 읽기 조건:
  `status = 'published' AND published_at IS NOT NULL AND published_at <= now()`
- `anon`·`authenticated`: SELECT만 허용
- `service_role`: SELECT·INSERT·UPDATE·DELETE 허용
- 공개 목록 정렬을 위한 partial index:
  `(published_at DESC, id DESC) WHERE status='published'`
- `updated_at` 트리거:
  `SECURITY INVOKER`, 빈 `search_path`, `pg_catalog.now()`
- 기존 객체와 이름이 충돌하면 덮어쓰지 않고 실패하는 fail-closed migration

정본 migration:
`migrations/2026-07-29_news_articles.sql`

정본 SHA-256:
`5d60520167da1723771b251048717da90fcc639698e0795840bfe86c44936939`

## 로컬 검증

- baseline: `840 passed, 3 skipped`
- focused migration/runtime tests: `7 passed`
- 구현 후 전체: `847 passed, 3 skipped`
- 로컬 PostgreSQL 15 probe:

```text
NEWS_ARTICLES_RUNTIME_OK
NEWS_ARTICLES_RLS_OK
PROBE_RESIDUE=0
```

## 프로덕션 적용

- Supabase organization: `terra-ai-dev`
- project: `Terra AI`
- project id: `slxjvzzfisxqwnghvrit`
- branch/environment: `main` / Production
- migration history name: `news_articles_public_read`
- migration history version: `20260729181701`
- created_by: `codex-desktop`
- idempotency key:
  `c387c5cc292034d64e6a29d65b0581e1e488017c`

적용 전에는 table·trigger function·policy가 모두 없음을 확인했다. 적용 후에는
다음을 catalog에서 재확인했다.

- 테이블 1개, 정본 컬럼 10개
- RLS enabled
- 공개 partial index 존재
- touch trigger와 trigger function 존재
- 공개 SELECT policy 1개
- anon/authenticated INSERT·UPDATE·DELETE 권한 없음
- service_role CRUD 및 bypass RLS
- trigger function의 anon/authenticated EXECUTE 회수
- migration history 정확히 1건

## 실제 production REST probe

고유한 probe 행 3개(과거 published·draft·미래 published)를 service role로 만들고,
익명 REST 호출 후 `finally` cleanup했다.

```text
NEWS_ARTICLES_PUBLIC_READ_OK
NEWS_ARTICLES_ANON_WRITE_DENIED
NEWS_ARTICLES_TOUCH_TRIGGER_OK
PROBE_RESIDUE=0
```

- anon은 과거 published 1건만 읽었다.
- draft와 미래 published는 숨겨졌다.
- anon POST는 401/403으로 거부됐다.
- service-role UPDATE에서 `updated_at` trigger가 동작했다.
- probe 행은 0건 남았다.

## Security Advisor

- Error: 0
- Warning: 11
- Info: 33
- `news_articles` 관련 신규 warning/error: 0

Warning 11건은 migration 전부터 존재한 기존 항목이다.

## 운영 중 발생한 비파괴적 오류

Supabase SQL Editor의 긴 기존 query 탭에서 Monaco textarea `fill`이 화면의 일부만
교체해, 검증 query 대신 migration 첫 `CREATE TABLE`을 한 번 재실행하려 했다.
이미 테이블이 존재해 `42P07 relation "news_articles" already exists`에서 즉시
중단됐고, migration이 transaction·collision fail-closed라 추가 변경은 없었다.
그 뒤 모든 검증 query를 새 빈 query 탭에서 실행했다.

## R1 연속성

기존 R1 24시간 검증 창은 계획된 외부 DB 변경 전에
`SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`로 정상 종료했다.

- 종료 시 runs: 473
- exit 0
- provider/Claude/VLM 호출: 0
- 비용: 0
- production 접근·변경: 0
- 종료 보고서:
  `/Users/baek-end/petcam-lab-r1-runtime-p3-control/docs/handoff-prompts/2026-07-29-r1-mac-mini-runtime-p3-v12-24h-superseded-report.md`

프로덕션 migration과 이 보고서의 main 반영 후, Mac mini에서 같은
`com.petcam.research-runtime`을 기준으로 immutable baseline을 새로 만들고
24시간 검증 창을 0부터 다시 시작한다.

## 금지 경계

- 기존 영상·라벨·GT·blind consensus·behavior·activity 변경 0
- R2/media write·delete 0
- provider/model/Claude/VLM/local LLM 호출 0
- Gemini CLI 실행·재설치 0
- primary dirty checkout 수정·reset·rebase 0
- force push 0

## 현재 후속

R1 새 24시간 창의 시작 시각·baseline·service 증거를 확보하면 이 보고서에
additive로 기록하고 최종 판정을
`NEWS_ARTICLES_MIGRATION_APPLIED_VERIFIED_R1_RESTARTED`로 승격한다.

## Additive: R1 v13 24시간 창 재시작

`NEWS_ARTICLES_MIGRATION_APPLIED_VERIFIED_R1_RESTARTED`

외부 DB 변경 완료 attestation을 기준으로 R1의 이전 superseded window를 이어 세지 않고
v13 창을 0초부터 새로 시작했어. 이 판정은 재시작 완료를 뜻하며, 24시간 검증 완료 판정은
아니다.

- 시작 KST:
  `2026-07-29T18:33:02.457813+09:00`
- 시작 UTC:
  `2026-07-29T09:33:02.457813+00:00`
- 완료 예정 KST:
  `2026-07-30T18:33:02.457813+09:00`
- 완료 예정 UTC:
  `2026-07-30T09:33:02.457813+00:00`
- R1 판정:
  `R1_RUNTIME_P3_RESTARTED_PENDING_24H`
- runtime service:
  `com.petcam.research-runtime`, loaded
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- 시작 runs / last exit:
  `507 / 0`
- provider calls / cost:
  `0 / 0`
- fresh runtime suite:
  `41 passed`
- adversarial:
  14 markers, `R1_RESIDUE_ZERO`
- fresh baseline:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v13.json`
- baseline SHA-256 / mode:
  `8afffc5737f7f734e2cda70821d9f67a3815067b75b83a7c0a1ab685af069fa7 / 0600`
- fresh marker:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-pending-v13.json`
- marker SHA-256 / mode:
  `5cf9c72d6b051579fb6bd9507a5b4882d0fe6baa9358acbc005dea1e70df3fbd / 0600`
- completion automation:
  `r1-runtime-v13-24h-completion`, ACTIVE, R1 automation exactly 1
- control report:
  `/Users/baek-end/petcam-lab-r1-runtime-p3-control/docs/handoff-prompts/2026-07-29-r1-mac-mini-runtime-p3-v13-24h-restart-report.md`
- control SHA:
  `2e282b2a8a21a9f4dacc2fb2a2c2accb7389d62c`

R1 재시작 과정에서 production DB를 직접 조회하거나 쓰지 않았고, R2/media/dataset/model/
provider 접근과 production service mutation도 0이야. 86400초 전에는
`DEPLOYED_VERIFIED`를 주장하지 않는다.
