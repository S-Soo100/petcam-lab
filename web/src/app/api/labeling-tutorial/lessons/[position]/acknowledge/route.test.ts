import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireLabelingAccess, helpers, rpc } = vi.hoisted(() => ({
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
  rpc: vi.fn(),
}));

vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('../../../_helpers', () => helpers);

import { POST } from './route';

function post(position = '1') {
  return POST(
    new NextRequest('https://label.tera-ai.uk/api/labeling-tutorial/lessons/1/acknowledge', {
      method: 'POST',
      headers: { authorization: 'Bearer t' },
      body: '{}',
    }),
    { params: { position } },
  );
}

describe('POST tutorial acknowledge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'u1', isOwner: false });
    helpers.loadActiveSetId.mockResolvedValue('set1');
    helpers.loadLessonByPosition.mockResolvedValue({ id: 'lesson1' });
    helpers.currentRunNo.mockResolvedValue(1);
    rpc.mockResolvedValue({ data: { tutorial_completed: false }, error: null });
  });

  it('검수 제출 전(gt_locked)이면 409, RPC 미호출', async () => {
    helpers.loadAttempt.mockResolvedValue({ id: 'a1', stage: 'gt_locked' });
    const res = await post();
    expect(res.status).toBe(409);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('attempt 없으면 409', async () => {
    helpers.loadAttempt.mockResolvedValue(null);
    expect((await post()).status).toBe(409);
  });

  it('review_submitted 면 RPC 호출·tutorial_completed 반환', async () => {
    helpers.loadAttempt.mockResolvedValue({ id: 'a1', stage: 'review_submitted' });
    const res = await post();
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_acknowledge_tutorial_lesson', {
      p_attempt_id: 'a1',
      p_user_id: 'u1',
    });
    expect((await res.json()).tutorial_completed).toBe(false);
  });

  it('5개째면 tutorial_completed true', async () => {
    helpers.loadAttempt.mockResolvedValue({ id: 'a5', stage: 'review_submitted' });
    rpc.mockResolvedValue({ data: { tutorial_completed: true }, error: null });
    expect((await (await post('5')).json()).tutorial_completed).toBe(true);
  });

  it('이미 completed 면 idempotent 200', async () => {
    helpers.loadAttempt.mockResolvedValue({ id: 'a1', stage: 'completed' });
    const res = await post();
    expect(res.status).toBe(200);
    expect(rpc).toHaveBeenCalled();
  });
});
