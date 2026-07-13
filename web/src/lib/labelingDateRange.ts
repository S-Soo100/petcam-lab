// 라벨링 큐 KST 날짜 범위 헬퍼 — 프리셋·하루 이동·URL 직렬화.
//
// 왜 별도 pure 모듈?
// - 큐 필터의 date_from/date_to 는 항상 `+09:00` 오프셋이 붙은 ISO 문자열(§4.6).
//   경계 계산(오늘/어제/최근 N일, 12/31↔1/1 이동)은 TZ 함정이 많아 단위 테스트가 필요.
// - `now: Date` 를 인자로 받아 테스트를 결정론적으로 만든다 (내부에서 new Date() 안 씀).
//
// KST 는 DST 가 없어 항상 UTC+9. 그래서 "달력상의 하루"는
// `YYYY-MM-DDT00:00:00+09:00` ~ `YYYY-MM-DDT23:59:59+09:00` 로 고정된다
// (기존 _filter-bar.tsx 의 date 입력과 같은 규약).

const KST_OFFSET = '+09:00';

export interface DateRange {
  date_from?: string;
  date_to?: string;
}

export type DatePreset = 'today' | 'yesterday' | 'last3' | 'last7';

// 어떤 순간(instant)이 KST 로 몇 월 며칠인지 — 'YYYY-MM-DD'.
// en-CA 로케일이 ISO 형태(YYYY-MM-DD)를 주므로 파싱 없이 그대로 쓴다.
export function kstDate(now: Date): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

export function dayStart(date: string): string {
  return `${date}T00:00:00${KST_OFFSET}`;
}

export function dayEnd(date: string): string {
  return `${date}T23:59:59${KST_OFFSET}`;
}

export function singleDayRange(date: string): DateRange {
  return { date_from: dayStart(date), date_to: dayEnd(date) };
}

// 'YYYY-MM-DD' 를 달력상 delta 일 이동. 월/연 경계는 UTC 기준 산술로 안전하게 처리
// (정오 UTC 로 만들지 않아도 날짜만 다루므로 DST/TZ 영향 없음).
export function shiftDate(date: string, delta: number): string {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  const yy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(dt.getUTCDate()).padStart(2, '0');
  return `${yy}-${mm}-${dd}`;
}

export function presetRange(preset: DatePreset, now: Date): DateRange {
  const today = kstDate(now);
  switch (preset) {
    case 'today':
      return singleDayRange(today);
    case 'yesterday':
      return singleDayRange(shiftDate(today, -1));
    case 'last3':
      // 오늘 포함 3개 달력일.
      return { date_from: dayStart(shiftDate(today, -2)), date_to: dayEnd(today) };
    case 'last7':
      // 오늘 포함 7개 달력일.
      return { date_from: dayStart(shiftDate(today, -6)), date_to: dayEnd(today) };
  }
}

// ISO 문자열 앞부분의 'YYYY-MM-DD' 추출 (없으면 null).
function datePart(iso: string | undefined): string | null {
  if (!iso) return null;
  const match = iso.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
}

// 범위가 정확히 KST 하루면 그 날짜('YYYY-MM-DD')를, 아니면 null.
// 이전·다음 날 버튼과 날짜 입력 표시는 단일 날짜일 때만 의미가 있다.
export function singleDayOf(range: DateRange): string | null {
  const from = datePart(range.date_from);
  const to = datePart(range.date_to);
  if (from && to && from === to) return from;
  return null;
}

// 단일 날짜 범위를 delta 일 이동. 단일 날짜가 아니면 null (버튼 비활성화 신호).
export function stepDay(range: DateRange, delta: number): DateRange | null {
  const single = singleDayOf(range);
  if (!single) return null;
  return singleDayRange(shiftDate(single, delta));
}

function krDate(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

// "현재 범위" 안내에 들어갈 사람용 문구.
export function describeRange(range: DateRange): string {
  if (!range.date_from && !range.date_to) return '전체 기간';
  const single = singleDayOf(range);
  if (single) return `${krDate(single)} 하루`;
  const from = datePart(range.date_from);
  const to = datePart(range.date_to);
  if (from && to) return `${krDate(from)} ~ ${krDate(to)}`;
  if (from) return `${krDate(from)}부터`;
  if (to) return `${krDate(to)}까지`;
  return '전체 기간';
}

// URL 직렬화/역직렬화 — 새로고침·링크 공유 시 범위 유지(§1 완료 조건).
export function rangeToParams(range: DateRange): Record<string, string> {
  const out: Record<string, string> = {};
  if (range.date_from) out.date_from = range.date_from;
  if (range.date_to) out.date_to = range.date_to;
  return out;
}

export function parseRange(sp: URLSearchParams): DateRange {
  return {
    date_from: sp.get('date_from') ?? undefined,
    date_to: sp.get('date_to') ?? undefined,
  };
}
