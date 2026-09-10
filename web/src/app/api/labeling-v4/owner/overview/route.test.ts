import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({ readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }) }));

import { GET } from './route';

const OWNER = '30000000-0000-4000-8000-000000000002';
const LABELER = '30000000-0000-4000-8000-000000000001';
const ANON = '30000000-0000-4000-8000-000000000003';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: OWNER });
  rpc.mockImplementation(async (name: string) => {
    if (name === 'fn_gme_contract_coverage') return { data: { last7d_total: '1006', last7d_with_run: 1006, all_total: 26761, all_with_run: '12530' }, error: null };
    return { data: { activity_day: '2026-09-08', unlabeled_total: 120, labeled_today: 12, labeled_7d: 80, members: [
      { user_id: LABELER, display_name: '김라벨', labeled_7d: 50 },
      { user_id: OWNER, display_name: null, labeled_7d: 20 },
      { user_id: ANON, display_name: null, labeled_7d: 10 },
    ], cameras: [] }, error: null };
  });
});
afterEach(() => { delete process.env.DEV_USER_ID; });

describe('GET owner overview', () => {
  it('집계는 그대로, members 표시명은 단일 resolver(Owner/이름/라벨러)로 해석하고 user_id 를 싣는다', async () => {
    process.env.DEV_USER_ID = OWNER;
    const body = await (await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/overview'))).json();
    expect(body.unlabeled_total).toBe(120);
    expect(body.members).toEqual([
      { user_id: LABELER, display_name: '김라벨', labeled_7d: 50 },
      { user_id: OWNER, display_name: 'Owner', labeled_7d: 20 },
      { user_id: ANON, display_name: '라벨러', labeled_7d: 10 },
    ]);
    expect(rpc).toHaveBeenCalledWith('fn_get_labeling_v4_overview', { p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64) });
    expect(body.coverage).toEqual({ last7d_total: 1006, last7d_with_run: 1006, all_total: 26761, all_with_run: 12530 });
  });
  it('커버리지 RPC 가 실패해도 현황은 뜨고 coverage 는 null', async () => {
    process.env.DEV_USER_ID = OWNER;
    rpc.mockImplementation(async (name: string) => name === 'fn_gme_contract_coverage'
      ? { data: null, error: { code: '42883', message: 'missing' } }
      : { data: { activity_day: '2026-09-08', unlabeled_total: 1, labeled_today: 0, labeled_7d: 0, members: [], cameras: [] }, error: null });
    const body = await (await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/overview'))).json();
    expect(body.unlabeled_total).toBe(1);
    expect(body.coverage).toBeNull();
  });
});
