# YOLO26n Owner 촬영물 외부 진단 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 673개 휴대폰 촬영물 중 사진 240장을 날짜 균형으로 익명화해 blind-first CVAT 큐로 만든다.

**Architecture:** 순수 selector가 metadata row를 capture-day round-robin으로 고르고, materializer가
ImageMagick으로 auto-orient·resize·strip한 JPEG와 private provenance, CSV, ZIP을 no-overwrite로 만든다.

**Tech Stack:** Python 3.12, Pillow/ImageMagick, pytest, macOS Spotlight metadata.

## Global Constraints

- 원본 673개는 읽기 전용이며 사진 638개 중 exact 240개만 1차 큐에 쓴다.
- capture-day당 최대 3장, diagnostic 60장, training candidate 180장을 유지한다.
- 모델 inference, DB, R2, service, active model, Vercel write는 0이다.
- CVAT 공개 산출물에는 원본 파일명·촬영일·기종·EXIF·GPS가 없어야 한다.
- output은 새 디렉터리에만 만들고 기존 artifact를 덮어쓰지 않는다.

### Task 1: 결정론적 selector와 fail-closed 계약

- Create: `scripts/build_yolo26n_owner_media_diagnostic.py`
- Create: `tests/test_build_yolo26n_owner_media_diagnostic.py`
- [ ] exact 240, day cap 3, 60/180 capture-day partition, reverse-input determinism의 실패 테스트를 작성한다.
- [ ] `uv run pytest -q tests/test_build_yolo26n_owner_media_diagnostic.py`가 missing API로 실패하는지 확인한다.
- [ ] SHA rank와 capture-day round-robin을 사용하는 최소 selector를 구현한다.
- [ ] 같은 테스트가 통과하는지 확인한다.

### Task 2: private inventory와 익명 CVAT materialization

- [ ] EXIF가 있는 fixture와 중복 fixture로 실패 테스트를 작성한다.
- [ ] source SHA/decode/dimension/date/model을 private manifest에 기록한다.
- [ ] 파생물은 `O####.jpg`, 장축 1920 이하, EXIF 제거, source/derived exact duplicate 0으로 만든다.
- [ ] `review-index.csv`, `ambiguous.csv`, `cvat-upload.zip`의 이름·순서·SHA를 교차검증한다.
- [ ] duplicate/decode/output-exists에서 ZIP 없이 fail-closed하는지 확인한다.

### Task 3: 실행과 독립 preflight

- [ ] Output을 `/Users/baek/Library/Application Support/petcam/yolo26n-owner-media-diagnostic-v1-20260812`로 고정한다.
- [ ] 모델 inference 없이 inventory와 큐를 생성한다.
- [ ] exact 수량·day cap·partition·ZIP CRC·EXIF 제거·원본 불변을 독립 재검증한다.
- [ ] 검증 결과를 `REPORT.md`에 기록하고 통과한 ZIP만 CVAT Owner task에 업로드한다.

### Task 4: 사람 export 이후

- bbox snapshot + exact `sequence,ambiguous` CSV를 검증한다.
- diagnostic 60장은 고정 v2.2 평가에만 쓰고 학습하지 않는다.
- training candidate 180장은 오류 분석 뒤 별도 승인된 v2.3 dataset에만 추가한다.
- 영상 35개는 같은 영상의 프레임이 split을 넘지 않는 별도 큐로 처리한다.
