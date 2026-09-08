# 하이라이트 품질 보강 구현 계획

**Goal:** 현재 규칙을 유지하면서 실험 버전 자동 유입을 막고, 사람 검수 결과를 계약별로 비교하게 해.
**Architecture:** API는 명시 env만 해석. 기존 stats는 보존하고 읽기 전용 quality RPC/API/owner 패널을 추가해.
**Tech Stack:** FastAPI, PostgreSQL, Next.js.
**Spec:** `docs/research/2026-09-08-gme-highlight-validity-and-v261-direction.md`.
**승인:** 2026-09-08 owner “1번 지금 가능한 고도화는 바로 보강하렴”. 이 세션에서 순차 실행해.

## 제약

- 10초/5초·off 트리거·사람 우선·원장 불변. 실제 검수값 생성 없음.
- production DB 변경/배포·커밋은 별도 명시 승인 전 실행하지 않아. 로컬 migration probe와 보호된 Preview build까지 검증해.
- 기존 checkout dirty는 보존하고 `codex/highlight-quality`에서 작업해.
- 사용자 흐름: 규칙 관리 → 카메라·GME별 표본/수용률/놓침률 확인 → off 트리거 추가 포착 확인.

## Task 1: 명시 GME 계약

- [x] `tests/test_highlights_api.py`에서 env 누락/공백/형식오류와 최신 shadow run이 함께 있어도 503인 테스트부터 실행해.
- [x] `backend/routers/highlights.py::_resolve_gme_contract`의 latest-run fallback을 제거해. schema v1, `gme-motion-v숫자`, 64자리 hex identity 검증. DB 조회 없음.
- [x] 해당 API 테스트로 정상 계약·페이지네이션·권한 동작을 확인해.

## Task 2: 품질 집계

- [x] 기존 disposable PG probe에 correction/대기/다른 detector/활동일/기간·권한 케이스를 추가해 RED 확인.
- [x] 새 migration `2026-09-10_highlight_quality_stats.sql`에 `fn_highlight_quality_stats(p_from timestamptz,p_to timestamptz) RETURNS jsonb`를 추가해.
- [x] 처음 검수한 기간(최대 31일)의 clip을 고르고 최초 run/규칙과 종료시각 이전 최신 verdict를 비교해. rows는 rule/camera/activity_day/schema/algorithm/detector별 4칸 분할·pending·correction·사유, shadow_rows는 원래 X이고 당시 off 트리거가 맞은 건만 집계해.
- [x] anon/authenticated/PUBLIC EXECUTE 금지, service_role만 허용. 합성 DB probe로 검증해.

## Task 3: Owner 품질 화면

- [x] `highlightQuality` mapper·`owner/highlight-quality/route` 테스트: 0분모 null, 숫자/필드 allowlist, 권한·기간 오류부터 실행해.
- [x] owner-only GET으로 RPC를 연결하고 최근 7일 quality 패널을 기존 규칙 관리에 추가해. 기존 최초 유지율도 보존해.
- [x] 표본 기반 수치임을 명시하고 카메라별 O/X 모두 검수하라는 설명, 당시 shadow 추가 O/X 수를 표시해.

## Task 4: 검증·기록

- [x] 실제 Next build: 보호된 Vercel Preview `dpl_GXca36ciR7ikfbKi45YKrX4PbpP3` READY, 원격 build 41초 완료. 로컬 훅 차단의 동등 대체 검증.
- [x] Python 전체 `-x`, Web 전체, TypeScript, PG probe, diff check를 실행해.
- [x] 최신 코드 독립 리뷰와 발견 수정 후 검증해. 런북·스펙·감사 기록을 갱신해.
- [x] 배포 전 env 일치 확인과 migration → Web/API 배포·인증 smoke 순서를 기록해. 운영 미반영을 명시해.


## 검증 결과

- Python: 2,461 passed / 5 skipped (89.27s).
- Web: 137 files / 1,090 passed, TypeScript exit 0.
- DB: `HIGHLIGHT_RULE_V0_PROBE_OK`, `PROBE_RESIDUE=0`. 경계값·정정·기간·서로 다른 detector/algorithm·KST 07시 경계·shadow 추가 포착·권한·인덱스 사용 가능성 확인.
- 독립 리뷰: 발견 3건 조치 후 재검토에서 남은 P1/P2 없음.
- Preview: `https://petcam-k1hkmyglh-ssoo100s-projects.vercel.app`, READY. 배포 ID `dpl_GXca36ciR7ikfbKi45YKrX4PbpP3`.
- 원격 빌드 소스: Web 419파일, SHA256 `b5c77cfc0f8b1cbaf81c310f55eab6e8f0d15c5fc053f88f7f872a7dd802fa1a` (정렬된 경로+파일 SHA 집계).
- 로컬 build는 리소스 경합 방지 훅이 거부. 첫 Preview는 제외 설정으로 파일 0개가 업로드되어 실패했고, 정확한 Web 파일만 staging하여 원격 build를 완료했어. 로컬 build 우회 실행은 없었어.
- 아직 미실행: 커밋·production migration·production 배포·실제 owner 데이터 품질표 canary. 별도 승인 후 migration → 웹/API 배포 → 인증 앱·owner canary 순서로 진행해.


## 운영 반영 승인

2026-09-08 owner가 커밋·운영 DB 적용·배포까지 명시 승인했어. 이전 승인 대기 표기는 구현 시점 기록이며, 이 승인으로 운영 반영을 진행해.
