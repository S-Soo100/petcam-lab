import { describe, expect, it } from 'vitest';

import { createRequestGeneration } from './requestGeneration';
import type { MotionQueueItem } from './labelingV3';
import {
  mergeMotionQueueItems,
  motionDetailPath,
  motionQueuePath,
  motionQueueScrollKey,
  parseMotionQueueFilters,
  readStoredMotionQueueScroll,
  toMotionQueueQuery,
} from './labelingV3QueueClient';

// getItem/removeItem 만 구현한 테스트용 Storage. one-shot 파서의 소비(삭제)까지 검증한다.
class MapStorage {
  private map: Map<string, string>;
  constructor(initial: Record<string, string> = {}) {
    this.map = new Map(Object.entries(initial));
  }
  getItem(key: string): string | null {
    return this.map.has(key) ? (this.map.get(key) as string) : null;
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
}

// motion 큐 클라이언트 순수 계약(구현계획 Task 7). 마이크로초 정렬·tie-break·dedup·직렬화.

function item(id: string, started_at: string): MotionQueueItem {
  return {
    id,
    camera_id: 'cam',
    camera_name: '2번',
    started_at,
    duration_sec: 30,
    media_ready: true,
    state: 'unreviewed',
    session_stage: null,
  };
}

describe('mergeMotionQueueItems', () => {
  it('started_at DESC 로 정렬한다(newer 먼저)', () => {
    const older = item('a', '2026-07-21T16:29:00.000000+09:00');
    const newer = item('b', '2026-07-21T16:30:00.000000+09:00');
    expect(mergeMotionQueueItems([], [older, newer]).map((i) => i.id)).toEqual(['b', 'a']);
  });

  it('마이크로초까지 구분한다(밀리초 동률을 뒤집지 않는다)', () => {
    const lo = item('a', '2026-07-21T16:30:00.123400+09:00');
    const hi = item('b', '2026-07-21T16:30:00.123499+09:00');
    expect(mergeMotionQueueItems([], [lo, hi]).map((i) => i.id)).toEqual(['b', 'a']);
  });

  it('같은 instant 는 id DESC 로 tie-break', () => {
    const a = item('aaaa', '2026-07-21T16:30:00.000000+09:00');
    const z = item('zzzz', '2026-07-21T16:30:00.000000+09:00');
    expect(mergeMotionQueueItems([], [a, z]).map((i) => i.id)).toEqual(['zzzz', 'aaaa']);
  });

  it('id 로 dedup 하고 incoming 이 최신값으로 덮는다', () => {
    const base = [item('a', '2026-07-21T16:30:00.000000+09:00')];
    const incoming = [{ ...item('a', '2026-07-21T16:30:00.000000+09:00'), state: 'label' as const }];
    const merged = mergeMotionQueueItems(base, incoming);
    expect(merged).toHaveLength(1);
    expect(merged[0].state).toBe('label');
  });
});

describe('toMotionQueueQuery', () => {
  it('필터를 쿼리스트링으로 직렬화한다', () => {
    const qs = toMotionQueueQuery({
      state: 'hold',
      camera_id: ['cam-1', 'cam-2'],
      date_from: '2026-07-21T00:00:00+09:00',
      date_to: '2026-07-22T00:00:00+09:00',
      media: 'ready',
    });
    expect(qs).toContain('state=hold');
    expect(qs).toContain('camera_id=cam-1%2Ccam-2');
    expect(qs).toContain('media=ready');
  });

  it('state=all 은 URL 에 명시한다(목록 복귀 시 뜻이 바뀌지 않게)', () => {
    expect(toMotionQueueQuery({ state: 'all' })).toBe('state=all');
  });

  it('query 순서를 state→camera_id→date_from→date_to→media 로 고정한다', () => {
    expect(
      toMotionQueueQuery({
        media: 'ready',
        date_to: '2026-07-22T00:00:00+09:00',
        date_from: '2026-07-21T00:00:00+09:00',
        camera_id: ['cam-1'],
        state: 'unreviewed',
      }),
    ).toBe(
      'state=unreviewed&camera_id=cam-1&date_from=2026-07-21T00%3A00%3A00%2B09%3A00&date_to=2026-07-22T00%3A00%3A00%2B09%3A00&media=ready',
    );
  });
});

describe('parseMotionQueueFilters round-trip', () => {
  it('직렬화→역직렬화가 필터를 보존한다', () => {
    const filters = {
      state: 'skip' as const,
      camera_id: ['cam-1'],
      date_from: '2026-07-21T00:00:00+09:00',
      date_to: '2026-07-22T00:00:00+09:00',
      media: 'unavailable' as const,
    };
    const round = parseMotionQueueFilters(new URLSearchParams(toMotionQueueQuery(filters)));
    expect(round.state).toBe('skip');
    expect(round.camera_id).toEqual(['cam-1']);
    expect(round.date_from).toBe('2026-07-21T00:00:00+09:00');
    expect(round.media).toBe('unavailable');
  });

  it('빈 쿼리는 state=unreviewed(기본 탭)', () => {
    expect(parseMotionQueueFilters(new URLSearchParams('')).state).toBe('unreviewed');
  });

  it('state=all 은 그대로 all 로 역직렬화한다(전체 영상 탭)', () => {
    expect(parseMotionQueueFilters(new URLSearchParams('state=all')).state).toBe('all');
  });

  it('알 수 없는 state 는 기본 탭(unreviewed)으로 접힌다', () => {
    expect(parseMotionQueueFilters(new URLSearchParams('state=quarantine')).state).toBe('unreviewed');
  });

  it('잘못된 media 는 무시한다', () => {
    expect(parseMotionQueueFilters(new URLSearchParams('media=maybe')).media).toBeUndefined();
  });
});

describe('motion 큐 문맥 helper', () => {
  it('motionQueuePath 는 목록 필터를 URL 로 직렬화한다', () => {
    expect(motionQueuePath({ state: 'unreviewed' })).toBe('/labeling/motion?state=unreviewed');
  });

  it('motionQueuePath 는 review_complete 플래그를 붙인다', () => {
    expect(motionQueuePath({ state: 'unreviewed' }, { reviewComplete: true })).toBe(
      '/labeling/motion?state=unreviewed&review_complete=1',
    );
  });

  it('motionDetailPath 는 상세 URL 에 목록 필터를 그대로 전달한다', () => {
    expect(
      motionDetailPath('clip-1', {
        state: 'unreviewed',
        camera_id: ['cam-1'],
        media: 'ready',
      }),
    ).toBe('/labeling/motion/clip-1?state=unreviewed&camera_id=cam-1&media=ready');
  });

  it('motionQueueScrollKey 는 정규화된 목록 query 로 sessionStorage key 를 만든다', () => {
    expect(motionQueueScrollKey({ state: 'unreviewed' })).toBe(
      'petcam-motion-queue-scroll:state=unreviewed',
    );
  });
});

describe('readStoredMotionQueueScroll', () => {
  it('저장된 스크롤 값을 읽고 즉시 소비(삭제)한다', () => {
    const storage = new MapStorage({ key: '320.5' });
    expect(readStoredMotionQueueScroll(storage, 'key')).toBe(320.5);
    expect(storage.getItem('key')).toBeNull();
  });

  it('값이 없으면 null', () => {
    expect(readStoredMotionQueueScroll(new MapStorage(), 'key')).toBeNull();
  });

  it('음수는 무시한다(null)', () => {
    expect(readStoredMotionQueueScroll(new MapStorage({ key: '-1' }), 'key')).toBeNull();
  });

  it('숫자가 아니면 무시한다(null)', () => {
    expect(readStoredMotionQueueScroll(new MapStorage({ key: 'NaN' }), 'key')).toBeNull();
  });
});

describe('stale generation guard', () => {
  it('늦게 도착한 이전 세대 응답을 폐기한다', () => {
    const gen = createRequestGeneration();
    const g1 = gen.next(); // 요청 1 시작
    gen.next(); // 요청 2 시작(필터 변경)
    // 요청 1 응답이 늦게 도착 → 더 이상 current 가 아님.
    expect(gen.isCurrent(g1)).toBe(false);
  });
});
