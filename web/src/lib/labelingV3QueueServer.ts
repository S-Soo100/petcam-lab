// motion_clips 큐/다음-영상 라우트가 공유하는 query 검증 — 순수 파서(설계 §6·§8).
//
// queue route 와 next route 가 같은 필터 계약(state/camera/date/media/limit)을 써야 하므로
// route 인라인이던 검증을 여기로 뽑았다. 잘못된 값은 DB 접근 전에 error 문자열로 접는다(라우트가
// 400 매핑). server-only 의존이 없는 순수 함수라 vitest 로 직접 검증한다.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// strict RFC3339(offset 필수) — cursor helper 와 동일 계약. 관대한 Date.parse 를 막는다.
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;
const OWNER_STATES = new Set(['unreviewed', 'label', 'hold', 'skip']);
// DB RPC 상한 100 안에서 limit+1 sentinel 한 행을 확보하려면 공개 페이지는 최대 99개다.
export const MAX_PUBLIC_PAGE_SIZE = 99;

export interface MotionQueueParams {
  state: string | null;
  cameraIds: string[] | null;
  dateFrom: string | null;
  dateTo: string | null;
  media: string | null;
  limit: number;
}

function validDate(raw: string): boolean {
  return raw.length <= 64 && RFC3339.test(raw) && !Number.isNaN(Date.parse(raw));
}

// query string → 검증된 RPC 파라미터. 잘못된 값은 error 문자열로(라우트가 400 매핑).
export function parseMotionQueueRequest(
  search: URLSearchParams,
  isOwner: boolean,
): { params: MotionQueueParams } | { error: string } {
  // limit: 미지정=30, 양의 정수만, 공개 페이지 99 상한 clamp.
  let limit = 30;
  const limitRaw = search.get('limit');
  if (limitRaw !== null) {
    if (!/^\d+$/.test(limitRaw) || Number(limitRaw) < 1) return { error: '잘못된 limit' };
    limit = Math.min(Number(limitRaw), MAX_PUBLIC_PAGE_SIZE);
  }

  // state: owner 만 필터. labeler 는 항상 label 큐(무시).
  let state: string | null = null;
  if (isOwner) {
    const raw = search.get('state');
    if (raw !== null && raw !== 'all') {
      if (!OWNER_STATES.has(raw)) return { error: '잘못된 state' };
      state = raw;
    }
  }

  // camera_id: 콤마 구분 UUID.
  let cameraIds: string[] | null = null;
  const camRaw = search.get('camera_id');
  if (camRaw) {
    const ids = camRaw.split(',').filter(Boolean);
    if (ids.some((id) => !UUID.test(id))) return { error: '잘못된 camera_id' };
    cameraIds = ids.length ? ids : null;
  }

  const dateFrom = search.get('date_from');
  if (dateFrom !== null && !validDate(dateFrom)) return { error: '잘못된 date_from' };
  const dateTo = search.get('date_to');
  if (dateTo !== null && !validDate(dateTo)) return { error: '잘못된 date_to' };

  const media = search.get('media');
  if (media !== null && media !== 'ready' && media !== 'unavailable') {
    return { error: '잘못된 media' };
  }

  return { params: { state, cameraIds, dateFrom, dateTo, media, limit } };
}
