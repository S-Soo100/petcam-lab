import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireLabelingAccess, helpers, from, fromTables } = vi.hoisted(() => {
  const fromTables: string[] = [];
  return {
    requireLabelingAccess: vi.fn(),
    helpers: {
      parsePosition: (raw: string) => {
        const n = Number(raw);
        return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
      },
      currentRunNo: vi.fn(),
      loadActiveSetId: vi.fn(),
      loadLessonByPosition: vi.fn(),
      loadAttempt: vi.fn(),
    },
    fromTables,
    from: vi.fn((table: string) => {
      fromTables.push(table);
      return { update: vi.fn(() => ({ eq: vi.fn(() => Promise.resolve({ error: null })) })) };
    }),
  };
});

vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('../../../_helpers', () => helpers);

import { POST } from './route';

const GT = {
  visibility: 'visible',
  primary_action: 'drinking',
  observed_actions: ['licking'],
  segments: [{ action: 'licking', start_sec: 1, end_sec: 5 }],
  target: 'water',
  human_confidence: 'certain',
  context_tags: [],
  activity_intensity: 'low',
  enrichment_object: 'none',
  interaction_types: [],
  note: null,
};
const LESSON = {
  id: 'lesson1',
  reference_gt: GT,
  reference_vlm_review: { verdict: 'incorrect', error_tags: ['action_confusion'], note: null },
  feedback_content: { primary_action: { why: 'x', next: 'y' } },
};
const REVIEW = { verdict: 'correct', error_tags: [], note: null };

function post(body: unknown, position = '1') {
  return POST(
    new NextRequest('https://label.tera-ai.uk/api/labeling-tutorial/lessons/1/vlm-review', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify(body),
    }),
    { params: { position } },
  );
}

describe('POST tutorial vlm-review', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fromTables.length = 0;
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
    helpers.currentRunNo.mockResolvedValue(1);
    helpers.loadActiveSetId.mockResolvedValue('set1');
    helpers.loadLessonByPosition.mockResolvedValue(LESSON);
  });

  it('GT 잠금 전이면 409', async () => {
    helpers.loadAttempt.mockResolvedValue({ id: 'a1', stage: 'draft', submitted_gt: null });
    const res = await post(REVIEW);
    expect(res.status).toBe(409);
    expect(fromTables).toHaveLength(0);
  });

  it('최초 제출은 reference·comparison·feedback 를 공개한다', async () => {
    helpers.loadAttempt.mockResolvedValue({
      id: 'a1',
      stage: 'gt_locked',
      submitted_gt: GT,
      submitted_vlm_review: null,
      comparison: null,
    });
    const res = await post(REVIEW);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.reference.gt).toEqual(GT);
    expect(json.feedback).toEqual(LESSON.feedback_content);
    expect(json.comparison.dimensions).toBeInstanceOf(Array);
    // verdict correct vs reference incorrect → review 그룹
    const verdict = json.comparison.dimensions.find((d: { key: string }) => d.key === 'vlm_verdict');
    expect(verdict.group).toBe('review');
    expect(fromTables).toContain('labeling_tutorial_attempts');
  });

  it('같은 review 재전송은 200 idempotent (쓰기 없음)', async () => {
    helpers.loadAttempt.mockResolvedValue({
      id: 'a1',
      stage: 'review_submitted',
      submitted_gt: GT,
      submitted_vlm_review: REVIEW,
      comparison: { dimensions: [] },
    });
    const res = await post(REVIEW);
    expect(res.status).toBe(200);
    expect(fromTables).toHaveLength(0);
  });

  it('다른 review 로 덮어쓰면 409', async () => {
    helpers.loadAttempt.mockResolvedValue({
      id: 'a1',
      stage: 'review_submitted',
      submitted_gt: GT,
      submitted_vlm_review: { verdict: 'incorrect', error_tags: ['action_confusion'], note: null },
      comparison: { dimensions: [] },
    });
    const res = await post(REVIEW);
    expect(res.status).toBe(409);
    expect((await res.json()).detail).toBe('review_already_submitted');
  });
});
