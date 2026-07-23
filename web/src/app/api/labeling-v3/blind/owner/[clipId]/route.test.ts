import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from } = vi.hoisted(() => ({ requireOwner: vi.fn(), from: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { GET } from './route';

const CLIP = '11111111-1111-4111-8111-111111111111';
const A = 'aaaaaaaa-1111-4111-8111-111111111111';
const B = 'bbbbbbbb-1111-4111-8111-111111111111';

function builder(result: unknown) {
  const b: Record<string, unknown> = {};
  for (const m of ['select', 'eq', 'in', 'limit', 'order']) b[m] = () => b;
  b.then = (resolve: (v: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return b;
}
function setTables(tables: Record<string, unknown>) {
  from.mockImplementation((t: string) => builder(tables[t] ?? { data: [], error: null }));
}
function req() {
  return new NextRequest(`https://label.tera-ai.uk/api/labeling-v3/blind/owner/${CLIP}`);
}

describe('GET owner/[clipId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    setTables({
      motion_clip_consensus: {
        data: [{ status: 'conflict', differing_fields: ['primary_action'], submission_a: A, submission_b: B, updated_at: '2026-07-22T00:00:00Z', final_decision: null }],
        error: null,
      },
      motion_clip_blind_submissions: {
        data: [
          { id: A, decision: 'label', reason_code: 'behavior_data', initial_gt: { primary_action: 'moving' }, note: 'a-note', reviewer_id: 'secret-a', digest: 'deadbeef' },
          { id: B, decision: 'label', reason_code: 'behavior_data', initial_gt: { primary_action: 'drinking' }, note: 'b-note', reviewer_id: 'secret-b', digest: 'cafe' },
        ],
        error: null,
      },
      motion_clips: { data: [{ id: CLIP, started_at: 't', duration_sec: 30, r2_key: 'secret.mp4', cameras: { name: '2번' } }], error: null },
    });
  });

  it('403 for a labeler', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(403);
  });

  it('returns both submissions to owner but never reviewer id/digest/r2_key', async () => {
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.submission_a.decision).toBe('label');
    expect(body.submission_b.initial_gt.primary_action).toBe('drinking');
    expect(body.updated_at).toBe('2026-07-22T00:00:00Z');
    const json = JSON.stringify(body);
    expect(json).not.toContain('secret-a');
    expect(json).not.toContain('deadbeef');
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('secret.mp4');
  });

  it('404 when there is no consensus row', async () => {
    setTables({ motion_clip_consensus: { data: [], error: null } });
    expect((await GET(req(), { params: { clipId: CLIP } })).status).toBe(404);
  });

  it('502 on DB error without raw text', async () => {
    setTables({ motion_clip_consensus: { data: null, error: { message: 'consensus boom' } } });
    const res = await GET(req(), { params: { clipId: CLIP } });
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain('boom');
  });
});
