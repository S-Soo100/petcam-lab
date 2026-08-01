import { describe, expect, it, vi } from 'vitest';

import {
  getBoundaryEnabled,
  isBoundaryDecision,
  isBoundaryEligibilityDecision,
  mapBoundaryWorkspace,
  mapBoundaryConflicts,
  mapLabelingDashboard,
} from './rbaBoundaryServer';

describe('boundary decision 계약', () => {
  it('세 값만 허용한다', () => {
    expect(isBoundaryDecision('same_event')).toBe(true);
    expect(isBoundaryDecision('different_event')).toBe(true);
    expect(isBoundaryDecision('uncertain')).toBe(true);
    expect(isBoundaryDecision('moving')).toBe(false);
    expect(isBoundaryDecision(null)).toBe(false);
  });
});

describe('eligibility decision 계약', () => {
  it('Owner 자격 판정 다섯 값만 허용한다', () => {
    for (const value of [
      'eligible', 'left_gecko_absent', 'right_gecko_absent',
      'both_gecko_absent', 'capture_or_media_error',
    ]) expect(isBoundaryEligibilityDecision(value)).toBe(true);
    expect(isBoundaryEligibilityDecision('uncertain')).toBe(false);
  });
});

describe('boundary access', () => {
  it('승인 팀원만 assignment RPC를 확인한다', async () => {
    const rpc = vi.fn().mockResolvedValue({ data: { enabled: true }, error: null });
    await expect(getBoundaryEnabled('u1', 'labeler', rpc)).resolves.toBe(true);
    await expect(getBoundaryEnabled('u1', 'owner', rpc)).resolves.toBe(true);
    await expect(getBoundaryEnabled('u1', 'pending', rpc)).resolves.toBe(false);
    expect(rpc).toHaveBeenCalledTimes(2);
  });

  it('DB 오류를 false로 숨기지 않는다', async () => {
    const rpc = vi.fn().mockResolvedValue({ data: null, error: { message: 'down' } });
    await expect(getBoundaryEnabled('u1', 'labeler', rpc)).rejects.toThrow('boundary access');
  });
});

describe('RPC 응답 mapper', () => {
  it('workspace는 필요한 pair 정보만 통과시킨다', () => {
    const mapped = mapBoundaryWorkspace({
      enabled: true,
      mode: 'boundary',
      reviewer_role: 'peer',
      split: 'development',
      total: 60,
      completed: 3,
      next_pair: {
        pair_id: '11111111-1111-4111-8111-111111111111',
        ordinal: 4,
        gap_sec: 29.4,
        gap_bin: 'le30',
        peer_decision: 'same_event',
        left: { clip_id: 'l', started_at: '2026-07-01T01:00:00Z', duration_sec: 30, camera_name: 'A' },
        right: { clip_id: 'r', started_at: '2026-07-01T01:01:00Z', duration_sec: 30, camera_name: 'A' },
      },
    });
    expect(mapped.completed).toBe(3);
    expect(mapped.next_pair?.ordinal).toBe(4);
    expect(JSON.stringify(mapped)).not.toContain('peer_decision');
  });

  it('Owner eligibility와 peer waiting mode를 분리한다', () => {
    const owner = mapBoundaryWorkspace({
      enabled: true, mode: 'eligibility', reviewer_role: 'owner', split: 'development',
      total: 120, completed: 0,
      next_pair: {
        pair_id: '11111111-1111-4111-8111-111111111111', ordinal: 1,
        gap_sec: 10, gap_bin: 'le30',
        left: { clip_id: 'l', started_at: '2026-07-01T01:00:00Z', duration_sec: 30, camera_name: 'A' },
        right: { clip_id: 'r', started_at: '2026-07-01T01:01:00Z', duration_sec: 30, camera_name: 'A' },
      },
    });
    const peer = mapBoundaryWorkspace({
      enabled: true, mode: 'waiting', reviewer_role: 'peer', split: null,
      total: 0, completed: 0, next_pair: null,
    });
    expect(owner.mode).toBe('eligibility');
    expect(owner.total).toBe(120);
    expect(peer).toMatchObject({ mode: 'waiting', next_pair: null });
  });

  it('dashboard 숫자와 행동 분포를 검증한다', () => {
    expect(mapLabelingDashboard({
      video_record_count: 20_000,
      playable_video_count: 17_000,
      gt_labeled_video_count: 2_000,
      behavior_counts: { moving: 1500, drinking: 500 },
      generated_at: '2026-07-31T10:00:00Z',
    })).toEqual({
      video_record_count: 20_000,
      playable_video_count: 17_000,
      gt_labeled_video_count: 2_000,
      behavior_counts: { moving: 1500, drinking: 500 },
      generated_at: '2026-07-31T10:00:00Z',
    });
    expect(() => mapLabelingDashboard({ video_record_count: -1 })).toThrow();
  });

  it('owner conflict는 역할과 판정 두 개만 통과시킨다', () => {
    const mapped = mapBoundaryConflicts({
      total: 1,
      items: [{
        pair_id: 'p1', ordinal: 1, split: 'development', gap_sec: 10, gap_bin: 'le30',
        submissions: [
          { reviewer_role: 'owner', decision: 'uncertain', reviewer_id: 'hidden' },
          { reviewer_role: 'peer', decision: 'uncertain' },
        ],
      }],
    });
    expect(mapped.total).toBe(1);
    expect(JSON.stringify(mapped)).not.toContain('reviewer_id');
  });
});
