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
  // owner 탭: 전체(all) | 라벨 대기(label) | 보류(hold) | 제외(skip). unreviewed 는 전체 탭에 포함.
  state?: MotionLabelingState | 'all';
  camera_id?: string[];
  date_from?: string;
  date_to?: string;
  media?: 'ready' | 'unavailable';
}

const KNOWN_STATES: readonly string[] = ['unreviewed', 'label', 'hold', 'skip'];

export function toMotionQueueQuery(filters: MotionQueueUiFilters): string {
  const p = new URLSearchParams();
  if (filters.state && filters.state !== 'all') p.set('state', filters.state);
  if (filters.camera_id?.length) p.set('camera_id', filters.camera_id.join(','));
  if (filters.date_from) p.set('date_from', filters.date_from);
  if (filters.date_to) p.set('date_to', filters.date_to);
  if (filters.media) p.set('media', filters.media);
  return p.toString();
}

export function parseMotionQueueFilters(sp: URLSearchParams): MotionQueueUiFilters {
  const stateRaw = sp.get('state');
  const state =
    stateRaw && KNOWN_STATES.includes(stateRaw) ? (stateRaw as MotionLabelingState) : 'all';
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
