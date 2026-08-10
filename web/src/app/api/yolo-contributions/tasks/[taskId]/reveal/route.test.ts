import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireLabelingAccess, rpc } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn(), rpc: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { POST } from './route';

const TASK = '11111111-1111-4111-8111-111111111111';
const request = new NextRequest(`https://label.tera-ai.uk/api/yolo-contributions/tasks/${TASK}/reveal`, { method: 'POST' });
const prediction = {
  request_id: 'req-1', media_kind: 'image', model_version: 'yolo-v1', provider_mode: 'worker',
  processed_at: '2026-08-10T08:00:00Z', warning: '연구용 결과이며 오류 가능', contribution_status: 'not_requested',
  frames: [{ frame_index: 0, timestamp_ms: 0, detections: [{ label: 'gecko', confidence: 0.9, bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }] }],
};

describe('POST yolo reveal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({ data: {
      task_id: TASK, revealed_at: '2026-08-10T08:01:00Z', prediction,
      blind_boxes: [{ frame_index: 0, bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }],
      blind_no_gecko: false, stage: 'revealed', internal: 'drop',
    }, error: null });
  });

  it('blind 제출 뒤 prediction과 blind 원본만 allowlist로 공개한다', async () => {
    const response = await POST(request, { params: { taskId: TASK } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_reveal_yolo_bbox_prediction', {
      p_contributor_id: 'labeler-1', p_task_id: TASK,
    });
    const text = JSON.stringify(await response.json());
    expect(text).toContain('model_version');
    expect(text).not.toContain('internal');
  });

  it('blind 제출 전 reveal은 409다', async () => {
    rpc.mockResolvedValue({ data: null, error: { code: 'PT409', message: 'blind_submission_required raw' } });
    const response = await POST(request, { params: { taskId: TASK } });
    expect(response.status).toBe(409);
    expect(JSON.stringify(await response.json())).not.toContain('raw');
  });
});
