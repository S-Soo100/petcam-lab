# petcam-lab

> 도마뱀 특화 펫캠 (게코 캠) 영상 백엔드 서비스. 학습 겸 실제 제품 코드.

## 상위 기획

이 레포는 `tera-ai-product-master` 레포의 아래 기획 문서를 구현한다:

- [제품 기획 (B2C 게코 캠)](../tera-ai-product-master/docs/specs/petcam-b2c.md)
- [백엔드 개발 기획 스펙](../tera-ai-product-master/docs/specs/petcam-backend-dev.md)
- [제품 포지션 요약](../tera-ai-product-master/products/petcam/README.md)

## 기술 스택

- **Python 3.12+** (예정)
- **FastAPI** — 웹 프레임워크
- **uvicorn** — ASGI 서버
- **OpenCV** (`opencv-python`) — 영상 I/O 및 움직임 감지
- **FFmpeg** — 영상 인코딩/디코딩 (나중 도입)
- **uv** — 패키지/환경 매니저

## 아키텍처 요약

메인 앱 백엔드는 **Supabase**. 영상 서비스는 **별도 Python FastAPI 서버**로 분리.

- **로컬 개발 초기**: FastAPI 독립 운영 (자체 DB/파일 저장)
- **중기**: Supabase Auth JWT 검증 + Supabase Postgres 연동
- **후기**: Supabase Storage 또는 독립 스토리지로 영상 저장

상세: [`petcam-backend-dev.md`](../tera-ai-product-master/docs/specs/petcam-backend-dev.md)

## 폴더 구조

```
petcam-lab/
├── backend/          # FastAPI 서버 코드
├── scripts/          # 실험 스크립트 (RTSP 테스트 등)
├── storage/          # 영상·클립 저장 (gitignore)
├── tests/            # 테스트 코드
├── .gitignore
├── README.md
└── pyproject.toml    # uv 설정 (uv init 후 생성)
```

## 카메라 소스

- **실제 기기**: TP-Link Tapo C200 × 2대 (주문 완료, 배송 대기 중)
  - RTSP URL: `rtsp://<user>:<pass>@<IP>:554/stream1`
- **대기 중 대체**: 스마트폰 IP 캠 앱
  - Android: `IP Webcam`
  - iOS: `iVCam` 또는 `EpocCam`

## 개발 로드맵

| Stage | 내용 | 상태 |
|-------|------|------|
| **A** | 스트리밍 + 서버 파일 저장 (MVP) | 🚧 진행 |
| **B** | OpenCV 움직임 감지 + 클립 분리 | 대기 |
| **C** | 메타데이터 DB + 클립 조회 API | 대기 |
| **D** | Supabase Auth 연동 + 앱 연결 | 대기 |
| **E** | 온디바이스 필터링 (ESP32-CAM) | 나중 |

## 셋업 (초기)

```bash
# uv 설치 (최초 1회)
brew install uv

# 환경 초기화
cd /Users/baek/petcam-lab
uv init          # pyproject.toml 생성
uv add fastapi uvicorn opencv-python python-dotenv

# 첫 실험
uv run python scripts/test_rtsp.py
```

## 참고

- 상위 제품 문서: `../tera-ai-product-master/products/petcam/`
- FastAPI 공식: https://fastapi.tiangolo.com/
- OpenCV-Python: https://docs.opencv.org/
