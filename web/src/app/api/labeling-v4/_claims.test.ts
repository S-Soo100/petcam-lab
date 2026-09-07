import { beforeEach, describe, expect, it, vi } from 'vitest';

const { rpc } = vi.hoisted(() => ({ rpc: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { claimView, pickUnclaimed } from './_claims';

beforeEach(() => vi.clearAllMocks());

describe('pickUnclaimed', () => {
  it('남이 최근에 연 clip 을 건너뛰고 순서를 지킨다', async () => {
    rpc.mockResolvedValue({ data: [{ clip_id: 'a' }, { clip_id: 'b' }], error: null });
    expect(await pickUnclaimed(['a', 'b', 'c', 'd'], 'me')).toBe('c');
    expect(rpc).toHaveBeenCalledWith('fn_fresh_motion_clip_view_claims', { p_clip_ids: ['a', 'b', 'c', 'd'], p_exclude_user: 'me', p_ttl_sec: 120 });
  });
  it('전부 남이 보고 있으면 첫 후보, 조회 실패도 첫 후보, 후보 없으면 null', async () => {
    rpc.mockResolvedValue({ data: [{ clip_id: 'a' }, { clip_id: 'b' }], error: null });
    expect(await pickUnclaimed(['a', 'b'], 'me')).toBe('a');
    rpc.mockResolvedValue({ data: null, error: { code: 'XX' } });
    expect(await pickUnclaimed(['a', 'b'], 'me')).toBe('a');
    expect(await pickUnclaimed([], 'me')).toBeNull();
    expect(rpc).toHaveBeenCalledTimes(2);
  });
});

describe('claimView', () => {
  it('RPC 를 부르고 실패는 삼킨다', async () => {
    rpc.mockRejectedValue(new Error('boom'));
    await expect(claimView('c', 'me')).resolves.toBeUndefined();
    expect(rpc).toHaveBeenCalledWith('fn_claim_motion_clip_view', { p_clip_id: 'c', p_user_id: 'me' });
  });
});
