// motion 큐 클라이언트 순수 헬퍼(설계 §8.3) — page.tsx 클라이언트 컴포넌트가 쓴다.
//
// merge 는 production v2 에서 검증된 mergeNewestQueueItems 를 복사하지 않고 재사용한다
// (마이크로초 보존 + id DESC tie-break + dedup). 필터 직렬화/역직렬화는 URL 영속용.

import { mergeNewestQueueItems } from './labelingQueueClient';
import type { MotionLabelingState, MotionQueueItem } from './labelingV3';

export function mergeMotionQueueItems(
  base: MotionQueueItem[],
  incoming: MotionQueueItem[],
): MotionQueueItem[] {
  return mergeNewestQueueItems(base, incoming);
}

export interface MotionQueueUiFilters {
  // owner 탭: 미분류(unreviewed, 기본) | 전체(all) | 라벨 대기(label) | 보류(hold) | 제외(skip).
  state?: MotionLabelingState | 'all';
  camera_id?: string[];
  date_from?: string;
  date_to?: string;
  media?: 'ready' | 'unavailable';
}

const KNOWN_STATES: readonly string[] = ['unreviewed', 'label', 'hold', 'skip'];

// 목록 필터 → 쿼리스트링. 순서는 state→camera_id→date_from→date_to→media 로 고정해
// 같은 필터가 항상 같은 URL·scrollKey 를 내도록 한다(정규화). state 는 all 도 명시한다(설계 §4).
export function toMotionQueueQuery(filters: MotionQueueUiFilters): string {
  const p = new URLSearchParams();
  if (filters.state) p.set('state', filters.state);
  if (filters.camera_id?.length) p.set('camera_id', filters.camera_id.join(','));
  if (filters.date_from) p.set('date_from', filters.date_from);
  if (filters.date_to) p.set('date_to', filters.date_to);
  if (filters.media) p.set('media', filters.media);
  return p.toString();
}

// 빈 query·미지 state 는 기본 탭(unreviewed)으로 접는다. all 은 명시적 query 값이라 그대로 둔다(설계 §4).
export function parseMotionQueueFilters(sp: URLSearchParams): MotionQueueUiFilters {
  const stateRaw = sp.get('state');
  let state: MotionLabelingState | 'all';
  if (stateRaw === 'all') state = 'all';
  else if (stateRaw && KNOWN_STATES.includes(stateRaw)) state = stateRaw as MotionLabelingState;
  else state = 'unreviewed';
  const camera = sp.get('camera_id');
  const media = sp.get('media');
  return {
    state,
    camera_id: camera ? camera.split(',').filter(Boolean) : undefined,
    date_from: sp.get('date_from') ?? undefined,
    date_to: sp.get('date_to') ?? undefined,
    media: media === 'ready' || media === 'unavailable' ? media : undefined,
  };
}

// ── 목록 문맥 helper (설계 §5) ────────────────────────────────────
// 목록 필터를 상세 URL·scrollKey 로 전달·복원하는 순수 helper. 임의 외부 URL 은 받지 않고
// 허용된 큐 query(state/camera_id/date_from/date_to/media)만 쓰므로 open redirect 를 만들지 않는다.

// 목록 URL. reviewComplete 면 완료 안내 플래그(review_complete=1)를 덧붙인다(설계 §7.2).
export function motionQueuePath(
  filters: MotionQueueUiFilters,
  extra: { reviewComplete?: boolean } = {},
): string {
  const p = new URLSearchParams(toMotionQueueQuery(filters));
  if (extra.reviewComplete) p.set('review_complete', '1');
  return `/labeling/motion?${p.toString()}`;
}

// 카드 → 상세 URL. 목록의 공개 필터 query 를 그대로 전달해 목록 복귀·다음 영상 문맥을 잇는다.
export function motionDetailPath(clipId: string, filters: MotionQueueUiFilters): string {
  const query = toMotionQueueQuery(filters);
  return `/labeling/motion/${clipId}${query ? `?${query}` : ''}`;
}

// 목록 스크롤 위치 저장 key. 정규화된 목록 query 로 만들어 같은 필터끼리만 복원된다(설계 §5).
export function motionQueueScrollKey(filters: MotionQueueUiFilters): string {
  return `petcam-motion-queue-scroll:${toMotionQueueQuery(filters)}`;
}
