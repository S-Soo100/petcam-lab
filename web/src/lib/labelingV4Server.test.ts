import { describe, expect, it } from 'vitest';

import { mapV4ClipRow, parseV4ListRequest } from './labelingV4Server';

describe('parseV4ListRequest', () => {
  it('기본값과 허용 필터', () => {
    const sp = new URLSearchParams('scope=mine&camera_id=11111111-1111-4111-8111-111111111111&label_state=unlabeled&highlight_state=yes&limit=20');
    expect(parseV4ListRequest(sp)).toEqual({ scope: 'mine', cameraIds: ['11111111-1111-4111-8111-111111111111'], labelState: 'unlabeled', highlightState: 'yes', limit: 20 });
    expect(parseV4ListRequest(new URLSearchParams('scope=all'))).toEqual({ scope: 'all', cameraIds: null, labelState: null, highlightState: null, limit: 30 });
  });
  it('잘못된 값은 throw', () => {
    expect(() => parseV4ListRequest(new URLSearchParams('scope=theirs'))).toThrow('invalid_scope');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&camera_id=nope'))).toThrow('invalid_camera_id');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&limit=500'))).toThrow('invalid_limit');
    expect(() => parseV4ListRequest(new URLSearchParams('scope=all&highlight_state=maybe'))).toThrow('invalid_highlight_state');
  });
});

describe('mapV4ClipRow', () => {
  const row = { clip_id: '00000000-0000-4000-8000-000000000001', camera_id: 'c1', camera_name: '거실', started_at: '2026-09-08T10:00:00Z', duration_sec: 60.6, media_ready: true, highlight_source: 'rule', highlight_status: 'decided', highlight_value: true, highlight_reason: '움직임 12.5초 · 최장 연속 6.0초', reviewer_name: null, decided_at: null };
  it('공개 필드만', () => {
    expect(mapV4ClipRow(row)).toEqual({ id: row.clip_id, camera_id: 'c1', camera_name: '거실', started_at: row.started_at, duration_sec: 60.6, media_ready: true, highlight: { source: 'rule', status: 'decided', value: true, reason: row.highlight_reason, reviewer_name: null, decided_at: null } });
  });
  it('모르는 source/status 는 throw', () => {
    expect(() => mapV4ClipRow({ ...row, highlight_source: 'ai' })).toThrow('invalid_v4_clip_row');
    expect(() => mapV4ClipRow({ ...row, highlight_status: 'weird' })).toThrow('invalid_v4_clip_row');
  });
});
