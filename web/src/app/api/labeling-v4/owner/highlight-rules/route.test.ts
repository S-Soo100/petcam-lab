import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET, POST } from './route';

const URL = 'https://label.tera-ai.uk/api/labeling-v4/owner/highlight-rules';
const params = { triggers: [{ name: 'long_activity', on: true, activity_sec_gte: 12 }, { name: 'sustained_move', on: true, longest_sec_gte: 5 }], guards: [] };

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
});

describe('highlight-rules', () => {
  it('GET 은 active 규칙을 돌려준다', async () => {
    rpc.mockResolvedValue({ data: [{ version: 'hl-rule-v0', params, activated_at: '2026-09-08T00:00:00Z' }], error: null });
    const body = await (await GET(new NextRequest(URL))).json();
    expect(body.version).toBe('hl-rule-v0');
    expect(rpc).toHaveBeenCalledWith('fn_get_active_highlight_rule', {});
  });
  it('POST 는 버전을 만들고 활성화한다', async () => {
    rpc.mockResolvedValue({ data: [{ version: 'hl-rule-v1', activated_at: '2026-09-08T01:00:00Z' }], error: null });
    const res = await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v1', params, note: '10→12' }) }));
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_create_highlight_rule_version', { p_version: 'hl-rule-v1', p_params: params, p_note: '10→12', p_actor_id: 'owner-1' });
  });
  it('버전 형식·모르는 트리거는 400', async () => {
    expect((await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'v1', params }) }))).status).toBe(400);
    expect((await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v1', params: { triggers: [{ name: 'nope', on: true }] } }) }))).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('owner 아니면 가드 응답', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: new Response(null, { status: 403 }) });
    expect((await GET(new NextRequest(URL))).status).toBe(403);
  });
});
