# ChatGPT 연구 정본 통합 설계

## 1. 목적

2026-07-21부터 RBA/VLM 연구의 최종 계획·판정·통합 책임을 ChatGPT가 맡는다. Claude가 만든 코드·실험·보고서는 삭제하거나 다시 쓰지 않고 검증 가능한 Git 이력으로 보존하되, 활성 연구 방향과 다음 작업은 `petcam-lab`의 단일 정본에서만 선언한다.

## 2. 감사 결과

| 레포 | 감사 결과 | 통합 조치 |
|---|---|---|
| `petcam-lab` | Claude 연구 브랜치가 전부 `origin/main`의 조상 | ChatGPT 연구 정본과 레포별 SHA manifest 추가 |
| `petcam-nightly-reporter` | `feat/vlm-basking-classification`만 `origin/main`과 분기 | 최신 Python Evidence `origin/main` 위에 merge commit으로 통합 |
| `gecko-vision-gate` | 모든 관련 브랜치가 `origin/main`의 조상 | 코드 변경 없이 정본 SHA만 기록 |
| `petcam-rba-worker` | 별도 미병합 연구 브랜치 없음 | 코드 변경 없이 정본 SHA만 기록 |

서로 다른 Git 저장소는 하나의 물리 브랜치를 공유할 수 없다. 따라서 변경이 필요한 두 레포에서 동일한 논리 브랜치 이름 `codex/research-consolidation-20260721`을 사용하고, `petcam-lab` manifest가 전체 연구선의 단일 인덱스가 된다.

## 3. 통합 원칙

1. `petcam-nightly-reporter`는 `origin/main`을 기준으로 Claude P1/basking 연구 브랜치를 `--no-ff` merge한다.
2. 연구 커밋을 squash하거나 재작성하지 않는다. 실패·reject·hold 기록도 그대로 보존한다.
3. 충돌 파일은 양쪽 계약을 합친다.
   - `reporter/config.py`: Python Evidence와 P1 설정을 모두 유지한다.
   - `specs/next-session.md`: 최신 운영 사실을 우선하고 P1 연구 결과를 additive history로 보존한다.
4. `petcam-lab`은 ChatGPT를 연구 최종 책임자로 명시한다. Claude는 계획에 따른 구현·실험 수행자이며, 결과는 ChatGPT 검수와 정본 반영 전까지 활성 판정이 아니다.
5. 기존 Claude 브랜치는 삭제하지 않는다. 통합 manifest에서 `superseded/read-only`로 표시한다.
6. 통합 중 production DB write, LaunchAgent 변경, VLM 호출, 배포는 하지 않는다.
7. Python Evidence 실패 Slack 링크 작업은 통합 완료 후 새 정본 브랜치에서 재개한다.

## 4. 활성 연구 정본

`docs/research/ACTIVE-RESEARCH.md`가 다음을 한 곳에서 관리한다.

- 연구 책임 주체와 역할 경계
- 레포별 기준 branch/commit SHA
- adopt/hold/reject 판정
- W1/W2/W3 우선순위
- superseded 브랜치 목록
- 다음 작업의 승인·STOP 조건

판정 근거의 우선순위는 다음과 같다.

1. `docs/decision-gate.md` append-only 판정 로그
2. `docs/research/ACTIVE-RESEARCH.md`
3. `specs/next-session.md`
4. 개별 handoff/report 문서

## 5. 완료 조건

- 두 변경 레포의 활성 브랜치 이름이 `codex/research-consolidation-20260721`이다.
- nightly 통합 브랜치가 최신 `origin/main`과 Claude P1 branch 양쪽을 모두 조상으로 가진다.
- `petcam-lab` 정본이 정확한 40자리 SHA와 역할 경계를 기록한다.
- takeover 문서의 작성 커밋 표기가 실제 커밋 `5f50242f0971275dd98da9e32b9df85605d15419`와 일치하고 historical handoff로 표시된다.
- `petcam-lab` 전체 테스트와 nightly 전체 테스트가 통합 후 통과한다.
- 두 브랜치가 원격에 push되고 local/remote가 일치한다.
- 기존 dirty checkout과 미추적 파일은 변경되지 않는다.

## 6. 범위 밖

- 통합 브랜치를 `main`에 merge하거나 배포하는 작업
- 기존 Claude/feature 브랜치 삭제
- W1 production DB 조회 실행
- W2 GT 스펙 작성
- W3 T1 v2 연구 재개
- Python Evidence Slack 실패 알림 구현
