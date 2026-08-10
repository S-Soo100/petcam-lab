import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireLabelingAccess, rpc, presignGet } = vi.hoisted(() => ({
  requireLabelingAccess: vi.fn(),
  rpc: vi.fn(),
  presignGet: vi.fn(),
}));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 3600 }));

import { GET } from './route';

const request = new NextRequest('https://label.tera-ai.uk/api/yolo-contributions/workspace');

describe('GET /api/yolo-contributions/workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1', isOwner: false });
    rpc.mockResolvedValue({
      data: { enabled: false, total: 0, completed: 0, next_task: null, prediction: 'must-drop' },
      error: null,
    });
    presignGet.mockResolvedValue('https://signed.example/yolo-media');
  });

  it('기존 승인 멤버 guard 뒤 bearer id로 본인 workspace만 읽는다', async () => {
    const response = await GET(request);
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_yolo_bbox_workspace', {
      p_contributor_id: 'labeler-1',
    });
    expect(JSON.stringify(await response.json())).not.toContain('prediction');
  });

  it('권한이 없으면 RPC 전에 차단한다', async () => {
    requireLabelingAccess.mockResolvedValue({
      ok: false,
      response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }),
    });
    expect((await GET(request)).status).toBe(403);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('DB 원문은 숨긴 502로 반환한다', async () => {
    rpc.mockResolvedValue({ data: null, error: { message: 'secret yolo table' } });
    const response = await GET(request);
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain('secret yolo table');
  });

  it('assignment RPC의 private media_ref를 짧은 signed URL로 바꾼다', async () => {
    rpc.mockResolvedValue({ data: {
      enabled: true, total: 1, completed: 0,
      next_task: {
        task_id: '11111111-1111-4111-8111-111111111111', media_kind: 'image',
        media_ref: 'private/gecko.jpg', frame_manifest: [{ frame_index: 0, timestamp_ms: 0 }], stage: 'blind',
      },
    }, error: null });
    const response = await GET(request);
    const text = JSON.stringify(await response.json());
    expect(presignGet).toHaveBeenCalledWith('private/gecko.jpg', 3600);
    expect(text).toContain('https://signed.example/yolo-media');
    expect(text).not.toContain('private/gecko.jpg');
  });
});
