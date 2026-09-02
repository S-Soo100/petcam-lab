# RBA Python Prescan + OpenAI VLM v1 — 3클립 기술 Smoke 시험지

> 동결일: 2026-08-03 KST
>
> 상태: `EXECUTED_SMOKE_PASS` — 동결 계약 변경 없이 2026-08-03 KST 실행

## 목적

정식 316개 성적 시험 전에 Mac mini에서 다음 기술 계약만 확인한다.

1. Python이 영상 native frame을 끝까지 순차 디코딩한다.
2. 전체 영상을 4fps 시간순 개별 JPEG로 만들고 frame을 누락하지 않는다.
3. 6초 window와 1초 overlap으로 OpenAI Responses API에 전달한다.
4. 구조화 행동·구간·최대 게코 수 결과와 usage·비용 원장을 남긴다.
5. 키·사람 GT·행동명 파일명·R2 key를 API 입력과 로그에 노출하지 않는다.

이 smoke는 행동 정확도 시험이 아니다. 결과를 사람 GT와 비교하거나 prompt 선택에 쓰지 않는다.

## 동결 입력

- 기존 `dataset-203` 로컬 원본 중 실제 파일이 있는 영상에서 media SHA-256 정렬로 3개를 고른다.
- smoke manifest에는 `clip_ref`, private local path, media SHA-256만 둔다.
- 기존 manifest의 `gt`, prediction, 파일명 행동 표기는 OpenAI 입력에 넣지 않는다.
- 세 영상은 Mac mini private runtime root로 복사하고 전송 전후 SHA-256이 같아야 한다.

## Python 계약

- 원본 fps가 30 이하이면 모든 decoded frame을 분석한다.
- 30fps 초과이면 모든 frame을 decode하되 분석은 최대 30fps다.
- decode count, fps, duration, brightness, IR transition, motion envelope, dense interval을 저장한다.
- 이번 smoke의 VLM은 Arm A이므로 dense interval을 API 입력 증가에 사용하지 않는다.
- summary는 16KiB 이하, frame sidecar는 gzip JSONL이다.

## OpenAI 계약

- API: Responses API
- SDK: 실행 시 `uv.lock`에 고정된 OpenAI Python SDK
- model: `gpt-5.6-terra`
- reasoning: `low`
- image detail: `original`
- input: 전체 4fps 시간순 개별 JPEG
- window: 6초, overlap 1초
- output: Pydantic strict structured output
- retry: SDK transient retry 최대 2회
- run budget: 최대 `$5.00`
- Platform 월 한도: Owner가 `$50`으로 설정, runner는 키나 결제정보를 읽지 않는다.
- `original`은 2026-08-03 공식 vision 문서와 설치 SDK 2.52.0의 허용 enum에서 확인했다.
- 실제 token 비용은 response 뒤에 확정되므로 앱 상한은 마지막 요청 1회분만큼 넘을 수 있다. 월 `$50` Platform 한도가 최종 차단선이다.
- 첫 window 실패 시 해당 window와 실행하지 않은 나머지 window를 각각 명시적 실패 row로 기록하고 clip을 `incomplete`로 닫는다. provider 오류 원문은 저장하지 않는다.

모델·vision·structured output·가격 근거:

- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/structured-outputs

2026-08-03 확인 가격은 `gpt-5.6-terra` input `$2.50/1M tokens`, output `$15.00/1M tokens`다.
runner의 smoke 비용은 API usage의 input/output token으로 보수적으로 계산한다.

## 성공 Gate

- [x] Mac mini hostname과 repo HEAD를 기록한다.
- [x] 정확히 3개 media SHA가 전송 전후 일치한다.
- [x] Python decode 실패 0, summary·sidecar 3/3다.
- [x] planned VLM frame와 actual frame이 3/3 exact match다.
- [x] 모든 planned window가 response 또는 명시적 실패 상태를 가진다.
- [x] structured output 성공 clip 3/3다.
- [x] usage·request id·추정 비용 ledger가 존재한다.
- [x] 총 추정 비용이 `$5.00` 미만이다.
- [x] 키·GT·개인정보·R2 key 노출 0이다.
- [x] DB/R2/GT/service/production 사용자 결과 write 0이다.

하나라도 실패하면 `SMOKE_FAIL`이며 63개 development 호출은 시작하지 않는다.

## 이번 smoke에서 하지 않는 일

- Gate detector 실행 또는 `absent` 판정
- Python dense interval의 20fps VLM 추가 입력
- Arm B/C 비교
- 행동 정확도·highlight 정확도 주장
- 316 dataset materialize
- production launchd 등록
- 자동 skip·자동 GT·사건 묶기·사용자 알림
