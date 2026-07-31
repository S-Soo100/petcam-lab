# 사건 경계 검수 + 팀 공용 대시보드 구현 계획

> 실행 정본: `docs/superpowers/specs/2026-07-31-rba-boundary-review-dashboard-design.md`

## 목표

기존 교차검수는 건드리지 않고 지정된 owner/peer의 사건 경계 판정 채널과 승인 팀원 공용 데이터
집계 화면을 production에 배포한다.

## Task 1 — DB 계약을 RED로 고정

- `tests/test_rba_boundary_review_migration.py` 작성
- 테이블/RLS/service-role/append-only/open-split/immutable submit·resolve 계약 검증
- 대시보드 RPC의 canonical GT 우선순위와 격리 영상 제외 계약 검증
- 대상 migration이 아직 없어 실패함을 확인

## Task 2 — forward migration 구현

- `migrations/2026-07-31_rba_boundary_review_dashboard.sql` 추가
- 5개 경계 테이블, trigger, RPC와 팀 집계 RPC 구현
- 기존 motion labeling 테이블에는 INSERT/UPDATE/DELETE 하지 않음
- static test와 disposable PostgreSQL probe 통과

## Task 3 — 서버 권한·도메인 TDD

- boundary decision/parser, workspace mapper, dashboard mapper test 작성 후 RED
- `requireLabelingAccess`와 assignment 확인을 분리해 구현
- raw key/상대 답/holdout 비공개 응답 계약 구현

## Task 4 — API route TDD

- access 응답의 `boundary_enabled`
- workspace, media URL, submit, owner conflicts/resolve
- team dashboard route
- 401/403/404/409와 immutable 재제출 test

## Task 5 — 내비게이션·화면 TDD

- owner/labeler 공통 `데이터 현황` nav test
- assignment 사용자만 `이어짐 확인` nav test
- 동적 모바일 grid와 기존 메뉴 active 상태 test
- 사건 A→B 재생, 3판정 제출, owner 충돌 해결 화면
- 집계 카드와 행동별 분포 화면

## Task 6 — 검증 완료 private manifest seed 도구

- media eligibility v1에서 R2 HEAD 240/240으로 검증된 exact-120 artifact를 읽는 one-shot import
  script와 dry-run test(이전 228/240 blocked artifact 사용 금지)
- reviewer 이메일을 DB에서 UUID로 해석하고 development 60 + holdout 60을 idempotent 준비
- seed 로그에는 count/digest만 출력
- 초기 상태는 development만 open, holdout은 sealed

## Task 7 — 교차검토·전체 검증

- iTerm 공식 AppleScript로 Claude에 설계/SQL/API 권한 교차검토
- `uv run pytest`, `npm test`, `npm run build`
- 320/390/desktop UI browser smoke
- 기존 cross-review 회귀와 mutation 0 aggregate audit

## Task 8 — 배포와 main 정리

- production DB forward migration
- Mac mini에서 private seed one-shot 실행
- Vercel Preview 검증 후 production 배포
- production owner/peer/team/unauthorized smoke
- commit/push/main 병합, 정본 문서와 `specs/next-session.md` 갱신
