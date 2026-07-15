import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const CLIP = '380d97fd-0000-4000-8000-000000000001';

function req(body?: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-triage/${CLIP}/quarantine`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

describe('POST /api/labeling-triage/[clipId]/quarantine', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
    rpc.mockResolvedValue({ data: { ok: true, changed: true }, error: null });
  });

  it('returns the owner guard response unchanged', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await POST(req({}), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a non-UUID clip id', async () => {
    const res = await POST(req({}), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('rejects a note over 500 chars', async () => {
    const res = await POST(req({ note: 'x'.repeat(501) }), { params: { clipId: CLIP } });
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('quarantines with the owner as actor', async () => {
    const res = await POST(req({ note: '빈 그릇' }), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_manual_quarantine_clip_for_labeling', {
      p_clip_id: CLIP,
      p_actor_id: 'owner-1',
      p_note: '빈 그릇',
    });
    expect(await res.json()).toEqual({ ok: true, changed: true });
  });

  it('accepts an empty body', async () => {
    const res = await POST(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_manual_quarantine_clip_for_labeling', {
      p_clip_id: CLIP,
      p_actor_id: 'owner-1',
      p_note: null,
    });
  });

  it('maps not_found to 404', async () => {
    rpc.mockResolvedValue({ data: { ok: false, code: 'not_found' }, error: null });
    const res = await POST(req({}), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });

  it('maps labeling_started to 409', async () => {
    rpc.mockResolvedValue({ data: { ok: false, code: 'labeling_started' }, error: null });
    const res = await POST(req({}), { params: { clipId: CLIP } });
    expect(res.status).toBe(409);
  });

  it('maps an unexpected RPC error to a generic 502', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: '08006', message: 'clip_labeling_triage lost' } });
    const res = await POST(req({}), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('clip_labeling_triage');
  });
});
