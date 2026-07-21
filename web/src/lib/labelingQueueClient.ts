// 라벨링 큐 클라이언트 merge 헬퍼 — 순수 함수(설계 §5).
//
// 더보기 응답을 단순 append 하면 중복 응답·경합에서 최종 배열의 정렬·고유성이 깨진다.
// 이 헬퍼는 매 merge 마다 clip.id 로 dedup 하고 정본 정렬키 (started_at DESC, id DESC) 로
// 다시 정렬해, 서버가 어떤 순서로 주든 UI 배열이 항상 최신순·고유하도록 만든다.
// 서버 코드가 아니라 'server-only' 를 붙이지 않는다(page.tsx 클라이언트 컴포넌트가 쓴다).
export function mergeNewestQueueItems<T extends { id: string; started_at: string }>(
  base: T[],
  incoming: T[],
): T[] {
  const byId = new Map(base.map((row) => [row.id, row]));
  // incoming 이 같은 id 를 덮는다 — 새 응답의 최신 데이터를 우선.
  for (const row of incoming) byId.set(row.id, row);
  // Array.from(map.values()) — tsconfig target 낮아 iterator 스프레드 대신 이걸 쓴다.
  return Array.from(byId.values()).sort((a, b) => {
    // ISO-8601 문자열 사전순 ≠ 시간순. '.100000+00:00' 처럼 fractional second 나
    // 다른 offset 표기가 섞이면 localeCompare 는 순서를 뒤집는다. Date.parse 로
    // epoch millisecond 를 비교해 실제 시간 DESC 를 보장한다(started_at 값은 안 바꾼다).
    const at = Date.parse(a.started_at);
    const bt = Date.parse(b.started_at);
    if (!Number.isNaN(at) && !Number.isNaN(bt)) {
      // 같은 instant(예: 'Z' vs '-05:00')면 epoch 동률 → id DESC tie-break.
      return bt !== at ? bt - at : b.id.localeCompare(a.id);
    }
    // API 에서는 올 수 없는 malformed timestamp fallback — NaN 반환 방지.
    // 결정론적으로 raw string DESC 후 id DESC.
    const raw = b.started_at.localeCompare(a.started_at);
    return raw !== 0 ? raw : b.id.localeCompare(a.id);
  });
}
