# Stage B — 움직임 감지 + 세그먼트 태그

> Stage A 의 상시 녹화에 "움직임 있었나" 판정을 얹어, 각 1분 세그먼트에 `_motion` / `_idle` 태그를 붙인다. 파일 구조는 그대로, 이벤트 기반 별도 폴더 분리는 Stage D 로 미룸.

**상태:** ✅ 완료 (2026-04-20)
**작성:** 2026-04-20
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` (Stage B 항목)

## 1. 목적

- **사용자 가치**: 도마뱀이 움직인 세그먼트만 골라볼 수 있게 → "오늘 밥 먹었나, 탈피 시작했나" 빠르게 확인. Stage C (조회 API), Stage D (이벤트 폴더 분리/자동 삭제) 의 재료 제공.
- **학습 목표**: OpenCV 픽셀 차분(`cv2.absdiff`), 그레이스케일/가우시안 블러 전처리, 임계값 튜닝, pytest 로 결정적(deterministic) 알고리즘 단위 테스트.
- **부가**: Stage A 에서 미해결된 **47초(현재 58초) 재생 시간 이슈** 를 "워커 시작 시 10초 FPS 실측 → VideoWriter 동적 설정" 으로 근본 해결.

## 2. 스코프

### In (이번 스펙에서 한다)
- `backend/motion.py` — 프레임 쌍을 받아 "움직임 있음/없음" 판정하는 `MotionDetector` 클래스
- `backend/capture.py` 수정 — 각 프레임에 motion 판정 → 세그먼트 단위로 "움직임 N초 이상이면 motion" 집계
- 세그먼트 파일명 suffix: `211147_motion.mp4` / `211147_idle.mp4`
- `GET /streams/{camera_id}/status` 에 새 필드 2개:
  - `last_motion_ts` — 가장 최근 움직임 감지 시각 (epoch 초)
  - `motion_segments_today` — 오늘 저장된 `_motion` 세그먼트 수
- **FPS 자동 보정**: 워커 시작 직후 10초간 실측 → 측정값으로 `VideoWriter` 개설 (Stage A 의 `CAPTURE_FPS=12.0` 상수 제거)
- pytest 추가: fake numpy 프레임으로 감지 TP/TN 2개 최소
- README 업데이트: motion 태그 의미 + 민감도 환경변수 설명

### Out (이번 스펙에서 **안 한다**)
- 움직임 세그먼트를 `events/` 등 **별도 폴더로 분리/이동** → Stage D (D안으로 진화하는 시점)
- 움직임 없는 세그먼트 **자동 삭제** → Stage C~D
- 움직임 이벤트 **DB 저장** (SQLite/Supabase) → Stage C
- **푸시 알림** (앱/이메일) → Stage D 이후
- **ROI (관심 영역)** 설정 — 화면 전체 감지만 → 나중
- **민감도 조절 UI** — `.env` 로 튜닝만 → 나중
- **멀티 카메라 motion 동시 처리** — 단일 워커 전제 → Stage C/D

### 경계 사유
- Stage B 는 **"움직임 신호를 데이터로 기록"** 까지가 책임. 그걸 활용한 저장 정책·알림·UI 는 다음 스테이지 몫. 한 번에 하면 감지 임계값 튜닝과 저장 로직 변경이 엉켜서 디버깅 어려움.

## 3. 완료 조건

체크리스트가 곧 진행 상태.

- [x] `backend/motion.py` — `MotionDetector` 클래스 (`update(frame) -> bool` 인터페이스)
- [x] pytest: fake numpy 프레임 (정적 N장 / 움직임 N장) 으로 TP / TN 검증 최소 2개 (6개 작성)
- [x] `backend/capture.py` — `_capture_loop` 안에서 매 프레임 motion 판정 → 세그먼트 내 movement_frames 카운트
- [x] 세그먼트 완료 시 파일명 rename: `_motion.mp4` / `_idle.mp4` suffix
- [x] 워커 시작 시 10초 FPS 실측 → `VideoWriter` 에 그 값 주입 (하드코딩 상수 제거)
- [x] 실 카메라로 2분 이상 녹화 → 손을 흔든 구간은 `_motion`, 가만히 있던 구간은 `_idle` 태그 수동 검증 (`225350_motion.mp4` 생성 확인)
- [x] `GET /streams/{camera_id}/status` 응답에 `last_motion_ts`, `motion_segments_today` 필드 등장 + `curl` 검증
- [x] 녹화된 `_motion` 세그먼트 재생 시간 **60초 ± 2초** (실측 59.986s, CFR 보정으로 안정화)
- [x] README 업데이트: motion 태그 설명 + `MOTION_SENSITIVITY` 등 신규 환경변수 표 갱신

### 스펙 밖 추가 구현 (같은 세션에서 발견·해결)
- [x] **CFR(Constant Frame Rate) 보정** — FPS 실측만으로는 해결 못 하던 재생 시간 편차(21~64초) 근본 해결. 매 프레임 `expected = elapsed × fps` 계산 → 부족분 패딩, 초과분 드롭.
- [x] **코덱 교체 (mp4v → avc1/H264)** — 용량 10MB/분 → 2~5MB/분 (약 60~70% 감소). 폴백 체인으로 OpenCV 빌드 차이 대응.
- [x] **깨진 세그먼트 자동 삭제** — 경과시간 < 5초 또는 파일크기 < 50KB 면 unlink. 0초 영상 방지.
- [x] 디버깅 필드 3종: `codec`, `last_changed_ratio`, `segment_motion_frames` — 튜닝·장애 진단용.

## 4. 설계 메모

### 선택한 방법 (초안)

- **전체 접근법**: **(B) 상시 녹화 + 태그** 채택. Stage A 의 1분 세그먼트 로직 유지. 파일 위치 그대로 (`storage/clips/{YYYY-MM-DD}/{camera_id}/`), 파일명에 `_motion` / `_idle` 접미사만 추가.
- **감지 알고리즘**: `cv2.absdiff` + 임계값 (간단·빠름). 도마뱀 사육장은 조명 고정이라 MOG2 같은 배경 차분 알고리즘 불필요. UVB 타이머 on/off 순간의 false positive 는 Stage C 이후 튜닝.
- **전처리**: 그레이스케일 변환 + 가우시안 블러 (노이즈 억제). 고정 해상도 입력이라 다운샘플 불필요 (720p 기준 CPU 여유).
- **판정 단위**:
  - **프레임 단위**: `absdiff` 후 threshold → 변한 픽셀 비율(%) 계산 → 임계 이상이면 "motion frame"
  - **세그먼트 단위**: 60초 세그먼트 내 motion frame 수가 `min_motion_frames` 이상이면 `_motion` 태그
- **FPS 자동 보정**: 워커 시작 시 warmup 10초 → 실제 수신 프레임 수 / 경과시간 = effective fps → 그 값으로 `VideoWriter` 개설. Stage A 의 `CAPTURE_FPS=12.0` 하드코딩 제거. `scripts/measure_fps.py` 의 측정 로직을 `backend/capture.py` 에 축약 복사.

### 고려했던 대안 (왜 안 골랐는지)

- **(A) 이벤트 트리거만 녹화**: 움직임 감지된 순간부터 녹화 시작. 디스크 극한 절약이지만 **움직임 직전 맥락 실종** — 도마뱀의 "멈췄다가 움직이는" 행동 패턴 관찰에 치명적.
- **(C) 링 버퍼 + 이벤트 클립**: 메모리 10초 버퍼 유지 → 감지 시 버퍼+이후 30초를 한 클립으로. 코드 복잡도 대비 (B) 보다 이득 적음.
- **(D) 세그먼트 + events/ 복사**: (B) + 움직임 세그먼트만 `events/` 복사 + `clips/` 자동 삭제. 이상적이지만 Stage B 스코프 과대. (B) 안착 후 Stage D 에서 자연스럽게 진화.
- **MOG2 배경 차분**: 조명 변화에 강하지만 사육장 조명 고정이라 오버스펙. `absdiff` 로 충분.

### 기존 구조와의 관계

- `backend/capture.py` 의 `_capture_loop` **안**에 motion 판정 한 줄 추가 + 세그먼트 단위 카운터. 전체 구조 안 바꿈.
- `CaptureState` dataclass 에 `last_motion_ts`, `motion_segments_today` 필드 추가.
- `_open_new_segment` 는 세그먼트 **시작 시점** 에 파일명 결정하는데, motion/idle 판정은 **종료 시점** 에 나옴 → 파일을 임시명으로 열고 종료 시 rename 하는 식. 또는 모든 파일 `.mp4.tmp` 로 열고 닫을 때 최종명 확정.

### 확정 파라미터 (2026-04-20 대화 결정)

| 환경변수 | 값 | 의미 / 근거 |
|---------|----|-----------|
| `MOTION_PIXEL_THRESHOLD` | **25** | `cv2.absdiff` 후 픽셀 밝기 차이 임계 (0~255). 낮은 센서 노이즈는 버리고 실제 장면 변화만 남김. OpenCV 튜토리얼 권장값 대역. |
| `MOTION_PIXEL_RATIO` | **1.0 %** | 전체 픽셀 중 변한 비율 임계. 도마뱀이 화면 5~10% 차지 → 일부만 움직여도 1% 근처. 야행성 IR 영상 노이즈 감안해 하단(0.5%)보다 보수적으로. |
| `MOTION_MIN_DURATION_FRAMES` | **12** (≈ 1초) | 노이즈 필터. N프레임 연속 motion 이어야 유효 run 으로 인정. 짧은 스파이크(1~2 프레임) 제거. |
| `MOTION_SEGMENT_THRESHOLD_SEC` | **3.0 초** | 1분 세그먼트 내 유효 motion 누적 시간. 3초 이상 → `_motion`, 미만 → `_idle`. 도마뱀 유의미 행동(혀날름 ×3, 보행 1회, 한 입 먹기) 최소 단위. |

오탐 많으면 `MOTION_PIXEL_RATIO` 를 1.5로, 놓침 많으면 0.7로 조정. Stage C 이후 주/야 모드 분리 계획.

### 리스크 / 미해결 질문

- **조명 변화 대응** — UVB 타이머 on/off 순간 전체 프레임 변동 → 일시적 false positive. Stage C 이후 "급격한 전체 밝기 변화 필터" 로 보완. (사용자 승인: 지금은 수용)
- **파일 rename 타이밍** — `VideoWriter.release()` 와 `os.rename()` 사이 크래시 시 `.tmp` 파일 남음. 서버 재기동 시 정리 루틴 필요? → 일단 무시, Stage D 에서.
- **첫 세그먼트 50초 한정** — FPS 자동 측정을 위해 시작 직후 10초는 VideoWriter 없이 프레임만 버림 → 첫 파일 길이가 짧아짐. 수용.

## 5. 학습 노트

### 개념 1 — 측정(measurement)과 실행(execution)의 간극

FPS 실측 후 그 값으로 `VideoWriter` 를 열었는데도 재생 시간이 38~64초로 요동. 수치로 파고드니 **측정 구간은 `cap.read()` 만 돌려서 과평가되는데, 본 루프는 `read + write + motion.update()` 라 실제 처리 FPS 가 더 낮다**는 구조적 불일치가 있었다. 벤치마크는 "실제 부하와 같은 조건" 이어야 한다는 걸 몸으로 배움.

### 개념 2 — CFR(Constant Frame Rate)의 본질

`cv2.VideoWriter` 는 파일 메타에 "초당 N 프레임" 한 개만 기록. 실시간 수신이 그보다 빠르면 파일이 길어지고, 느리면 짧아진다. **재생 시간 = 저장된 프레임 수 ÷ 선언된 fps** 공식이 머리에 박힘. 해결: 매 프레임 "지금까지 있었어야 할 이상적 프레임 수" 를 계산해 부족하면 직전 프레임 복제(패딩), 넘치면 드롭. 네트워크 jitter 가 있어도 재생 시간은 실시간과 일치.

### 개념 3 — 코덱(컨테이너가 아니라 인코딩)

`.mp4` 는 컨테이너, 안에 든 비디오 스트림은 별도 코덱. `mp4v`(MPEG-4 Part 2, 1999) 와 `avc1`(H.264, 2003) 은 같은 `.mp4` 파일에 들어가지만 압축 효율이 30~50% 차이. Tapo C200 은 이미 H.264 로 송출하는데 우리가 `cv2.VideoCapture` 로 받아 디코드 → re-encode(mp4v) 하며 오히려 부풀려 저장하고 있었음. `VIDEO_FOURCC_CANDIDATES = ("avc1", "H264", "X264", "mp4v")` 폴백으로 빌드 차이 대응 + 용량 70% 감소.

### 개념 4 — 판정 기준은 "정보 가치" 관점으로

짧은/깨진 세그먼트 필터링을 처음엔 `MIN_SEGMENT_BYTES=100KB` 로 했는데, 코덱/장면 복잡도에 따라 파일 크기가 크게 변동. 같은 10초 세그먼트여도 avc1 정적 장면은 300KB, 복잡한 장면은 600KB. **파일 크기가 아니라 "경과 시간"이 정보 가치를 더 잘 반영**. `MIN_SEGMENT_SEC=5.0` 으로 바꾸니 `motion_segment_threshold_sec=3.0` 과 일관성 있는 판정이 됨.

## 6. 참고

- SOT 스펙: `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
- Stage A 스펙 (완료): `./stage-a-streaming.md`
- OpenCV motion detection tutorial: https://docs.opencv.org/4.x/d1/dc5/tutorial_background_subtraction.html
- `cv2.absdiff` 레퍼런스: https://docs.opencv.org/4.x/d2/de8/group__core__array.html#ga6fef31bc8c4071cbc114a758a2b79c14
