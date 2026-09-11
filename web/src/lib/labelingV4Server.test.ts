import { describe, expect, it } from 'vitest';

import { dayKeyOf, dayKeyStartUtc, featuredWindowDays, featuredWindowFor, mapFeaturedInfo, mapFeaturedRowToItem, mapV4ClipRow, parseV4FeaturedRequest, parseV4ListRequest } from './labelingV4Server';
import { featuredBadgeText, featuredLineText } from './labelingV4';

describe('featured tier — 하루 키(20시 KST 경계)', () => {
  it('dayKeyOf: 19:30 KST 는 전날, 20:10 KST 는 당일, 05:00 KST 는 전날 키', () => {
    expect(dayKeyOf('2026-09-01T10:30:00Z')).toBe('2026-08-31');
    expect(dayKeyOf('2026-09-01T11:10:00Z')).toBe('2026-09-01');
    expect(dayKeyOf('2026-09-01T20:00:00Z')).toBe('2026-09-01');
  });
  it('dayKeyStartUtc: 키의 20:00 KST = 11:00Z', () => {
    expect(dayKeyStartUtc('2026-09-01').toISOString()).toBe('2026-09-01T11:00:00.000Z');
  });
  it('featuredWindowFor: 항목들의 하루 키를 덮는 [from, to)', () => {
    expect(featuredWindowFor(['2026-09-01T10:30:00Z', '2026-09-03T12:00:00Z'])).toEqual({ from: '2026-08-31T11:00:00.000Z', to: '2026-09-04T11:00:00.000Z' });
    expect(featuredWindowFor([])).toBeNull();
  });
  it('featuredWindowDays: 오늘 키 기준 최근 N일', () => {
    const now = new Date('2026-09-10T01:00:00Z'); // 10:00 KST → 오늘 키 09-09
    expect(featuredWindowDays(now, 7)).toEqual({ from: '2026-09-03T11:00:00.000Z', to: now.toISOString() });
  });
});

describe('featured tier — 매퍼·문구', () => {
  const row = { clip_id: '00000000-0000-4000-8000-000000000009', camera_id: 'c1', camera_name: '거실', started_at: '2026-09-09T12:00:00Z', duration_sec: 60, day_key: '2026-09-09', episode_no: 2, episode_started_at: '2026-09-09T12:00:00Z', episode_ended_at: '2026-09-09T12:06:00Z', episode_clip_count: 6, episode_activity_sec: 84, episode_rank: 2, episode_hour_rank: 1, tier: 'featured', is_representative: true, activity_sec: 20.5, highlight_source: 'rule', highlight_reason: '움직임 20.5초 · 최장 연속 9.0초', reviewer_id: null, reviewer_display_name: null, behavior_flagged: false };
  it('mapFeaturedInfo', () => {
    expect(mapFeaturedInfo(row, null)).toEqual({ tier: 'featured', day_key: '2026-09-09', episode_rank: 2, episode_hour_rank: 1, episode_clip_count: 6, episode_activity_sec: 84, is_representative: true, top_n: null });
    expect(() => mapFeaturedInfo({ ...row, tier: 'best' }, 3)).toThrow('invalid_featured_row');
  });
  it('mapFeaturedRowToItem: 카드 항목 + reviewer UUID 비노출', () => {
    const REVIEWER = '30000000-0000-4000-8000-000000000001';
    const out = mapFeaturedRowToItem({ ...row, highlight_source: 'human', reviewer_id: REVIEWER, reviewer_display_name: '김라벨' }, 3, (id, name) => `${name}<${id.slice(0, 8)}>`);
    expect(out.highlight).toEqual({ source: 'human', status: 'decided', value: true, reason: row.highlight_reason, reviewer_name: '김라벨<30000000>', decided_at: null });
    expect(out.featured?.tier).toBe('featured');
    expect(JSON.stringify(out)).not.toContain(REVIEWER);
  });
  it('문구', () => {
    const f = mapFeaturedInfo(row, 3);
    expect(featuredBadgeText(f)).toBe('⭐ 대표 2위');
    expect(featuredLineText(f)).toBe('⭐ 이 날 대표 2위 · 사건 6클립 · 움직임 84초');
    expect(featuredBadgeText({ ...f, tier: 'candidate' })).toBe('후보');
    expect(featuredLineText({ ...f, tier: 'candidate', is_representative: false })).toBe('후보 · 같은 사건의 다른 클립(사건 2위) · 사건 6클립 · 움직임 84초');
    expect(featuredLineText(null)).toBeNull();
  });
  it('parseV4FeaturedRequest', () => {
    expect(parseV4FeaturedRequest(new URLSearchParams('days=7&camera_id=00000000-0000-4000-8000-000000000001'))).toEqual({ days: 7, cameraIds: ['00000000-0000-4000-8000-000000000001'] });
    expect(parseV4FeaturedRequest(new URLSearchParams(''))).toEqual({ days: 7, cameraIds: null });
    expect(() => parseV4FeaturedRequest(new URLSearchParams('days=40'))).toThrow('invalid_days');
  });
});

describe('parseV4ListRequest', () => {
  it('기본값과 허용 필터', () => {
    const sp = new URLSearchParams('scope=mine&camera_id=11111111-1111-4111-8111-111111111111&label_state=unlabeled&highlight_state=yes&limit=20');
    expect(parseV4ListRequest(sp)).toEqual({ scope: 'mine', cameraIds: ['11111111-1111-4111-8111-111111111111'], labelState: 'unlabeled', highlightState: 'yes', behaviorFlag: null, sampleId: null, limit: 20 });
    expect(parseV4ListRequest(new URLSearchParams('scope=all&sample=eval-2026-09')).sampleId).toBe('eval-2026-09');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&sample=BAD id'))).toThrow('invalid_sample');
    expect(parseV4ListRequest(new URLSearchParams('scope=all'))).toEqual({ scope: 'all', cameraIds: null, labelState: null, highlightState: null, behaviorFlag: null, sampleId: null, limit: 30 });
  });
  it('잘못된 값은 throw', () => {
    expect(() => parseV4ListRequest(new URLSearchParams('scope=theirs'))).toThrow('invalid_scope');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&camera_id=nope'))).toThrow('invalid_camera_id');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&limit=500'))).toThrow('invalid_limit');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&highlight_state=maybe'))).toThrow('invalid_highlight_state');
  });
});

describe('mapV4ClipRow', () => {
  const REVIEWER = '30000000-0000-4000-8000-000000000001';
  const resolve = (id: string, name: string | null) => `${name ?? '라벨러'}<${id.slice(0, 8)}>`;
  const row = { clip_id: '00000000-0000-4000-8000-000000000001', camera_id: 'c1', camera_name: '거실', started_at: '2026-09-08T10:00:00Z', duration_sec: 60.6, media_ready: true, highlight_source: 'rule', highlight_status: 'decided', highlight_value: true, highlight_reason: '움직임 12.5초 · 최장 연속 6.0초', reviewer_id: null, reviewer_display_name: null, decided_at: null, behavior_flagged: false, behavior_flagged_by: null, behavior_flagged_by_display_name: null, behavior_flagged_at: null };
  it('공개 필드만', () => {
    expect(mapV4ClipRow(row, resolve)).toEqual({ id: row.clip_id, camera_id: 'c1', camera_name: '거실', started_at: row.started_at, duration_sec: 60.6, media_ready: true, highlight: { source: 'rule', status: 'decided', value: true, reason: row.highlight_reason, reviewer_name: null, decided_at: null }, behavior_flag: { flagged: false, flagged_by_name: null, flagged_at: null }, thumbnail_url: null, featured: null });
  });
  it('human 은 resolver 로 표시명만 남기고 reviewer_id·raw 이름은 공개 JSON 에 없다', () => {
    const human = { ...row, highlight_source: 'human', highlight_value: false, reviewer_id: REVIEWER, reviewer_display_name: '김라벨', decided_at: '2026-09-08T11:00:00Z' };
    const out = mapV4ClipRow(human, resolve);
    expect(out.highlight.reviewer_name).toBe('김라벨<30000000>');
    expect(out.highlight.decided_at).toBe('2026-09-08T11:00:00Z');
    expect(Object.keys(out.highlight)).not.toContain('reviewer_id');
    expect(JSON.stringify(out)).not.toContain(REVIEWER);
    // rule 행은 resolver 를 부르지 않는다(reviewer 없음).
    const calls: string[] = [];
    mapV4ClipRow(row, (id) => { calls.push(id); return id; });
    expect(calls).toEqual([]);
  });
  it('모르는 source/status, human 인데 reviewer_id 없음은 throw', () => {
    expect(() => mapV4ClipRow({ ...row, highlight_source: 'ai' }, resolve)).toThrow('invalid_v4_clip_row');
    expect(() => mapV4ClipRow({ ...row, highlight_status: 'weird' }, resolve)).toThrow('invalid_v4_clip_row');
    expect(() => mapV4ClipRow({ ...row, highlight_source: 'human', reviewer_id: null }, resolve)).toThrow('invalid_v4_clip_row');
  });
});
