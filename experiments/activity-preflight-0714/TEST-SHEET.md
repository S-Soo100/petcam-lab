# TEST-SHEET — 활동필터 v0 사람 preflight (activity-preflight-0714)

> 실행 전 고정, 사후 변경 금지 (research-testing.md). 작성 2026-07-14, 사람 blind 판단 **전**.
> 목적: detector four-state 판정을 사람 GT 와 대조해 exclude_absent / exclude_static 스위치를
>       테스트 카메라 A 에서 **켜도 안전한지** 결정. (Claude/VLM proxy 를 GT 로 쓰지 않는다)

## 1. 가설
- **H0**: detector 의 exclude 판정이 사람 판단과 어긋난다 — 특히 사람이 "활동(active)"으로 본 clip 을
  detector 가 exclude_absent 또는 exclude_static 으로 판정한다(= false exclusion, 활동시간을 잘못 깎음).
- **H1**: 사람이 명확히 active 로 판단한 clip 을 detector 가 exclude 로 판정하는 경우가 **0건**이다
  (fail-open 이 지켜져 활동시간을 잘못 깎지 않는다).

## 2. sample list (고정, 재현 가능)
- 카메라 **A** blind 30 clip = detector 후보 exclude_absent 10 + exclude_static 10 + active 10.
- 선정: `select_candidates.py` (motion_score 3등분 라운드로빈 스캔, seed=714 로 순서 shuffle).
- 고정 파일: `answer_key.json`(detector 판정, 숨김) · `review_manifest.csv`(clip_id + 동영상경로, 사람 입력란).
- 동영상: `storage/activity-preflight-0714/clips/<clip_id>.mp4` (gitignore).
- ⚠️ 실제 확보 수가 목표(10/10/10) 미달이면 REPORT 에 명시하고 있는 수로 진행(사후 목표 변경 아님).

## 3. 모델 / 입력 / 정책 버전
- Gate: RF-DETR nano, `runs/gecko_v2/checkpoint_best_ema.pth`, threshold 0.25.
- 입력: 균등 12프레임 (Gate sampler `even-uniform-v1`), schema `gate-evidence-v1`.
- 정책: `ActivityPolicy` version `activity-v0-preflight` (기본 임계값 — 이 preflight 로 검증).
- 사람 판단: **동영상 재생**(QuickTime 등), blind. 라벨 = absent / static / active / unclear.

## 4. 측정 지표
1. **false exclusion 수** (최우선): 사람=active 인데 detector=exclude_absent 또는 exclude_static 인 clip 수.
2. exclude_absent precision: detector=exclude_absent 중 사람=absent 비율.
3. exclude_static precision: detector=exclude_static 중 사람=static 비율.
4. active recall: 사람=active 중 detector=active 비율 (참고용, unknown 은 fail-open 이라 무해).
5. unknown 비율 및 사유 분포 (fail-open 이 과도하지 않은지).
6. 불일치(discordant) clip 의 사유·hard case.

## 5. 합격 기준 (숫자, 스위치별 독립)
지시문 §316 = "명확한 active 가 exclude 로 1건이라도 판정되면 그 스위치 활성화 금지".
- **exclude_absent 스위치 활성화 권장 ⟺** (사람=active → detector=exclude_absent) **0건** AND exclude_absent precision ≥ 0.90.
- **exclude_static 스위치 활성화 권장 ⟺** (사람=active → detector=exclude_static) **0건** AND exclude_static precision ≥ 0.90.
- unclear 는 active 로 간주하지 않되(보수), false exclusion 판정에서 제외하고 hard case 로 기록.

## 6. 예상 비용
- Claude/VLM 호출 0. detector 스캔 최대 160 clip(전기·R2 다운로드만). 사람 판단 시간 30 clip.

## 7. decision 룰
- 두 스위치 각각 §5 충족 → 해당 스위치 Phase 5 활성화 **권장**.
- false exclusion ≥ 1 → 그 스위치 **비활성 유지**, hard case 원인 분석 후 임계값(policy) 재설계.
- precision < 0.90 이지만 false exclusion 0 → 활성화 가능하나 "제외량 적음" 경고(보수적 임계값 조정 후보).
- 결과는 `REPORT.md` (decision: adopt/hold/reject per switch) + `experiments/INDEX.md` 등록.
