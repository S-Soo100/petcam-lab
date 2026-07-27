import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const {
  requireOwner,
  loadOwnerConflictScope,
  from,
  presignGet,
  isMotionMediaDeleted,
  queryCalls,
} = vi.hoisted(() => ({
  requireOwner: vi.fn(),
  loadOwnerConflictScope: vi.fn(),
  from: vi.fn(),
  presignGet: vi.fn(),
  isMotionMediaDeleted: vi.fn(),
  queryCalls: [] as { table: string; method: string; args: unknown[] }[],
}));

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 300 }));
vi.mock('@/lib/labelingV3Server', () => ({ isMotionMediaDeleted }));
vi.mock('../../../../_access', () => ({ loadOwnerConflictScope }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const COHORT = '22222222-2222-4222-8222-222222222222';
const R2_KEY = 'terra-clips/canary-secret.mp4';
const NON_REVIEWABLE_CONSENSUS: { status: string }[][] = [
  [],
  [{ status: 'awaiting' }],
  [{ status: 'agreed' }],
];

function builder(table: string, result: unknown) {
  const chain: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'is', 'in', 'limit']) {
    chain[method] = (...args: unknown[]) => {
      queryCalls.push({ table, method, args });
      return chain;
    };
  }
  chain.then = (resolve: (value: unknown) => unknown) =>
    Promise.resolve(result).then(resolve);
  return chain;
}

function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((table: string) =>
    builder(table, tables[table] ?? { data: [], error: null }),
  );
}

function req(qs = '') {
  return new NextRequest(
    `https://label.tera-ai.uk/api/labeling-v3/blind/owner/${CLIP}/file/url${qs}`,
  );
}

describe('GET owner/[clipId]/file/url', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryCalls.length = 0;
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    loadOwnerConflictScope.mockResolvedValue({
      ok: true,
      scope: { cohortKind: 'live', cohortId: null },
    });
    presignGet.mockResolvedValue('https://r2.example/signed');
    isMotionMediaDeleted.mockResolvedValue(false);
    setTables({
      motion_clip_consensus: { data: [{ status: 'conflict' }], error: null },
      motion_clips: { data: [{ r2_key: R2_KEY }], error: null },
    });
  });

  it('requires Owner before scope, DB, or signing', async () => {
    requireOwner.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(403);
    expect(loadOwnerConflictScope).not.toHaveBeenCalled();
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('rejects a malformed clip id before scope, DB, or signing', async () => {
    const res = await GET(req(), { params: { clipId: 'nope' } });
    expect(res.status).toBe(400);
    expect(loadOwnerConflictScope).not.toHaveBeenCalled();
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('signs only after exact Canary consensus and returns no raw r2_key', async () => {
    loadOwnerConflictScope.mockResolvedValue({
      ok: true,
      scope: { cohortKind: 'canary', cohortId: COHORT },
    });
    const res = await GET(req(`?cohort_id=${COHORT}`), {
      params: { clipId: CLIP },
    });
    expect(res.status).toBe(200);
    expect(loadOwnerConflictScope).toHaveBeenCalledWith(COHORT);
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['clip_id', CLIP],
    });
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['cohort_kind', 'canary'],
    });
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['cohort_id', COHORT],
    });
    expect(presignGet).toHaveBeenCalledWith(R2_KEY, 300);
    const body = await res.json();
    expect(body).toEqual({
      url: 'https://r2.example/signed',
      expires_in: 300,
    });
    expect(JSON.stringify(body)).not.toContain(R2_KEY);
  });

  it.each(NON_REVIEWABLE_CONSENSUS)(
    'fails closed before reading media for missing/non-reviewable consensus %#',
    async (consensusRows) => {
      setTables({
        motion_clip_consensus: { data: consensusRows, error: null },
        motion_clips: { data: [{ r2_key: R2_KEY }], error: null },
      });
      const res = await GET(req(), { params: { clipId: CLIP } });
      expect(res.status).toBe(404);
      expect(from.mock.calls.map((call: unknown[]) => call[0])).toEqual([
        'motion_clip_consensus',
      ]);
      expect(presignGet).not.toHaveBeenCalled();
    },
  );

  it('allows owner_resolved consensus for audit playback', async () => {
    setTables({
      motion_clip_consensus: {
        data: [{ status: 'owner_resolved' }],
        error: null,
      },
      motion_clips: { data: [{ r2_key: R2_KEY }], error: null },
    });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(200);
    expect(presignGet).toHaveBeenCalledOnce();
  });

  it('returns scope validation errors before consensus or signing', async () => {
    loadOwnerConflictScope.mockResolvedValue({
      ok: false,
      response: NextResponse.json(
        { detail: '검증 코호트를 찾을 수 없어.', code: 'not_found' },
        { status: 404 },
      ),
    });
    const res = await GET(req(`?cohort_id=${COHORT}`), {
      params: { clipId: CLIP },
    });
    expect(res.status).toBe(404);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('keeps live default explicitly scoped to null cohort_id', async () => {
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(200);
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'eq',
      args: ['cohort_kind', 'live'],
    });
    expect(queryCalls).toContainEqual({
      table: 'motion_clip_consensus',
      method: 'is',
      args: ['cohort_id', null],
    });
  });

  it('returns 410 for missing media without signing', async () => {
    setTables({
      motion_clip_consensus: { data: [{ status: 'conflict' }], error: null },
      motion_clips: { data: [{ r2_key: null }], error: null },
    });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('media_unavailable');
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('returns 410 media_deleted without signing', async () => {
    isMotionMediaDeleted.mockResolvedValue(true);
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(410);
    expect((await res.json()).code).toBe('media_deleted');
    expect(presignGet).not.toHaveBeenCalled();
  });

  it('generalizes signing failures without leaking raw error or r2_key', async () => {
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => {});
    presignGet.mockRejectedValue(new Error(`credentials failed for ${R2_KEY}`));
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    const json = JSON.stringify(await res.json());
    expect(json).not.toContain('credentials');
    expect(json).not.toContain(R2_KEY);
    expect(JSON.stringify(errorLog.mock.calls)).not.toContain('credentials');
    expect(JSON.stringify(errorLog.mock.calls)).not.toContain(R2_KEY);
  });
});
