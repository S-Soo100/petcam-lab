import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

// requireLabelingAccess·_helpers·supabase 를 mock 하고 validator/비교는 실물 사용.
const { requireLabelingAccess, helpers, from, fromTables } = vi.hoisted(() => {
  const fromTables: string[] = [];
  return {
    requireLabelingAccess: vi.fn(),
    helpers: {
      parsePosition: (raw: string) => {
        const n = Number(raw);
        return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
      },
      loadActiveSetId: vi.fn(),
      loadLessonByPosition: vi.fn(),
      loadLessonClip: vi.fn(),
      ensureProgress: vi.fn(),
      loadRunStages: vi.fn(),
      loadAttempt: vi.fn(),
    },
    fromTables,
    from: vi.fn((table: string) => {
      fromTables.push(table);
      return {
        insert: vi.fn(() => Promise.resolve({ error: null })),
        update: vi.fn(() => ({ eq: vi.fn(() => Promise.resolve({ error: null })) })),
      };
    }),
  };
});

vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('../../../_helpers', () => helpers);

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

const LESSON = {
  id: 'lesson1',
  clip_id: 'clip1',
  prediction_snapshot: { action: 'moving', confidence: 0.8 },
  reference_gt: { ...VALID_GT, primary_action: 'drinking' },
  reference_vlm_review: { verdict: 'incorrect', error_tags: ['action_confusion'], note: null },
  feedback_content: { primary_action: { why: 'x', next: 'y' } },
};

function post(body: unknown, position = '1') {
  return POST(
    new NextRequest('https://label.tera-ai.uk/api/labeling-tutorial/lessons/1/gt', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify(body),
    }),
    { params: { position } },
  );
}

describe('POST tutorial gt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fromTables.length = 0;
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
    helpers.loadActiveSetId.mockResolvedValue('set1');
    helpers.loadLessonByPosition.mockResolvedValue(LESSON);
    helpers.loadLessonClip.mockResolvedValue({ id: 'clip1', duration_sec: 60 });
    helpers.ensureProgress.mockResolvedValue(1);
    helpers.loadRunStages.mockResolvedValue(new Map());
    helpers.loadAttempt.mockResolvedValue(null);
  });

  it('최초 제출은 prediction_snapshot 만 반환하고 reference/feedback 은 없다', async () => {
    const res = await post(VALID_GT);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.prediction_snapshot).toEqual(LESSON.prediction_snapshot);
    expect(json).not.toHaveProperty('reference');
    expect(json).not.toHaveProperty('feedback');
    expect(json).not.toHaveProperty('comparison');
  });

  it('behavior_labels / clip_labeling_sessions 에 쓰지 않는다', async () => {
    await post(VALID_GT);
    expect(fromTables).toContain('labeling_tutorial_attempts');
    expect(fromTables).not.toContain('behavior_labels');
    expect(fromTables).not.toContain('clip_labeling_sessions');
  });

  it('같은 payload 재전송은 200 idempotent (쓰기 없음)', async () => {
    helpers.loadAttempt.mockResolvedValue({ id: 'a1', stage: 'gt_locked', submitted_gt: VALID_GT });
    const res = await post(VALID_GT);
    expect(res.status).toBe(200);
    expect((await res.json()).prediction_snapshot).toEqual(LESSON.prediction_snapshot);
    expect(fromTables).toHaveLength(0);
  });

  it('다른 payload 로 덮어쓰면 409', async () => {
    helpers.loadAttempt.mockResolvedValue({
      id: 'a1',
      stage: 'gt_locked',
      submitted_gt: { ...VALID_GT, primary_action: 'drinking' },
    });
    const res = await post(VALID_GT);
    expect(res.status).toBe(409);
    expect((await res.json()).detail).toBe('gt_already_submitted');
  });

  it('순서 건너뛰기(이전 미완료)면 409 + current_position', async () => {
    const res = await post(VALID_GT, '3');
    expect(res.status).toBe(409);
    const json = await res.json();
    expect(json.detail).toBe('out_of_order');
    expect(json.current_position).toBe(1);
  });

  it('잘못된 GT 는 400', async () => {
    const res = await post({ ...VALID_GT, visibility: 'bogus' });
    expect(res.status).toBe(400);
  });
});
