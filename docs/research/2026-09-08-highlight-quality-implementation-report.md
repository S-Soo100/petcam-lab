# 하이라이트 품질 보강 결과 — 2026-09-08

상태: 운영 Web/API/DB 반영 완료. owner 화면 canary 확인, 앱 로그인 종단간 피드 검증은 미완료야.

## 반영 내용

- API의 최신 GME run fallback을 제거해. 명시 계약 누락/오류는 503이야.
- 규칙·카메라·활동일·검출기·알고리즘별 O 수용률/X 놓침률과 분모를 표시해.
- 최초 자동값과 조회 종료 전 최신 사람 정정을 비교하고 대기·실패·사유를 분리해.
- off 트리거는 기존 X에서 추가로 포착한 표본의 사람 O/X를 표시해.
- 읽기 전용 quality RPC와 기간 인덱스를 추가했어. 10초/5초 규칙과 트리거 상태는 그대로야.

## 검증

Python 2461 passed / 5 skipped, Web 1090 passed / 137 files, tsc PASS.
일회용 PostgreSQL `HIGHLIGHT_RULE_V0_PROBE_OK` / `PROBE_RESIDUE=0`.
독립 리뷰 3건 보강 후 남은 P1/P2 없음.
보호된 Vercel Preview 원격 Next build 41초, deployment READY.
Preview 새 API에서 앱 인증 없는 GET은 401을 반환했어. 실제 owner 데이터 canary는 운영 migration 적용 뒤 확인해야 해.

Preview: https://petcam-k1hkmyglh-ssoo100s-projects.vercel.app
배포 ID: `dpl_GXca36ciR7ikfbKi45YKrX4PbpP3`.
Web 소스 419파일 SHA256: `b5c77cfc0f8b1cbaf81c310f55eab6e8f0d15c5fc053f88f7f872a7dd802fa1a`.

로컬 build는 리소스 경합 방지 훅 때문에 실행하지 않았고 원격으로 대체했어.
첫 Preview는 업로드 제외 설정 오류로 파일 0개라 실패했고, Web 소스만 별도 staging해서 성공했어.
구현 당시의 설정 값 비교 미검증은 아래 운영 반영 단계에서 해소했어.

## 운영 반영 — 2026-09-08 owner 승인

코드 commit: `f52f3a675ec3e14e237e737af0d17fd186709c93`, origin/main에 push했어.
Vercel production: `dpl_GEG2Fbm3VXxnu51Co1u5sMQxKN2u`, READY, 위 SHA 일치.
운영 주소: https://label.tera-ai.uk/labeling/owner/highlight-rules.

운영 SQL Editor에서 committed `2026-09-10_highlight_quality_stats.sql`을 적용했어.
전후 검수 원장 80건, 활성화 기록 1건, 활성 규칙 `hl-rule-v0` 불변.
인덱스 존재, service_role EXECUTE 허용, anon/authenticated EXECUTE 거부를 확인했어.
웹/Fly exact algorithm·detector 값 일치 및 형식 유효성을 확인했어.

실제 owner 로그인 화면에서 새 집계가 표시돼. 표본 79건, O 수용률 31/36,
X 놓침률 8/43, 사람 정정 1건. off early_action 사람 O/X=2/12,
frequent_bursts=7/6. 검수 표본 수치이며 전체 정확도로 일반화하지 않아.
웹/API 무인증 요청은 각각 401, API health는 정상.

Fly API release `rel_56m7zkk03q98zlg0` (v5), machine `2861246b761328`, nrt.
image `deployment-01M1Z9ZM6KBW12EEM3KYZ11FAF`, digest
`sha256:e2b57788cb9e82b7357eaab2117158c8bafdb591f8e0b99ab5aedba084ae8b32`.
배포 smoke/health 통과. runtime `/app/backend/routers/highlights.py` SHA256이
로컬 committed 파일과 `2389d406ddc86c3fda57d8b001d5b2e7c211f68aff4d9c75fd45e7faaac5109c`로 일치해. 별도 Python 프로세스로 피드를 직접 호출하는 검증을 시도했지만
256MB machine에서 01:29:49 UTC uvicorn OOM이 발생했어. 이 검증은 중단했고 자동 재시작 뒤
01:30:00 UTC startup 완료, 외부 health 200과 무인증 피드 401로 복구를 확인했어.
추가 Python 프로세스가 원인으로 추정돼. 운영 서버에서 이 방식은 다시 쓰지 않아.
검수 데이터 write는 없었어. 로그인 앱 피드와 비-owner 403 운영 canary는 미검증이며,
로컬 테스트 및 DB 권한 검사로 확인한 범위와 구분해. 성능 향상 수치는 아직 입증하지 않았어.

복귀 이미지: `registry.fly.io/petcam-api:deployment-01M1XQXGCSH3F21E7M6P3XN8PN`.
현재 규칙은 그대로이고 조회 함수는 이전 코드에도 영향을 주지 않아.

## v2.6.1 적용 방향

학습 종료만으로 자동 승격하지 않아. 기존 학습 계약과 별도 봉인 평가를 통과한 뒤,
같은 영상·같은 algorithm·같은 rule v0로 검출기만 바꿔 비교해.
기술적 오추천과 실제 하이라이트 누락을 함께 측정하고, 조회 기간의 새 exact run을
확보한 뒤 웹/API 계약을 함께 전환해. 규칙 튜닝은 검출기 검증 다음 단계야.
상세는 [유효성·적용 방향](2026-09-08-gme-highlight-validity-and-v261-direction.md) §6을 따라.

## Git 기록

구현 worktree: `/Users/baek/petcam-lab/.worktrees/highlight-quality`.
코드 배포 시 HEAD와 origin/main 모두 `f52f3a675ec3e14e237e737af0d17fd186709c93`.
`git status --short --branch`는 `## codex/highlight-quality...origin/main`이고
tracked/untracked 변경이 없었어. 원래 main checkout의 사용자 dirty는 보존했어.
