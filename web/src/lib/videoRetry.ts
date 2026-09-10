// 영상 로드 실패 재시도(순수) — R2 가 같은 서명 URL 에 503 을 간헐적으로 준다(2026-09-08 실측, 재요청은 206 성공).
// 같은 URL 로 1·2·4초 뒤 세 번 다시 불러오고, 그래도 실패하면 호출자가 "다시 시도"(서명 URL 재발급) 버튼을 낸다.
export const VIDEO_RETRY_MAX = 3;

// attempt = 지금까지 실패한 횟수(0-based). 더 시도할 수 없으면 null.
export function nextRetryDelayMs(attempt: number): number | null {
  if (!Number.isInteger(attempt) || attempt < 0) return null;
  return attempt >= VIDEO_RETRY_MAX ? null : 1000 * 2 ** attempt;
}
