import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({ readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }) }));

import { GET } from './route';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  rpc.mockResolvedValue({ data: { activity_day: '2026-09-08', unlabeled_total: 120, labeled_today: 12, labeled_7d: 80, members: [{ display_name: '김라벨', labeled_7d: 50 }], cameras: [] }, error: null });
});

describe('GET owner overview', () => {
  it('jsonb 를 그대로 돌려준다', async () => {
    const body = await (await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/overview'))).json();
    expect(body.unlabeled_total).toBe(120);
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_v4_overview', { p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64) });
  });
});
