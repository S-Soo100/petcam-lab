# 영상 분류 파이프라인 — 학습 노트

> 2026-06-16 작성. petcam-lab이 **영상을 받아 행동 라벨을 내는 방법** + 적응형 프레임 추출 코드 + 정지프레임 VLM의 근본 한계.
> 선수 자료: `cloud-architecture-overview-learning.md`, `stage-c/d-*-learning.md`.
> 다음 기획: **계층 줌인 + ROI crop**(이 노트 §7 → `specs/`로).

---

## 1. 큰 그림 — 영상 1개가 "행동 라벨"이 되기까지

```
📹 카메라(RTSP)
  ▼ ① 움직임 감지 (backend/motion.py)        ← 게코가 움직인 구간만
  ▼ ② 60초 클립 저장 (clip_recorder.py)
  ▼ ③ 인코딩 + 클라우드 업로드 (encoding → R2)
  ▼ ④ VLM 분류 (vlm/worker.py)               ← ⭐ "분류"의 심장
  ▼ ⑤ DB 저장 (behavior_logs: action + confidence)
```

- **① motion** = 직전↔현재 프레임 픽셀 차이(`cv2.absdiff`) → 변한 픽셀 1% 넘으면 "움직임". 야행성+저활동이라 통째 분석은 낭비, 움직인 구간만 → `moving` ~31% 스킵. (JS: `git diff`로 바뀐 줄 세기)
- **②③** 트리거 구간 60초 mp4 → ffmpeg ~44% 압축 → Cloudflare R2(S3 호환).
- **④** 아래 §2/§4가 핵심.
- **⑤** `frame_idx=0` = 클립당 라벨 1개.

## 2. ⭐ "현재 기준"의 진실 — 코드 ≠ 실제로 쓰는 것

코드의 production 경로(`vlm/worker.py`, Gemini)는 **셧다운**이다 (2026-06-12 Gemini 퇴역 → Claude 피벗). `DEFAULT_PROMPT_VERSION="v3.5"`는 production 워커용인데 **실사용 0** — 그래서 최신 v4.0인데도 코드 디폴트를 안 바꿈(DEFAULT 승격 = production 재가동 시점 사안). **현재 유효한 분류 방법은 코드 디폴트가 아니라 "연구 기준":**

| | 과거 production (셧다운) | **현재 유효 기준** |
|---|---|---|
| 입력 | 영상 통째로(`classify_clip(video_bytes)`) | **적응형 frames@1080** |
| 모델 | Gemini 2.5 Flash | **Claude Sonnet 4.6 / Opus 4.8** |
| 프롬프트 | v3.5 (9-class) | **v4.0 (7-class)** |
| 실행 | 자동 폴링 워커 | Workflow blind 서브에이전트 |
| 정확도 | (구 floor 85.5%, 무효) | **Sonnet 85.5% / Opus 88.7%** |

**왜 영상직접 → 프레임?** Claude API는 **영상 입력 인터페이스가 없다**(이미지만). Gemini는 영상 bytes를 통째로 받았음(그래서 과거 production이 영상 직접). Claude로 피벗하며 프레임 추출이 강제됐고, 마침 **개별 프레임이 몽타주보다 +21%p 정확**(입력 표현이 1순위 레버)이라 손해도 아니었음.

## 3. 7개 클래스 (v4.0)
`moving` · `shedding` · `hand_feeding` · `eating_prey` · `eating_paste` · `drinking` · `unseen`
(`defecating`·`basking`·`hiding`은 폐기 — 모션 트리거에 안 잡히거나 잔류물로 대체)

## 4. 적응형 프레임 추출 — 코드 레벨 (`scripts/_extract_frames_clip.py`)

**`_adaptive_n` — 몇 장 뽑을지:**
```python
def _adaptive_n(dur, interval, lo, hi):
    return max(lo, min(hi, round(dur / interval)))   # = clamp
```
- `clamp` = **"값을 lo~hi 범위에 가두기"** (게임 체력바 `Math.max(0, Math.min(maxHp, hp))`와 동일 관용구).
- if문으로 풀면: `n=round(dur/3.5)` → `n=min(20,n)`(상한) → `n=max(6,n)`(하한).
- 실측 데모: **15.6초 → round(4.46)=4 → clamp → 6장** (하한 발동). 120초 → 34 → **20장** (상한 발동).
- 왜: 짧아도 최소 6장(정보 보장), 길어도 최대 20장(토큰 폭발 방지).

**`extract_adaptive` — 어디서 뽑을지:**
```python
for i in range(n):
    t = (i + 0.5) * dur / n            # ⭐ 구간 중앙
    ffmpeg -ss {t} -i video -frames:v 1 -q:v 3 → f_001.jpg
```
- 영상을 n칸으로 자르고 **각 칸 한가운데**(`+0.5`)를 찍음.
- `+0.5` 없으면 두 문제: ① 첫 장이 t=0(행동 전 빈 프레임) ② 마지막 칸 통째 손실. 중앙을 찍으면 둘 다 회피 + 균등.
- `ffmpeg -ss {t}` = t초로 seek(점프) 후 1프레임. 고정N의 fps 필터는 위치를 못 찍어서 t=0/뒷부분 손실 결함이 있었음 → 적응형이 대체.

**`_enforce_no_upscale` — 해상도 정책:** 긴 변 >1080이면 다운스케일(`INTER_AREA`), 이하면 **원본 유지**(업스케일 X — 가짜 보간 픽셀이 VLM 교란 + 토큰 낭비).

**`--shuffle SEED`:** blind 평가용. GT가 정렬돼 있으면 모델이 패턴을 읽으므로 순서 셔플.

## 5. ⭐ 핵심 한계 — 정지프레임 VLM의 천장

**두 개의 독립 축 (직교):**
- **시간 밀도** = 몇 초마다 1장 (interval) — 빠른 동작 포착
- **공간 해상도** = 프레임당 px (1080) — 작은 대상 포착

**빠른 혀(drinking)·작은 먹이(prey)를 왜 못 잡나:**
1. **시간 밀도**: 3.5초 간격 vs 혀 날름 0.2초 → 프레임 사이로 빠짐 (영화로 총알 안 보이는 undersampling). **프레임률 올려도 안 풀림** — P2 실험(모션 키프레임) recovered 1/11, 결론 "병목은 시간밀도가 아니라 공간해상도".
2. **공간 해상도**: 혀가 몇 px, 물방울 안 보임. 1080에서도 한계 (근본 = ROI crop).
3. **정지프레임이라 시간축 사건 자체가 안 담김** — "혀가 들락날락"하는 *움직임*은 정지 이미지에 없음.

→ 입력(두 축)·프롬프트·모델 **네 레버를 다 당겨도** drinking/prey는 안 풀림. **C/D2 정량 확인**(2026-06-16): Sonnet→Opus 모델 교체로도 drinking 20%·prey 22%만 회수 = **모델불변 시각한계**. (drinking은 quality-sensitive=화질에 일부 반응하나 @1080서 천장 / prey는 quality-invariant=화질 올려도 안 됨)

## 6. 시도된 입력 트릭 + 평가

| 시도 | 푸는 축 | 막히는 지점 |
|---|---|---|
| 몽타주 셀↓ (2~4장) | 공간해상도(부분) | 셀 1개=개별 프레임이 종착지 → 이미 표준 (M0 12변형 hold) |
| 계층 줌인(의심 구간 촘촘히) | 시간 밀도 | 공간해상도 그대로 + 1차 detection 닭-달걀 (P2 1/11) |
| **계층 줌인 + ROI crop** | **둘 다** ✅ | 입/혀 자동 검출이 어려움 (YOLO, OWLv2 47.5% 교훈) |
| 영상 네이티브 | 시간축 연속성 | Gemini 퇴역 (미래 모델 대기) |

**교훈: 정지프레임 안에서 프레임을 재배치하는 트릭(시간 재샘플링·몽타주)은 결국 "공간 해상도 천장"에 다 막힌다.** 진짜 두 길 = (a) ROI crop으로 공간 확대 (b) 영상 네이티브로 시간축.

## 7. 다음 기획 — 계층 줌인 + ROI crop (미답 레버)

```
1차: 적응형 frames@1080으로 "여기 미세동작/drinking 의심" 후보 구간 검출
2차: 그 구간 + 입·혀 영역만 crop해서 확대 + 촘촘히 재샘플
     → 시간밀도↑ AND 공간해상도↑  (두 축 동시 공략)
```
- §5/§6이 가리키는 "근본 = ROI crop"의 구체화. 정지프레임 패러다임의 천장을 넘는 유일한 frame-side 레버.
- **걸림돌:** 입/혀 영역 자동 검출(YOLO custom — 작은 게코 부위 검출 난이도, OWLv2 47.5% 검출실패 교훈) → 비-VLM(YOLO evidence layer) 트랙.
- **닭-달걀 회피:** 1차 트리거를 VLM의 "drinking 의심"이 아니라 **motion 신호**(미세 반복 움직임)로 잡으면 1차 detection 약점 우회 가능 — 단 P2에서 global motion이 미세행동 못 잡은 전례 있어 ROI-local motion으로 좁혀야.
- → 다음 세션에서 spec 기획 + PoC 테스트.
