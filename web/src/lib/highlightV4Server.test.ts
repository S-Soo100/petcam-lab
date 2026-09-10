import { describe, expect, it } from 'vitest';

import { mapHighlightCurrentRow, mapHighlightInitialRow } from './highlightV4Server';

const initialRow = {
  status: 'decided', initial: true, rule_version: 'hl-rule-v0',
  gme_run_id: '20000000-0000-4000-8000-000000000001',
  reason: '움직임 12.5초 · 최장 연속 6.0초',
  fired: ['long_activity'], shadow: ['early_action'],
  features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 3, first_moving_sec: 0.2, visible_sec: 60, duration_sec: 60 },
};

describe('mapHighlightInitialRow', () => {
  it('공개 필드만 통과시키고 run id는 버린다', () => {
    const out = mapHighlightInitialRow(initialRow);
    expect(out).toEqual({
      status: 'decided', value: true, rule_version: 'hl-rule-v0',
      reason: '움직임 12.5초 · 최장 연속 6.0초', fired: ['long_activity'], shadow: ['early_action'],
      features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 3, first_moving_sec: 0.2, visible_sec: 60 },
    });
    expect(JSON.stringify(out)).not.toContain('20000000');
  });
  it('pending 은 value null 이고 features 없음', () => {
    const out = mapHighlightInitialRow({ ...initialRow, status: 'pending', initial: null, gme_run_id: null, features: null, fired: [], shadow: [] });
    expect(out.status).toBe('pending');
    expect(out.value).toBeNull();
    expect(out.features).toBeNull();
  });
  it('모르는 status 는 throw', () => {
    expect(() => mapHighlightInitialRow({ ...initialRow, status: 'weird' })).toThrow('invalid_highlight_initial');
  });
  it('decided 인데 value 가 null 이면 throw', () => {
    expect(() => mapHighlightInitialRow({ ...initialRow, initial: null })).toThrow('invalid_highlight_initial');
  });
});

describe('mapHighlightCurrentRow', () => {
  it('human 은 reviewer 표시명을 받고 UUID 는 버린다', () => {
    const out = mapHighlightCurrentRow({
      source: 'human', status: 'decided', value: false, rule_version: 'hl-rule-v0', reason: '짧은 움직임 4.9초',
      reviewer_id: '30000000-0000-4000-8000-000000000001', decided_at: '2026-09-08T00:00:00Z', verdict_kind: 'initial',
    }, '김라벨');
    expect(out).toEqual({ source: 'human', status: 'decided', value: false, rule_version: 'hl-rule-v0', reason: '짧은 움직임 4.9초', reviewer_name: '김라벨', decided_at: '2026-09-08T00:00:00Z', verdict_kind: 'initial' });
  });
  it('rule 은 reviewer 없음', () => {
    const out = mapHighlightCurrentRow({ source: 'rule', status: 'pending', value: null, rule_version: 'hl-rule-v0', reason: '분석 대기', reviewer_id: null, decided_at: null, verdict_kind: null }, null);
    expect(out.reviewer_name).toBeNull();
    expect(out.verdict_kind).toBeNull();
  });
});
