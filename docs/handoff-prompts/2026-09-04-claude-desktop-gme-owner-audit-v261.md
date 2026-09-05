# Claude Desktop 작업 지시문 — GME Owner 점검과 YOLO v2.6.1 후보 수집

> 이 문서 전체를 Claude Desktop에 그대로 전달해. Chrome의 기존 로그인 세션을 사용하되 계정·비밀번호·토큰을 읽거나 기록하지 마.

## 1. 목적

Owner 라벨링 웹에서 실제 영상을 처음부터 끝까지 확인해 다음 두 문제를 분리해서 기록해.

1. YOLO v2.6이 게코의 존재와 위치를 제대로 찾는가.
2. 게코 박스는 맞지만 GME의 움직임 시간이 틀리는가.

결과는 YOLO v2.6.1의 학습·검증 후보와 GME 활동량 알고리즘 개선 후보를 구분하는 데 사용한다. Claude의 판단 자체는 정답 라벨이나 학습 GT가 아니다.

## 2. 역할과 권한

Claude의 역할은 `화면 점검자 + 후보 기록자`다.

- Chrome에서 Owner 라벨링 화면을 직접 열고 영상을 재생·탐색할 수 있다.
- GME 박스, 게코 존재 여부, 탐지 끊김, 활동시간 오류를 관찰하고 비공개 원장에 기록할 수 있다.
- 라벨 방법이 명확한 경우 Owner에게 무엇을 확인해야 하는지 설명할 수 있다.
- `Owner 최종 확정`, bbox 정답 저장, 데이터셋 편입, 모델 학습·평가·배포는 수행하지 않는다.
- 라벨링 웹의 제출·제외·GT 보정 버튼은 누르지 않는다. 사용자가 그 자리에서 특정 동작을 명시적으로 지시한 경우에만 해당 한 건을 수행한다.
- Claude의 영상 판정을 행동 GT, 존재 GT, 자동 제외 근거로 사용하지 않는다.

## 3. 시작 전 확인

1. Chrome에서 `https://label.tera-ai.uk`의 기존 Owner 로그인 상태를 확인한다.
2. 비밀번호, 쿠키, 토큰, 사용자 UUID를 출력하거나 문서에 기록하지 않는다.
3. 실제 기록 파일은 다음 비공개 경로만 사용한다.

   `/Users/baek/private-rba/gme-owner-audit-v261/review-ledger.csv`

4. 기록 파일이 이미 있으면 삭제하거나 덮어쓰지 말고 기존 header와 마지막 행을 확인한 뒤 append한다.
5. 원본 영상·스크린샷·clip 식별자를 Git 저장소, Slack, 공개 문서에 복사하지 않는다.

## 4. 영상 한 건의 점검 순서

각 영상마다 아래 순서를 지켜.

1. 영상 길이, GME 모델 표기, 활동시간 요약이 보이는지 확인한다.
2. 재생 전 전체 GME 요약을 기록한다.
3. 영상을 처음부터 끝까지 한 번 재생한다.
4. 이상이 의심되는 구간은 앞뒤로 이동하면서 최소 0.5초 단위로 다시 확인한다.
5. 다음을 서로 독립적으로 판정한다.

   - 실제 게코가 보이는가.
   - GME 박스가 게코를 덮는가.
   - 게코가 없는데 박스가 생기는가.
   - 게코가 계속 보이는데 박스가 끊기는가.
   - 박스는 맞지만 움직임/정지 구간이 실제와 다른가.

6. 이상 구간의 시작·종료 시각을 초 단위로 기록한다. 여러 구간이면 한 구간당 CSV 한 행을 사용한다.
7. 확신할 수 없으면 추측하지 말고 `uncertain`으로 기록한다.

### 원장 행 작성 규칙

- 한 번의 작업에서 `audit_session_id`는 동일한 KST 시작시각 문자열을 사용한다.
- `reviewer_stage`는 항상 `claude_suggested`다.
- `clip_ref`, 카메라 별칭, 원본 페이지 주소는 비공개 원장 안에서만 사용할 수 있다.
- `full_video_reviewed`는 실제로 처음부터 끝까지 확인했을 때만 `true`다.
- `owner_final`은 항상 `pending`으로 남긴다.
- `miss`, `bad_box`, `intermittent`에서 게코가 보이면 `bbox_required=yes`; 그 외는 `no`다.
- 새 후보의 `bbox_status`, `dedup_status`, `protected_split_status`는 각각 `not_started`, `unchecked`, `unchecked`로 시작한다.
- `evidence_ref`에는 필요한 경우에만 비공개 로컬 스크린샷 경로나 Owner 페이지 주소를 기록한다.
- 쉼표나 줄바꿈이 들어간 메모는 올바른 CSV 큰따옴표로 감싸고, 한 관찰 구간은 한 행으로 유지한다.

## 5. 허용 판정값

### `gecko_presence`

- `present`: 사람이 보기에 게코가 분명히 보임
- `absent`: 영상을 확인했지만 게코가 보이지 않음
- `uncertain`: 가림·반사·흐림 때문에 확정 불가

### `gme_box_verdict`

- `correct`: 실제 게코를 실용적으로 덮고 탐지가 유지됨
- `miss`: 게코가 보이는데 박스가 없음
- `false_positive`: 게코가 없는데 박스가 있음
- `bad_box`: 박스가 게코가 아닌 곳을 덮거나 몸에서 크게 벗어남
- `intermittent`: 같은 게코가 보이는 동안 박스가 반복적으로 끊김
- `uncertain`: 육안으로 확정 불가
- `not_applicable`: 게코와 박스가 모두 없음

### `activity_verdict`

- `correct`: 움직임·정지 요약이 육안과 대체로 일치
- `overcount`: 정지 구간을 움직임으로 과하게 계산
- `undercount`: 실제 움직임을 기록하지 않음
- `unverifiable`: 가림·탐지 끊김 등으로 비교 불가
- `not_checked`: 이번 점검에서 활동시간을 확인하지 않음

## 6. bbox 판단 규칙

- 화면에 실제로 보이는 머리와 몸통을 중심으로 판단한다.
- 가려졌거나 화면 밖에 있는 부분을 상상해서 확장하지 않는다.
- 화면 경계에 일부만 보이는 게코는 보이는 부분을 제대로 잡으면 정상으로 볼 수 있다.
- 실제 개체가 여러 마리면 각각 별도 박스가 원칙이다.
- 유리 반사상은 실제 개체 GT와 구분해서 `reflection` 메모를 남긴다. 반사 박스가 활동시간을 오염시키는지도 별도로 기록한다.
- 박스가 몸 전체를 완벽히 감싸지 않아도 머리·몸통을 안정적으로 따라가면 단순히 조금 작다는 이유만으로 오류로 확정하지 않는다.
- 투명 쳇바퀴·급여기·유리 뒤에서 탐지가 사라지는 구간은 반드시 `miss` 또는 `intermittent` 후보로 기록한다.

## 7. 데이터셋 경로 제안 규칙

`dataset_route_suggestion`은 다음 중 하나만 사용한다.

- `none`: GME가 정상이며 새 학습 가치가 없음
- `train_candidate`: 명확한 미탐·오탐·bad box가 있어 Owner bbox 후 학습 후보
- `validation_candidate`: 개선 확인용으로 보존할 가치가 있으며 학습에는 넣지 않을 후보
- `holdout_only`: 학습·튜닝에서 격리하고 미래 성능 확인에만 사용할 후보
- `activity_algorithm_candidate`: 박스는 맞지만 움직임 시간 계산이 틀린 후보
- `owner_review_required`: Claude가 확정할 수 없어 Owner 판단이 먼저 필요한 후보

주의:

- 같은 영상 전체를 곧바로 학습에 넣지 않는다. 오류 전후의 대표 프레임만 후보로 제안한다.
- `train_candidate`도 `owner_final=confirmed`, bbox 검수, SHA/dHash 중복 제거, 기존 train/validation/test 보호 확인 전에는 학습 자료가 아니다.
- 같은 장면의 유사 영상이 여러 개면 전부 학습시키지 말고 일부는 validation 또는 holdout으로 남긴다.
- 박스가 맞고 활동시간만 틀리면 YOLO 학습 후보로 보내지 않는다.

## 8. 기존 5개 영상 우선 점검 기준

먼저 제공된 5개 DB terminal-failure 영상을 확인하게 되면 다음 사전 관찰을 참고하되, 화면에서 독립적으로 다시 확인한다.

- 1·2·5번: 현재 사전 점검에서는 탐지가 대체로 정상으로 보였음
- 3번: 투명 구조물 내부에서 긴 탐지 공백이 관찰됨
- 4번: 같은 유형의 짧은 탐지 공백이 관찰됨

이 사전 관찰을 정답처럼 복사하지 말고, 실제 영상 전체를 본 결과와 불일치하면 그 사실을 기록한다.

## 9. 금지 사항

- 운영 DB/R2 데이터 수정·삭제·재큐잉
- 기존 GME run이나 artifact 삭제·덮어쓰기
- 모델 학습·평가·배포 또는 서비스 재시작
- 원본 영상과 식별자의 외부 업로드
- Claude 판정을 `OWNER_FINAL` 또는 GT로 표시
- GME가 틀렸다는 이유만으로 영상을 라벨링 대상에서 제외
- 활동시간 오류를 무조건 YOLO 오류로 분류

## 10. 사람에게 즉시 알려야 하는 경우

- Owner 로그인이 풀려 있음
- 영상 또는 GME overlay가 열리지 않음
- 같은 영상에서 실제 게코와 반사상을 구분할 수 없음
- 어떤 버튼을 눌러야 할지 확정되지 않음
- 원장 header가 예상과 다르거나 기존 행이 손상된 것으로 보임
- protected validation/test/holdout 영상일 가능성이 있음

## 11. 종료 보고 형식

작업을 마치면 식별자 없이 집계만 보고해.

- 전체 확인 영상 수
- `correct / miss / false_positive / bad_box / intermittent / uncertain` 수
- 활동시간 `correct / overcount / undercount / unverifiable` 수
- `train_candidate / validation_candidate / holdout_only / activity_algorithm_candidate / owner_review_required` 수
- Owner가 다음에 직접 확인해야 할 영상 수와 예상 시간
- 실제 제출·GT 확정·데이터셋 편입·운영 변경이 모두 0건인지
