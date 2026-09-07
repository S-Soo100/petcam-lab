import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess, from } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), from: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { loadReviewerDisplayNames, loadV4ClipAccess, resolveReviewerName } from './_access';

const CLIP = '00000000-0000-4000-8000-000000000001';
const OWNER = '30000000-0000-4000-8000-000000000002';
const LABELER = '30000000-0000-4000-8000-000000000001';
const req = () => new NextRequest(`https://label.tera-ai.uk/api/labeling-v4/clips/${CLIP}`);

// PostgREST 빌더 흉내: 어떤 체인이든 마지막에 await 하면 rows 를 돌려준다.
function chain(rows: unknown[]) {
  const calls: { method: string; args: unknown[] }[] = [];
  const self: Record<string, unknown> = { calls };
  for (const m of ['select', 'eq', 'in', 'limit']) self[m] = (...args: unknown[]) => { calls.push({ method: m, args }); return self; };
  self.then = (resolve: (v: { data: unknown[]; error: null }) => void) => resolve({ data: rows, error: null });
  return self as unknown as { calls: typeof calls };
}

const production = { id: CLIP, camera_id: 'c1', started_at: '2026-09-08T00:00:00Z', duration_sec: 60, r2_key: 'terra-clips/clips/2026/09/08/x.mp4', clip_purpose: 'production' };

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: LABELER, isOwner: false });
});
afterEach(() => { delete process.env.DEV_USER_ID; });

describe('loadV4ClipAccess — 운영 적격 가드', () => {
  it('production + canonical 경로 + 미제외면 clip 을 돌려준다', async () => {
    from.mockImplementation((t: string) => chain(t === 'motion_clips' ? [production] : []));
    const r = await loadV4ClipAccess(req(), CLIP);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.clip.clip_purpose).toBe('production');
  });
  it("clip_purpose 'test' 는 존재해도 404 not_found", async () => {
    from.mockImplementation((t: string) => chain(t === 'motion_clips' ? [{ ...production, clip_purpose: 'test' }] : []));
    const r = await loadV4ClipAccess(req(), CLIP);
    expect(r.ok).toBe(false);
    if (!r.ok) { expect(r.response.status).toBe(404); expect((await r.response.json()).code).toBe('not_found'); }
    expect(from).not.toHaveBeenCalledWith('motion_clip_system_exclusions');
  });
  it('비 canonical R2 경로도 404', async () => {
    from.mockImplementation((t: string) => chain(t === 'motion_clips' ? [{ ...production, r2_key: 'terra-clips/quarantine/x.mp4' }] : []));
    const r = await loadV4ClipAccess(req(), CLIP);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.response.status).toBe(404);
  });
  it('격리(quarantined)·삭제(media_deleted) 상태면 404', async () => {
    const exclusions = chain([{ state: 'quarantined' }]);
    from.mockImplementation((t: string) => (t === 'motion_clips' ? chain([production]) : exclusions));
    const r = await loadV4ClipAccess(req(), CLIP);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.response.status).toBe(404);
    expect(exclusions.calls.find((c) => c.method === 'in')?.args).toEqual(['state', ['quarantined', 'media_deleted']]);
  });
  it('가드 실패는 그대로, 잘못된 uuid 는 DB 전 400', async () => {
    requireLabelingAccess.mockResolvedValue({ ok: false, response: new Response(null, { status: 401 }) });
    const r = await loadV4ClipAccess(req(), CLIP);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.response.status).toBe(401);
    const bad = await loadV4ClipAccess(req(), 'nope');
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.response.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });
});

describe('resolveReviewerName — 표시명 단일 resolver', () => {
  it('owner 는 Owner, display_name 있으면 그대로, 없으면 라벨러', () => {
    process.env.DEV_USER_ID = OWNER;
    expect(resolveReviewerName({ reviewerId: OWNER, displayName: null })).toBe('Owner');
    expect(resolveReviewerName({ reviewerId: OWNER, displayName: '누구' })).toBe('Owner');
    expect(resolveReviewerName({ reviewerId: LABELER, displayName: '김라벨' })).toBe('김라벨');
    expect(resolveReviewerName({ reviewerId: LABELER, displayName: null })).toBe('라벨러');
  });
  it('DEV_USER_ID 미설정이면 아무도 Owner 가 아니다', () => {
    expect(resolveReviewerName({ reviewerId: OWNER, displayName: null })).toBe('라벨러');
  });
});

describe('loadReviewerDisplayNames', () => {
  it('한 번의 in 쿼리로 묶고, 없는 사용자는 null', async () => {
    const q = chain([{ user_id: LABELER, display_name: '김라벨' }]);
    from.mockReturnValue(q);
    const names = await loadReviewerDisplayNames([LABELER, OWNER, LABELER]);
    expect(from).toHaveBeenCalledTimes(1);
    expect(q.calls.find((c) => c.method === 'in')?.args).toEqual(['user_id', [LABELER, OWNER]]);
    expect(names.get(LABELER)).toBe('김라벨');
    expect(names.get(OWNER)).toBeNull();
  });
  it('빈 입력은 쿼리 없이 빈 Map', async () => {
    expect((await loadReviewerDisplayNames([])).size).toBe(0);
    expect(from).not.toHaveBeenCalled();
  });
});
