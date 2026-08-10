# YOLO 공개 시연 드래그앤드롭 업로드 설계

**상태:** Owner 승인 완료 · 구현 전

## 1. 목표와 범위

공개 `/gecko-detector`의 기존 파일 선택 입력을 클릭·키보드·모바일 선택과 드래그앤드롭을 함께
지원하는 단일 drop zone으로 바꾼다. inference provider, API, 파일 형식·크기 제한, 학습 후보 동의,
production 503 fail-closed 계약은 변경하지 않는다.

## 2. 사용자 체험 흐름

1. `[화면]` 점선 테두리 영역에 “사진·영상을 끌어 놓거나 파일 선택”과 현재 제한이 보인다.
   `[조작]` 사용자는 영역을 클릭하거나 키보드로 활성화한다.
   `[반응]` 운영체제 파일 선택기가 열린다.
   `[감정]` 기존 방식도 사라지지 않았다는 안정감을 느낀다.
2. `[화면]` idle drop zone이 보인다.
   `[조작]` 사용자가 파일을 영역 위로 끌어온다.
   `[반응]` 배경·테두리가 강조되고 “여기에 놓아줘” 안내가 보인다.
   `[감정]` 놓을 위치를 즉시 이해한다.
3. `[조작]` 사용자가 지원되는 파일 하나를 놓는다.
   `[반응]` 기존 `selectFile` 검증과 object URL preview 경로가 그대로 실행되고 파일명이 보인다.
   `[감정]` 업로드 대상으로 선택됐음을 확인한다.
4. `[조작]` 지원하지 않는 형식, 빈 파일, 초과 크기 파일을 놓는다.
   `[반응]` 기존 파일 선택과 동일한 오류 문구가 `aria-live`에 표시된다.
   `[감정]` 실패 이유와 다음 행동을 이해한다.
5. `[조작]` 여러 파일을 한 번에 놓는다.
   `[반응]` 어느 파일도 선택하지 않고 “한 번에 파일 하나만 올려줘.”를 표시한다.
   `[감정]` 임의로 첫 파일을 고르는 모호함을 피한다.

## 3. 컴포넌트 계약

- 기존 `DetectorDemo` 안에 추가 의존성 없이 React drag event를 사용한다.
- drop zone은 실제 `<input type="file">`을 포함한 `<label>`로 유지해 클릭·키보드·모바일 접근성을
  보존한다.
- `dragenter`/`dragover`에서 브라우저 기본 파일 열기 동작을 막고 active 시각 상태를 켠다.
- `dragleave`에서 관련 target이 zone 내부라면 active 상태를 유지하고, 완전히 벗어날 때만 끈다.
- `drop`에서 기본 동작을 막고 active 상태를 끈 뒤 `dataTransfer.files`를 처리한다.
- 단일 파일은 기존 `selectFile`로 전달해 형식·크기·빈 파일 검증을 중복 구현하지 않는다.
- 다중 파일은 기존 선택값과 결과를 초기화하고 전용 오류를 표시한다.

## 4. 오류·보안 경계

- 허용 형식: JPEG, PNG, WebP, MP4, WebM.
- 크기: 사진 10 MiB, 영상 50 MiB. 빈 파일 금지.
- drop은 클라이언트 편의 기능일 뿐이며 API의 magic byte·multipart·횟수 제한을 대체하지 않는다.
- 실제 worker/checkpoint는 연결하지 않는다. production fake/local limiter는 계속 503을 반환한다.
- R2 write, Dataset 후보 생성, DB migration은 없다.

## 5. 테스트와 배포

- RED: drop zone 문구, drag active 상태, 단일 파일 drop, 다중 파일 거부를 컴포넌트 테스트로 먼저
  작성하고 현재 구현에서 실패를 확인한다.
- GREEN: 최소 drag handler와 시각 상태만 추가해 focused test를 통과시킨다.
- 전체 Web test, TypeScript, Next production build를 검증한다.
- PR merge 후 Vercel production READY와 `label.tera-ai.uk/gecko-detector` 200을 확인한다.
- 실제 worker 미연결 canary는 `/api/yolo-demo/infer` 503을 정상으로 확인한다.

## 6. 완료 조건

- 클릭·키보드 파일 선택이 유지된다.
- drag active 피드백과 단일 파일 drop이 동작한다.
- 다중 파일·기존 파일 오류가 명확히 표시된다.
- API·DB·R2·worker 계약 변경이 없다.
- production 배포와 공개 canary가 통과한다.
