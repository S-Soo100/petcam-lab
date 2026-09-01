# YOLO26n v2.6 bbox 좌표 계약 수정 실행 계획

## 1. 안전 정지와 재현

- GME LaunchAgent와 감시 자동화를 일시정지한다.
- 이전 identity의 queued, processing, succeeded, failure count를 읽기 전용으로 기록한다.
- 중심 xywh가 좌상단으로 잘못 해석되는 회귀 테스트를 먼저 추가해 실패를 확인한다.

## 2. 구현

- `gecko-vision-gate` adapter에서 중심 xywh를 좌상단 xywh로 변환한다.
- post-NMS 입력은 기존 중심 좌표를 유지한다.
- `bbox_coordinate_contract=xywh-top-left-v1`을 execution contract에 넣는다.
- 새 identity를 Nightly worker, 설치 fail-closed 계약, 웹 production dependency에 반영한다.
- 이전 live identity를 확인한 뒤 새 identity로 바꾸는 append-only migration을 추가한다.

## 3. 검증

- Gate 전체 테스트
- Nightly 전체 테스트
- petcam-lab 전체 테스트
- web 전체 테스트와 `tsc --noEmit`
- 독립 코드 리뷰에서 Critical/Important 이슈 0

## 4. 고정 순서 운영 반영

1. 세 repository의 수정 commit을 push하고 cross-repo handoff를 검증한다.
2. Mac mini의 clean runtime worktree와 checkpoint SHA를 다시 확인한다.
3. 새 worker code와 identity를 설치하되 live trigger·web identity는 아직 바꾸지 않는다.
4. 문제를 재현한 영상과 주간·야간·반사 사례를 새 identity smoke로만 실행한다.
5. 박스 좌표, 복수 탐지 보존, run 연결, artifact SHA/provenance, failure 0을 독립 확인한다.
6. 성공 시 migration으로 신규 live enqueue를 새 identity로 전환한다.
7. web active identity를 새 identity로 전환하고 실제 라벨링 화면을 검증한다.
8. 저장 영상 전체를 새 identity로 append-only enqueue하고 live 우선 bounded worker를 재개한다.
9. 완료 조건을 감시하는 새 자동화를 활성화한다.

## 5. 중단 조건

- checkpoint 또는 execution identity 불일치
- 새 claim RPC가 다른 identity job을 claim함
- 문제 영상의 박스 위치가 보정되지 않음
- 복수/반사 탐지가 의도치 않게 합쳐짐
- canary retryable/terminal failure 발생
- 기존 artifact 변경·삭제 또는 금지된 GT/원본 변경 감지

중단 시 자동 재queue나 기존 결과 수정을 하지 않고 원인과 다음 안전 조치만 보고한다.
