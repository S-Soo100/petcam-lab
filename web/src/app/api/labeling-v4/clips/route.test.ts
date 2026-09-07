import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/labelingV3Server', () => ({ readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }) }));

import { GET } from './route';
import { encodeQueueCursor } from '@/lib/labelingQueueCursor';

const row = (i: number) => ({ clip_id: `0000000${i}-0000-4000-8000-000000000001`, camera_id: 'c1', camera_name: '거실', started_at: `2026-09-08T0${i}:00:00Z`, duration_sec: 60, media_ready: true, highlight_source: 'rule', highlight_status: 'decided', highlight_value: i % 2 === 0, highlight_reason: 'r', reviewer_id: null, reviewer_display_name: null, decided_at: null });
const REVIEWER = '30000000-0000-4000-8000-000000000001';
const req = (qs: string) => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips?${qs}`);

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
});

describe('GET /api/labeling-v4/clips', () => {
  it('limit+1 로 has_more 와 cursor 를 만든다', async () => {
    rpc.mockResolvedValue({ data: [row(3), row(2), row(1)], error: null });
    const res = await GET(req('scope=all&limit=2'));
    const body = await res.json();
    expect(body.items).toHaveLength(2);
    expect(body.has_more).toBe(true);
    expect(body.next_cursor).toBe(encodeQueueCursor({ startedAt: row(2).started_at, id: row(2).clip_id }));
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_viewer_id: 'u1', p_is_owner: false, p_scope: 'all', p_limit: 3, p_cursor_started_at: null, p_cursor_id: null });
  });
  it('cursor 를 RPC 에 풀어 넘긴다', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    const cursor = encodeQueueCursor({ startedAt: '2026-09-08T02:00:00Z', id: row(2).clip_id });
    await GET(req(`scope=mine&cursor=${encodeURIComponent(cursor)}`));
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_scope: 'mine', p_cursor_started_at: '2026-09-08T02:00:00Z', p_cursor_id: row(2).clip_id });
  });
  it('human 행은 표시명만 싣고 reviewer UUID·raw 이름 컬럼을 공개 JSON 에서 뺀다', async () => {
    rpc.mockResolvedValue({ data: [
      { ...row(2), highlight_source: 'human', reviewer_id: REVIEWER, reviewer_display_name: '김라벨', decided_at: '2026-09-08T03:00:00Z' },
      { ...row(1), highlight_source: 'human', reviewer_id: REVIEWER, reviewer_display_name: null, decided_at: '2026-09-08T03:00:00Z' },
    ], error: null });
    const body = await (await GET(req('scope=all'))).json();
    expect(body.items[0].highlight.reviewer_name).toBe('김라벨');
    expect(body.items[1].highlight.reviewer_name).toBe('라벨러');
    const text = JSON.stringify(body);
    expect(text).not.toContain(REVIEWER);
    expect(text).not.toContain('reviewer_id');
    expect(text).not.toContain('reviewer_display_name');
  });
  it('behavior_flag=yes 를 RPC 에 넘기고 행의 체크 정보를 표시명으로 접는다', async () => {
    rpc.mockResolvedValue({ data: [
      { ...row(2), behavior_flagged: true, behavior_flagged_by: REVIEWER, behavior_flagged_by_display_name: '김라벨', behavior_flagged_at: '2026-09-08T04:00:00Z' },
      { ...row(1) },
    ], error: null });
    const body = await (await GET(req('scope=all&behavior_flag=yes'))).json();
    expect(rpc.mock.calls[0][1]).toMatchObject({ p_behavior_flag: 'yes' });
    expect(body.items[0].behavior_flag).toEqual({ flagged: true, flagged_by_name: '김라벨', flagged_at: '2026-09-08T04:00:00Z' });
    expect(body.items[1].behavior_flag).toEqual({ flagged: false, flagged_by_name: null, flagged_at: null });
    expect(JSON.stringify(body)).not.toContain('behavior_flagged_by');
    expect((await GET(req('scope=all&behavior_flag=no'))).status).toBe(400);
  });
  it('잘못된 scope/cursor 는 DB 전 400', async () => {
    expect((await GET(req('scope=theirs'))).status).toBe(400);
    expect((await GET(req('scope=all&cursor=garbage'))).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });
});
