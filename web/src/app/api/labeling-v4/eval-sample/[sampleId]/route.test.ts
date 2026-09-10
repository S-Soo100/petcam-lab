import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const req = (id: string) => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/eval-sample/${id}`);

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
});

describe('GET /api/labeling-v4/eval-sample/[sampleId]', () => {
  it('진행 수를 숫자로 정규화한다', async () => {
    rpc.mockResolvedValue({ data: [{ total: '100', labeled: 57 }], error: null });
    const body = await (await GET(req('eval-2026-09'), { params: { sampleId: 'eval-2026-09' } })).json();
    expect(body).toEqual({ sample_id: 'eval-2026-09', total: 100, labeled: 57 });
    expect(rpc).toHaveBeenCalledWith('fn_eval_sample_progress', { p_sample_id: 'eval-2026-09' });
  });
  it('잘못된 id 는 DB 전 400', async () => {
    expect((await GET(req('BAD%20id'), { params: { sampleId: 'BAD id' } })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
