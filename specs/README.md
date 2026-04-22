# specs/ — Lightweight Spec-Driven Development

> "내일의 나/사용자가 '왜 이렇게 했지?' 물을 확률이 높으면 스펙을 쓴다. 아니면 그냥 한다."

## 이 폴더의 역할

개발 작업의 **의사결정 기록**과 **진행 상태**를 한 파일에 모아둔다. 체크리스트가 status, 설계 메모가 ADR, 학습 노트가 개인 위키 역할.

**연관:**
- 상위 **기획 스펙**(무엇/왜)은 `tera-ai-product-master/docs/specs/`
- 여기 **개발 스펙**(어떻게)은 그걸 받아서 구현 관점으로 구체화

## 스펙 쓸지 말지 판단

### ✅ 쓴다
- 스테이지 단위 작업 (Stage A~E)
- 3일 이상 걸릴 기능
- 설계 결정이 필요한 작업 (라이브러리 선택, 아키텍처 선택 등)
- 여러 스크립트·모듈이 묶이는 실험
- 버그가 아키텍처 이슈로 번진 대형 수정

### ❌ 안 쓴다
- 단발 버그 수정 (1~2시간 이내)
- 순수 리팩토링 (동작 동일)
- 의존성 업데이트
- 오타/문서 수정
- 스크립트 한두 줄 추가

### 애매하면?
**판단 기준 한 줄**: "내일의 나/사용자가 '왜 이렇게 했지?' 물을 확률이 높으면 쓴다."

## 작업 흐름

1. **작업 시작 전** — 관련 스펙 있는지 확인 → 있으면 읽고 완료 조건 체크.
2. **스펙 없는데 필요** — `_template.md` 복사 → `specs/{주제}.md`로 저장 → **스코프/완료 조건만 먼저 채우고** 사용자 확인.
3. **작업 중** — 설계 결정 생기면 "설계 메모" 섹션에 추가. 새 개념 쓰면 "학습 노트"에.
4. **작업 완료** — 모든 체크박스 ✅ → 상태 `✅ 완료`로 변경 → 스펙에 마지막 요약 한 줄.
5. **중단/폐기** — `⏸️ 보류` 또는 `🗑️ 폐기` + 사유 한 줄.

## 네이밍

- 형식: `{stage/feature}-{kebab-case}.md`
- 스테이지: `stage-a-streaming.md`, `stage-b-motion-detect.md`
- 기능: `feature-clip-retention.md`, `feature-supabase-auth.md`
- 실험: `experiment-rtsp-codec-compare.md`

## 상태 표기

| 기호 | 의미 |
|------|------|
| 🚧 | 진행 중 |
| ✅ | 완료 (완료 조건 전부 체크) |
| ⏸️ | 보류 (재개 가능, 사유 기록) |
| 🗑️ | 폐기 (다시 안 할 것, 사유 기록) |

## 원칙

1. **체크리스트가 진행 상태** — 별도 칸반/status 파일 만들지 말 것.
2. **완료 조건은 검증 가능하게** — "잘 작동한다"가 아니라 "`pytest tests/test_foo.py` 통과" 같은 구체 기준.
3. **Out 섹션이 핵심** — 뭘 안 할지 명시하지 않으면 스코프가 뭉개진다.
4. **학습 노트는 나중의 나를 위한 것** — 작성 시점엔 귀찮지만 3개월 뒤 효자.
5. **폐기도 기록** — 실패·보류한 스펙도 남긴다. 왜 안 했는지가 미래의 의사결정에 도움.

## 현재 스펙 목록

<!-- 스펙 추가 시 이 표를 업데이트 -->

| 상태 | 파일 | 한 줄 |
|------|------|------|
| ✅ | [stage-a-streaming.md](stage-a-streaming.md) | RTSP 스트리밍 + 서버 파일 저장 MVP (완료 2026-04-20) |
| ✅ | [stage-b-motion-detect.md](stage-b-motion-detect.md) | 움직임 감지 + 세그먼트 `_motion`/`_idle` 태그 (완료 2026-04-20) |
| ✅ | [stage-c-db-api.md](stage-c-db-api.md) | Supabase `camera_clips` + 조회 API 3종 (완료 2026-04-21) |
| 🚧 | [stage-d-roadmap.md](stage-d-roadmap.md) | Stage D 전체 로드맵 + 결정 기록 (JWT/카메라/썸네일/배포) |
| ✅ | [stage-d1-auth-crypto.md](stage-d1-auth-crypto.md) | JWT 검증 `Depends` + Fernet 비번 암호화 인프라 (완료 2026-04-22) |
| ✅ | [stage-d2-cameras-api.md](stage-d2-cameras-api.md) | `cameras` 테이블 + CRUD API 6종 + RTSP 테스트 연결 (완료 2026-04-22) |
