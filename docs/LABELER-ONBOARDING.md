# petcam 라벨러 가입·튜토리얼·본작업 안내

> 운영 상태(2026-07-14): 가입·승인·날짜 선택과 대화형 튜토리얼이 production에 배포됐다.
> `tutorial-v1`은 owner 기준 영상 5개로 seed·활성화됐고, 운영 화면에서 0/5 시작 상태와
> 팀원 진행 화면을 확인했다. 승인 대기 0명·활동 중 라벨러 2명이며 둘 다 0/5다. 두 명 중
> 1명을 pilot으로 먼저 진행시켜 5/5 완료→본 큐 진입을 확인한 뒤 나머지 팀원에게 확대한다.

## 현재 배포 단계

- 가입 링크 공유: 가능
- 활동 중 라벨러 2명 중 지정한 1명 tutorial pilot: 진행 가능
- 전체 팀 본작업 개방: pilot 5/5와 본 큐 진입 확인 후
- 튜토리얼 정답 5개: production GT와 분리되며 모델 평가용 holdout에서 제외

## 팀원에게 전달할 안내

1. `https://label.tera-ai.uk/labeling/signup`에서 이름·이메일·6자 이상 비밀번호로 가입한다.
2. `관리자 승인 대기 중` 화면이 나오면 가입한 이름과 이메일을 관리자에게 알린다.
3. 승인 안내를 받으면 `상태 새로고침`을 누른다.
4. 일반 큐에 들어가기 전에 `튜토리얼`에서 지정된 공통 영상 5개를 완료한다.
5. 각 영상은 `AI를 보기 전 사람 판정 → AI 판정 비교 → 기준 답·차이·해설 확인` 순서로 진행한다.
6. 다른 팀원과 답을 상의하지 않고 영상에서 실제로 확인되는 사실만 기록한다.
7. 5개 해설을 모두 확인하면 관리자가 전달한 날짜를 큐에서 선택해 본작업을 시작한다.
8. 첫 본작업 5개를 완료한 뒤 더 진행하지 말고 관리자에게 알려 기준을 한 번 확인한다.

pilot 중 문제는 `lesson 번호 · 누른 버튼 · 화면 캡처 · 이해하기 어려운 문구`를 함께 보낸다.
완료 보고에는 `튜토리얼 5/5 · 일반 큐 진입 여부`를 반드시 포함한다.

튜토리얼에는 합격 점수가 없다. 목적은 일반 이동, wheel/object interaction, 탈피,
판단 불가, 행동 구간과 VLM 오류 검수 기준을 실제 영상으로 익히는 것이다.

## 관리자 운영 순서

1. 가입 신청자의 이름·이메일을 확인하고 `/labeling/team`에서 승인한다.
2. 팀원이 tutorial 0/5→5/5를 완료하는지 확인한다.
3. mismatch dimension을 보고 필요한 기준만 짧게 교정한다.
4. 날짜를 구두로 배정한다. 별도 assignment 테이블은 사용하지 않는다.
5. 첫 production 5개를 확인한 뒤 날짜별 본작업 지속 여부를 결정한다.
6. 썸네일·영상·저장 오류는 날짜, clip ID, 화면 캡처, 오류 문구를 함께 받는다.

## 라벨링 핵심 기준

- `moving`: 사물과 명확한 직접·반복 상호작용이 없는 이동·등반·자세 변경
- `wheel_interaction`: wheel을 직접 ride/push/rotate하는 evidence가 확인됨
- `object_interaction`: 사물을 직접 밀기·타기·추적·반복 접근하는 evidence가 확인됨
- `playing`: 사람이 직접 선택하는 GT가 아니라 확인된 interaction evidence에서 제품용으로 파생
- `shedding`: 허물이 실제로 벗겨지는 장면. 의심만 되면 낮은 confidence/판단 불가
- `unseen`: 게코가 안 보일 때만 사용

빠르다는 이유만으로 playing으로 분류하지 않는다. 애매한 장면을 억지로 확정하지 않고
`uncertain / unjudgeable`을 사용한다. 최초 GT를 잠그기 전에는 VLM 답을 보지 않는다.

## 파일럿의 유효 범위

공통 5개는 UI와 라벨 기준을 배우는 calibration이다. 라벨러 간 신뢰도, 행동별 정확도,
VLM 개선을 통계적으로 증명하지 않는다. 본작업 확대 전 후속 공통 blind 30개의
일치도 계약을 별도로 확정한다.

상세 설계:

- [라벨러 가입·승인·날짜 선택](superpowers/specs/2026-07-13-labeler-signup-date-controls-design.md)
- [대화형 튜토리얼](superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md)
- [쉬운 말·입력 복구와 조건부 tutorial-v2 계획](superpowers/specs/2026-07-14-labeling-tutorial-plain-language-v2-design.md)
