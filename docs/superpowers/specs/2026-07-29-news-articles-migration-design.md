# terra ai News 공개 읽기 DB 설계

> 상태: production 적용 전
> 요청 정본: `/Users/baek/terra-ai-promotion-website/docs/requests/2026-07-29-petcam-lab-news-articles-migration.md`
> 대상 프로젝트: Supabase `slxjvzzfisxqwnghvrit`

## 목표

홍보 웹사이트가 발행된 뉴스 아티클을 Vercel 빌드와 브라우저에서 anon key로 읽을 수 있게
`public.news_articles`를 독립 추가한다. 기존 영상·라벨링·연구 테이블은 변경하지 않는다.

## 공개 경계

- anon/authenticated에는 `SELECT`만 부여한다.
- RLS는 `status = 'published' AND published_at <= now()`인 행만 공개한다.
- 초안·예약 전 글은 존재 자체를 공개하지 않는다.
- INSERT/UPDATE/DELETE는 `service_role`만 사용한다.
- 트리거 함수는 `SECURITY INVOKER`, `search_path = ''`이고 client execute 권한을 회수한다.

## fail-closed 보완

- 새 객체에 `IF NOT EXISTS`, `CREATE OR REPLACE`, `DROP IF EXISTS`를 쓰지 않는다. 이름 충돌은
  조용히 수용하지 않고 migration을 중단한다.
- slug는 영문 소문자·숫자·하이픈 조합, 최대 120자로 제한한다.
- 발행 상태에는 `published_at`이 반드시 존재해야 한다.
- 검증 데이터는 transaction rollback probe로만 만들고 잔여 0을 확인한다.
- 기존 `motion_clips` anon 접근은 계속 차단되어야 한다.

## 소유권과 실행 위치

- 스키마·migration·DB 이력 소유: `petcam-lab`
- 웹 조회·표시 소유: `terra-ai-promotion-website`
- 구현·production apply: MacBook clean worktree
- Mac mini R1 runtime: 이번 migration을 실행하지 않는다. 기존 24시간 측정창은 계획된 외부
  DB 변경으로 종료하고 migration 이후 새 baseline에서 다시 시작한다.

## 완료 조건

1. 정적 계약 테스트와 전체 pytest 통과
2. disposable PostgreSQL runtime probe 통과, 잔여 0
3. production migration 적용
4. anon published-only, anon write 차단, 기존 테이블 차단 확인
5. advisor 신규 보안 오류 없음
6. `docs/DATABASE.md`와 완료 보고서에 applied=true 기록
7. R1 새 24시간 baseline 시작
