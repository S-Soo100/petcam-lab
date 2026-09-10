import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, rpc, from } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(), rpc: vi.fn(), from: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));
vi.mock('@/lib/labelingV3Server', () => ({
  readGmeActiveContract: () => ({ engine_schema_version: 'gme-shadow-v1', algorithm_version: 'gme-motion-v1', detector_identity: 'a'.repeat(64) }),
}));

import { GET } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const req = () => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}/highlight`);

// PostgREST 빌더 흉내(select/eq/in/limit 체인 → await 시 rows).
function clipQuery(rows: unknown[]) {
  const self: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'in', 'limit']) self[m] = () => self;
  self.then = (resolve: (v: { data: unknown[]; error: null }) => void) => resolve({ data: rows, error: null });
  return self;
}

const LABELER = '30000000-0000-4000-8000-000000000001';
const productionClip = { id: CLIP, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, r2_key: 'terra-clips/clips/2026/09/08/x.mp4', clip_purpose: 'production' };
const currentRow = { source: 'rule', status: 'decided', value: true, rule_version: 'hl-rule-v0', reason: '움직임 12.5초 · 최장 연속 6.0초', reviewer_id: null, decided_at: null, verdict_kind: null };
const initialRow = { status: 'decided', initial: true, rule_version: 'hl-rule-v0', gme_run_id: '2'.repeat(8) + '-0000-4000-8000-000000000001', reason: currentRow.reason, fired: ['long_activity'], shadow: [], features: { activity_sec: 12.5, longest_moving_sec: 6, moving_burst_count: 1, first_moving_sec: 0, visible_sec: 60, duration_sec: 60 } };

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
  from.mockImplementation((table: string) => {
    if (table === 'motion_clips') return clipQuery([productionClip]);
    if (table === 'motion_clip_system_exclusions') return clipQuery([]);
    if (table === 'labeler_applications') return clipQuery([{ user_id: LABELER, display_name: '김라벨' }]);
    throw new Error(`unexpected table ${table}`);
  });
  rpc.mockImplementation(async (name: string) => {
    if (name === 'fn_highlight_current') return { data: [currentRow], error: null };
    if (name === 'fn_highlight_initial') return { data: [initialRow], error: null };
    throw new Error(`unexpected rpc ${name}`);
  });
});

describe('GET /api/labeling-v4/clips/[clipId]/highlight', () => {
  it('현재값 + 1차 판정을 돌려주고 run id 를 노출하지 않는다', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.current.value).toBe(true);
    expect(body.initial.fired).toEqual(['long_activity']);
    expect(JSON.stringify(body)).not.toContain('22222222');
    expect(rpc.mock.calls[0][1]).toEqual({ p_clip_id: CLIP, p_engine_schema_version: 'gme-shadow-v1', p_algorithm_version: 'gme-motion-v1', p_detector_identity: 'a'.repeat(64) });
  });
  it('인증 실패는 가드 응답 그대로', async () => {
    requireLabelingAccess.mockResolvedValue({ ok: false, response: new Response(null, { status: 401 }) });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(401);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('clip 없음은 404', async () => {
    from.mockImplementation(() => clipQuery([]));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
  });
  it("clip_purpose 'test' 는 404 (존재 비노출), RPC 호출 없음", async () => {
    from.mockImplementation((table: string) => clipQuery(table === 'motion_clips' ? [{ ...productionClip, clip_purpose: 'test' }] : []));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect((await res.json()).code).toBe('not_found');
    expect(rpc).not.toHaveBeenCalled();
  });
  it('격리(quarantined) clip 은 404', async () => {
    from.mockImplementation((table: string) => clipQuery(table === 'motion_clips' ? [productionClip] : [{ state: 'quarantined' }]));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });
  it('잘못된 uuid 는 DB 접근 전 400', async () => {
    const res = await GET(req(), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });
  it('human 현재값이면 표시명을 붙인다', async () => {
    rpc.mockImplementation(async (name: string) => name === 'fn_highlight_current'
      ? { data: [{ ...currentRow, source: 'human', value: false, reviewer_id: LABELER, decided_at: '2026-09-08T00:00:00Z', verdict_kind: 'initial' }], error: null }
      : { data: [initialRow], error: null });
    const body = await (await GET(req(), { params: { clipId: CLIP } })).json();
    expect(body.current.reviewer_name).toBe('김라벨');
    expect(JSON.stringify(body)).not.toContain('30000000');
  });
});
