# 라벨링 영상 상세 촬영 정보·다운로드 설계

**상태:** 승인됨 / 구현 전  
**작성일:** 2026-07-12

## 목표

라벨러가 상세 화면에 들어오자마자 영상 촬영 시각과 길이를 확인하고, 같은 위치에서
원본 MP4를 안정적으로 내려받을 수 있게 한다.

## 사용자 경험

1. 상세 화면 진입 시 제목 아래에 `촬영 · 2026년 7월 8일 (수) 오전 5:11:29 · 32초`를 표시한다.
2. 우측의 단계 배지 옆에 `영상 다운로드` 버튼을 표시한다.
3. 버튼을 누르면 인증된 서버 route가 attachment용 R2 signed URL을 새로 발급한다.
4. 브라우저는 원본 MP4를 `petcam_YYYY-MM-DD_HHmmss_<clip-id 앞 8자리>.mp4`로 저장한다.
5. URL 발급 중에는 버튼을 비활성화하고, 실패하면 페이지 오류 영역과 toast에 재시도 가능한 메시지를 표시한다.

## 설계 결정

- 촬영 시각의 SOT는 `camera_clips.started_at`이며 `Asia/Seoul` 시간대로 표시한다.
- 영상 길이는 `camera_clips.duration_sec`를 반올림해 초 단위로 표시한다.
- 기존 playback signed URL은 재생 전용으로 유지한다.
- 다운로드 route는 기존 `loadClipWithPerms` 권한 검사를 재사용한다.
- R2 `GetObjectCommand`에 `ResponseContentDisposition=attachment; filename=...`를 지정해
  cross-origin `download` 속성의 불확실성을 제거한다.
- Vercel이 MP4 byte stream을 proxy하지 않는다. R2가 직접 전송한다.
- 원본 `r2_key`가 없는 clip은 410을 반환하고 버튼에서 오류를 안내한다.

## 화면 배치

- 촬영 정보는 제목과 설명 사이의 보조 정보 행에 둔다.
- 다운로드 버튼은 단계 배지·삭제 버튼과 같은 상단 action group에 둔다.
- 모바일에서는 header가 줄바꿈되며 촬영 정보와 action group이 각각 읽을 수 있는 순서를 유지한다.
- 기존 흰색·zinc·emerald UI 체계와 Button 컴포넌트를 그대로 사용한다.

## 코드 경계

- `web/src/lib/labelingV2.ts`: KST 표시 문자열과 안전한 다운로드 파일명 생성 helper
- `web/src/app/api/clips/[id]/download/url/route.ts`: 권한 확인 및 attachment signed URL 발급
- `web/src/lib/r2.ts`: attachment disposition을 선택적으로 받는 presign helper
- `web/src/lib/labelingApi.ts`: 다운로드 URL client 함수
- `web/src/app/labeling/[clipId]/page.tsx`: 상단 촬영 정보·버튼·상태 처리
- `web/src/lib/labelingV2.test.ts`: 시간대·파일명 회귀 테스트

## 완료 조건

- KST 촬영 시각과 duration이 상세 상단에 보인다.
- 다운로드가 원본 MP4와 합의한 파일명으로 시작된다.
- owner와 labeler 모두 기존 clip 접근 권한 범위 안에서 다운로드할 수 있다.
- 권한 없는 사용자는 기존과 동일하게 404/401 처리된다.
- Web test, TypeScript, Vercel build, production browser E2E가 통과한다.

## 제외 범위

- 영상 재인코딩, 해상도 선택, clip 일부 구간 다운로드
- 다운로드 이력 테이블과 사용량 분석
- Flutter 앱 다운로드 기능
