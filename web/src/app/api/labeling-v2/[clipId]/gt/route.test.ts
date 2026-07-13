import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

// loadClipWithPerms·_helpers·supabase 를 mock 하고 validator 는 실물 사용 —
// GT 검증 400 응답 형식(detail + issues[], 설계 §6.3)만 격리 검증한다.
const { loadClipWithPerms, helpers, from } = vi.hoisted(() => ({
  loadClipWithPerms: vi.fn(),
  helpers: {
    loadOwnSession: vi.fn(),
    loadLatestVlmPrediction: vi.fn(),
    databaseError: vi.fn(),
  },
  from: vi.fn(),
}));

vi.mock('@/lib/clipPerms', () => ({ loadClipWithPerms }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('../../_helpers', () => helpers);

import { POST } from './route';

const VALID_GT = {
  visibility: 'visible',
  primary_action: 'moving',
  observed_actions: ['moving'],
  segments: [{ action: 'moving', start_sec: 0, end_sec: 60 }],
  target: 'none',
  human_confidence: 'certain',
  context_tags: [],
  activity_intensity: null,
  highlight_recommendation: 'include',
  enrichment_object: 'none',
  interaction_types: [],
  note: null,
};

function post(body: unknown) {
  return POST(
    new NextRequest('https://label.tera-ai.uk/api/labeling-v2/clip1/gt', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify(body),
    }),
    { params: { clipId: 'clip1' } },
  );
}

describe('POST labeling-v2 gt validation response', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadClipWithPerms.mockResolvedValue({
      ok: true,
      access: { clip: { id: 'clip1', duration_sec: 60 }, userId: 'owner', isOwner: true },
    });
  });

  it('returns 400 with detail + issues[] for a semantic GT violation', async () => {
    // drinking + target tool 은 규칙 7 위반.
    const res = await post({ ...VALID_GT, primary_action: 'drinking', target: 'tool' });
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(typeof json.detail).toBe('string');
    expect(Array.isArray(json.issues)).toBe(true);
    expect(json.issues.map((issue: { code: string }) => issue.code)).toContain(
      'drinking_target_invalid',
    );
    expect(json.issues[0]).toHaveProperty('field');
    expect(json.issues[0]).toHaveProperty('message');
    // GT 검증에서 끊기므로 DB 는 건드리지 않는다.
    expect(from).not.toHaveBeenCalled();
  });

  it('returns 400 with detail only (no issues) for a malformed enum payload', async () => {
    const res = await post({ ...VALID_GT, visibility: 'bogus' });
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(typeof json.detail).toBe('string');
    expect(json).not.toHaveProperty('issues');
  });
});
