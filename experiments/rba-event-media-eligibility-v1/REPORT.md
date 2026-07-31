# RBA 사건 묶기 Media Eligibility v1 실행 보고서

**판정:** `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`
**실행일:** 2026-07-31
**실행 호스트:** `baeg-endeuui-Macmini.local`
**코드 기준:** branch `codex/rba-event-media-eligibility-v1`, base HEAD
`540a8b5501d79eb51f3cd6d5e05b2ba6d1d192e4` 위 미커밋 검증 diff

## 결론

기존 fixed historical source만으로 media eligibility를 먼저 동결한 뒤 exact 120 사건 경계 표본을
준비했다. 새 영상 대기는 필요하지 않았다. R2 LIST에서 실제 객체가 확인되지 않은 source는
행동 label과 무관한 `diagnostic_integrity`로 제외했고, 선택된 240 clip은 최종 HEAD `240/240`을
통과했다. 이 결과는 사람 사건 경계 GT용 private worksheet 준비 완료이며, 사건 묶기 품질 채택이나
local VLM 실행 승인은 아니다.

## 실행 결과

| 항목 | 결과 |
|---|---:|
| cutoff 이전 fixed DB inventory 대상 | 19,279 |
| R2 LIST | 37 pages |
| media available | 17,702 |
| object absent 또는 size 0 | 1,577 |
| missing DB key / duplicate DB key | 0 / 0 |
| 선택된 12 camera-night의 source / accounting | 5,034 / 5,034 |
| 선택 | exact 120 pairs |
| split | development 60 / holdout 60 |
| gap bin | split마다 `<=30 / 30–60 / 60–300s` 각 20 |
| camera-night | development 6 / holdout 6 |
| camera 수 | development 3 / holdout 2 |
| camera cap / split-bin camera cap 최대 | 36 / 14 |
| unique clip / reuse | 240 / 0 |
| final R2 HEAD | 240 / 240 |
| DB write/RPC | 0 / 0 |
| R2 GET/write/delete | 0 / 0 / 0 |
| model/frame/service 변경 | 0 |

inventory SHA-256는
`2ee36f89c62e17d19a31e8df2ee10035e9c1a0e1e9ada6a1daef1535759fc17e`, 최종 pair manifest
SHA-256는 `905518428b2809b1e23612df2e0da38fe41cc23e2632138af757bc0e37b14a8f`다.

## 독립 감사

- pair/source manifest hash를 canonical JSON 공식으로 각각 재계산해 일치했다.
- source와 pair manifest의 media inventory provenance가 일치했다.
- exact 120, split 60/60, bin 20/20/20, 12 camera-nights, unique clip 240, reuse 0,
  camera cap 36, split-bin camera cap 14를 artifact에서 다시 계산했다.
- private output directory는 `0700`, 파일 8개는 모두 `0600`이다.
- 실행 직전 short-clip retention plist는 파일로 존재했지만 launchd에는 loaded되지 않았다.
  service를 pause·kickstart하지 않았다.
- Mac mini production repo HEAD는 실행 전후
  `befa56e594adbe1da913b447fac745bb26c6ec61`로 같고, 기존 dirty 목록도 변하지 않았다.

private artifact 위치:
`/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-event-media-eligibility-v1-20260731T124018Z`

raw clip/camera/reviewer ID, R2 key/URL/ETag, GT 원문은 이 보고서에 기록하지 않았다.

## 해석과 다음 gate

이전 shadow v2의 `228/240` 실패는 영상 총량 부족이 아니라 DB 참조와 R2 실객체의 drift였다.
이번 방식으로 그 blocker는 해소됐다. 다만 R2에 남은 영상만 대상으로 했으므로 availability bias가
있다. 이 표본으로 production 자연 분포를 주장하면 안 된다.

다음 단계는 reviewer prior exposure를 확인하고 사람 채널 계약을 별도로 동결하는 것이다. 그 전에는
worksheet를 배정하지 않고 `READY_FOR_HUMAN_BOUNDARY_GT_V2`도 선언하지 않는다. 사람 경계 GT가
끝난 뒤에야 over-merge/split과 사건 묶기 품질을 채점한다. local VLM baseline과 all-event shadow는
그 다음 별도 gate다.
