import { describe, expect, it } from 'vitest';

import { mapV4ClipRow, parseV4ListRequest } from './labelingV4Server';

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
    expect(mapV4ClipRow(row, resolve)).toEqual({ id: row.clip_id, camera_id: 'c1', camera_name: '거실', started_at: row.started_at, duration_sec: 60.6, media_ready: true, highlight: { source: 'rule', status: 'decided', value: true, reason: row.highlight_reason, reviewer_name: null, decided_at: null }, behavior_flag: { flagged: false, flagged_by_name: null, flagged_at: null }, thumbnail_url: null });
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
