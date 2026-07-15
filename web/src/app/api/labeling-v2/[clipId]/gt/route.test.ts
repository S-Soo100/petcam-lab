import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

// loadClipWithPerms·_helpers·supabase 를 mock 하고 validator 는 실물 사용 —
// GT 검증 400 응답 형식(detail + issues[], 설계 §6.3)만 격리 검증한다.
const { loadClipWithPerms, helpers, from } = vi.hoisted(() => ({
  loadClipWithPerms: vi.fn(),
  helpers: {
    loadOwnSession: vi.fn(),
    loadLatestVlmPrediction: vi.fn(),
    loadTriageEffectiveState: vi.fn(),
    mapLickTarget: vi.fn(() => null),
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
    // 기본은 격리 아님(queue) — 격리 테스트만 override.
    helpers.loadTriageEffectiveState.mockResolvedValue('queue');
    helpers.loadOwnSession.mockResolvedValue(null);
    helpers.loadLatestVlmPrediction.mockResolvedValue(null);
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

  it('rejects saving GT for a quarantined clip with 409 triage_quarantined (설계 §9)', async () => {
    helpers.loadTriageEffectiveState.mockResolvedValue('pending');
    const res = await post(VALID_GT);
    expect(res.status).toBe(409);
    const json = await res.json();
    expect(json.code).toBe('triage_quarantined');
    // 저장 로직에 도달하지 않는다.
    expect(from).not.toHaveBeenCalled();
  });

  it('rejects saving GT for an owner-skipped clip', async () => {
    helpers.loadTriageEffectiveState.mockResolvedValue('skipped');
    const res = await post(VALID_GT);
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe('triage_quarantined');
  });

  it('maps a guard-trigger PT409 race on session insert to 409 without leaking the DB message', async () => {
    helpers.loadTriageEffectiveState.mockResolvedValue('queue'); // 사전검사 통과 후 경합
    const chain: Record<string, unknown> = {};
    chain.insert = vi.fn(() => chain);
    chain.select = vi.fn(() => chain);
    chain.single = vi.fn(async () => ({
      data: null,
      error: { code: 'PT409', message: 'clip 99 is quarantined/skipped for labeling' },
    }));
    from.mockReturnValue(chain);

    const res = await post(VALID_GT);
    expect(res.status).toBe(409);
    const json = await res.json();
    expect(json.code).toBe('triage_quarantined');
    expect(JSON.stringify(json)).not.toContain('quarantined/skipped for labeling');
    // DB 원문 502 경로로 새지 않았다.
    expect(helpers.databaseError).not.toHaveBeenCalled();
  });
});
