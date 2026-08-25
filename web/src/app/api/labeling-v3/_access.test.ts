import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireOwner, from } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { loadMotionClipAccess } from './_access';

const CLIP = '11111111-1111-4111-8111-111111111111';
const OWNER = '22222222-2222-4222-8222-222222222222';

function query(table: string) {
  let columns = '';
  const chain: Record<string, unknown> = {};
  chain.select = vi.fn((value: string) => {
    columns = value;
    return chain;
  });
  chain.eq = vi.fn(() => chain);
  chain.limit = vi.fn(() => chain);
  chain.then = (resolve: (value: unknown) => unknown) => {
    if (table === 'motion_clips') {
      return resolve({
        data: [{
          id: CLIP,
          camera_id: '33333333-3333-4333-8333-333333333333',
          started_at: '2026-08-25T09:00:00Z',
          duration_sec: 60,
          r2_key: 'terra-clips/clips/video.mp4',
          clip_purpose: 'production',
          cameras: { name: '카메라' },
        }],
        error: null,
      });
    }
    if (table === 'motion_clip_labeling_triage') {
      return resolve({ data: [{ owner_decision: 'label', updated_at: '2026-08-25T09:01:00Z' }], error: null });
    }
    if (table === 'motion_clip_labeling_sessions' && columns === 'clip_id') {
      return resolve({ data: [{ clip_id: CLIP }], error: null });
    }
    if (table === 'motion_clip_labeling_sessions') {
      return resolve({ data: [], error: null });
    }
    return resolve({ data: [], error: null });
  };
  return chain;
}

describe('loadMotionClipAccess', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: OWNER });
    from.mockImplementation((table: string) => query(table));
  });

  it('Owner 본인 세션이 없어도 다른 사람 세션이 있으면 labelingStarted를 true로 반환한다', async () => {
    const result = await loadMotionClipAccess(
      new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/${CLIP}`),
      CLIP,
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.session).toBeNull();
    expect(result.labelingStarted).toBe(true);
  });
});
