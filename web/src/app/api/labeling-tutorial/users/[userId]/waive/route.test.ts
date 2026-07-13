import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, helpers, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  helpers: { loadActiveSetId: vi.fn(), requireApprovedLabelerTarget: vi.fn() },
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('../../../_helpers', () => helpers);

import { POST } from './route';

function post(body: unknown, userId = 'u2') {
  return POST(
    new NextRequest('https://label.tera-ai.uk/x', {
      method: 'POST',
      headers: { authorization: 'Bearer t', 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }),
    { params: { userId } },
  );
}

describe('POST tutorial waive (owner)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
    helpers.requireApprovedLabelerTarget.mockResolvedValue(null);
    helpers.loadActiveSetId.mockResolvedValue('set1');
    rpc.mockResolvedValue({ data: { waived_at: 'now' }, error: null });
  });

  it('non-owner 는 403', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await post({ reason: '사유' })).status).toBe(403);
  });

  it('빈 사유는 400 (target 검증 전)', async () => {
    const res = await post({ reason: '   ' });
    expect(res.status).toBe(400);
    expect(helpers.requireApprovedLabelerTarget).not.toHaveBeenCalled();
  });

  it('201자 사유는 400', async () => {
    expect((await post({ reason: 'x'.repeat(201) })).status).toBe(400);
  });

  it('대상이 labeler 아니면 404', async () => {
    helpers.requireApprovedLabelerTarget.mockResolvedValue(
      NextResponse.json({ detail: 'labeler not found' }, { status: 404 }),
    );
    expect((await post({ reason: '정상 사유' })).status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('valid → fn_waive_tutorial(사유 trim) 호출 200', async () => {
    const res = await post({ reason: '  급한 마감  ' }, 'u2');
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_waive_tutorial', {
      p_set_id: 'set1',
      p_user_id: 'u2',
      p_owner_id: 'owner-1',
      p_reason: '급한 마감',
    });
  });
});
