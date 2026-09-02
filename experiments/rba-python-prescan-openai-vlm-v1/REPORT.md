# RBA Python Prescan + OpenAI VLM v1 — 3클립 Smoke 보고서

> 실행일: 2026-08-03 KST
>
> 상태: `SMOKE_PASS`

## 결론

Mac mini one-shot 기술시험은 통과했다. Python은 영상 3개의 native frame을 끝까지
디코딩했고, OpenAI `gpt-5.6-terra`는 27/27 window에 구조화 응답을 반환했다.
프로덕션 DB·R2·GT·service write는 하지 않았다.

다만 3클립 추정 비용이 `$3.24742`라 같은 분포의 63클립 development는 단순
환산 약 `$68.20`이다. Owner가 설정한 월 `$50` 한도를 넘으므로 63클립 실행은
자동으로 열지 않는다. 이 smoke는 기술 경로가 작동한다는 증거이지 비용 채택
판정은 아니다.

## 실행 provenance

- host: `baeg-endeuui-Macmini.local`
- source repo HEAD: `f2cfbb84185ca05221cfb45b3212d1209277080f`
- Python/OpenAI SDK: project `uv` 환경 / `openai 2.52.0`
- OpenCV: `4.13.0`
- model: `gpt-5.6-terra`, reasoning `low`, image detail `original`
- 실행 시 동결 TEST-SHEET SHA-256: `2ecaa0bd67d5a1439c6636d9a4d69c0b1c9ac2c74d4474186cb4f77443f8a6f4`
- smoke manifest SHA-256: `8194998238c260f52ee4b4e59beae840a5bafe84bd12b10185230a718e09a628`
- 실행 code bundle SHA-256: `8482e7b372db433ffa4a1bbdab76ec0ae65f5139862040560d5286b713b9b998`

## 실측

| clip | 길이 | source fps | decoded/analyzed | VLM frame | window | 비용 |
|---|---:|---:|---:|---:|---:|---:|
| A | 59.98초 | 17.09 | 1,025 / 1,025 | 240 | 12/12 | `$1.4982850` |
| B | 12.75초 | 59.76 | 762 / 381 | 51 | 3/3 | `$0.2636125` |
| C | 59.98초 | 17.09 | 1,025 / 1,025 | 240 | 12/12 | `$1.4855225` |

- 실행시간: `239.02초`
- API request: `27 성공 / 0 실패`
- input tokens: `1,235,884`
- output tokens: `10,514`
- response id 존재: `27/27`
- 총 추정 비용: `$3.24742` (`$5.00` one-shot 상한 안)
- Python decode invalid reason: `0`
- planned/actual VLM frame: `3/3 exact match`

60fps에 가까운 B는 모든 762 frame을 디코딩하고 30fps 상한에 맞춰 381 frame을
Python 분석했다. A와 C는 source fps가 30 이하라 decoded frame 전부를 분석했다.

## 안전성 감사

- media 전송 SHA-256: `3/3 일치`
- window ledger: `27 complete / 0 failed`
- key 원문 artifact 포함: `0`
- GT·human label key ledger 포함: `0`
- group/world-readable private file: `0`
- smoke launchd/service 등록: `0`
- remote repo HEAD: 실행 전후 동일
- remote repo 기존 dirty entry: 실행 전후 `9`로 동일
- DB/R2/GT/production 사용자 결과 write: `0`

첫 실행은 API 키 앞에 6글자 설명 문구가 붙어 있어 HTTP 요청 전
`UnicodeEncodeError`로 종료됐다. API 성공 호출과 비용은 0이었다. 실제
`sk-proj-...` 후보가 하나뿐이고 local/remote 값이 같음을 확인한 뒤 설명 문구만
제거했고, 새 runtime에서 재실행했다. 키 값은 로그·보고서에 출력하지 않았다.

## 다음 판정

- 기술 경로: `PASS`
- 63클립 development 자동 실행: `HOLD_COST_CAP`
- 정식 316 성적시험: dataset manifest 완성 전 `NOT_READY`
- 다음 결정: 월 `$50` 안에서 프레임 표현/해상도 비용을 줄이는 별도 동결 시험을
  설계하거나, 63클립 예산을 별도로 승인받아야 한다.
