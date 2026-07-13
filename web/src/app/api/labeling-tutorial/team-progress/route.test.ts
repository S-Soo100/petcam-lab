import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

// team-progress 의 네 쿼리 중 어느 하나가 실패해도 내부 Supabase 메시지 없이 일반 502 를 반환한다.
const { requireOwner, loadActiveTutorial, from, results } = vi.hoisted(() => {
  const results: Record<string, { data: unknown; error: unknown }> = {};
  function makeBuilder(result: { data: unknown; error: unknown }) {
    const b: Record<string, unknown> = {
      select: () => b,
      eq: () => b,
      order: () => b,
      then: (resolve: (v: unknown) => unknown, reject?: (e: unknown) => unknown) =>
        Promise.resolve(result).then(resolve, reject),
    };
    return b;
  }
  return {
    requireOwner: vi.fn(),
    loadActiveTutorial: vi.fn(),
    from: vi.fn((table: string) => makeBuilder(results[table])),
    results,
  };
});

vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/labelingTutorialGate', () => ({ loadActiveTutorial }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { GET } from './route';

const TABLES = [
  'labeling_tutorial_lessons',
  'labeler_applications',
  'labeling_tutorial_progress',
  'labeling_tutorial_attempts',
] as const;

function ok() {
  return new NextRequest('https://label.tera-ai.uk/api/labeling-tutorial/team-progress', {
    headers: { authorization: 'Bearer t' },
  });
}

function resetSuccess() {
  results.labeling_tutorial_lessons = { data: [{ id: 'l1', position: 1 }], error: null };
  results.labeler_applications = {
    data: [{ user_id: 'u1', display_name: 'A', email: 'a@x' }],
    error: null,
  };
  results.labeling_tutorial_progress = { data: [], error: null };
  results.labeling_tutorial_attempts = { data: [], error: null };
}

describe('GET tutorial team-progress 오류 은닉', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
    loadActiveTutorial.mockResolvedValue({
      setId: 'set1',
      version: 'v1',
      title: 't',
      lessonCount: 5,
    });
    resetSuccess();
  });

  it('네 쿼리 모두 성공하면 200', async () => {
    const res = await GET(ok());
    expect(res.status).toBe(200);
  });

  for (const table of TABLES) {
    it(`${table} 오류는 내부 메시지 없는 502`, async () => {
      resetSuccess();
      results[table] = { data: null, error: { message: `secret-${table}` } };
      const res = await GET(ok());
      expect(res.status).toBe(502);
      const body = JSON.stringify(await res.json());
      expect(body).not.toContain('secret');
      expect(body).not.toContain(table);
    });
  }
});
