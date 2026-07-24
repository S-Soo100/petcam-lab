import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireOwner, rpc } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  rpc: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

const GROUP = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const COHORT = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

function req(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/owner/overview${query}`);
}

function overview() {
  return {
    activity_day: '2026-07-22',
    groups: [
      {
        group_id: GROUP,
        group_name: 'A조',
        clip_total: 10,
        members: [
          { display_name: '라벨러 A', submitted_count: 8, email: 'a@x.com', reviewer_id: 'peer-uuid' },
          { display_name: '라벨러 B', submitted_count: 7 },
        ],
        agreed_count: 5,
        conflict_count: 1,
        awaiting_count: 4,
      },
    ],
    open_canaries: [
      { cohort_id: COHORT, label: '카나리', group_id: GROUP, clip_total: 3, submitted_total: 2, conflict_count: 0 },
    ],
  };
}

describe('GET /api/labeling-v3/blind/owner/overview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    rpc.mockResolvedValue({ data: overview(), error: null });
  });

  it('owner 가 아니면 requireOwner 응답 그대로', async () => {
    const { NextResponse } = await import('next/server');
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(req())).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('activity_day 없으면 직전 닫힌 활동일로 기본 호출', async () => {
    await GET(req());
    const arg = rpc.mock.calls[0][1].p_activity_day;
    expect(arg).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('잘못된 activity_day 는 400', async () => {
    const res = await GET(req('?activity_day=2026-13-40'));
    expect(res.status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('집계만 노출 — reviewer UUID·이메일·개별 제출 body 없음', async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.groups[0].members[0].submitted_count).toBe(8);
    const json = JSON.stringify(body);
    expect(json).not.toContain('a@x.com');
    expect(json).not.toContain('reviewer_id');
    expect(json).not.toContain('peer-uuid');
  });
});
