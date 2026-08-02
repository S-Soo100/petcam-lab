# Local VLM Mac Studio 구매 판단 Gate v1

## 질문

더 비싼 Mac Studio를 사면 RBA 사건 경계 판독이 실제로 좋아지는지, 아니면 같은 실패를 더 빠르게
반복하는지만 **구매 전에** 확인한다. 하드웨어를 추측으로 평가하지 않고, 현재 32GB MacBook에서
실행 가능한 모델 크기 사다리를 같은 입력·같은 채점표로 비교한다.

## 고정 후보

실행 순서는 작고 싼 모델에서 큰 모델 순서로 고정한다.

1. `gemma3:4b-it-q8_0` — 기존 4B의 양자화 손실 가설 확인
2. `gemma4:12b-it-qat` — 중간급 멀티모달 후보
3. `qwen3-vl:8b-instruct-q4_K_M` — 다른 계열 중간급 후보
4. `qwen3-vl:30b-a3b-instruct-q4_K_M` — 큰 모델이 필요한지 확인하는 상한 후보

Ollama는 `0.32.5`, temperature 0, seed `20260802`, retry 0으로 동결한다. 모델 tag와 실제 digest가
다르면 실행하지 않는다.

## 1단계: 합성 능력시험

각 모델은 실제 사람 GT를 보기 전에 개별 이미지 12장을 받는다. 정답을 코드가 정확히 아는 장면으로
어두운 화면, 정지 물체, 이동 물체, 움직이는 그림자, 전체 밝기 전환을 시험한다. 같은 장면을 두 번
실행해 schema, 정답, 반복 일치를 모두 확인한다. 이어 실제 2단계와 같은 `4A+4B` 형식과 boundary
schema로 `연속 이동=same_event`, `위치 점프=different_event` 두 경계를 두 번씩 시험한다. 총
18/18 중 하나라도 실패하면 그 모델은 2단계에 진입하지 않는다.

이 단계의 목적은 프레임 수·prompt·runtime 문제를 동물 행동 성능과 섞지 않는 것이다.

## 2단계: 사람-final development 74경계

1단계 통과 모델만 기존 사람-final development 74경계(same 57/different 17)를 본다. 새 DB 조회나
GT 재구성을 하지 않는다. 선행 baseline의 동결 manifest, 74개 `combined_4x2` JPEG, ledger가
SHA-256으로 고정한 원본 media 78개를 MacBook 비공개 폴더로 복사한다.

pair→원본 media 대응을 추측하지 않는다. 78개 원본에서 frozen fractions로 A/B contact sheet를
다시 만들고, 가능한 조합이 과거 `combined_4x2`의 동결 SHA-256과 **exact 일치하는 경우가 정확히
한 개**일 때만 대응을 인정한다. 74/74가 아니거나 중복 후보가 있으면 실행을 중단한다. 그 대응으로
원본에서 긴 변 768px 이하의 A 4장+B 4장을 새로 추출해 개별 이미지로 보낸다. 따라서 사람 GT와
pair identity는 과거 artifact 그대로 유지하면서 합성·재압축으로 잃었던 시각정보만 복원한다.

채택 후보 조건은 다음을 모두 만족해야 한다.

- schema·완주 `74/74`
- 사람이 `different_event`라고 한 17개를 잘못 합친 수(over-merge) `0`
- 사람이 `same_event`라고 한 57개 중 최소 `29`개 회수
- model digest, input hash, prompt hash 불변

74개는 모델 선택용 development 자료다. 결과를 본 뒤 prompt·sampler·threshold를 바꾸지 않는다.

## 자원·운영 안전

- 실행 위치: 현재 MacBook Pro M5 32GB의 격리 worktree와 `0700/0600` private artifact
- free memory `3% 이하`가 연속 두 번, swap 증가 `2GiB 초과`, Ollama crash/PID drift, timeout
  180초면 해당 모델을 `REJECT_RESOURCE`로 중단한다.
- 32GB에서 큰 모델의 실행 가능성을 관찰하기 위해 이전 16GB canary의 5%/1GiB보다 완화하되,
  OS가 swap thrash에 빠지기 전 중단하도록 3%/2GiB를 고정한다.
- 모델 전환 때 명시적으로 unload한다. 생산 카메라·DB·R2·서비스·LaunchAgent는 사용하지 않는다.
- 사람 GT·ID·원본 파일명은 public report에 출력하지 않는다.

## 구매 판정

모델별 상태는 `PASS / QUALITY_FAIL / SYNTHETIC_GATE_FAIL / RESOURCE_FAIL / TAG_UNAVAILABLE` 중
하나로 끝낸다. 구매 판정 우선순위는 다음과 같다.

| 관찰 | 판정 |
|---|---|
| 12B 이하가 2단계 통과 | `MAC_STUDIO_NOT_REQUIRED_FOR_QUALITY` |
| 4B·12B·8B가 모두 품질/합성 실패로 평가 완료되고 30B만 통과 | `MAC_STUDIO_64GB_PURCHASE_EVIDENCE_PENDING_HOLDOUT` |
| 작은 모델 또는 30B에 resource/tag 미평가가 하나라도 있음 | `INCONCLUSIVE_NEEDS_COMPATIBLE_HARDWARE` |
| 전 모델이 품질 실패 | `NO_MAC_STUDIO_PURCHASE_EVIDENCE` |

어떤 경우에도 이번 실행만으로 구매하거나 production에 연결하지 않는다. 30B만 통과해도 구매 전
빌린/반품 가능한 64GB 장비에서 같은 artifact와 별도 future holdout을 통과해야 한다. 30B가 현재
32GB MacBook에서 통과하더라도 구매 논거는 **상시가동 Mac mini 16GB를 대체할 64GB host가 필요한가**지,
개발용 MacBook에서 실행 자체가 불가능하다는 뜻이 아니다.

## Out of scope

- historical/future holdout 개방
- 모델 미세조정·LoRA·prompt 반복 튜닝
- 자동 사건 병합, 자동 skip, 행동 GT 생성, 사용자 노출
- DB/R2 read·write, production service/plist 변경, Mac Studio 구매
