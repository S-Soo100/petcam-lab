# Don'ts — Python / FastAPI / OpenCV / uv

> Python 백엔드 & 영상 처리 작업에서 반복될 만한 실수. 루트 [`../donts.md`](../donts.md)의 제너럴 규칙과 함께 적용.
> 현재는 초기 추정치이므로 실제 재발 시에만 유지, 아니면 삭제.

## 📦 의존성 관리 (uv)

1. **`pip install` 직접 사용 금지** — 이 레포는 `uv` 전용. 의존성은 반드시 `uv add <pkg>`로 추가해 `pyproject.toml` + `uv.lock` 동기화.
2. **`.venv/` 커밋 금지** — `.gitignore`에 이미 있음. `uv run`으로만 실행.
3. **Python 버전은 `.python-version`으로만** — 전역 pyenv/asdf 버전 강제 변경 금지.

## 🌐 FastAPI / 비동기

4. **블로킹 I/O를 async 핸들러에 직접 쓰지 않기** — `cv2.VideoCapture`, `cv2.imwrite`, 파일 I/O 등은 이벤트 루프를 막는다. `run_in_executor` / `asyncio.to_thread` 로 감싸거나 **동기 핸들러(def)** 로 선언.
5. **스트리밍 엔드포인트는 `StreamingResponse` + 제너레이터** — 한 번에 bytes 로드 금지. MJPEG/HLS 세그먼트는 chunk 단위로 yield.
6. **의존성 주입은 `Depends()`로만** — 전역 싱글톤/모듈 수준 상태 금지. 테스트에서 override 못 함.

## 📹 OpenCV / 영상 I/O

7. **`cap.release()` 누락 금지** — `VideoCapture`는 `try/finally` 또는 context manager로 반드시 해제. 안 하면 스레드 누수 + 다음 연결 실패.
8. **`cap.read()` 실패를 `raise` 하지 말고 재시도 카운터** — RTSP는 일시 끊김이 정상. 3~5회 재시도 후에만 실패 판정.
9. **프레임 복사 금지(기본)** — `frame.copy()`는 비용 큼. 읽은 프레임을 그대로 처리 파이프라인에 넘기고, **필요한 곳에서만** 복사.
10. **해상도·FPS 가정 금지** — Tapo/스마트폰/웹캠 소스마다 다름. `cap.get(cv2.CAP_PROP_*)`로 런타임 확인 후 처리.

## 💾 파일 / 경로

11. **상대 경로 금지** — 스크립트 실행 위치에 따라 깨짐. `Path(__file__).resolve().parent` 기준으로 절대 경로 만들기.
12. **`storage/` 밖에 영상 저장 금지** — 레포 루트에 `.mp4`/`.jpg` 흩뿌리면 `.gitignore` 통과해 사고 남. 영상은 전부 `storage/` 하위.

## 🧪 pytest / 품질

13. **실제 RTSP 소스에 의존하는 테스트 금지(기본)** — 네트워크/카메라 의존 테스트는 `@pytest.mark.integration` 붙이고 CI에서 분리. 유닛 테스트는 fake 프레임(numpy array)로.
14. **`pytest -x` 없이 대량 실행 금지** — 하나 깨지면 바로 멈추고 원인 분석. 로그 홍수 회피.

## 🐛 예외 처리

15. **bare except / 광범위 Exception 캐치 금지** — `except:` 또는 `except Exception: pass` 금지. 특정 예외만 잡고 logging + 필요 시 `raise ... from e`로 chain. 침묵 실패 = 디버깅 불가.

---
**상태:** 초기 추정. 재발 시마다 donts-audit에 기록하고, 3회 쌓이지 않으면 정리.
