// 라벨링 큐 클라이언트 merge 헬퍼 — 순수 함수(설계 §5).
//
// 더보기 응답을 단순 append 하면 중복 응답·경합에서 최종 배열의 정렬·고유성이 깨진다.
// 이 헬퍼는 매 merge 마다 clip.id 로 dedup 하고 정본 정렬키 (started_at DESC, id DESC) 로
// 다시 정렬해, 서버가 어떤 순서로 주든 UI 배열이 항상 최신순·고유하도록 만든다.
// 서버 코드가 아니라 'server-only' 를 붙이지 않는다(page.tsx 클라이언트 컴포넌트가 쓴다).

// started_at 정렬키 = (epoch millisecond, 밀리초 이후 sub-millisecond 6자리).
//
// Date.parse 는 소수 초를 밀리초(3자리)까지만 truncate 반영한다(V8 실측: '.123999'→…123,
// 다음 초로 넘치지 않음). PostgreSQL timestamptz 는 마이크로초(6자리)까지 저장하므로,
// ms 만 비교하면 '.123400' 과 '.123499' 가 동률이 돼 DB 정본 순서와 어긋난다. 밀리초 이후
// 자릿수를 따로 추출해 epoch 와 겹치지 않는 정수로 비교한다(BigInt 불필요). timestamp 원문은
// 바꾸지 않고 비교 키만 만든다.
function startedAtSortKey(value: string): { ms: number; subMicros: number } | null {
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return null;
  // RFC3339 에서 점은 소수 초 구분자뿐(offset '+09:00' 엔 점이 없다).
  const match = /\.(\d+)/.exec(value);
  const fraction = match ? match[1] : '';
  // 9자리(나노초)로 right-pad 후 밀리초 이후 6자리 — Date.parse 가 반영한 앞 3자리와 겹치지 않는다.
  const nanos = (fraction + '000000000').slice(0, 9);
  return { ms, subMicros: Number(nanos.slice(3)) };
}

export function mergeNewestQueueItems<T extends { id: string; started_at: string }>(
  base: T[],
  incoming: T[],
): T[] {
  const byId = new Map(base.map((row) => [row.id, row]));
  // incoming 이 같은 id 를 덮는다 — 새 응답의 최신 데이터를 우선.
  for (const row of incoming) byId.set(row.id, row);
  // Array.from(map.values()) — tsconfig target 낮아 iterator 스프레드 대신 이걸 쓴다.
  return Array.from(byId.values()).sort((a, b) => {
    // ISO-8601 문자열 사전순 ≠ 시간순. fractional second·offset 표기 차이가 섞이면
    // localeCompare 는 순서를 뒤집는다. epoch + sub-millisecond 로 실제 시간 DESC 를 보장한다.
    const ka = startedAtSortKey(a.started_at);
    const kb = startedAtSortKey(b.started_at);
    if (ka && kb) {
      if (kb.ms !== ka.ms) return kb.ms - ka.ms; // epoch millisecond DESC
      if (kb.subMicros !== ka.subMicros) return kb.subMicros - ka.subMicros; // 마이크로초 DESC
      // 같은 instant(예: 'Z' vs '-05:00', 동일 마이크로초)면 id DESC tie-break.
      return b.id.localeCompare(a.id);
    }
    // API 에서는 올 수 없는 malformed timestamp fallback — NaN 반환 방지.
    // 결정론적으로 raw string DESC 후 id DESC.
    const raw = b.started_at.localeCompare(a.started_at);
    return raw !== 0 ? raw : b.id.localeCompare(a.id);
  });
}
