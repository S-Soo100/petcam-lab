# 연구 자료 보존·정리 정책

## 이번 정리의 원칙

이번에는 연구를 **삭제하는 정리**가 아니라 **찾을 수 있게 만드는 정리**를 한다. 과거의 기각·보류는
실패가 아니라 같은 가설을 다시 투자하지 않게 하는 evidence다.

## 보존 기준

| 자료 | 처리 | 이유 |
|---|---|---|
| tracked 설계·TEST-SHEET·REPORT·요약 JSON | 보존 | 판정 재현과 다음 연구의 출발점 |
| 실험 raw 결과·프레임·영상 | gitignore 상태 유지, 원본 위치만 카탈로그에 기록 | 대용량·민감 매체를 중앙 문서로 복제하지 않음 |
| 기각·보류·대체 연구 | 보존 + `do_not` 기록 | 재등판·사후 threshold 조정을 막음 |
| 외부 레포의 설계·보고서 | 원문 레포에 보존, 이 카탈로그에는 경로·commit만 기록 | 소유권과 SOT를 보존 |
| 운영 로그·production 스냅샷 | 원 운영 보존정책을 따름 | 연구 문서가 DB/R2 lifecycle을 대체하지 않음 |
| R1 local ledger·JSONL·redacted log | runtime 원본 유지, Git에는 미추적 | crash/reboot 복구와 감사 증거이며 media가 아님 |

## 이번에 실제로 한 일

- `docs/research/`에 사람용 인덱스, 기계용 상태 원장, 보존 정책을 추가했다.
- Owner GT·ROI·VLM consensus·Python Evidence·local router·Gate의 판정과 재개 조건을 연결했다.
- `petcam-nightly-reporter`와 `gecko-vision-gate` 원문은 이동·복사·수정하지 않고 기준 commit만 기록했다.

## 이번에 하지 않은 일

- 영상·raw 결과·R2 object·DB row 삭제 또는 이동
- 원인 미확인 파일·공유 primary worktree의 untracked 파일 삭제
- 원격 branch 삭제, history rewrite, main merge

공유 worktree의 파일은 다른 작업이 소유할 수 있다. 필요 없어 보이더라도 소유자, 생성 경로,
재현 영향, gitignore 상태가 확인되기 전에는 cleanup 후보로 확정하지 않는다.

## 물리 정리 절차

실제 삭제는 아래 네 조건을 모두 만족하는 별도 승인 작업으로만 한다.

1. 대상의 절대경로·생성 작업·소유자를 목록화한다.
2. tracked/ignored 여부와 재현·감사에 미치는 영향을 확인한다.
3. raw·영상·DB/R2가 아니라는 점, 또는 별도 백업·보존정책이 있다는 점을 증명한다.
4. 삭제 후 `git status`, 카탈로그 링크, 재현 명령을 다시 검증한다.

이 절차 전에는 중앙 카탈로그의 상태 변경이 곧 삭제 승인이 아니다.

R1 runtime root는 `storage/research-runtime/` 또는 Mac mini 전용 Application Support 아래에
두고 Git에서 제외해. ledger 손상 시 새 파일로 자동 교체하지 말고 원본을 보존한 채 fail-closed
진단해.
