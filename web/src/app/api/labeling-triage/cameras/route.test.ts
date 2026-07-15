import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

function req() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-triage/cameras');
}

describe('GET /api/labeling-triage/cameras', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  });

  it('returns the owner guard response unchanged', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req());
    expect(res.status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('returns triage-target camera options via the distinct RPC', async () => {
    rpc.mockResolvedValue({
      data: [
        { camera_id: 'cam-a', name: '거실 캠' },
        { camera_id: 'cam-b', name: null },
      ],
      error: null,
    });
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_triage_camera_options');
    const body = await res.json();
    expect(body.cameras).toEqual([
      { camera_id: 'cam-a', name: '거실 캠' },
      { camera_id: 'cam-b', name: 'cam-b' }, // name 없으면 id 로 대체
    ]);
  });

  it('returns a generic 502 on a Supabase error', async () => {
    rpc.mockResolvedValue({ data: null, error: { message: 'boom clip_labeling_triage' } });
    const res = await GET(req());
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('clip_labeling_triage');
  });
});
