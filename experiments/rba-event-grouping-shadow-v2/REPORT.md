# RBA 사건 묶기 shadow v2 실행 보고서

**실행일:** 2026-07-31
**상태:** `BLOCKED_MEDIA_PREFLIGHT_FAILED:verified=228:failed=12`
**실행 위치:** `baeg-endeuui-Macmini.local` 격리 임시 경로(mode `0700`)
**production repo HEAD:** `befa56e594adbe1da913b447fac745bb26c6ec61` (repo 파일은 변경하지 않음)

## 결론

기존 영상은 사건 경계 표본을 만들기에 충분했다. exact 120 pair와 unique clip 240을 동결 계약대로
선택했지만, R2 HEAD에서 12개가 실패해 private artifact를 만들지 않고 중단했다. 실패 clip을
다른 clip으로 바꾸지 않았으며 사람 검수도 시작하지 않았다.

## 선택 감사

| 항목 | 결과 |
|---|---:|
| cutoff 이전 closed source | 19,279 |
| activity candidate | 17,628 |
| diagnostic integrity | 1,606 |
| blocked research | 45 |
| adjacent candidate pair | 16,633 |
| 선택 pair / unique clip | 120 / 240 |
| development | 60 (bin별 20/20/20, 6박, 2 cameras, camera cap 35) |
| historical holdout | 60 (bin별 20/20/20, 6박, 3 cameras, camera cap 36) |
| canonical search | attempt 1125 / `le30,30to60,60to300` |
| selection fingerprint | `0e66ae801a0220c231a64050e14ea38af30384d12eb5ce3d93161559841c5d37` |

20/20/20은 의도적으로 층화한 평가 표본이라 production 자연 발생률이 아니다.

## Media preflight

| 검사 | 결과 |
|---|---:|
| R2 HEAD | 240회 |
| 확인 성공 | 228 |
| 실패 | 12 (`404 Not Found` 12, auth/기타 오류 0) |
| R2 GET / 원본 다운로드 | 0 |
| output directory / manifest / worksheet | 0 / 0 / 0 |

첫 실행이 첫 실패에서 멈추는 진단 약점을 발견해, key·URL을 숨긴 채 240개를 끝까지 검사하고
성공/실패 aggregate만 내도록 TDD로 보완했다. 이후 재실행에서 228/12가 확인됐다.

## 안전·재현성 감사

- production DB: SELECT only, write/RPC 0
- R2: `HeadObject` only, mutation/GET 0
- GT 원문, raw clip/camera/reviewer ID, R2 key/URL 출력 0
- frame decode, Python Evidence, Gate, local/cloud model 호출 0
- service/launchd/Vercel/Slack 변경 0
- Mac mini production repo HEAD와 기존 dirty 상태는 실행 전후 동일
- local 전체 테스트: `999 passed, 5 skipped`
- 관련 사건 묶기 테스트: `59 passed`
- 임시 실행 파일 4개의 SHA-256은 local과 Mac mini가 일치했다.

## 판정과 다음 gate

현재 상태는 `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`도,
`READY_FOR_HUMAN_BOUNDARY_GT_V2`도 아니다. ID를 공개하지 않는 별도 SELECT/HEAD-only 감사 결과,
12건은 전부 R2 object 부재를 뜻하는 `404 Not Found`였고 권한·기타 오류는 0이었다. 다음에는
이 결손을 표본에서 제외할 수 있는 media-integrity source 계약과 재실행 정책을 별도 TEST-SHEET에
동결해야 한다. 그 전에는 재선택·대체·cutoff 변경을 하지 않는다.
