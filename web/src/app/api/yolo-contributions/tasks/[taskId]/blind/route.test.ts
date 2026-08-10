import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const TASK = '11111111-1111-4111-8111-111111111111';
function request(body: unknown) {
  return new NextRequest(`https://label.tera-ai.uk/api/yolo-contributions/tasks/${TASK}/blind`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
}
const annotation = { boxes: [{ frame_index: 0, bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }], no_gecko: false };

describe('POST yolo blind submission', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: { task_id: TASK, submission_id: 's1', stage: 'submitted' }, error: null });
  });

  it('bearer contributor와 allowlisted 사람 박스만 RPC에 보낸다', async () => {
    const response = await POST(request({ ...annotation, ignored: 'drop' }), { params: { taskId: TASK } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_submit_yolo_bbox_blind', {
      p_contributor_id: 'labeler-1', p_task_id: TASK,
      p_boxes: annotation.boxes, p_no_gecko: false,
    });
  });

  it('무효 박스는 RPC 전에 400으로 막는다', async () => {
    expect((await POST(request({ boxes: [], no_gecko: false }), { params: { taskId: TASK } })).status).toBe(400);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('assignment 불일치와 중복 제출을 403/409로 매핑한다', async () => {
    rpc.mockResolvedValueOnce({ data: null, error: { code: 'PT403', message: 'contributor_forbidden raw' } });
    expect((await POST(request(annotation), { params: { taskId: TASK } })).status).toBe(403);
    rpc.mockResolvedValueOnce({ data: null, error: { code: 'PT409', message: 'blind_already_submitted raw' } });
    expect((await POST(request(annotation), { params: { taskId: TASK } })).status).toBe(409);
  });
});
