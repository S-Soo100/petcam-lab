import { describe, expect, it } from 'vitest';

import { mapOwnerCleanupRow } from './rbaOwnerMediaCleanup';

describe('mapOwnerCleanupRow', () => {
  it('공개 allowlist만 반환하고 raw R2 key/GT/owner id를 버린다', () => {
    const item = mapOwnerCleanupRow({
      clip_id: '11111111-1111-4111-8111-111111111111',
      started_at: '2026-07-14T12:00:00Z',
      duration_sec: 30,
      camera_name: '카메라 A',
      seed_reason: 'owner_review_pending',
      state: 'quarantined',
      has_canonical_gt: false,
      decision: null,
      r2_key: 'secret/key.mp4',
      owner_id: 'private-owner',
      final_gt: { primary_action: 'secret' },
    });
    expect(item).toEqual({
      clip_id: '11111111-1111-4111-8111-111111111111',
      started_at: '2026-07-14T12:00:00Z',
      duration_sec: 30,
      camera_name: '카메라 A',
    });
    expect(JSON.stringify(item)).not.toContain('secret');
    expect(JSON.stringify(item)).not.toContain('private-owner');
  });
});
