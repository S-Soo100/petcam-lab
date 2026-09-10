# YOLO26n v2.7 C500G prospective 사람 GT 데이터셋 준비 설계

> 상태: `DESIGN_REVISED / USER_REVIEW_PENDING / EXECUTION_NOT_STARTED`
>
> 승인일: 2026-08-28 KST
>
> 개정일: 2026-08-29 KST — iTerm Claude 교차검토와 최신 v2.6 Task 10/11 대조 반영
>
> 범위: 조사·설계·계획 준비만. 프레임 추출, 추론, CVAT task 생성, 학습은 아직 실행하지 않는다.

## 1. 결정

YOLO26n v2.7은 C500G 3대가 일주일 동안 촬영하는 9개 사육장 야간 영상을 새 prospective 사람 GT의
주요 원천으로 사용한다. 30분 원본은 불변 보존하고, 사람이 직접 보게 될 단위만 사육장 ROI 기반의
결정론적 가상 스트림으로 만든다. CVAT에는 원본 영상을 통째로 넣지 않고 prediction-free 정지 이미지
task를 제공한다.

전체 source inventory 뒤 v2.6 sealed holdout, v2.7 train, v2.7 validation 역할을 camera-night 단위로
먼저 고정한다. 그 다음 v2.7 train 역할에서만 600개 ROI 판단 파일럿을 뽑아 실제 사육장 경계, 작은
게코의 유효 픽셀 크기, ROI 가장자리 누락, 검수 시간과 빈 화면 비율을 측정한다. 그 결과로 v2.7
학습 표현을 다음 둘 중 하나로 고정한다.

1. 원본 full-frame GT를 발행하고 full-frame 모델을 학습한다.
2. ROI crop GT를 발행하고 C500G 전용 3-tile 추론·원본 좌표 복원 계약을 함께 사용한다.

같은 시점의 crop과 full-frame을 서로 독립적인 학습 예제로 동시에 발행하지 않는다. v2.6은 완전히
freeze되기 전에는 어떤 후보 선택에도 쓰지 않고, freeze 뒤에도 train 역할의 추가 hard-case 순위화에만
쓴다. 첫 사람 검수 화면, development validation, 봉인 holdout에는 예측을 노출하지 않는다.

이 `한 representation` 규칙은 C500G 파생 예제에 적용한다. 기존 replay GT는 원래의 단일 사육장
구도와 train-only 역할을 그대로 보존한다. C500G full-frame을 고르면 replay와 C500G의 bbox pixel-size
분포 및 provenance별 성능을 따로 보고하고 혼합을 허용한 근거를 남긴다.

### 1.1 v2.6 기준선

검증한 v2.6 private manifest는 전체 4,471장, active train+validation 4,167장, 최근 cohort 2,508장이다.
최근 cohort는 positive 1,465장, negative 1,043장, bbox 1,474개다. 그러나 계획된 6개 학습 run은 아직
완료되지 않았으므로 v2.6 candidate나 teacher는 현재 확정되지 않았다.

또한 v2.6 최근 split의 실제 manifest에서는 같은 camera-night가 train과 validation 양쪽에 나타났다.
episode 단위로는 분리됐지만 v2.7이 요구하는 camera-night 독립성에는 부족하므로, v2.7은 더 강한
atomic camera-night split을 새 계약으로 사용한다. 개별 camera/source 식별자는 이 문서에 남기지 않는다.

## 2. 확인된 촬영 원천과 저장 계약

### 2.1 카메라·사육장 구성

- C500G는 3대이며 각 카메라의 전체 화면에 사육장 3개가 함께 잡힌다. 총 9개 사육장이다.
- 로컬 검증용 thumbnail을 직접 확인했고, 모든 카메라 화면이 3개 사육장을 포함하는 것을 확인했다.
- 사육장 폭과 경계는 화면을 단순히 3등분한 형태가 아니다. 카메라별 수동 ROI calibration이 필요하다.
- 현재 원본은 카메라 단위 full frame이며 촬영 단계에서 ROI crop을 만들지 않는다.

### 2.2 30분 원본 계약

- 촬영 시간: 매일 20:00–08:00 KST
- 슬롯: 카메라당 30분 고정 구간 24개/야간
- 완전한 7일 촬영의 기대치: 72개 원본/야간, 504개 원본/주, 756 사육장-hours
- 검증한 로컬 표본은 약 30분 길이, HEVC, 2880×1620이었다. frame rate 등 전체 주간의 실제 media
  parameter는 source inventory에서 manifest와 파일을 다시 대조한다.
- 촬영 주간이 아직 진행 중이므로 504개는 기대치이지 현재 실재 수량이 아니다. 이전 검증 시점에는
  세 저장 계층의 42개 원본이 일치했지만, 현재 최종 수량은 원격 접속 실패로 재확인하지 못했다.

### 2.3 정본 저장 위치

- 로컬 정본: `/Volumes/RAP-C500G/recordings/{camera}/night=YYYY-MM-DD/{segment_start}/`
- 한 슬롯의 정본 artifact: 원본 영상, thumbnail, 정제 로그, manifest
- R2 bucket `c500g`: 로컬 정본과 같은 상대 key 구조
- DB: `rap_c500g_recordings`
- MacBook의 별도 복사본은 검증용 사본이며 정본으로 취급하지 않는다.

원본 영상은 overwrite, 재인코딩, 자동 삭제하지 않는다. ROI, 대표 프레임, CVAT image, 파생 manifest는
원본과 별도의 파생 계층에 만들고 원본 artifact hash와 좌표 변환 버전을 참조한다.

## 3. 왜 30분 영상을 그대로 CVAT에 넣지 않는가

| 방식 | 장점 | 핵심 문제 | 판정 |
|---|---|---|---|
| 30분 원본 영상 전체를 CVAT에 입력 | 시간 맥락을 모두 볼 수 있다 | 검수 frame 수가 사실상 무제한이고 인접 frame 중복·라벨 피로가 커진다 | reject |
| full-frame 대표 frame만 입력 | 원본 배치와 세 사육장 문맥을 보존한다 | 960px 전처리 뒤 개체가 너무 작아질 수 있고 빈 사육장별 판단이 불명확하다 | 파일럿 비교군 |
| ROI 가상 스트림에서 대표 frame·구간·hard-case를 입력 | 한 사육장에 집중하고 검수 단위·비용을 통제할 수 있다 | ROI 경계와 운영 inference가 맞지 않으면 잘림·학습/서빙 불일치가 생긴다 | primary review 방식 |

CVAT는 결정론적으로 추출한 정지 이미지 task만 받는다. 시간 문맥이 필요한 가림·진입·이탈 사례는
인접 대표 frame 묶음이나 짧은 review strip으로 사람에게 보여줄 수 있지만, 라벨은 선택된 canonical
frame에만 기록한다. 원본 30분 영상은 provenance와 재검수 근거로만 보존한다.

## 4. ROI와 학습 표현 결정

### 4.1 ROI 계약

- 카메라별 3개 사육장 ROI를 day/IR 화면에서 각각 보정하고 profile hash와 버전을 고정한다.
- ROI calibration pixel은 v2.7 train 역할 또는 study 이전의 별도 calibration frame에서만 본다.
  sealed holdout과 validation 화면을 열어 ROI·padding을 조정하지 않는다.
- ROI는 단순 3등분이 아니라 실제 유리·벽·프레임 경계를 포함해 수동 정의한다.
- 사람은 익명화된 단일 사육장 crop을 보지만, 라벨 좌표는 원본 full-frame 좌표로 역변환할 수 있어야 한다.
- 같은 원본 timestamp의 세 ROI 판단을 하나의 source group으로 묶는다.
- full-frame 발행 시 세 ROI의 bbox를 원본 좌표로 합치고, 세 ROI가 모두 사람 `absent`일 때만 해당
  full-frame을 negative로 확정한다.
- 형제 ROI 중 하나라도 `uncertain` 또는 `media_error`이면 그 timestamp의 full-frame은 발행하지 않는다.
  ROI branch에서는 사람 판정이 유효한 ROI만 개별 발행할 수 있다.
- positive full-frame 안의 빈 ROI는 별도 negative 이미지가 아니라 full-frame의 background context다.

### 4.2 파일럿 decision rule

정확한 serve 전처리 `imgsz=960`을 재현해 다음을 측정한다.

- 먼저 ROI 경계로 인한 잘림·누락이 2% 이하여야 한다. 넘으면 ROI padding·경계를 재보정하고 파일럿을
  반복한다. 이 오류를 crop 학습 선택의 근거로 쓰지 않는다.
- 유효한 ROI review에서 GT bbox short side의 95% 이상이 full-frame serve 전처리 뒤 16px 이상이면
  full-frame publication을 우선한다.
- pixel 조건을 만족하지 못하면 ROI crop publication과 C500G 3-tile inference·NMS·원본 좌표 복원
  계약을 v2.7의 필수 serving 계약으로 채택한다.
- 16px, 95%, 2%는 사전 engineering acceptance threshold다. 파일럿 결과를 본 뒤 유리하게 바꾸지 않는다.
- 파일럿 600개는 v2.7 train 역할에서 prediction 없이 사전 층화한다. 9개 사육장에 66–67개씩 배분하고,
  시간대·IR/컬러 상태·가림·빈 화면 층을 유지한다. 편의표본으로 threshold를 판정하지 않는다.
- train 역할에서 특정 사육장의 66개를 확보할 수 없으면 다른 사육장으로 조용히 채우지 않고
  enclosure shortage를 보고한다.
- C500G 파생 예제는 한 model experiment 안에서 full-frame 또는 ROI crop 중 하나만 사용한다.
- 3-tile branch를 고르면 본 라벨링 전에 calibration 결과로 padding/overlap, cross-tile NMS, 원본 좌표
  복원 계약과 경계 bbox round-trip 검사를 고정해야 한다. 이 계약이 없으면 본 작업으로 진입하지 않는다.

## 5. 사람이 실제로 겪는 CVAT 흐름

- **[화면]** source 이름과 카메라 식별자가 숨겨진 단일 사육장 야간 이미지가 보인다. 모델 bbox나
  confidence는 없다.
- **[조작]** 라벨러가 `present / absent / uncertain / media_error` 중 하나를 먼저 고른다.
- **[반응]** `present`이면 보이는 모든 게코에 bbox를 그리고 제출한다. 나머지는 이유를 기록하고 다음
  이미지로 이동한다. 시스템은 원본 timestamp, ROI version, 원본 좌표를 뒤에서 연결한다.
- **[감정]** 라벨러는 모델 답을 수정하는 사람이 아니라, 한 사육장을 독립적으로 판정하는 사람이라고
  느껴야 한다.

YOLO 사람 GT는 존재 여부와 bbox만 다룬다. 행동명, 거리, 환경 상태, 건강 판단은 이 task에서 묻지 않는다.
`uncertain`과 `media_error`는 negative로 변환하지 않는다.

CVAT task는 다음 정합성을 강제한다.

- 이미지마다 status 하나가 필수이며 미판정과 `absent`는 서로 다른 상태다.
- `present`는 bbox 1개 이상, `absent`는 bbox 0개여야 한다. 위반 제출은 저장하지 않고 같은 항목으로
  돌려보낸다.
- bbox는 추정한 몸 전체가 아니라 화면에서 실제 보이는 게코 부분을 감싼다. target 사육장 밖의 개체가
  유리 투과·반사로 보이면 label하지 않고 `cross_enclosure_reflection` 또는 `uncertain`으로 보낸다.
- 제출 전에는 뒤로 가기와 수정을 허용한다. 제출 뒤 원본 판정은 append-only로 보존하고 정정은 별도
  재검수 queue에서 새 revision으로 남긴다.
- `uncertain`은 Owner adjudication으로 보내고, double review는 첫 검수와 분리된 blind job으로 배정한다.
- 본 파일럿 전에 20–30장 워밍업을 수행한다. 워밍업 판단과 시간은 600개 파일럿 통계에서 제외한다.

## 6. 샘플링 전략

### 6.1 prediction-independent base

role을 먼저 고정한 뒤 각 enclosure-night 안에서 다음 층을 균형 있게 뽑는다.

- 시간대: 20–22시, 22–02시, 02–05시, 05–08시
- 조명·개체: IR/컬러 상태, IR 전환, 어두운/밝은 개체, 작은 개체, 부분 가림, 정지·수면,
  탈피 중인 개체와 남은 허물, 다개체처럼 보이는 반사·중첩
- 위치: ROI 중앙, 가장자리, 출입·은신처 경계, 상단·하단
- 오탐 구조: 반사, 인접 사육장 개체의 유리 투과·반사, 물방울, mesh, 가지, 잎, 카메라 본체,
  칸막이, 먹이 곤충, 급여·관리 중 사람 손, 질감이 강한 배경
- negative: 사람이 확인한 빈 화면을 최종 unique ROI 판단의 30–40%로 유지한다. full-frame
  이미지 negative는 세 ROI 전부 `absent`인 별도 지표이며 30–40% 목표를 적용하지 않는다.
- 그릇 상태 (dish_present, 슬롯 단위·thumbnail 기준 — 2026-09-10 owner 승인 addendum
  [`2026-09-10-yolo26n-v27-c500g-dish-present-stratum-addendum.md`](2026-09-10-yolo26n-v27-c500g-dish-present-stratum-addendum.md)):
  `dish_visible`(그릇 객체가 보임) / `food_in_dish`(그릇에 먹이가 있음 — 빈 그릇은 false) 두 단계.
  선택 항목으로 그릇의 상/중/하 위치. 태그는 role freeze 뒤 train·validation role 의 thumbnail 에서만
  사람이 붙이고, sealed holdout·future holdout 의 thumbnail 은 열지 않는다.
  하한: train base 에서 9개 사육장 각각에 `dish_visible` 슬롯 유래 ROI 판단이 최소 10% 포함돼야 한다.
  부족하면 모델로 채우지 않고 재층화·shortage 보고 규칙을 그대로 따른다.

연속 frame의 양을 늘리지 않도록 exact SHA, perceptual hash, timestamp 간격을 함께 사용하고
enclosure-night별 상한을 둔다. 특정 사육장이나 한밤의 반복 장면이 전체를 지배하거나 ROI negative가
30% 미만 또는 40% 초과이면 재층화한다. 재층화는 최대 3회이며 이후에도 목표를 못 맞추면 실제 분포와
shortage를 보고하고 중단한다. 모델 결과로 부족분을 채우지 않는다.

### 6.2 hard-case 추가

prediction-independent base가 먼저 사람 GT로 확정된 뒤, frozen v2.6으로 train-pool에서만 다음 후보를
추가할 수 있다.

- 높은 confidence 오탐 후보
- 낮은 confidence 또는 반복 추론 불안정 후보
- 사람 GT와 v2.6 prediction이 불일치하는 후보
- 운영 중 사람이 남긴 미탐·오탐 제보와 연결되는 새 source 후보

hard-case는 CVAT 첫 화면에 prediction을 보여주지 않고 다시 blind 판정한다. 모델 결과 자체를 label로
복사하지 않는다.

### 6.3 사람 QA

- unique ROI 판단의 10%를 독립적인 두 번째 라벨러가 blind 재검수한다.
- base와 teacher hard-case의 double-review 결과를 분리 집계한다.
- presence 상태나 bbox가 충돌한 건은 전부 Owner adjudication을 거친다.
- adjudication 전에는 normalized GT나 dataset manifest를 발행하지 않는다.

## 7. 데이터 역할과 누수 방지

v2.7의 최소 원자 split은 `camera-night`다. 같은 camera-night의 세 ROI, 인접 frame, 파생 crop,
원본 full-frame은 항상 하나의 역할만 가진다. v2.6 최근 데이터에서 사용한 episode split을 그대로
복제하지 않는다.

1. 전체 source inventory를 먼저 만든다.
2. prediction, ROI 파일럿, 대표 frame 선정 전에 각 camera-night의 role을 고정한다.
3. 최신 v2.6 Task 10 계약에 따라 v2.6 freeze 이후 첫 3개 eligible complete camera-night을 sealed
   holdout 후보로 예약한다.
4. 나머지를 v2.7 development train/validation으로 배치한다. 가능하면 같은 촬영일의 세 카메라를
   하나의 date block으로 묶어 train과 validation의 시설·관리 이벤트 공유를 막는다.
5. SHA, perceptual hash, source lineage, camera-night role 중 하나라도 충돌하면 dataset build를 중단한다.

7일이 완전하면 총 21 camera-nights다. v2.6 freeze 시점과 실제 결손에 따라 eligible holdout과 남는
development 수량이 달라지므로 train/validation 숫자는 inventory에서 확정한다. date block 분리가
불가능하면 atomic camera-night는 유지하되 같은 날짜가 train/validation에 공유된 이유와 한계를
development report에 명시한다. validation은 가능한 범위에서 모든 카메라와 시간대를 포함한다.

v2.6 Task 10은 holdout 최소 조건을 `3 complete camera-night, 300 clip, 1,200 frame GT`로 정의하지만,
C500G 정본 source 단위는 30분 원본이다. `clip`이 원본, 결정론적 하위 구간, 또는 review item 중 무엇인지
Owner 승인 addendum으로 고정하고 source-group 누수를 검사하기 전에는 holdout 추출·개봉을 시작하지 않는다.
freeze 이후 3개 complete camera-night을 확보하지 못하면 pre-freeze 밤을 대체 편입하지 않고 v2.6
`HOLDOUT_SHORTAGE`를 기록한다.

v2.6 sealed holdout에 들어간 source는 v2.7 train으로 재사용하지 않는다. 또한 이번 촬영 주간을 v2.7
train과 genuine v2.7 future holdout으로 동시에 주장할 수 없다. v2.7 checkpoint와 threshold를 freeze한 뒤
새로 촬영한 별도 camera-night가 있어야 최종 future holdout이 된다. 그 영상이 없으면
`HOLDOUT_SHORTAGE`를 기록하고 production 성능을 주장하지 않는다.

## 8. v2.6 teacher 사용 경계

### 8.1 사용 가능 시점

다음이 모두 충족된 뒤에만 teacher를 켠다.

- 계획된 6개 run이 모두 끝났다.
- development 기준으로 candidate가 선택됐다.
- checkpoint, 전처리, raw confidence, NMS, 평가 threshold가 immutable manifest로 freeze됐다.
- 기존 fixed-test regression gate를 통과했다.

현재 v2.6은 완료 전이므로 teacher 사용은 금지 상태다.

### 8.2 허용

- 이미 train 역할로 고정된 pool의 FP, FN 의심, 낮은 confidence, seed 불안정 후보 순위화
- prediction-independent 사람 GT와의 불일치 후보 탐색
- 사람의 운영 제보를 새 train 후보와 연결하는 검색 보조

### 8.3 금지

- CVAT 첫 blind pass에 bbox나 confidence 표시
- prediction을 pseudo-label로 복사하거나 `absent`를 자동 확정
- validation, v2.6 holdout, v2.7 future holdout의 선택·채굴·threshold tuning
- 중간 best checkpoint나 단일 seed 결과 사용
- source 영상의 삭제·격리·재인코딩·overwrite 근거로 사용

## 9. 사람 검수량과 예상 시간

### 9.1 파일럿

- 워밍업 20–30개, 통계 제외
- unique ROI 판단 600개
- blind double review 60개
- 판단당 30–45초 가정 시 약 5.5–8.2시간

### 9.2 본 작업 목표

- 새 prospective unique ROI 판단 약 3,000개
- blind double review 약 300개
- 1차+2차 판단 약 27.5–41.2시간
- conflict adjudication 약 3–6시간
- 총 약 31–47시간
- ROI negative 30–40%, `uncertain+media_error` 10% 이하라는 관찰 gate를 만족할 때 positive는 약
  50–70%다. 대부분 ROI당 게코 한 마리라는 가정에서 bbox 약 1,500–2,100개다.

시간과 bbox 수는 파일럿으로 교정할 추정치다. 새 prospective cohort는 최소 3,000 unique ROI 판단을
목표로 하며, 기존 사람 GT를 replay해 v2.6 이전 데이터 전체를 버리는 reset은 하지 않는다.
`uncertain+media_error`가 10%를 넘으면 negative로 치환하지 않고 ROI·교육·media 품질 원인을 먼저 고친다.

## 10. 단계별 산출물과 중단 조건

| 단계 | 산출물 | 다음 단계 진입 조건 |
|---|---|---|
| 0. Source inventory | USB/R2/DB/manifest 대조표, 기대/실제/결손 수량, media parameter 요약 | 세 저장 계층과 hash가 일치 |
| 1. Role freeze·holdout 계약 | train/validation/v2.6 holdout source manifest, v2.6 clip-unit addendum | sampling 전 역할 고정, camera-night와 lineage 충돌 0 |
| 2. ROI calibration | train/pre-study frame 기반 카메라별 3 ROI profile, day/IR 검증, version/hash | holdout pixel 접근 0, 경계가 사람 검수에서 재현 가능 |
| 3. 워밍업·600 ROI 파일럿 | train-only blind GT, 시간, empty 비율, bbox pixel, edge error, representation 판정 | 사전 decision rule 통과, full-frame 또는 tiled 계약 고정 |
| 4. Base 사람 GT | prediction-independent CVAT 결과, double-review queue | ROI empty 30–40%, strata coverage 충족 |
| 5. Teacher hard-case | frozen v2.6 train-only 후보 queue | v2.6 freeze와 fixed-test gate 충족 |
| 6. GT normalize·QA | adjudicated bbox/presence, provenance, 좌표 변환 감사 | unresolved conflict 0 |
| 7. Dataset build | replay+prospective manifest, dedup/leakage report | 모든 role test 통과 |
| 8. 후속 학습·평가 | 별도 실행 계획의 artifact | 이번 설계 범위 밖 |

다음 조건에서는 fail-closed한다.

- USB/R2/DB 수량·hash·manifest가 다르거나 source가 변했다.
- decode 결과가 manifest와 다르다.
- role freeze 전 파일럿·샘플링·prediction이 실행되려 한다.
- v2.6 holdout의 `clip` 단위와 source grouping이 승인된 addendum으로 고정되지 않았다.
- ROI calibration을 위해 validation 또는 sealed holdout pixel을 열려고 한다.
- ROI 경계가 불명확하거나 파일럿 edge crop·miss가 2%를 넘는다. ROI 재보정·파일럿 반복은 최대 3회다.
- v2.6 freeze 전 teacher 결과가 후보 선정에 섞였다.
- 한 source, camera-night, exact/near duplicate가 둘 이상의 role에 들어갔다.
- 사람이 확인한 ROI empty 비율이 30–40% 밖이다. 모델로 채우지 않고 최대 3회 재층화한다.
- `uncertain+media_error`가 10%를 넘는다. negative로 바꾸지 않고 원인을 해결한다.
- `uncertain` 또는 `media_error`를 negative로 바꾸려 한다.
- sibling ROI가 `uncertain/media_error`인데 full-frame을 발행하려 한다.
- double-review conflict가 adjudication되지 않았다.
- v2.7 freeze 뒤 새 future media가 없다. `HOLDOUT_SHORTAGE`로 종료한다.

## 11. 현재 승인 범위와 다음 decision gate

이번 승인은 조사 결과와 데이터 준비 설계를 문서화하는 데까지다. 원본 영상, DB, R2, 서비스, git,
production model, 라벨링 웹은 변경하지 않는다. 프레임 추출, 추론, CVAT task 생성, 학습도 시작하지
않는다.

다음에는 이 개정 설계를 Owner가 검토한 뒤 별도 implementation plan을 작성한다. 실행 승인은 그 plan에서
source inventory의 read-only 명령, 파생 artifact 위치, 파일럿 task 수량, 검증·rollback 없는 불변 원본
경계를 다시 확인한 뒤 받아야 한다.

## 12. 근거 문서

- `docs/decision-gate.md`
- `specs/feature-rba-data-engine-v1.md`
- 최신 v2.6 recent dense retraining design §4.4와 plan Task 10/11
- C500G R2 recording design과 실제 로컬 manifest·thumbnail·30분 media probe
- 2026-08-28 기준 C500G recording 작업의 최근 상태

개별 source 식별자와 비밀값은 이 문서에 기록하지 않는다.
구현 전에는 이 설계와 인용한 v2.6/C500G 정본 문서가 같은 tracked clean commit에서 접근 가능해야 한다.
