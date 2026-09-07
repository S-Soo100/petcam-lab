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
  it('POST 에 version 만 있으면 기존 버전을 재활성화한다', async () => {
    rpc.mockResolvedValue({ data: [{ version: 'hl-rule-v0', activated_at: '2026-09-08T02:00:00Z' }], error: null });
    const res = await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v0' }) }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ version: 'hl-rule-v0', activated_at: '2026-09-08T02:00:00Z' });
    expect(rpc).toHaveBeenCalledWith('fn_activate_highlight_rule_version', { p_version: 'hl-rule-v0', p_actor_id: 'owner-1' });
    expect(rpc).not.toHaveBeenCalledWith('fn_create_highlight_rule_version', expect.anything());
  });
  it('모르는 버전 재활성화는 DB P0002 → 404, 빠진 숫자 키는 22023 → 400', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'P0002' } });
    expect((await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v9' }) }))).status).toBe(404);
    rpc.mockResolvedValue({ data: null, error: { code: '22023' } });
    const bad = await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ version: 'hl-rule-v2', params: { triggers: [{ name: 'frequent_bursts', on: true, activity_sec_gte: 3 }] } }) }));
    expect(bad.status).toBe(400);
    expect(rpc).toHaveBeenLastCalledWith('fn_create_highlight_rule_version', expect.objectContaining({ p_version: 'hl-rule-v2' }));
  });
  it('version 도 params 도 없으면 400, RPC 호출 없음', async () => {
    expect((await POST(new NextRequest(URL, { method: 'POST', body: JSON.stringify({ note: 'x' }) }))).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('owner 아니면 가드 응답', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: new Response(null, { status: 403 }) });
    expect((await GET(new NextRequest(URL))).status).toBe(403);
  });
});
