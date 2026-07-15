import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from } = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  from: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { GET } from './route';

const CAM = '380d97fd-0000-4000-8000-0000000000aa';

// 모든 체이닝 메서드가 self 를 반환하고, await 하면 preset 결과로 resolve 되는 stub.
function chain(result: unknown) {
  const c: Record<string, unknown> = {};
  for (const m of ['select', 'is', 'eq', 'or', 'order', 'limit', 'neq', 'in', 'gte', 'lte']) {
    c[m] = vi.fn(() => c);
  }
  c.then = (resolve: (v: unknown) => unknown) => resolve(result);
  return c;
}

function joinRow() {
  return {
    clip_id: '380d97fd-0000-4000-8000-000000000001',
    suggested_route: 'quarantine',
    suggestion_reason: 'gate_absent',
    suggestion_source: 'gate_activity_policy',
    policy_version: 'gate-v2',
    owner_decision: null,
    decided_at: null,
    decision_note: null,
    updated_at: '2026-07-15T00:00:00.000Z',
    evidence_snapshot: { checkpoint: '/secret/path.pt', producer_host: 'mac-mini.local' },
    camera_clips: {
      camera_id: 'cam-1',
      started_at: '2026-07-14T18:00:00.000Z',
      duration_sec: 42,
    },
  };
}

function listOk() {
  from
    .mockReturnValueOnce(chain({ data: [joinRow()], error: null })) // 목록
    .mockReturnValueOnce(chain({ count: 3, error: null })) // pending count
    .mockReturnValueOnce(chain({ count: 1, error: null })) // skipped count
    .mockReturnValueOnce(chain({ count: 2, error: null })); // labeled count
}

function req(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-triage${query}`);
}

describe('GET /api/labeling-triage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
  });

  it('returns the owner guard response unchanged', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req('?state=pending'));
    expect(res.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
  });

  it('rejects an invalid state', async () => {
    const res = await GET(req('?state=bogus'));
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('rejects an out-of-range limit', async () => {
    const res = await GET(req('?state=pending&limit=999'));
    expect(res.status).toBe(400);
  });

  it('rejects an invalid cursor', async () => {
    const res = await GET(req('?state=pending&cursor=!!!bad'));
    expect(res.status).toBe(400);
  });

  it('returns a generic 502 on a Supabase error without leaking the table or message', async () => {
    from.mockReturnValueOnce(chain({ data: null, error: { message: 'relation clip_labeling_triage does not exist' } }));
    const res = await GET(req('?state=pending'));
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(JSON.stringify(body)).not.toContain('clip_labeling_triage');
    expect(JSON.stringify(body)).not.toContain('relation');
  });

  it('returns items, counts and pagination without raw evidence', async () => {
    listOk();
    const res = await GET(req('?state=pending&limit=30'));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items).toHaveLength(1);
    expect(body.counts).toEqual({ pending: 3, skipped: 1, labeled: 2 });
    expect(body.has_more).toBe(false);
    expect(body.items[0].reason_label).toBe('게코가 보이지 않을 가능성이 높음');
    expect(JSON.stringify(body)).not.toContain('evidence_snapshot');
    expect(JSON.stringify(body)).not.toContain('checkpoint');
    expect(JSON.stringify(body)).not.toContain('producer_host');
  });

  it('rejects an invalid date filter', async () => {
    const res = await GET(req('?state=pending&date_from=not-a-date'));
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('rejects a non-UUID camera filter', async () => {
    const res = await GET(req('?state=pending&camera_id=bogus'));
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });

  it('applies date/camera filters to both the list query and every count query', async () => {
    listOk();
    const res = await GET(
      req(
        `?state=pending&date_from=2026-07-01T00:00:00%2B09:00&date_to=2026-07-02T00:00:00%2B09:00&camera_id=${CAM}`,
      ),
    );
    expect(res.status).toBe(200);
    // 목록 + 3개 count = from 4회. 각각에 동일 필터가 걸린다.
    expect(from).toHaveBeenCalledTimes(4);
    for (let i = 0; i < 4; i += 1) {
      const q = from.mock.results[i].value as Record<string, ReturnType<typeof vi.fn>>;
      expect(q.eq).toHaveBeenCalledWith('camera_clips.camera_id', CAM);
      expect(q.gte).toHaveBeenCalledWith('camera_clips.started_at', '2026-07-01T00:00:00+09:00');
      expect(q.lte).toHaveBeenCalledWith('camera_clips.started_at', '2026-07-02T00:00:00+09:00');
    }
  });

  it('keeps filters alongside the cursor keyset on paginated requests', async () => {
    listOk();
    const cursor = Buffer.from(
      JSON.stringify({ updatedAt: '2026-07-15T00:00:00.000Z', clipId: CAM }),
    ).toString('base64url');
    const res = await GET(req(`?state=pending&camera_id=${CAM}&cursor=${cursor}`));
    expect(res.status).toBe(200);
    const listChain = from.mock.results[0].value as Record<string, ReturnType<typeof vi.fn>>;
    expect(listChain.eq).toHaveBeenCalledWith('camera_clips.camera_id', CAM);
    expect(listChain.or).toHaveBeenCalled(); // cursor keyset 도 함께 적용
  });
});
