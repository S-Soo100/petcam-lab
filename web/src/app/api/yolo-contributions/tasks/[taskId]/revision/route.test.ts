import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const TASK = '11111111-1111-4111-8111-111111111111';
const body = {
  boxes: [{ frame_index: 0, bbox: { x: 0.12, y: 0.22, width: 0.28, height: 0.38 } }],
  no_gecko: false,
  reason: '모델과 비교해 경계를 조정함',
};
function request(value: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/yolo-contributions/tasks/${TASK}/revision`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(value),
  });
}

describe('POST yolo revision', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: { task_id: TASK, revision_id: 'r1', stage: 'owner_review' }, error: null });
  });

  it('reveal 뒤 최종 사람 revision과 사유를 RPC에 보낸다', async () => {
    const response = await POST(request(body), { params: { taskId: TASK } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_submit_yolo_bbox_revision', {
      p_contributor_id: 'labeler-1', p_task_id: TASK, p_boxes: body.boxes,
      p_no_gecko: false, p_reason: body.reason,
    });
  });

  it('짧은 사유와 reveal 전 제출을 400/409로 막는다', async () => {
    expect((await POST(request({ ...body, reason: 'x' }), { params: { taskId: TASK } })).status).toBe(400);
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'prediction_reveal_required raw' } });
    const response = await POST(request(body), { params: { taskId: TASK } });
    expect(response.status).toBe(409);
  });
});
