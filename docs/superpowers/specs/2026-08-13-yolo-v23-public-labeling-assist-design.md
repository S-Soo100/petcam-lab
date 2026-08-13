# YOLO Dataset v2.3 공개 라벨링 보조 설계

**상태:** `DEPLOYED_VERIFIED_LABELING_ASSIST_ONLY`

## 1. 목적

보호 Preview에서 검증한 Dataset v2.3 `warm-start` worker를 기존 라벨링 웹
`https://label.tera-ai.uk/gecko-detector`의 접속자가 Vercel 로그인 없이 사용할 수 있게 한다.
공개되는 것은 사용자가 직접 업로드한 사진·영상의 후보 bbox 보조 기능뿐이며, production 자동분류나
GT 생성 기능으로 승격하지 않는다.

이 설계는
[`2026-08-13-yolo-v23-labeling-assist-worker-design.md`](./2026-08-13-yolo-v23-labeling-assist-worker-design.md)의
검증된 worker·모델·rollback 계약을 재사용한다. 기존 문서의 `production inference 503` 경계는 이 설계가
정한 전용 assist route와 명시적 production flag에 한해서만 좁게 대체한다. 그 밖의 production 경로는
계속 fail-closed다.

## 2. 사용자 체험

`[화면]` 사용자가 라벨링 웹의 게코 찾기 페이지를 열면 로그인 화면 대신 업로드 영역과
`development-only 라벨링 보조`, `박스가 없어도 게코가 없다는 뜻은 아니야` 경고를 본다.

→ `[조작]` 사용자가 지원되는 이미지 또는 짧은 영상을 선택하거나 drop한다.

→ `[반응]` 서버가 인증된 v2.3 worker에 일시적으로 전달하고, 모델 버전·threshold `0.25`·후보 bbox를
표시한다. 업로드 원본과 prediction은 이 기능에서 DB/R2에 저장하지 않는다.

→ `[조작]` 사용자는 박스를 보이거나 숨기며 후보와 원본을 비교한다. 이 연구 페이지 자체는 bbox 편집이나
GT 제출 기능을 제공하지 않으며, 사용자의 최종 판단을 대신하지 않는다.

→ `[반응]` AI prediction은 GT로 숨겨 저장되지 않으며, detection 0개면
`후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.`를 표시한다.

→ `[감정]` 사용자는 로그인 마찰 없이 보조 기능을 쓰되, 결과가 정답이나 부재 판정이 아님을 계속
확인한다.

## 3. 방식 비교와 선택

### A. 기존 Vercel 프로젝트의 Preview 보호 해제

구현은 빠르지만 같은 프로젝트의 다른 Preview와 과거 deployment URL까지 공개될 수 있다. 공개 범위가
요청보다 넓고 rollback 경계도 프로젝트 단위라 제외한다.

### B. 보호 Preview의 shareable link 배포

Vercel 로그인은 피할 수 있지만 URL에 접근용 비밀 query parameter가 붙는다. 고정된 라벨링 웹 URL을
접속자가 바로 쓰는 요구와 맞지 않아 제외한다.

### C. 기존 라벨링 웹 production의 전용 assist route 활성화 — 채택

기존 공개 URL과 사용자 동선을 유지한다. `YOLO_LABELING_ASSIST_ENABLED=true`라는 별도 명시적 flag가
있을 때만 production의 `/api/yolo-demo/infer`가 worker provider를 선택하게 한다. Preview의
`YOLO_PREVIEW_ENABLED`와 분리해 각 환경을 독립적으로 끄고 되돌릴 수 있게 한다.

여기서 `production`은 Vercel 배포 환경을 뜻할 뿐, 모델을 production 자동판정에 채택한다는 뜻이 아니다.

## 4. 시스템·보안 경계

```text
public browser
  -> label.tera-ai.uk/gecko-detector
  -> same-origin POST /api/yolo-demo/infer
  -> server-only YOLO_WORKER_URL + YOLO_WORKER_TOKEN
  -> authenticated yolo-v23-preview.tera-ai.uk
  -> versioned candidate bbox response
  -> human review (no GT persistence in this page)
```

- worker URL과 bearer token은 Vercel server environment에만 둔다. HTML, client bundle, response, log에
  노출하지 않는다.
- production provider는 `VERCEL_ENV=production`, `YOLO_LABELING_ASSIST_ENABLED=true`, worker URL/token이
  모두 있을 때만 선택한다. 하나라도 빠지거나 URL validation이 실패하면 fake provider의 503으로 닫힌다.
- 기존 Preview provider 선택은 그대로 유지한다.
- production 요청은 `@vercel/firewall`의 분산 rate limit을 반드시 통과한다. rate-limit ID는
  `yolo-labeling-assist-ip`, 기준은 IP별 10분당 5회 fixed window로 고정한다. SDK 또는 WAF rule이
  준비되지 않거나 확인에 실패하면 503으로 닫는다.
- worker의 process-global limiter(10분당 30회)와 concurrency 1을 2차 방어로 유지한다. 파일
  형식·크기·decode·frame 제한과 no-store 응답도 유지한다.
- 사용자 업로드와 prediction은 이 route에서 DB/R2에 쓰지 않고 worker temporary file은 처리 후 삭제한다.
- GT 자동확정, 빈 이미지/게코 부재 판정, GME routing, R2 A/B 분류, 삭제, VLM skip, 행동명, 사건 묶기에
  연결하지 않는다.
- recall `0.588888...`이므로 0 detection을 부재로 표현하거나 downstream 판정에 전달하지 않는다.

## 5. 구성과 rollback

Production 환경에만 다음을 설정한다.

- `YOLO_LABELING_ASSIST_ENABLED=true`
- `YOLO_WORKER_URL=<server-only v2.3 hostname>`
- `YOLO_WORKER_TOKEN=<server-only secret>`

Vercel Firewall에는 production 요청을 위한 `@vercel/firewall` rule
`yolo-labeling-assist-ip`를 먼저 publish한다. 현재 공식 요금은 허용 요청 100만 건당 `$0.50`이며, 차단된
요청은 worker까지 도달하지 않는다. 이 구성은 Supabase·R2 schema/data를 변경하지 않는다.

정상 rollback은 `YOLO_LABELING_ASSIST_ENABLED`를 제거하거나 `false`로 바꾸고 직전 검증 commit을
재배포하는 것이다. 그 결과 production infer는 worker를 호출하지 않고 503으로 돌아가야 한다. v2.3 worker,
immutable release와 기존 v2.1 rollback worker는 수정하거나 삭제하지 않는다.

긴급 rollback은 Vercel의 직전 production deployment로 되돌린 뒤 production endpoint 503과 worker request
count 불변을 확인한다. DB/R2 rollback은 필요하지 않아야 하며, 필요해지는 변경은 이 설계 범위 밖이다.

## 6. 구현과 테스트 계약

1. TDD로 production enable flag와 분산 limiter의 fail-closed matrix를 추가한다.
   - flag 없음/false: worker env가 있어도 503, worker 호출 0
   - flag true지만 URL/token 누락 또는 invalid: 503, worker 호출 0
   - flag true + 유효 URL/token이지만 WAF check 실패/미구성: 503, worker 호출 0
   - flag true + 유효 URL/token + WAF 허용: worker 응답 전달
   - WAF 제한 초과: 429, worker 호출 0
   - 기존 Preview와 test/development 동작 회귀 없음
2. page도 같은 환경 판정 함수를 사용해 provider와 UI 상태가 어긋나지 않게 한다.
3. public copy는 실제 model version/threshold를 응답 뒤 표시하고 0 detection 경고를 유지한다.
4. 전체 Python/Web 테스트, typecheck, Vercel build와 독립 코드 검수를 통과한다.
5. 새 production deployment 전에 보호 Preview canary를 다시 확인한다.
6. production에서 동일 IP의 제한 초과 요청이 429이고 worker request count를 늘리지 않는지 먼저 확인한다.
7. production에서 이미지·영상·0-detection canary, model version, threshold, health full SHA, 브라우저
   console error 0, worker temp residue 0을 확인한다.
8. rollback canary로 flag-off deployment의 503/worker 호출 0을 확인한 뒤 공개 deployment로 복귀한다.
9. production 자동분류·GT·DB/R2·GME·R2/VLM 경로가 호출되지 않았음을 negative canary로 확인한다.

## 7. 완료 조건

- `https://label.tera-ai.uk/gecko-detector`가 Vercel 로그인 없이 열린다.
- 공개 접속자가 이미지와 영상을 업로드해
  `yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018`, threshold `0.25`, 후보 bbox를 확인한다.
- 0 detection UI가 게코 부재가 아니라고 명시한다.
- worker health의 전체 SHA-256이
  `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`와 일치한다.
- secret/path leak 0, DB/R2 write 0, GT/자동판정 경로 호출 0이다.
- Vercel WAF의 IP별 5회/10분 제한과 worker의 process-global 제한이 실제로 동작한다.
- flag-off rollback과 공개 재전환이 모두 실제 canary를 통과한다.

위 증거가 모두 있을 때만 `DEPLOYED_VERIFIED_LABELING_ASSIST_ONLY`로 보고한다. Dataset v2.3의 production
자동분류 채택이나 게코 부재 판정으로 표현하지 않는다.

## 8. 2026-08-13 배포 증거

- 배포 소스 commit은 `85f40613ecf2e785c7012d8c6288c62bfdba256a`다. 독립 검수에서 처음 발견한
  worker origin/identity 결속과 UI/provider config drift를 TDD로 보완한 뒤 actionable defect 0을
  재확인했다.
- fresh 검증은 Python `1266 passed, 5 skipped`, Web `1043 passed`(122 files), TypeScript typecheck
  exit 0, Vercel production build exit 0이다. 기존 `npm audit`의 high 3건은 이 작업 전부터 있던 별도
  dependency 이슈로 자동 수정하지 않았다.
- Vercel Firewall active rule은 `yolo-labeling-assist-ip`, IP별 fixed window 600초/5회, action 429다.
  기능 canary 뒤 동일 공인 IP에서 malformed POST를 보내 400 뒤 429를 확인했고 worker infer log count는
  14→14로 유지됐다.
- flag-off 선행 배포 `dpl_MbiK6d62qSYNveN2ncv7jxiiji9F`에서 page 200/infer 503을 확인했다. 공개 기능
  canary 배포 `dpl_G625Vm7UEuojiZKh8uwTFC24cAi6`에서 로그인 없는 page 200을 확인했다.
- 고정 development sample canary는 image 200/1 bbox, video 200/138 frames였고 둘 다 model version
  `yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018`, threshold `0.25`,
  `development_only=true`, `usage_scope=labeling_bbox_assist_only`를 반환했다. 영상의 detection 0개는
  부재로 판정하지 않았고 공개 UI의 직접 확인 경고를 검증했다.
- Chrome 공개 사용자 흐름에서 Vercel 로그인 없이 업로드 선택→처리 완료→bbox overlay→모델
  버전/threshold/후보 경고 표시를 확인했다. worker temporary residue는 0이었다.
- authenticated worker health는 `status=ok`, device `mps`, checkpoint SHA-256
  `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`, threshold `0.25`,
  development-only/scope identity가 모두 일치했다. 기존 v2.1 worker와 immutable v2.3 release는
  변경하지 않았다.
- 실제 rollback 배포 `dpl_Hzu5Bqpz8FnUW485dUx3DEMfNgAo`에서 flag=false/infer 503/worker infer log
  14→14를 확인했다. flag=true로 복귀한 최종 production deployment는
  `dpl_FtC5Up5MANYieALZyqysagvmgC3Y`이고 page 200, assist warning 활성, rate-limit window의 429를
  확인했다.
- `/api/yolo-demo/infer` 경로는 DB/R2 client를 호출하지 않고 업로드를 temporary file로만 처리한다.
  이번 배포에서 Supabase/R2 schema/data mutation, GT 자동확정, 부재 판정, GME/R2/VLM routing 변경은
  없었다. token·local model path·raw media는 source/client/문서/Slack에 기록하지 않았다.
- Slack 완료 공유: https://teraaihq.slack.com/archives/C0B66NLM8R1/p1786608559235079
