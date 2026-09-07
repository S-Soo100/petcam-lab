import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireOwner, rpc } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

beforeEach(() => {
  vi.clearAllMocks();
  requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  rpc.mockResolvedValue({ data: [{ rule_version: 'hl-rule-v0', camera_id: 'c1', camera_name: '거실', verdict_count: 40, kept_count: 30, o_to_x: 7, x_to_o: 3, pending_initial: 0, reason_counts: { false_detection: 5 } }], error: null });
});

describe('GET highlight-stats', () => {
  it('기본 7일 범위로 집계를 돌려주고 유지율을 계산한다', async () => {
    const body = await (await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/highlight-stats'))).json();
    expect(body.rows[0].kept_ratio).toBe(0.75);
    const args = rpc.mock.calls[0][1] as { p_from: string; p_to: string };
    expect(new Date(args.p_to).getTime() - new Date(args.p_from).getTime()).toBe(7 * 24 * 3600 * 1000);
  });
  it('from/to 를 받는다, 잘못되면 400', async () => {
    const ok = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/highlight-stats?from=2026-09-01&to=2026-09-08'));
    expect(ok.status).toBe(200);
    expect((rpc.mock.calls[0][1] as { p_from: string }).p_from).toBe('2026-09-01T00:00:00.000Z');
    const bad = await GET(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/owner/highlight-stats?from=zzz'));
    expect(bad.status).toBe(400);
  });
});
