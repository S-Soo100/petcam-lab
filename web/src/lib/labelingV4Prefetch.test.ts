import { beforeEach, describe, expect, it, vi } from 'vitest';

import { _resetPrefetchCache, dropPrefetched, isPrefetched, peekPrefetched, prefetchClip, takePrefetched, type PrefetchApi } from './labelingV4Prefetch';
import type { V4ClipDetail } from './labelingV4';

const detail = (id: string, mediaReady = true): V4ClipDetail => ({
  id, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, media_ready: mediaReady,
  highlight: {
    current: { source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: 'r', reviewer_name: null, decided_at: null, verdict_kind: null },
    initial: { status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: 'r', fired: [], shadow: [], features: null },
  },
  behavior_flag: { flagged: false, flagged_by_name: null, flagged_at: null },
});

function api(overrides: Partial<PrefetchApi> = {}): PrefetchApi & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    getV4Clip: vi.fn(async (id: string) => { calls.push(`clip:${id}`); return detail(id); }),
    getV4FileUrl: vi.fn(async (id: string) => { calls.push(`file:${id}`); return { url: `https://r2/${id}.mp4`, expires_in: 600 }; }),
    getV4GmeOverlay: vi.fn(async (id: string) => { calls.push(`overlay:${id}`); return { available: false, overlay_revision: null, duration_sec: 60, points: [], intervals: [] }; }),
    ...overrides,
  };
}

beforeEach(() => _resetPrefetchCache());

describe('prefetchClip / takePrefetched', () => {
  it('메타·서명 URL·overlay 를 한 번에 받아 두고, 꺼내면 지운다', async () => {
    const a = api();
    await prefetchClip('x', a, 1_000_000);
    expect(isPrefetched('x')).toBe(true);
    const hit = takePrefetched('x', 1_000_001);
    expect(hit?.detail.id).toBe('x');
    expect(hit?.fileUrl).toBe('https://r2/x.mp4');
    expect(hit?.overlay?.available).toBe(false);
    expect(takePrefetched('x')).toBeNull();
    expect(a.calls.sort()).toEqual(['clip:x', 'file:x', 'overlay:x']);
  });
  it('peek 은 지우지 않고(StrictMode 이중 mount 대비) drop 이 지운다', async () => {
    await prefetchClip('x', api());
    expect(peekPrefetched('x')?.detail.id).toBe('x');
    expect(peekPrefetched('x')?.detail.id).toBe('x');
    dropPrefetched('x');
    expect(peekPrefetched('x')).toBeNull();
  });
  it('서명 URL 이 만료 30초 전을 지나면 url 만 null 로 돌려준다', async () => {
    await prefetchClip('x', api(), 0);
    const hit = takePrefetched('x', 600_000 - 30_000 + 1);
    expect(hit?.detail.id).toBe('x');
    expect(hit?.fileUrl).toBeNull();
  });
  it('media_ready=false 면 서명 URL 을 요청하지 않는다', async () => {
    const a = api({ getV4Clip: async (id) => detail(id, false) });
    await prefetchClip('x', a);
    expect(a.calls).not.toContain('file:x');
    expect(takePrefetched('x')?.fileUrl).toBeNull();
  });
  it('메타 실패는 조용히 무시, 부분 실패(overlay)는 null 로 채운다', async () => {
    await prefetchClip('x', api({ getV4Clip: async () => { throw new Error('boom'); } }));
    expect(isPrefetched('x')).toBe(false);
    await prefetchClip('y', api({ getV4GmeOverlay: async () => { throw new Error('boom'); } }));
    expect(takePrefetched('y')?.overlay).toBeNull();
  });
  it('같은 clip 동시 요청은 한 번만 부르고, 캐시는 최근 4개만 남긴다', async () => {
    const a = api();
    await Promise.all([prefetchClip('x', a), prefetchClip('x', a)]);
    expect(a.calls.filter((c) => c === 'clip:x')).toHaveLength(1);
    for (const id of ['a', 'b', 'c', 'd']) await prefetchClip(id, a);
    expect(isPrefetched('x')).toBe(false);
    expect(isPrefetched('d')).toBe(true);
  });
});
