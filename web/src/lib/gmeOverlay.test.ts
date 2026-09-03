import { describe, expect, it } from 'vitest';

import {
  parseGmeOverlayArtifact,
  selectGmeOverlayPoints,
  selectGmeStateAtTime,
} from './gmeOverlay';

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'gme-artifact-v1',
    artifact_identity: { engine_schema_version: 'gme-v1' },
    duration_sec: 60,
    intervals: [
      { start_sec: 0, end_sec: 2, state: 'static', track_ids: ['track-b'] },
      { start_sec: 2, end_sec: 60, state: 'unknown', track_ids: [] },
    ],
    tracking_quality: {},
    track_points: [
      {
        track_id: 'track-b',
        timestamp_sec: 1.2,
        bbox_norm: [0.1, 0.2, 0.3, 0.4],
        confidence: 0.9,
        provenance: 'observed',
      },
      {
        track_id: 'track-a',
        timestamp_sec: 1.25,
        bbox_norm: [0.2, 0.3, 0.2, 0.2],
        confidence: 0.7,
        provenance: 'tracked',
      },
      {
        track_id: 'track-a',
        timestamp_sec: 2,
        bbox_norm: [0.25, 0.3, 0.2, 0.2],
        confidence: 0.6,
        provenance: 'unknown',
      },
    ],
    ...overrides,
  };
}

describe('parseGmeOverlayArtifact', () => {
  it('익명 track index로 변환하고 unknown point는 표시 대상에서 제외한다', () => {
    const parsed = parseGmeOverlayArtifact(artifact());

    expect(parsed.duration_sec).toBe(60);
    expect(parsed.points).toEqual([
      expect.objectContaining({ track_index: 1, timestamp_sec: 1.2, provenance: 'observed' }),
      expect.objectContaining({ track_index: 0, timestamp_sec: 1.25, provenance: 'tracked' }),
    ]);
    expect(parsed.intervals).toEqual([
      { start_sec: 0, end_sec: 2, state: 'static', track_indexes: [1] },
      { start_sec: 2, end_sec: 60, state: 'unknown', track_indexes: [] },
    ]);
    expect(JSON.stringify(parsed)).not.toContain('track-a');
    expect(JSON.stringify(parsed)).not.toContain('track-b');
    expect(JSON.stringify(parsed)).not.toContain('artifact_identity');
  });

  it.each([
    ['schema', { schema_version: 'other' }],
    ['duration', { duration_sec: Number.NaN }],
    ['track_points', { track_points: 'bad' }],
    ['interval overlap', { intervals: [
      { start_sec: 0, end_sec: 3, state: 'static', track_ids: ['track-b'] },
      { start_sec: 2, end_sec: 4, state: 'moving', track_ids: ['track-b'] },
    ] }],
    ['tiny interval overlap', { intervals: [
      { start_sec: 0, end_sec: 2, state: 'static', track_ids: ['track-b'] },
      { start_sec: 1.9999995, end_sec: 4, state: 'moving', track_ids: ['track-b'] },
    ] }],
    ['tiny duration overflow', { intervals: [
      { start_sec: 0, end_sec: 60.0005, state: 'static', track_ids: ['track-b'] },
    ] }],
    ['interval state', { intervals: [
      { start_sec: 0, end_sec: 1, state: 'active', track_ids: ['track-b'] },
    ] }],
    ['interval track', { intervals: [
      { start_sec: 0, end_sec: 1, state: 'moving', track_ids: ['private-track'] },
    ] }],
    ['bbox overflow', { track_points: [{ track_id: 'x', timestamp_sec: 1, bbox_norm: [0.9, 0, 0.2, 0.2], confidence: 1, provenance: 'observed' }] }],
    ['confidence', { track_points: [{ track_id: 'x', timestamp_sec: 1, bbox_norm: [0, 0, 0.2, 0.2], confidence: 2, provenance: 'observed' }] }],
    ['timestamp', { track_points: [{ track_id: 'x', timestamp_sec: 61, bbox_norm: [0, 0, 0.2, 0.2], confidence: 1, provenance: 'observed' }] }],
  ])('잘못된 %s artifact를 거부한다', (_name, overrides) => {
    expect(() => parseGmeOverlayArtifact(artifact(overrides))).toThrow();
  });
});

describe('selectGmeStateAtTime', () => {
  it('현재 track의 반열린 상태 구간을 반환하고 구간 공백은 unknown으로 둔다', () => {
    const intervals = parseGmeOverlayArtifact(artifact()).intervals;

    expect(selectGmeStateAtTime(intervals, 1, 1)).toBe('static');
    expect(selectGmeStateAtTime(intervals, 2, 1)).toBe('unknown');
    expect(selectGmeStateAtTime(intervals, 61, 1)).toBe('unknown');
  });
});

describe('selectGmeOverlayPoints', () => {
  it('현재 시각과 가장 가까운 track별 point만 고른다', () => {
    const points = parseGmeOverlayArtifact({
      ...artifact(),
      intervals: [],
      track_points: [
        { track_id: 'a', timestamp_sec: 1, bbox_norm: [0, 0, 0.2, 0.2], confidence: 1, provenance: 'observed' },
        { track_id: 'a', timestamp_sec: 1.2, bbox_norm: [0.1, 0, 0.2, 0.2], confidence: 1, provenance: 'tracked' },
        { track_id: 'b', timestamp_sec: 1.15, bbox_norm: [0.5, 0, 0.2, 0.2], confidence: 1, provenance: 'interpolated' },
      ],
    }).points;

    expect(selectGmeOverlayPoints(points, 1.16, 0.25).map((p) => p.timestamp_sec)).toEqual([1.2, 1.15]);
    expect(selectGmeOverlayPoints(points, 3, 0.25)).toEqual([]);
  });
});
