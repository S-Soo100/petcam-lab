# 연구 카탈로그·보존 설계

**상태:** 승인됨 · 정리 진행
**작성:** 2026-07-27
**범위:** `petcam-lab`을 중앙 카탈로그로 삼아, 연관 연구 문서가 있는 `petcam-nightly-reporter`와 `gecko-vision-gate`의 기준 위치를 함께 추적한다.

## 목적

실험 결과·보류·기각·운영 검증을 한 화면에서 찾고, 다음 연구가 이미 기각된 가설이나 다른 트랙의 결과를 다시 실행하지 않게 한다. 원본 보고서와 재현 산출물은 이동하거나 삭제하지 않는다.

## 사용자 체험

`docs/research/README.md`를 열면 연구별 현재 상태와 다음 허용 행동을 바로 본다. 필요한 근거는 같은 행의 원문 링크로 이동한다. 원본 결과를 삭제하려다 고민할 때는 `RETENTION.md`에서 보존·후보·금지 기준을 확인한다.

## 카탈로그 계약

1. 한 연구 항목은 고유 `id`, 상태, 질문, 판정, 근거 위치, 기준 repo/branch/commit, 다음 허용 행동을 가진다.
2. 상태는 `active`, `planned`, `hold`, `rejected`, `superseded`, `validated-limited`, `operational` 중 하나다.
3. `rejected`와 `superseded`는 삭제 대상이 아니다. 재등판 방지용 failure evidence로 보존한다.
4. 중앙 카탈로그는 메타데이터만 보관한다. 영상, raw 결과, DB 스냅샷, R2 객체, 비밀값은 복사하지 않는다.
5. 외부 레포 항목은 절대경로가 아닌 repo-relative 원문 경로와 확인한 commit SHA를 기록한다.
6. 카탈로그의 상태가 원문 SOT와 충돌하면 원문 보고서와 `specs/next-session.md`가 우선이다. 다음 정리 때 카탈로그를 고친다.

## 보존 정책

| 분류 | 처리 |
|---|---|
| tracked 설계·시험지·보고서·요약 결과 | 보존 |
| raw 결과·프레임·영상 | gitignore 상태를 유지하고 원본 위치만 카탈로그에 기록 |
| 기각/보류 연구 | 보존, 삭제 대신 상태와 재등판 조건 기록 |
| 중복·임시 산출물 | 근거와 소유자가 확인된 뒤에만 별도 cleanup 후보 목록으로 이동 |
| 공유 worktree의 미추적 파일 | 이번 정리에서 건드리지 않음 |

## 완료 조건

- `docs/research/catalog.json`이 현재 핵심 연구와 연관 연구 원문을 구조적으로 기록한다.
- `docs/research/README.md`가 사람이 읽기 쉬운 상태표와 우선순위를 제공한다.
- `docs/research/RETENTION.md`가 보존·정리 원칙과 이번에 실제로 하지 않은 삭제를 명확히 적는다.
- 모든 기록 경로와 commit 참조를 로컬에서 확인하고 JSON 문법을 검증한다.

## 비목표

- production DB/R2 변경, 데이터 삭제, branch 삭제, main merge.
- 기존 연구의 결론 변경 또는 새 성능 주장.
- 연구 워커·selector·prompt·threshold 변경.
