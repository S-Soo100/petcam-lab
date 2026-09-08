# 하이라이트 품질 보강 결과 — 2026-09-08

상태: `REVIEWED_READY_FOR_INTEGRATION`. 코드·로컬 DB·원격 Web build 검증 완료, 운영 DB/서비스는 미반영이야.

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
운영 Fly에는 GME algorithm/detector 설정 이름이 Deployed임을 확인했지만 웹과의 값 일치는 이번에 확인하지 않았어.

## 다음 반영 순서

커밋·production DB migration·배포 승인 후:
1. 웹/Fly exact 계약 값 일치 확인.
2. `2026-09-10_highlight_quality_stats.sql` 적용(원장/규칙 데이터 수정 없음).
3. Web/API 배포. owner 품질표, 비-owner 접근 거부, 인증 앱 하이라이트를 확인.
4. 규칙 변경 없이 O와 X를 함께 검수해서 첫 품질 분포를 모아.

아직 성능 향상 수치는 측정하지 않았어. 이 변경은 안전한 버전 고정과 개선 판단 기반 보강이야.

## Git 실제 출력

작업 공간: `/Users/baek/petcam-lab/.worktrees/highlight-quality`.
branch: `codex/highlight-quality`. 커밋·push·main 통합 없음. 원래 main의 dirty는 보존했어.
HEAD / upstream 순서:

```text
ace7acbdfef61038683f0a2d806b522bfb66f413
ace7acbdfef61038683f0a2d806b522bfb66f413
```

tracked/untracked:

```text
 M .claude/donts-audit.md
 M backend/routers/highlights.py
 M docs/API.md
 M docs/decision-gate.md
 M docs/handoff-prompts/2026-09-08-app-highlight-api-handoff.md
 M docs/highlight-rule-operations.md
 M scripts/run_highlight_rule_v0_probe.py
 M specs/README.md
 M specs/feature-highlight-auto-initial-designation.md
 M tests/test_highlights_api.py
 M web/src/app/labeling/owner/highlight-rules/page.tsx
?? docs/research/
?? docs/superpowers/plans/2026-09-08-highlight-quality.md
?? migrations/2026-09-10_highlight_quality_stats.sql
?? tests/sql/highlight_quality_probe.sql
?? web/src/app/api/labeling-v4/owner/highlight-quality/
?? web/src/app/labeling/owner/highlight-rules/_quality-panel.test.tsx
?? web/src/app/labeling/owner/highlight-rules/_quality-panel.tsx
?? web/src/lib/highlightQuality.test.ts
?? web/src/lib/highlightQuality.ts
```
