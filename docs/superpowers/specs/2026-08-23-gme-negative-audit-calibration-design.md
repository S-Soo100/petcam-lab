# GME negative audit 캘리브레이션 설계

> GME가 게코를 탐지하지 못했다고 기록한 운영 영상을 사람에게 blind로 다시 보여, 존재 미탐을 측정하고 다음 detector hard-case 후보를 안전하게 만든다.

**상태:** 설계 작성 완료·Owner 문서 검토 대기
**작성:** 2026-08-23
**연관 SOT:** `docs/superpowers/specs/2026-08-03-gecko-motion-engine-v1-design.md`, `/Users/baek/tera-ai-product-master/docs/sot.md`

## 1. 배경과 문제

현재 운영 라벨링은 GME가 게코를 탐지한 eligible 영상을 우선 처리한다. 이 흐름은 탐지된 영상의 행동 GT를 만드는 데 적합하지만, GME가 게코를 놓친 영상은 사람 눈에 거의 도달하지 않아 존재 미탐을 구조적으로 발견하기 어렵다.

과거 `exclude_absent`는 실제 active 영상을 놓친 근거로 reject됐다. 이번 작업은 그 자동 제외를 되살리지 않는다. 반대로 GME-negative 표본을 사람이 확인해 놓친 게코를 찾고, 모델 개선 전까지 모든 원본·eligible 상태를 그대로 보존한다.

이 설계의 `negative`는 **최신 고정 detector/GME run이 `detected=false`로 기록한 영상**만 뜻한다. GME run 없음, 처리 실패, 해시·원본 불일치는 별도의 `unavailable` 품질 버킷이며 negative 성능 표본으로 간주하지 않는다.

## 2. 연구 질문

1. post-checkpoint 운영 GME-negative 영상 가운데 실제 게코가 보이는 비율은 얼마인가?
2. 어떤 camera/morph/IR/occlusion 조건에서 존재 미탐이 집중되는가?
3. 사람 검수에서 확정된 존재 미탐과 대표 bbox를 다음 detector hard-case 후보로 안전하게 보존할 수 있는가?

초기 캘리브레이션은 **게코 존재 미탐**만 다룬다. 게코를 찾았지만 `moving`을 `static`으로 판단한 활동 미탐과 초 단위 활동시간 오차는 후속 사람 시간구간 GT 연구로 분리한다.

## 3. Decision Gate

| 게이트 | 판정 | 근거 |
|---|---|---|
| SOT 부합 | ✓ | GME v1의 사람 bbox/mask hard-case 보존, strata 평가, future holdout 전 사용자 지표 미승격 계약과 직접 정합한다. |
| 기대효과 | ✓ | 존재 미탐 발견, negative pool 오염도 측정, detector recall 개선용 사람 확인 후보를 만든다. |
| 측정가능 | ✓ | TEST-SHEET, frozen manifest, 층화 무작위 negative와 blind positive control, 사전 정의 지표로 판정한다. |
| 유효한 계획 | ✓ | 기존 라벨링 웹 task type 재사용, append-only provenance, 자동 제외·학습 편입·배포 금지를 명시한다. |

**판정:** `adopt_with_preregistered_calibration`. TEST-SHEET와 표본 manifest가 동결되기 전에는 사람 평가를 시작하지 않는다.

## 4. 범위

### In

- 기존 라벨링 웹 안에 별도 `GME 점검` 메뉴와 presence-audit task type을 추가한다.
- 로그인한 승인 라벨러가 배정된 영상을 blind로 검수한다. Owner가 주 검수자일 수 있다.
- 최초 캘리브레이션은 item당 1회의 1차 판정만 요구하며, 이중 독립검수를 기본값으로 강제하지 않는다.
- 최초 캘리브레이션은 층화 무작위 GME-negative와 사람 확인 positive control을 섞는다.
- verdict는 `gecko_present`, `gecko_absent`, `uncertain`, `media_error` 네 값으로 고정한다.
- `gecko_present`는 대표 timestamp와 normalized bbox 한 개를 필수로 받는다. control 여부를 숨기기 위해 모든 present verdict에 같은 UI 계약을 적용한다.
- batch, frozen item, submission, correction/adjudication provenance를 append-only로 저장한다.
- 사람 확인 미탐은 dedup·leakage·Owner membership 승인을 거친 뒤에만 별도 Dataset 후보가 될 수 있다.

### Out

- GME-negative 영상 전량검수
- `moving/static/not_visible/unknown/camera_motion` 시간구간 GT
- detector recall/FNR을 negative 표본 하나만으로 주장하는 것
- 미탐 발견 즉시 production 판정, queue eligibility, 사용자 활동시간을 변경하는 것
- 자동 학습 편입, 자동 checkpoint 교체, 자동 배포
- 기존 validation/internal test/Owner external/future holdout 개방 또는 재사용
- 공개 인터넷 접근, 비승인 사용자 접근

## 5. 사용자 체험

```text
[화면] 라벨링 웹 메뉴에 `GME 점검`이 보인다.
→ [조작] 라벨러가 오늘 배정된 점검 영상을 연다.
→ [반응] 영상만 재생되고 GME 판단·점수·표본 stratum은 보이지 않는다.
→ [조작] `게코 있음 / 없음 / 판단 어려움 / 영상 오류` 중 하나를 고른다.
→ [반응] `게코 있음`이면 대표 장면에서 bbox 한 개를 그리는 단계가 열린다.
→ [조작] 저장한다.
→ [반응] `저장 완료`와 남은 개수만 보이고 다음 영상으로 이동한다.
→ [감정] 모델 답을 맞히는 시험이 아니라 실제 영상을 짧고 반복 가능하게 확인한다고 느낀다.
```

상대 판정, GME-negative/control 여부, detector confidence, GME activity/state, VLM 결과, Dataset membership은 제출 전후 라벨러 화면에 노출하지 않는다.

## 6. 선택한 구조와 대안

### 선택: 기존 라벨링 웹 + 별도 task type

사용자에게는 별도 메뉴로 보이지만 인증, media URL, 키보드 조작, 진행률, 오류 처리는 기존 라벨링 인프라를 재사용한다. 행동 교차검수와 DB provenance는 섞지 않는다.

### 기각한 대안

1. **완전히 별도 웹/DB 시스템:** blind media·권한·재시도 코드를 중복시키므로 과잉이다.
2. **GME-negative 전량 공개 큐:** Owner 시간 비용이 크고 표본 편향을 제어하지 못한다.
3. **UI 없는 오프라인 CSV 감사:** 대표 bbox, immutable submission, access audit가 약해진다.
4. **GME-negative임을 화면에 표시:** 게코가 있어야 한다는 탐색 편향을 높인다.

## 7. 최초 캘리브레이션 표본

정확한 수량과 seed는 read-only availability preflight 후 TEST-SHEET에서 동결한다. 설계 기본값은 다음과 같다.

- **random negative 120:** checkpoint 학습 cutoff 이후의 정상·재생 가능 production-purpose 영상 중 latest pinned GME run이 `detected=false`인 표본
- **positive control 30:** 사람 GT로 게코 존재가 확정됐고 이번 모델 평가·future holdout에 속하지 않는 표본
- **총 150:** UI에서는 순서를 결정론적으로 섞고 stratum을 숨긴다.

random negative는 clip 단순 무작위가 아니라 camera-night와 episode를 먼저 층화한다. 연속 clip이 한 환경을 과대표집하지 않도록 동일 episode cap을 TEST-SHEET에 고정한다. camera/night별 표본이 부족하면 임의 대체하지 않고 shortage를 보고하고 표본 정의를 실행 전에 다시 승인받는다.

다음은 initial random population에서 제외한다.

- detector/GME checkpoint 학습에 사용된 exact·near-duplicate media
- 기존 validation/internal test/Owner external/future holdout
- source missing, decode failure, media deleted, research quarantine
- GME run 없음·실패·lineage 불일치

오류 가능성이 높은 `suspicious` hard-case 마이닝은 캘리브레이션과 분리한다. 이 표본은 Dataset 후보 발굴에는 쓸 수 있지만 전체 비율·정확도·카메라 비교의 분모로 사용하지 않는다.

## 8. 측정 지표와 해석 경계

### 캘리브레이션 정본 지표

- `negative_pool_gecko_prevalence = random_negative에서 gecko_present / valid random_negative`
- positive-control 발견률
- `uncertain` 비율
- `media_error` 비율
- camera/night strata별 descriptive count
- 사람 확인 present 중 valid bbox 비율

`negative_pool_gecko_prevalence`는 “GME가 negative라고 한 영상 중 실제 게코가 보이는 비율”이다. 이것만으로 detector recall이나 FNR을 주장하지 않는다. recall은 같은 기간의 representative positive/negative 전체 분모와 sampling weight가 추가로 있을 때만 별도 계산한다.

positive control은 라벨러 주의력과 UI 계약 검증용이며 GME negative 지표의 분자·분모와 Dataset 신규 기여 수에서 제외한다.

최초 batch의 기본 검수자는 Owner다. 다른 승인 라벨러가 참여한 경우 `gecko_present`, `uncertain`, `media_error`는 REPORT 동결 전에 Owner가 별도 adjudication row로 확인한다. `gecko_absent`는 1차 판정을 그대로 사용하되 단일 검수의 한계를 REPORT에 명시한다. Owner가 직접 1차 판정한 item은 별도 중복 판정을 요구하지 않으며, Dataset membership 승인은 audit verdict와 독립된 후속 결정으로 유지한다.

정확한 adopt/hold/reject 수치, confidence interval 방식, shortage 규칙은 결과를 보기 전에 TEST-SHEET에 고정한다.

## 9. 데이터·provenance 계약

최소 논리 단위는 세 가지다.

1. **Batch:** TEST-SHEET SHA, seed, cutoff, sampling contract, source manifest SHA, detector/GME/checkpoint/schema version, counts
2. **Frozen item:** batch, clip identity, stratum, GME snapshot identity, source/media hash, deterministic order, assignment
3. **Submission:** reviewer, verdict, timestamp, bbox, created_at, optional supersedes reference

Batch와 item은 평가 시작 전에 동결한다. submission은 append-only이며 UPDATE/DELETE/TRUNCATE를 허용하지 않는다. 사람 실수 정정은 원본을 보존한 correction row로만 추가한다. Owner adjudication과 Dataset membership은 audit submission과 다른 append-only 원장으로 분리한다.

표본 생성 뒤 media·GME snapshot·manifest hash가 달라지면 해당 item을 `invalid_input`으로 제외하고 같은 batch 안에서 교체하지 않는다.

## 10. 권한·블라인드 계약

- anon과 일반 authenticated는 audit table/RPC 직접 접근이 없다.
- 승인 라벨러는 자기 frozen assignment의 공개 allowlist와 제출 RPC만 사용한다.
- Owner는 batch 상태, aggregate, correction/adjudication을 볼 수 있다.
- service-role API가 scope와 identity를 검증한다.
- 공개 item에는 stratum, GME 결과·버전, control 여부, 다른 제출, source key, raw hash가 없다.
- signed media URL은 기존 만료·scope 계약을 재사용한다.
- 로그에는 사용자 식별자, source key, bbox 원문, model raw result를 쓰지 않는다.

“누구나 접근”은 제품 인터넷 공개가 아니라 **라벨링 웹에 로그인한 승인 사용자 누구나 배정받을 수 있음**을 뜻한다.

## 11. 결과의 사용 경계

```text
사람이 GME-negative에서 gecko_present 제출
→ Owner 확인
→ bbox/media hash 검증
→ 기존 데이터·holdout과 exact/near-duplicate 감사
→ development Dataset 후보 원장
→ 별도 승인된 detector 재학습
→ validation + sealed future holdout
→ 채택 또는 보류
```

audit 결과는 기존 GME run, queue eligibility, 행동 GT, 활동시간, VLM prediction, 하이라이트를 덮어쓰지 않는다. 새 checkpoint도 동일 protocol과 future holdout을 통과하기 전에는 shadow 밖으로 승격하지 않는다.

## 12. 오류 처리

- media decode 실패: `media_error`, 지표에서 분리, 자동 대체 금지
- 사람이 판단하기 어려움: `uncertain`, absent로 합치지 않음
- GME lineage/hash mismatch: 평가 시작 전 fail closed
- 중복·holdout leakage: batch 생성 중 fail closed
- positive control 여부가 라벨러 UI/API 공개 응답에 노출됨: batch 전체 중단
- 부분 batch: 완료율과 shortage를 그대로 보고하고 임의 보충 금지
- 동시 제출: 최초 immutable submission만 인정하고 중복은 안정 오류로 거부

## 13. 단계별 실행

1. read-only availability·leakage preflight
2. TEST-SHEET와 exact sampling contract 작성·Owner 승인
3. frozen batch/manifest 생성
4. Preview에서 권한·blind·bbox·mobile/desktop UX canary
5. 별도 승인 후 production 캘리브레이션 batch 생성
6. 사람 검수
7. deterministic scorer + REPORT + decision label
8. 결과에 따라 상시 random quota와 suspicious mining 채널을 별도로 설계

## 14. 완료 조건

- [ ] TEST-SHEET가 표본 생성·사람 평가 전에 동결됨
- [ ] random negative/control exact count와 manifest SHA가 고정됨
- [ ] protected holdout·train leakage·episode 중복이 0임
- [ ] 라벨러 공개 응답에서 GME/control/source 내부 필드 노출이 0임
- [ ] 네 verdict와 present bbox 계약이 Preview에서 검증됨
- [ ] submission/correction이 append-only이고 기존 GT·queue·GME row를 수정하지 않음
- [ ] deterministic report가 negative-pool 지표와 control 지표를 분리함
- [ ] Dataset 편입·재학습·production 적용이 별도 승인 경계로 유지됨

## 15. 교차검토 반영

iTerm Claude Fable 5/high의 read-only 교차검토에서 별도 감사 채널 필요성에는 동의했지만, 다음을 Critical로 지적했다.

- presence 미탐과 activity 미탐 정의 분리
- suspicious 표본으로 전체 미탐률을 주장하지 않기
- 의사결정 전 TEST-SHEET 동결

또한 blind positive control, GME/checkpoint snapshot, `unknown` 분리, frozen manifest를 Important로 제안했다. 이 설계는 모두 반영했고, negative 표본 하나로 FNR/recall을 주장하지 않는 통계적 해석 경계를 추가했다.

## 16. 참고

- [GME v1 설계](2026-08-03-gecko-motion-engine-v1-design.md)
- [GME 활동량 라벨링·VLM 활용 설계](2026-08-22-gme-detected-human-labeling-activity-use-design.md)
- [연구 테스트 프로토콜](../../../.claude/rules/research-testing.md)
- [Decision Gate](../../../docs/decision-gate.md)
